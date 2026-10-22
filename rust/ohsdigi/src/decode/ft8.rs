//! FT8 decoding, stage by stage, as WSJT-X 2.7.0 does it.
//!
//! Ported from WSJT-X 2.7.0 (GPL-3): lib/ft8_decode.f90, lib/ft8/sync8.f90,
//! get_spectrum_baseline.f90, baseline.f90, ft8_downsample.f90, sync8d.f90,
//! ft8b.f90, subtractft8.f90, gen_ft8wave.f90. Copyright (C) 2001-2024 Joe
//! Taylor K1JT, Steve Franke K9AN, Bill Somerville G4WJS and the WSJT-X
//! development team. ft8_lib (Karlis Goba YL3JG, MIT) was the second
//! reference for structure.
//!
//! The port keeps WSJT-X's arithmetic in single precision where the Fortran
//! uses default REAL, and keeps its decision rules even where they look
//! accidental (they are listed where they occur), because the acceptance
//! test for this decoder is "decodes what jt9 decodes": a cleaner rule that
//! decodes differently would be a different decoder to validate.
//!
//! One structural change: within a pass, candidates are decoded in
//! parallel and their signals subtracted afterwards, in candidate order.
//! That is exactly equivalent to WSJT-X's serial loop, because ft8b reads
//! the audio only through the downsampler's FFT, which WSJT-X computes once
//! at the start of each pass (`newdat`) and does not refresh after a
//! subtraction - so no candidate's decode ever sees another's subtraction
//! within the pass.

use super::ap::ApCalls;
use super::ldpc::decode174_91;
use super::util::{fft_fwd, fft_inv, indexx, maxloc, nint, normalizebmet, nuttall_window, pctile, polyfit, rfft, C32};
use crate::ft8::{tones as ft8_tones, COSTAS as ICOS7, GRAY as GRAYMAP8};
use crate::ldpc::ldpc174_91::N as NBITS;
use crate::msg77::{unpack77, CallHashes};
use rayon::prelude::*;
use std::sync::OnceLock;

// ft8_params.f90
pub const NN: usize = 79;
pub const NSPS: usize = 1920;
pub const NMAX: usize = 15 * 12000;
pub const NFFT1: usize = 2 * NSPS;
pub const NH1: usize = NFFT1 / 2;
pub const NSTEP: usize = NSPS / 4;
pub const NHSYM: usize = NMAX / NSTEP - 3;
pub const NDOWN: usize = 60;
const NP2: usize = 2812;
const NFFT_DS: usize = 192000;
const NFFT2: usize = 3200;
const JZ: i32 = 62;
const MAXPRECAND: usize = 1000;

#[inline]
fn twopi() -> f32 {
    8.0f32 * 1f32.atan()
}

/// One sync8 candidate.
#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Candidate {
    pub freq: f32,
    /// Seconds relative to the nominal 0.5 s start.
    pub dt: f32,
    pub sync: f32,
}

/// jt9 run from the command line, as NB runs it, has MyCall K1ABC and
/// DxCall W9XYZ unless told otherwise (jt9.f90), so its a-priori passes
/// look for those calls.
pub const JT9_MYCALL: &str = "K1ABC";
pub const JT9_DXCALL: &str = "W9XYZ";

/// Decoder settings. `default()` is jt9's file-mode configuration (`jt9
/// -8`: depth 1, 200-4000 Hz, nfqso 1500, AP on) without any calls, so only
/// the CQ a-priori pass can fire; `jt9()` adds jt9's built-in dummy calls,
/// for like-for-like comparison with jt9 itself.
#[derive(Clone, Debug)]
pub struct Ft8Params {
    pub nfa: i32,
    pub nfb: i32,
    pub nfqso: i32,
    pub nftx: i32,
    /// 1 fast (BP only), 2 normal (BP + OSD on channel LLRs), 3 deep.
    pub ndepth: i32,
    /// A-priori decoding. jt9 runs with it on (lft8apon=.true.).
    pub lapon: bool,
    pub lapcqonly: bool,
    pub napwid: f32,
    /// WSJT-X's QSO progress state, 0..5 (which AP types are tried).
    pub nqso_progress: usize,
    /// MyCall/DxCall for AP, from ap::ft8_ap (ft8apset.f90). None = no
    /// MyCall (AP types 2-6 skipped); without a DxCall, types 3-6 are.
    pub ap: Option<ApCalls>,
    pub maxcand: usize,
    /// Reproduce jt9's file-mode early passes (nzhsym 41/47 then 50) at
    /// depth >= 2, as `jt9 -8 -d N file.wav` does. When false, one full
    /// pass set on the whole slot.
    pub jt9_file_mode: bool,
    /// Decoder threads (util::with_pool): 0 = cores - 1, 1 = one core.
    pub threads: usize,
}

impl Ft8Params {
    /// Exactly what `jt9 -8 [-d N] file.wav` does, dummy calls included.
    pub fn jt9() -> Self {
        Ft8Params {
            ap: super::ap::ft8_ap(JT9_MYCALL, JT9_DXCALL),
            ..Default::default()
        }
    }
}

impl Default for Ft8Params {
    fn default() -> Self {
        Ft8Params {
            nfa: 200,
            nfb: 4000,
            nfqso: 1500,
            nftx: 0,
            ndepth: 1,
            lapon: true,
            lapcqonly: false,
            napwid: 75.0,
            nqso_progress: 0,
            ap: None,
            maxcand: 600,
            jt9_file_mode: true,
            threads: 0,
        }
    }
}

/// A decode, as ft8_decode's callback sees it.
#[derive(Clone, Debug)]
pub struct Ft8Decode {
    /// The message as WSJT-X shows it (unpack77, as received).
    pub text: String,
    pub payload: [u8; 77],
    pub snr: i32,
    /// Seconds relative to the nominal 0.5 s start (what jt9 prints).
    pub dt: f32,
    pub freq: f32,
    pub sync: f32,
    /// 0 = no a-priori help; 1-6 WSJT-X's AP types ("a1".."a6").
    pub iaptype: i32,
    pub nharderrors: i32,
    pub dmin: f32,
    pub qual: f32,
    pub tones: [u8; 79],
    /// Which call (41/47/50, see Ft8Params::jt9_file_mode) and pass found it.
    pub nzhsym: i32,
    pub ipass: i32,
}

// ---------------------------------------------------------------- stage 1

/// Spectrogram + Costas sync scoring: sync8.f90. Returns the candidates
/// (best first, those within 10 Hz of nfqso ahead of all others) and
/// `sbase`, the noise baseline in dB per 3.125 Hz bin (index = bin, 1-based
/// as in WSJT-X; sbase[0] unused) that the SNR estimate needs.
pub fn sync8(dd: &[f32], nfa: i32, nfb: i32, syncmin: f32, nfqso: i32, maxcand: usize) -> (Vec<Candidate>, Vec<f32>) {
    let tstep = NSTEP as f32 / 12000.0;
    let df = 12000.0f32 / NFFT1 as f32;
    let fac = 1.0f32 / 300.0;

    // s(i,j): bin i (1..NH1), quarter-symbol step j (1..NHSYM).
    let mut s = vec![0f32; (NH1 + 1) * (NHSYM + 1)];
    let at = |i: usize, j: usize| j * (NH1 + 1) + i;
    let rows: Vec<Vec<f32>> = (1..=NHSYM)
        .into_par_iter()
        .map(|j| {
            let ia = (j - 1) * NSTEP;
            let x: Vec<f32> = dd[ia..ia + NSPS].iter().map(|v| fac * v).collect();
            let cx = rfft(&x, NFFT1);
            (1..=NH1).map(|i| cx[i].re * cx[i].re + cx[i].im * cx[i].im).collect()
        })
        .collect();
    for (jj, row) in rows.into_iter().enumerate() {
        let j = jj + 1;
        for i in 1..=NH1 {
            s[at(i, j)] = row[i - 1];
        }
    }

    let (mut nfa, mut nfb) = (nfa, nfb);
    let sbase = get_spectrum_baseline(dd, &mut nfa, &mut nfb);

    let ia = 1.max(nint(nfa as f32 / df)) as usize;
    let ib = nint(nfb as f32 / df) as usize;
    let nssy = (NSPS / NSTEP) as i32;
    let nfos = NFFT1 / NSPS;
    let jstrt = (0.5f32 / tstep) as i32;

    let nj = (2 * JZ + 1) as usize;
    let sync2d: Vec<Vec<f32>> = (ia..=ib)
        .into_par_iter()
        .map(|i| {
            let mut row = vec![0f32; nj];
            for j in -JZ..=JZ {
                let (mut ta, mut tb, mut tc) = (0f32, 0f32, 0f32);
                let (mut t0a, mut t0b, mut t0c) = (0f32, 0f32, 0f32);
                for n in 0..7 {
                    let m = j + jstrt + nssy * n as i32;
                    let sum7 = |mm: i32| -> f32 {
                        let mut acc = 0f32;
                        for q in 0..7 {
                            acc += s[at(i + nfos * q, mm as usize)];
                        }
                        acc
                    };
                    if m >= 1 && m <= NHSYM as i32 {
                        ta += s[at(i + nfos * ICOS7[n] as usize, m as usize)];
                        t0a += sum7(m);
                    }
                    let mb = m + nssy * 36;
                    tb += s[at(i + nfos * ICOS7[n] as usize, mb as usize)];
                    t0b += sum7(mb);
                    let mc = m + nssy * 72;
                    if mc <= NHSYM as i32 {
                        tc += s[at(i + nfos * ICOS7[n] as usize, mc as usize)];
                        t0c += sum7(mc);
                    }
                }
                let t = ta + tb + tc;
                let t0 = (t0a + t0b + t0c - t) / 6.0;
                let sync_abc = t / t0;
                let t = tb + tc;
                let t0 = (t0b + t0c - t) / 6.0;
                let sync_bc = t / t0;
                row[(j + JZ) as usize] = sync_abc.max(sync_bc);
            }
            row
        })
        .collect();
    let s2d = |i: usize, j: i32| sync2d[i - ia][(j + JZ) as usize];

    let mut red = vec![0f32; NH1 + 1];
    let mut red2 = vec![0f32; NH1 + 1];
    let mut jpeak = vec![0i32; NH1 + 1];
    let mut jpeak2 = vec![0i32; NH1 + 1];
    let mlag = 10;
    let mlag2 = JZ;
    for i in ia..=ib {
        let (mut bj, mut bv) = (-mlag, s2d(i, -mlag));
        for j in -mlag..=mlag {
            if s2d(i, j) > bv {
                bv = s2d(i, j);
                bj = j;
            }
        }
        jpeak[i] = bj;
        red[i] = bv;
        let (mut bj, mut bv) = (-mlag2, s2d(i, -mlag2));
        for j in -mlag2..=mlag2 {
            if s2d(i, j) > bv {
                bv = s2d(i, j);
                bj = j;
            }
        }
        jpeak2[i] = bj;
        red2[i] = bv;
    }
    let iz = ib - ia + 1;
    let indx = indexx(&red[ia..=ib]);
    let npctile = nint(0.40 * iz as f32);
    if npctile < 1 {
        return (vec![], sbase);
    }
    let ibase = (indx[npctile as usize - 1] + ia).clamp(1, NH1);
    let base = red[ibase];
    for v in red.iter_mut() {
        *v /= base;
    }
    let indx2 = indexx(&red2[ia..=ib]);
    let ibase2 = (indx2[npctile as usize - 1] + ia).clamp(1, NH1);
    let base2 = red2[ibase2];
    for v in red2.iter_mut() {
        *v /= base2;
    }

    let mut c0: Vec<Candidate> = Vec::new();
    for i in 1..=MAXPRECAND.min(iz) {
        let n = ia + indx[iz - i];
        if c0.len() >= MAXPRECAND {
            break;
        }
        if red[n] >= syncmin && !red[n].is_nan() {
            c0.push(Candidate {
                freq: n as f32 * df,
                dt: (jpeak[n] as f32 - 0.5) * tstep,
                sync: red[n],
            });
        }
        if jpeak2[n] == jpeak[n] {
            continue;
        }
        if c0.len() >= MAXPRECAND {
            break;
        }
        if red2[n] >= syncmin && !red2[n].is_nan() {
            c0.push(Candidate {
                freq: n as f32 * df,
                dt: (jpeak2[n] as f32 - 0.5) * tstep,
                sync: red2[n],
            });
        }
    }
    let ncand = c0.len();
    // Keep only the best of near-duplicates.
    for i in 1..ncand {
        for j in 0..i {
            let fdiff = c0[i].freq.abs() - c0[j].freq.abs();
            let tdiff = (c0[i].dt - c0[j].dt).abs();
            if fdiff.abs() < 4.0 && tdiff < 0.04 {
                if c0[i].sync >= c0[j].sync {
                    c0[j].sync = 0.0;
                }
                if c0[i].sync < c0[j].sync {
                    c0[i].sync = 0.0;
                }
            }
        }
    }
    let syncs: Vec<f32> = c0.iter().map(|c| c.sync).collect();
    let order = indexx(&syncs);
    let mut out: Vec<Candidate> = Vec::new();
    for i in 0..ncand {
        if (c0[i].freq - nfqso as f32).abs() <= 10.0 && c0[i].sync >= syncmin {
            out.push(c0[i]);
            c0[i].sync = 0.0;
        }
    }
    for i in (0..ncand).rev() {
        let j = order[i];
        if c0[j].sync >= syncmin {
            out.push(Candidate {
                freq: c0[j].freq.abs(),
                dt: c0[j].dt,
                sync: c0[j].sync,
            });
            if out.len() >= maxcand {
                break;
            }
        }
    }
    (out, sbase)
}

/// get_spectrum_baseline.f90 + baseline.f90. sbase is indexed by bin,
/// 1-based (index 0 unused); bins outside nfa..nfb are 0, as in WSJT-X.
pub fn get_spectrum_baseline(dd: &[f32], nfa: &mut i32, nfb: &mut i32) -> Vec<f32> {
    static WINDOW: OnceLock<Vec<f32>> = OnceLock::new();
    let window = WINDOW.get_or_init(|| {
        let w = nuttall_window(NFFT1);
        let sum: f32 = w.iter().sum();
        w.iter().map(|v| v / sum * NSPS as f32 * 2.0 / 300.0).collect()
    });
    let nst = NFFT1 / 2;
    let nf = 93;
    let mut savg = vec![0f32; NH1 + 1];
    let nspec = (1..=nf).take_while(|j| (j - 1) * nst + NFFT1 <= NMAX).count();
    let spectra: Vec<Vec<f32>> = (1..=nspec)
        .into_par_iter()
        .map(|j| {
            let ia = (j - 1) * nst;
            let x: Vec<f32> = dd[ia..ia + NFFT1]
                .iter()
                .zip(window.iter())
                .map(|(a, b)| a * b)
                .collect();
            let cx = rfft(&x, NFFT1);
            (1..=NH1).map(|i| cx[i].norm_sqr()).collect()
        })
        .collect();
    // Summed in spectrum order, as the Fortran's loop does.
    for sp in &spectra {
        for i in 1..=NH1 {
            savg[i] += sp[i - 1];
        }
    }
    let nwin = *nfb - *nfa;
    if *nfa < 100 {
        *nfa = 100;
        if nwin < 100 {
            *nfb = *nfa + nwin;
        }
    }
    if *nfb > 4910 {
        *nfb = 4910;
        if nwin < 100 {
            *nfa = *nfb - nwin;
        }
    }
    baseline(&mut savg, *nfa, *nfb)
}

/// baseline.f90: fit a 5-term polynomial to the lowest 10 % of each of
/// ten segments of the dB spectrum. Quirk kept: the abscissa is `i - i0`
/// with i0 half the *width*, not the middle bin.
fn baseline(s: &mut [f32], nfa: i32, nfb: i32) -> Vec<f32> {
    let df = 12000.0f64 / 3840.0;
    let ia = 1.max((nfa as f64 / df).round() as i64) as usize;
    let ib = (nfb as f64 / df).round() as usize;
    for i in ia..=ib {
        s[i] = 10.0 * s[i].log10();
    }
    let nseg = 10;
    let npct = 10;
    let nlen = (ib - ia + 1) / nseg;
    let i0 = (ib - ia).div_ceil(2) as i64;
    let mut x = vec![0f64; 1000];
    let mut y = vec![0f64; 1000];
    let mut k = 0usize;
    for n in 1..=nseg {
        let ja = ia + (n - 1) * nlen;
        let jb = ja + nlen - 1;
        let base = pctile(&s[ja..ja + nlen], npct);
        for i in ja..=jb {
            if s[i] <= base {
                if k < 1000 {
                    k += 1;
                }
                x[k - 1] = i as f64 - i0 as f64;
                y[k - 1] = s[i] as f64;
            }
        }
    }
    let a = polyfit(&x[..k], &y[..k], 5);
    let mut sbase = vec![0f32; NH1 + 1];
    for i in ia..=ib {
        let t = i as f64 - i0 as f64;
        sbase[i] = (a[0] + t * (a[1] + t * (a[2] + t * (a[3] + t * a[4]))) + 0.65) as f32;
    }
    sbase
}

// ---------------------------------------------------------------- stage 2

/// ft8_downsample.f90's long FFT, made once per pass (WSJT-X's `newdat`).
pub struct Downsampler {
    cx: Vec<C32>,
}

impl Downsampler {
    pub fn new(dd: &[f32]) -> Self {
        Downsampler {
            cx: rfft(&dd[..NMAX], NFFT_DS),
        }
    }

    /// Mix f0 to baseband and decimate to 200 Hz (32 samples a symbol).
    pub fn downsample(&self, f0: f32) -> Vec<C32> {
        static TAPER: OnceLock<Vec<f32>> = OnceLock::new();
        let taper = TAPER.get_or_init(|| {
            let pi = 4.0f32 * 1f32.atan();
            (0..=100).map(|i| 0.5 * (1.0 + (i as f32 * pi / 100.0).cos())).collect()
        });
        let df = 12000.0f32 / NFFT_DS as f32;
        let baud = 12000.0f32 / NSPS as f32;
        let i0 = nint(f0 / df);
        let ft = f0 + 8.5 * baud;
        let it = nint(ft / df).min((NFFT_DS / 2) as i32);
        let fb = f0 - 1.5 * baud;
        let ib = 1.max(nint(fb / df));
        let mut c1 = vec![C32::new(0.0, 0.0); NFFT2];
        let mut k = 0usize;
        for i in ib..=it {
            c1[k] = self.cx[i as usize];
            k += 1;
        }
        for m in 0..=100 {
            c1[m] *= taper[100 - m];
        }
        for t in 0..=100 {
            c1[k - 1 - 100 + t] *= taper[t];
        }
        // cshift(c1, i0-ib): out(i) = in(i + shift), circularly.
        let sh = (i0 - ib).rem_euclid(NFFT2 as i32) as usize;
        c1.rotate_left(sh);
        fft_inv(&mut c1);
        let fac = 1.0f32 / ((NFFT_DS as f32) * NFFT2 as f32).sqrt();
        for v in c1.iter_mut() {
            *v *= fac;
        }
        c1
    }
}

fn csync8() -> &'static [[C32; 32]; 7] {
    static CS: OnceLock<[[C32; 32]; 7]> = OnceLock::new();
    CS.get_or_init(|| {
        let tp = twopi();
        let mut cs = [[C32::new(0.0, 0.0); 32]; 7];
        for i in 0..7 {
            let mut phi = 0f32;
            let dphi = tp * ICOS7[i] as f32 / 32.0;
            for j in 0..32 {
                cs[i][j] = C32::new(phi.cos(), phi.sin());
                phi = (phi + dphi) % tp;
            }
        }
        cs
    })
}

/// sync8d.f90: Costas sync power of the downsampled signal at offset i0,
/// optionally with a frequency tweak.
pub fn sync8d(cd0: &[C32], i0: i32, ctwk: Option<&[C32; 32]>) -> f32 {
    let cs = csync8();
    let p = |z: C32| z.re * z.re + z.im * z.im;
    let mut sync = 0f32;
    for i in 0..7 {
        let i1 = i0 + i as i32 * 32;
        let i2 = i1 + 36 * 32;
        let i3 = i1 + 72 * 32;
        let mut csync2 = cs[i];
        if let Some(t) = ctwk {
            for j in 0..32 {
                csync2[j] = t[j] * csync2[j];
            }
        }
        let corr = |st: i32| -> C32 {
            if st >= 0 && st + 31 < NP2 as i32 {
                let mut z = C32::new(0.0, 0.0);
                for j in 0..32 {
                    z += cd0[st as usize + j] * csync2[j].conj();
                }
                z
            } else {
                C32::new(0.0, 0.0)
            }
        };
        sync += p(corr(i1)) + p(corr(i2)) + p(corr(i3));
    }
    sync
}

// ---------------------------------------------------------------- stage 3

/// Everything ft8b works out before the LDPC decoder: fine sync and the
/// four sets of soft bit metrics. Public so the harness can compare them.
#[derive(Clone, Debug)]
pub struct Ft8Metrics {
    pub f1: f32,
    /// Absolute start time in the buffer, seconds ((ibest-1)*dt2).
    pub xdt: f32,
    pub ibest: i32,
    pub delfbest: f32,
    pub sync: f32,
    pub nsync: i32,
    /// Symbol magnitudes |FFT| (s8 in ft8b), [symbol][tone].
    pub s8: Vec<[f32; 8]>,
    /// llra..llrd: scaled, normalised metrics for nsym = 1, 2, 3 and the
    /// bit-by-bit normalised nsym = 1.
    pub llr: [[f32; NBITS]; 4],
}

/// ft8b's front half: downsample, refine time and frequency, symbol
/// spectra, hard sync check, bit metrics. None if the sync check fails
/// (nsync <= 6).
pub fn ft8_metrics(ds: &Downsampler, f1_in: f32, xdt_in: f32) -> Option<Ft8Metrics> {
    let fs2 = 12000.0f32 / NDOWN as f32;
    let dt2 = 1.0f32 / fs2;
    let tp = twopi();
    let mut f1 = f1_in;
    let cd0 = ds.downsample(f1);
    let i0 = nint((xdt_in + 0.5) * fs2);
    let mut smax = 0f32;
    let mut ibest = 0i32;
    for idt in (i0 - 10)..=(i0 + 10) {
        let sync = sync8d(&cd0, idt, None);
        if sync > smax {
            smax = sync;
            ibest = idt;
        }
    }
    smax = 0.0;
    let mut delfbest = 0f32;
    for ifr in -5..=5 {
        let delf = ifr as f32 * 0.5;
        let dphi = tp * delf * dt2;
        let mut phi = 0f32;
        let mut ctwk = [C32::new(0.0, 0.0); 32];
        for c in ctwk.iter_mut() {
            *c = C32::new(phi.cos(), phi.sin());
            phi = (phi + dphi) % tp;
        }
        let sync = sync8d(&cd0, ibest, Some(&ctwk));
        if sync > smax {
            smax = sync;
            delfbest = delf;
        }
    }
    // (WSJT-X applies twkfreq1 to cd0 here, then immediately recomputes cd0
    // from the shifted frequency below, so that tweak has no effect.)
    f1 += delfbest;
    let cd0 = ds.downsample(f1);
    let mut ss = [0f32; 9];
    for idt in -4..=4i32 {
        ss[(idt + 4) as usize] = sync8d(&cd0, ibest + idt, None);
    }
    let iloc = maxloc(&ss);
    let smax = ss[iloc];
    ibest += iloc as i32 - 4;
    let xdt = (ibest - 1) as f32 * dt2;

    let mut cs = vec![[C32::new(0.0, 0.0); 8]; NN];
    let mut s8 = vec![[0f32; 8]; NN];
    let mut csymb = [C32::new(0.0, 0.0); 32];
    for k in 0..NN {
        let i1 = ibest + k as i32 * 32;
        if i1 >= 0 && i1 + 31 < NP2 as i32 {
            csymb.copy_from_slice(&cd0[i1 as usize..i1 as usize + 32]);
        } else {
            csymb = [C32::new(0.0, 0.0); 32];
        }
        fft_fwd(&mut csymb);
        for t in 0..8 {
            cs[k][t] = csymb[t] / 1e3;
            s8[k][t] = csymb[t].norm();
        }
    }

    let mut nsync = 0;
    for k in 0..7 {
        for off in [0usize, 36, 72] {
            if maxloc(&s8[k + off]) == ICOS7[k] as usize {
                nsync += 1;
            }
        }
    }
    if nsync <= 6 {
        return None;
    }

    let mut bmeta = [0f32; NBITS];
    let mut bmetb = [0f32; NBITS];
    let mut bmetc = [0f32; NBITS];
    let mut bmetd = [0f32; NBITS];
    let mut s2 = [0f32; 512];
    for nsym in 1..=3usize {
        let nt = 1usize << (3 * nsym);
        for ihalf in 1..=2 {
            let mut k = 1;
            while k <= 29 {
                let ks = if ihalf == 1 { k + 7 } else { k + 43 }; // 1-based symbol
                for i in 0..nt {
                    let i1 = i / 64;
                    let i2 = (i & 63) / 8;
                    let i3 = i & 7;
                    s2[i] = match nsym {
                        1 => cs[ks - 1][GRAYMAP8[i3] as usize].norm(),
                        2 => (cs[ks - 1][GRAYMAP8[i2] as usize] + cs[ks][GRAYMAP8[i3] as usize]).norm(),
                        _ => (cs[ks - 1][GRAYMAP8[i1] as usize]
                            + cs[ks][GRAYMAP8[i2] as usize]
                            + cs[ks + 1][GRAYMAP8[i3] as usize])
                            .norm(),
                    };
                }
                let i32_ = 1 + (k - 1) * 3 + (ihalf - 1) * 87;
                let ibmax = match nsym {
                    1 => 2,
                    2 => 5,
                    _ => 8,
                };
                for ib in 0..=ibmax {
                    let bit = ibmax - ib;
                    let mut m1 = f32::NEG_INFINITY;
                    let mut m0 = f32::NEG_INFINITY;
                    for i in 0..nt {
                        if (i >> bit) & 1 == 1 {
                            m1 = m1.max(s2[i]);
                        } else {
                            m0 = m0.max(s2[i]);
                        }
                    }
                    let bm = m1 - m0;
                    if i32_ + ib > 174 {
                        continue;
                    }
                    let idx = i32_ + ib - 1;
                    match nsym {
                        1 => {
                            bmeta[idx] = bm;
                            let den = m1.max(m0);
                            bmetd[idx] = if den > 0.0 { bm / den } else { 0.0 };
                        }
                        2 => bmetb[idx] = bm,
                        _ => bmetc[idx] = bm,
                    }
                }
                k += nsym;
            }
        }
    }
    normalizebmet(&mut bmeta);
    normalizebmet(&mut bmetb);
    normalizebmet(&mut bmetc);
    normalizebmet(&mut bmetd);
    let scalefac = 2.83f32;
    let mut llr = [[0f32; NBITS]; 4];
    for i in 0..NBITS {
        llr[0][i] = scalefac * bmeta[i];
        llr[1][i] = scalefac * bmetb[i];
        llr[2][i] = scalefac * bmetc[i];
        llr[3][i] = scalefac * bmetd[i];
    }
    Some(Ft8Metrics {
        f1,
        xdt,
        ibest,
        delfbest,
        sync: smax,
        nsync,
        s8,
        llr,
    })
}

// ---------------------------------------------------------------- stage 4

// AP message templates from ft8b.f90 (bits; mapped to +/-1 at use).
const MCQ: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0,
];
const MRRR: [u8; 19] = [0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1];
const M73: [u8; 19] = [0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1];
const MRR73: [u8; 19] = [0, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 0, 1];
const NAPPASSES: [usize; 6] = [2, 2, 2, 4, 4, 3];
const NAPTYPES: [[i32; 4]; 6] = [
    [1, 2, 0, 0],
    [2, 3, 0, 0],
    [2, 3, 0, 0],
    [3, 4, 5, 6],
    [3, 4, 5, 6],
    [3, 1, 2, 0],
];

#[inline]
fn pm(b: u8) -> f32 {
    2.0 * b as f32 - 1.0
}

/// What ft8b returns for one candidate.
#[derive(Clone, Debug)]
pub struct Ft8bOut {
    /// The candidate decoded (nbadcrc = 0).
    pub decoded: Option<Ft8Decode>,
    /// Tones to subtract, if WSJT-X would have subtracted: every valid
    /// decode, including the ones it then throws away as likely false
    /// (nsync <= 10 and SNR < -24 dB) - it subtracts before that test.
    pub subtract: Option<([u8; 79], f32, f32)>,
    /// The payload of every decode that passed unpack77, kept or not: ft8b
    /// unpacks each one, and unpacking remembers the calls it saw.
    pub payload: Option<[u8; 77]>,
}

/// Payload validity tests ft8b makes after the CRC (i3/n3 ranges), plus
/// unpack77's success test, supplied by the caller (`unpack_ok`) because it
/// needs call tables.
pub type UnpackOk<'a> = &'a (dyn Fn(&[u8; 77]) -> bool + Sync);

fn payload_plausible(m: &[u8; 77]) -> bool {
    let n3 = (m[71] << 2 | m[72] << 1 | m[73]) as i32;
    let i3 = (m[74] << 2 | m[75] << 1 | m[76]) as i32;
    if i3 > 5 || (i3 == 0 && n3 > 6) {
        return false;
    }
    if i3 == 0 && n3 == 2 {
        return false;
    }
    true
}

/// ft8b.f90: one candidate through fine sync, metrics, the LDPC passes
/// (regular, then a-priori), validity checks and the SNR estimate.
#[allow(clippy::too_many_arguments)]
pub fn ft8b(
    ds: &Downsampler,
    p: &Ft8Params,
    ndepth: i32,
    nzhsym: i32,
    f1_in: f32,
    xdt_in: f32,
    xbase: f32,
    sync_cand: f32,
    unpack_ok: Option<UnpackOk>,
) -> Ft8bOut {
    let none = Ft8bOut {
        decoded: None,
        subtract: None,
        payload: None,
    };
    let Some(mt) = ft8_metrics(ds, f1_in, xdt_in) else {
        return none;
    };
    let f1 = mt.f1;
    let apmag = mt.llr[0].iter().fold(0f32, |a, &b| a.max(b.abs())) * 1.01;

    // apsym as ft8apset leaves it: +/-1 bits, or 99 in slots 1/30 when the
    // call is unknown.
    let mut apsym = [0f32; 58];
    let mut have_my = false;
    let mut have_dx = false;
    if let Some(ap) = &p.ap {
        for i in 0..58 {
            apsym[i] = pm(ap.payload[i]);
        }
        have_my = true;
        have_dx = ap.has_dxcall;
    }

    let npasses = if nzhsym < 50 {
        4
    } else if p.lapon {
        if !p.lapcqonly {
            4 + NAPPASSES[p.nqso_progress]
        } else {
            5
        }
    } else {
        4
    };

    for ipass in 1..=npasses {
        let mut llrz = match ipass {
            2 => mt.llr[1],
            3 => mt.llr[2],
            4 => mt.llr[3],
            _ => mt.llr[0],
        };
        let mut apmask = [0u8; NBITS];
        let mut iaptype = 0;
        if ipass > 4 {
            iaptype = if !p.lapcqonly {
                NAPTYPES[p.nqso_progress][ipass - 5]
            } else {
                1
            };
            // ncontest = 0 only (see the module note in decode/mod.rs).
            if iaptype >= 3 && (f1 - p.nfqso as f32).abs() > p.napwid && (f1 - p.nftx as f32).abs() > p.napwid {
                continue;
            }
            if iaptype >= 2 && !have_my {
                continue;
            }
            if iaptype >= 3 && !have_dx {
                continue;
            }
            match iaptype {
                1 => {
                    for i in 0..29 {
                        apmask[i] = 1;
                        llrz[i] = apmag * pm(MCQ[i]);
                    }
                    apmask[74] = 1;
                    apmask[75] = 1;
                    apmask[76] = 1;
                    llrz[74] = -apmag;
                    llrz[75] = -apmag;
                    llrz[76] = apmag;
                }
                2 => {
                    for i in 0..29 {
                        apmask[i] = 1;
                        llrz[i] = apmag * apsym[i];
                    }
                    apmask[74] = 1;
                    apmask[75] = 1;
                    apmask[76] = 1;
                    llrz[74] = -apmag;
                    llrz[75] = -apmag;
                    llrz[76] = apmag;
                }
                3 => {
                    for i in 0..58 {
                        apmask[i] = 1;
                        llrz[i] = apmag * apsym[i];
                    }
                    apmask[74] = 1;
                    apmask[75] = 1;
                    apmask[76] = 1;
                    llrz[74] = -apmag;
                    llrz[75] = -apmag;
                    llrz[76] = apmag;
                }
                4..=6 => {
                    for i in 0..77 {
                        apmask[i] = 1;
                    }
                    for i in 0..58 {
                        llrz[i] = apmag * apsym[i];
                    }
                    let tail = match iaptype {
                        4 => &MRRR,
                        5 => &M73,
                        _ => &MRR73,
                    };
                    for i in 0..19 {
                        llrz[58 + i] = apmag * pm(tail[i]);
                    }
                }
                _ => continue,
            }
        }

        let maxosd = match ndepth {
            1 => -1,
            2 => 0,
            _ => 2,
        };
        let r = decode174_91(&llrz, maxosd, 2, &apmask);
        if r.nharderror < 0 || r.nharderror > 36 {
            continue;
        }
        if r.cw.iter().all(|&b| b == 0) {
            continue;
        }
        let mut m77 = [0u8; 77];
        m77.copy_from_slice(&r.message91[..77]);
        if !payload_plausible(&m77) {
            continue;
        }
        if let Some(f) = unpack_ok {
            if !f(&m77) {
                continue;
            }
        }
        let itone = ft8_tones(&m77);
        let subtract = Some((itone, f1, mt.xdt));
        let mut xsig = 0f32;
        let mut xnoi = 0f32;
        for i in 0..79 {
            xsig += mt.s8[i][itone[i] as usize].powi(2);
            let ios = (itone[i] as usize + 4) % 7;
            xnoi += mt.s8[i][ios].powi(2);
        }
        let _ = xnoi; // WSJT-X computes the noise-ratio SNR too but reports xsnr2 unless nagain.
        let mut xsnr2 = 0.001f32;
        let arg = xsig / xbase / 3.0e6 - 1.0;
        if arg > 0.1 {
            xsnr2 = arg;
        }
        let mut xsnr = 10.0 * xsnr2.log10() - 27.0;
        if mt.nsync <= 10 && xsnr < -24.0 {
            return Ft8bOut {
                decoded: None,
                subtract,
                payload: Some(m77),
            };
        }
        if xsnr < -24.0 {
            xsnr = -24.0;
        }
        let qual = 1.0 - (r.nharderror as f32 + r.dmin) / 60.0;
        return Ft8bOut {
            payload: Some(m77),
            decoded: Some(Ft8Decode {
                text: String::new(),
                payload: m77,
                snr: nint(xsnr),
                dt: mt.xdt - 0.5,
                freq: f1,
                sync: sync_cand,
                iaptype,
                nharderrors: r.nharderror,
                dmin: r.dmin,
                qual,
                tones: itone,
                nzhsym,
                ipass: 0,
            }),
            subtract,
        };
    }
    none
}

// ---------------------------------------------------------------- stage 5

/// gen_ft8wave.f90 with icmplx=1: the complex reference waveform, through
/// WSJT-X's 65536-entry phase table.
pub fn gen_ft8wave_complex(
    itone: &[u8],
    nsym: usize,
    nsps: usize,
    bt: f32,
    fsample: f32,
    f0: f32,
    nwave: usize,
) -> Vec<C32> {
    const NTAB: usize = 65536;
    static CTAB: OnceLock<Vec<C32>> = OnceLock::new();
    let tp = twopi();
    let ctab = CTAB.get_or_init(|| {
        (0..NTAB)
            .map(|i| {
                let phi = i as f32 * tp / NTAB as f32;
                C32::new(phi.cos(), phi.sin())
            })
            .collect()
    });
    let dt = 1.0f32 / fsample;
    let pulse = super::util::gfsk_pulse_table(bt, nsps);
    let dphi_peak = tp * 1.0 / nsps as f32;
    let mut dphi = vec![0f32; (nsym + 2) * nsps];
    for j in 0..nsym {
        let ib = j * nsps;
        for t in 0..3 * nsps {
            dphi[ib + t] += dphi_peak * pulse[t] * itone[j] as f32;
        }
    }
    for t in 0..2 * nsps {
        dphi[t] += dphi_peak * itone[0] as f32 * pulse[nsps + t];
        dphi[nsym * nsps + t] += dphi_peak * itone[nsym - 1] as f32 * pulse[t];
    }
    let mut phi = 0f32;
    let fstep = tp * f0 * dt;
    for v in dphi.iter_mut() {
        *v += fstep;
    }
    let mut cw = vec![C32::new(0.0, 0.0); nwave];
    for (k, j) in (nsps..nsps + nwave).enumerate() {
        let i = (phi * NTAB as f32 / tp) as usize;
        cw[k] = ctab[i.min(NTAB - 1)];
        phi = (phi + dphi[j]) % tp;
    }
    let nramp = nint(nsps as f32 / 8.0) as usize;
    for i in 0..nramp {
        cw[i] *= (1.0 - (tp * i as f32 / (2.0 * nramp as f32)).cos()) / 2.0;
    }
    let k1 = nsym * nsps - nramp;
    for i in 0..nramp {
        cw[k1 + i] *= (1.0 + (tp * i as f32 / (2.0 * nramp as f32)).cos()) / 2.0;
    }
    cw
}

struct SubFilter {
    cw: Vec<C32>,
    endcorrection: Vec<f32>,
}

const NFILT: usize = 4000;
const NFRAME: usize = NSPS * NN;

fn sub_filter() -> &'static SubFilter {
    static F: OnceLock<SubFilter> = OnceLock::new();
    F.get_or_init(|| {
        let pi = 4.0f32 * 1f32.atan();
        let nfft = NMAX;
        let fac = 1.0f32 / nfft as f32;
        let half = (NFILT / 2) as i32;
        let window: Vec<f32> = (-half..=half)
            .map(|j| (pi * j as f32 / NFILT as f32).cos().powi(2))
            .collect();
        let sumw: f32 = window.iter().sum();
        let mut cw = vec![C32::new(0.0, 0.0); nfft];
        for (t, w) in window.iter().enumerate() {
            cw[t] = C32::new(w / sumw, 0.0);
        }
        // cshift(cw, NFILT/2+1): the Fortran's own alignment, kept (it puts
        // the filter's centre one sample before t=0).
        cw.rotate_left(NFILT / 2 + 1);
        fft_fwd(&mut cw);
        for v in cw.iter_mut() {
            *v *= fac;
        }
        // endcorrection(j) = 1/(1 - sum(window(j-1:NFILT/2))/sumw), j=1..NFILT/2+1
        let endcorrection = (1..=NFILT / 2 + 1)
            .map(|j| {
                // window index (j-1) in -half..half -> vector index j-1+half
                let from = j - 1 + half as usize;
                let s: f32 = window[from..].iter().sum();
                1.0 / (1.0 - s / sumw)
            })
            .collect();
        SubFilter { cw, endcorrection }
    })
}

/// subtractft8.f90: remove a decoded signal from the audio, estimating its
/// complex amplitude by low-pass filtering audio x conj(reference). With
/// `lrefinedt`, first tries +-90 samples and moves to the parabolic
/// minimum of residual power (giving up if that lies outside the bracket).
pub fn subtractft8(dd: &mut [f32], itone: &[u8; 79], f0: f32, dt: f32, lrefinedt: bool) {
    let cref = gen_ft8wave_complex(itone, 79, NSPS, 2.0, 12000.0, f0, NFRAME);
    let flt = sub_filter();
    let dd0: Vec<f32> = dd[..NMAX].to_vec();

    let sqf = |idt: i32, measure: bool, out: &mut [f32]| -> f32 {
        let nstart = (dt * 12000.0 + 1.0 + idt as f32) as i32; // Fortran truncation
        out[..NMAX].copy_from_slice(&dd0);
        let mut cfilt = vec![C32::new(0.0, 0.0); NMAX];
        for i in 0..NFRAME {
            let j = nstart + i as i32; // 1-based index nstart-1+(i+1)
            if j >= 1 && j as usize <= NMAX {
                cfilt[i] = out[j as usize - 1] * cref[i].conj();
            }
        }
        fft_fwd(&mut cfilt);
        for (c, w) in cfilt.iter_mut().zip(flt.cw.iter()) {
            *c *= *w;
        }
        fft_inv(&mut cfilt);
        for j in 0..=NFILT / 2 {
            cfilt[j] *= flt.endcorrection[j];
            cfilt[NFRAME - 1 - j] *= flt.endcorrection[j];
        }
        let mut x = if measure { vec![0f32; NMAX] } else { vec![] };
        for i in 0..NFRAME {
            let j = nstart + i as i32;
            if j >= 1 && j as usize <= NMAX {
                let z = cfilt[i] * cref[i];
                out[j as usize - 1] -= 2.0 * z.re;
                if measure {
                    x[i] = out[j as usize - 1];
                }
            }
        }
        if !measure {
            return 0.0;
        }
        let cx = rfft(&x, NMAX);
        let df = 12000.0f32 / NMAX as f32;
        let ia = ((f0 - 1.5 * 6.25) / df) as usize;
        let ib = ((f0 + 8.5 * 6.25) / df) as usize;
        let mut sqq = 0f32;
        for i in ia..=ib {
            sqq += cx[i].re * cx[i].re + cx[i].im * cx[i].im;
        }
        sqq
    };

    let mut work = vec![0f32; NMAX];
    if lrefinedt {
        // The three trial subtractions each start from the original audio,
        // so they are independent: run them side by side.
        let (mut wa, mut wb) = (vec![0f32; NMAX], vec![0f32; NMAX]);
        let ((sqa, sqb), sq0) = rayon::join(
            || rayon::join(|| sqf(-90, true, &mut wa), || sqf(90, true, &mut wb)),
            || sqf(0, true, &mut work),
        );
        let b = (sqb - sqa) / 2.0;
        let c = (sqb + sqa - 2.0 * sq0) / 2.0;
        let dx = -b / (2.0 * c);
        if dx.abs() > 1.0 || dx.is_nan() {
            return;
        }
        let i2 = nint(90.0 * dx);
        sqf(i2, false, &mut work);
    } else {
        sqf(0, false, &mut work);
    }
    dd[..NMAX].copy_from_slice(&work);
}

// ------------------------------------------------------- the pass structure

/// What a whole-slot decode returns, with the residual audio for tests.
pub struct Ft8SlotResult {
    pub decodes: Vec<Ft8Decode>,
    /// The audio after every subtraction (dd at the end of the last call).
    pub residual: Vec<f32>,
}

const MAX_EARLY: usize = 200;

struct DecState {
    dd: Vec<f32>,
    dd1: Vec<f32>,
    ndec_early: usize,
    saves: Vec<([u8; 79], f32, f32)>, // itone, f1, xdt(+0.5 absolute)
    lsubtracted: Vec<bool>,
    allmessages: Vec<String>,
    out: Vec<Ft8Decode>,
}

/// One call of ft8_decode's `decode` (one nzhsym), for nagain = false.
fn decode_call(st: &mut DecState, iwave: &[f32], nzhsym: i32, p: &Ft8Params, hashes: &mut CallHashes) {
    let ndepth = p.ndepth;
    if ndepth == 1 && nzhsym < 50 {
        st.ndec_early = 0;
        return;
    }
    if ndepth == 1 && nzhsym == 50 {
        st.dd.copy_from_slice(iwave);
    }
    if nzhsym <= 47 {
        st.dd.copy_from_slice(iwave);
        st.dd1.copy_from_slice(iwave);
    }
    let mut ndecodes;
    if nzhsym == 41 {
        ndecodes = 0;
        st.allmessages.clear();
        st.saves.clear();
    } else {
        ndecodes = st.ndec_early;
        st.allmessages.truncate(ndecodes);
        st.saves.truncate(ndecodes);
    }
    if nzhsym == 47 && st.ndec_early == 0 {
        st.dd1.copy_from_slice(&st.dd);
        st.ndec_early = 0;
        return;
    }
    if nzhsym == 47 && st.ndec_early >= 1 {
        st.lsubtracted = vec![false; MAX_EARLY];
        let lrefinedt = ndepth > 2;
        for i in 0..st.ndec_early {
            let (it, f1, xdt) = st.saves[i];
            if xdt - 0.5 < 0.396 {
                subtractft8(&mut st.dd, &it, f1, xdt, lrefinedt);
                st.lsubtracted[i] = true;
            }
        }
        st.dd1.copy_from_slice(&st.dd);
        return; // "go to 900": ndec_early kept for the 50 call
    }
    if nzhsym == 50 && st.ndec_early >= 1 {
        let n = 47 * 3456;
        let (a, b) = st.dd.split_at_mut(n);
        a.copy_from_slice(&st.dd1[..n]);
        b.copy_from_slice(&iwave[n..]);
        for i in 0..st.ndec_early {
            if st.lsubtracted.get(i).copied().unwrap_or(false) {
                continue;
            }
            let (it, f1, xdt) = st.saves[i];
            subtractft8(&mut st.dd, &it, f1, xdt, true);
        }
    }

    let npass = if ndepth == 1 { 2 } else { 3 };
    let mut n2 = 0;
    for ipass in 1..=npass {
        let mut syncmin = 1.3f32;
        if ndepth <= 2 {
            syncmin = 1.6;
        }
        if nzhsym == 41 {
            syncmin = 2.0;
        }

        let ndeep = if ipass == 1 {
            if ndepth == 3 {
                2
            } else {
                ndepth
            }
        } else if ipass == 2 {
            n2 = ndecodes;
            if ndecodes == 0 {
                continue;
            }
            ndepth
        } else {
            if ndecodes - n2 == 0 {
                continue;
            }
            ndepth
        };
        let (cands, sbase) = sync8(&st.dd, p.nfa, p.nfb, syncmin, p.nfqso, p.maxcand);
        let ds = Downsampler::new(&st.dd);
        // ft8b rejects what unpack77 cannot unpack. Candidates run in
        // parallel, so each test unpacks into a copy of the tables as they
        // stood at the start of the pass; the real tables are then updated
        // below, in candidate order, as WSJT-X's serial loop would.
        let snapshot = hashes.clone();
        let ok = |m: &[u8; 77]| unpack77(m, true, &mut snapshot.clone()).ok;
        let unpack_ok: Option<UnpackOk> = Some(&ok);
        let run = |c: &Candidate| {
            let ib = nint(c.freq / 3.125).clamp(0, NH1 as i32) as usize;
            let xbase = 10f32.powf(0.1 * (sbase[ib] - 40.0));
            ft8b(&ds, p, ndeep, nzhsym, c.freq, c.dt, xbase, c.sync, unpack_ok)
        };
        let results: Vec<Ft8bOut> = if p.threads != 1 {
            cands.par_iter().map(run).collect()
        } else {
            cands.iter().map(run).collect()
        };
        for r in results {
            if let Some((it, f1, xdt)) = r.subtract {
                subtractft8(&mut st.dd, &it, f1, xdt, false);
            }
            let text = match &r.payload {
                Some(m) => unpack77(m, true, hashes).text_lossy(),
                None => continue,
            };
            let Some(mut d) = r.decoded else { continue };
            d.text = text;
            // WSJT-X compares the unpacked text, not the bits.
            let ldupe = st.allmessages.contains(&d.text);
            if ldupe {
                continue;
            }
            if ndecodes >= MAX_EARLY {
                continue;
            }
            ndecodes += 1;
            st.allmessages.push(d.text.clone());
            st.saves.push((d.tones, d.freq, d.dt + 0.5));
            d.ipass = ipass;
            st.out.push(d);
        }
    }
    st.ndec_early = if nzhsym < 50 { ndecodes } else { 0 };
}

/// Decode one 15 s FT8 slot: `audio` is 12 kHz, in 16-bit sample units
/// (what jt9 reads from its WAV), slot start at index 0; shorter input is
/// zero padded. `hashes` are the session's call tables (a receiver keeps
/// one): decodes are unpacked into them, so a hashed call heard in full
/// earlier is shown by name.
pub fn decode_slot(audio: &[f32], p: &Ft8Params, hashes: &mut CallHashes) -> Ft8SlotResult {
    super::util::with_pool(p.threads, || decode_slot_in_pool(audio, p, hashes))
}

fn decode_slot_in_pool(audio: &[f32], p: &Ft8Params, hashes: &mut CallHashes) -> Ft8SlotResult {
    let mut iwave = vec![0f32; NMAX];
    let n = audio.len().min(NMAX);
    iwave[..n].copy_from_slice(&audio[..n]);
    let mut st = DecState {
        dd: vec![0f32; NMAX],
        dd1: vec![0f32; NMAX],
        ndec_early: 0,
        saves: vec![],
        lsubtracted: vec![false; MAX_EARLY],
        allmessages: vec![],
        out: vec![],
    };
    if p.jt9_file_mode {
        // jt9.f90's file mode: nzhsym 41 and 47 on the slot cut short and
        // zero filled, then 50 on all of it (only 50 does anything at
        // depth 1).
        for (nz, keep) in [(41, 41 * 3456), (47, 47 * 3456), (50, 50 * 3456)] {
            let mut cut = iwave.clone();
            for v in cut[keep.min(NMAX)..].iter_mut() {
                *v = 0.0;
            }
            decode_call(&mut st, &cut, nz, p, hashes);
        }
    } else {
        decode_call(&mut st, &iwave, 50, p, hashes);
    }
    Ft8SlotResult {
        decodes: st.out,
        residual: st.dd,
    }
}
