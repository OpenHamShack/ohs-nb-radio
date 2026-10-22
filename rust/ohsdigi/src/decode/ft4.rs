//! FT4 decoding, as WSJT-X 2.7.0 does it.
//!
//! Ported from WSJT-X 2.7.0 (GPL-3): lib/ft4_decode.f90,
//! lib/ft4/getcandidates4.f90, ft4_baseline.f90, ft4_downsample.f90,
//! sync4d.f90, get_ft4_bitmetrics.f90, subtractft4.f90, gen_ft4wave.f90,
//! lib/ft8/twkfreq1.f90. Copyright (C) 2001-2024 Joe Taylor K1JT, Steve
//! Franke K9AN, Bill Somerville G4WJS and the WSJT-X development team.
//!
//! Same shape as `ft8`: candidates from a smoothed average spectrum, a
//! coarse-then-fine time/frequency search over three DT segments, three
//! sets of bit metrics (1, 2 and 4 symbols coherently), LDPC, subtraction.
//! Within a pass candidates are decoded in parallel and subtracted after,
//! in order - equivalent to WSJT-X's serial loop for the reason given in
//! ft8.rs (the downsampler's FFT is taken once per pass).
//!
//! One deliberate difference: ft4_decode.f90 sets `napwid=80` only inside
//! its a-priori branch, so on the regular passes (1-3) of a slot's first
//! candidate the variable is uninitialised when it picks the OSD depth.
//! This port uses 80 throughout, which is what the code evidently means.
//! (At depth 1, jt9's default and NB's, OSD is off and it does not arise.)

use super::ap::ApCalls;
use super::ldpc::decode174_91;
use super::util::{fft_fwd, fft_inv, maxloc, nint, normalizebmet, nuttall_window, pctile, polyfit, rfft, C32};
use crate::ft4::{tones as ft4_tones, COSTAS as ICOS4, GRAY as GRAYMAP4, RVEC as FT4_RVEC};
use crate::ldpc::ldpc174_91::{encode as encode174_91, N as NBITS};
use crate::msg77::{unpack77, CallHashes};
use rayon::prelude::*;
use std::sync::OnceLock;

// ft4_params.f90
pub const NN: usize = 103;
pub const NSPS: usize = 576;
pub const NMAX: usize = 21 * 3456;
pub const NFFT1: usize = 2304;
pub const NH1: usize = NFFT1 / 2;
pub const NSTEP: usize = NSPS;
pub const NHSYM: usize = (NMAX - NFFT1) / NSTEP;
pub const NDOWN: usize = 18;
const NSS: usize = NSPS / NDOWN; // 32
const NDMAX: usize = NMAX / NDOWN; // 4032
const NFFT2: usize = NMAX / NDOWN;
const MAXCAND: usize = 100;

#[inline]
fn twopi() -> f32 {
    8.0f32 * 1f32.atan()
}

#[derive(Clone, Copy, Debug, PartialEq)]
pub struct Candidate4 {
    pub freq: f32,
    /// Smoothed spectrum / baseline at the peak ("snr" + 1 in ft4_decode).
    pub strength: f32,
}

#[derive(Clone, Debug)]
pub struct Ft4Params {
    pub nfa: f32,
    pub nfb: f32,
    pub nfqso: i32,
    /// 1: one pass, BP only, no subtraction (jt9's default). 2: three
    /// passes with subtraction, BP only. 3: three passes, BP + OSD.
    pub ndepth: i32,
    pub lapcqonly: bool,
    pub nqso_progress: usize,
    /// MyCall/DxCall for AP, from ap::ft4_ap ("MYCALL DXCALL RR73", as
    /// ft4_decode builds its AP bits); None = no MyCall.
    pub ap: Option<ApCalls>,
    /// Decoder threads (util::with_pool): 0 = cores - 1, 1 = one core.
    pub threads: usize,
    /// Record each stage in the verification harness's line format
    /// (harness/ft8h.f90's FT4 lines). Off in use: it costs allocations.
    pub trace: bool,
}

impl Ft4Params {
    /// Exactly what `jt9 -5 [-d N] file.wav` does, dummy calls included
    /// (they matter only at depth >= 2: depth 1 runs no AP passes).
    pub fn jt9() -> Self {
        Ft4Params {
            ap: super::ap::ft4_ap(super::ft8::JT9_MYCALL, super::ft8::JT9_DXCALL),
            ..Default::default()
        }
    }
}

impl Default for Ft4Params {
    fn default() -> Self {
        Ft4Params {
            nfa: 200.0,
            nfb: 4000.0,
            nfqso: 1500,
            ndepth: 1,
            lapcqonly: false,
            nqso_progress: 0,
            ap: None,
            threads: 0,
            trace: false,
        }
    }
}

#[derive(Clone, Debug)]
pub struct Ft4Decode {
    /// The message as WSJT-X shows it (unpack77, as received).
    pub text: String,
    /// Descrambled 77-bit payload.
    pub payload: [u8; 77],
    pub snr: i32,
    pub dt: f32,
    pub freq: f32,
    pub sync: f32,
    pub iaptype: i32,
    pub nharderrors: i32,
    pub dmin: f32,
    pub qual: f32,
    pub ipass: i32,
}

// ---------------------------------------------------------------- stage 1

/// getcandidates4.f90 (+ ft4_baseline.f90).
pub fn getcandidates4(dd: &[f32], fa: f32, fb: f32, syncmin: f32, nfqso: i32, maxcand: usize) -> Vec<Candidate4> {
    static WINDOW: OnceLock<Vec<f32>> = OnceLock::new();
    let window = WINDOW.get_or_init(|| nuttall_window(NFFT1));
    let df = 12000.0f32 / NFFT1 as f32;
    let fac = 1.0f32 / 300.0;
    let mut savg = vec![0f32; NH1 + 1];
    for j in 1..=NHSYM {
        let ia = (j - 1) * NSTEP;
        let ib = ia + NFFT1;
        if ib > NMAX {
            break;
        }
        let x: Vec<f32> = dd[ia..ib].iter().zip(window.iter()).map(|(a, w)| fac * a * w).collect();
        let cx = rfft(&x, NFFT1);
        for i in 1..=NH1 {
            savg[i] += cx[i].norm_sqr();
        }
    }
    for v in savg.iter_mut() {
        *v /= NHSYM as f32;
    }
    let mut savsm = vec![0f32; NH1 + 1];
    for i in 8..=NH1 - 7 {
        let s: f32 = savg[i - 7..=i + 7].iter().sum();
        savsm[i] = s / 15.0;
    }
    let mut nfa = (fa / df) as i32;
    if nfa < nint(200.0 / df) {
        nfa = nint(200.0 / df);
    }
    let mut nfb = (fb / df) as i32;
    if nfb > nint(4910.0 / df) {
        nfb = nint(4910.0 / df);
    }
    let sbase = ft4_baseline(&mut savg, nfa, nfb);
    if (nfa..=nfb).any(|i| sbase[i as usize] <= 0.0) {
        return vec![];
    }
    for i in nfa..=nfb {
        savsm[i as usize] /= sbase[i as usize];
    }
    let f_offset = -1.5 * 12000.0 / NSPS as f32;
    let mut ct: Vec<Candidate4> = Vec::new();
    for i in (nfa + 1)..=(nfb - 1) {
        let i = i as usize;
        if savsm[i] >= savsm[i - 1] && savsm[i] >= savsm[i + 1] && savsm[i] >= syncmin {
            let den = savsm[i - 1] - 2.0 * savsm[i] + savsm[i + 1];
            let del = if den != 0.0 {
                0.5 * (savsm[i - 1] - savsm[i + 1]) / den
            } else {
                0.0
            };
            let fpeak = (i as f32 + del) * df + f_offset;
            if !(200.0..=4910.0).contains(&fpeak) {
                continue;
            }
            let speak = savsm[i] - 0.25 * (savsm[i - 1] - savsm[i + 1]) * del;
            ct.push(Candidate4 {
                freq: fpeak,
                strength: speak,
            });
            if ct.len() == maxcand {
                break;
            }
        }
    }
    let mut out: Vec<Candidate4> = ct
        .iter()
        .copied()
        .filter(|c| (c.freq - nfqso as f32).abs() <= 20.0)
        .collect();
    out.extend(ct.iter().copied().filter(|c| (c.freq - nfqso as f32).abs() > 20.0));
    out
}

/// ft4_baseline.f90: converts s to dB over ia..ib in place (as the
/// Fortran does) and returns the fitted baseline, linear.
fn ft4_baseline(s: &mut [f32], nfa: i32, nfb: i32) -> Vec<f32> {
    let df = 12000.0f64 / NFFT1 as f64;
    let ia = ((200.0 / df).round() as i32).max(nfa) as usize;
    let ib = (NH1 as i32).min(nfb) as usize;
    for i in ia..=ib {
        s[i] = 10.0 * s[i].log10();
    }
    let nseg = 10;
    let nlen = (ib - ia + 1) / nseg;
    let i0 = (ib - ia).div_ceil(2) as f64;
    let mut x = vec![0f64; 1000];
    let mut y = vec![0f64; 1000];
    let mut k = 0usize;
    for n in 1..=nseg {
        let ja = ia + (n - 1) * nlen;
        let jb = ja + nlen - 1;
        let base = pctile(&s[ja..ja + nlen], 10);
        for i in ja..=jb {
            if s[i] <= base {
                if k < 1000 {
                    k += 1;
                }
                x[k - 1] = i as f64 - i0;
                y[k - 1] = s[i] as f64;
            }
        }
    }
    let a = polyfit(&x[..k], &y[..k], 5);
    let mut sbase = vec![0f32; NH1 + 1];
    for i in ia..=ib {
        let t = i as f64 - i0;
        let db = (a[0] + t * (a[1] + t * (a[2] + t * (a[3] + t * a[4]))) + 0.65) as f32;
        sbase[i] = 10f32.powf(db / 10.0);
    }
    sbase
}

// ---------------------------------------------------------------- stage 2

pub struct Downsampler4 {
    cx: Vec<C32>,
}

impl Downsampler4 {
    pub fn new(dd: &[f32]) -> Self {
        Downsampler4 {
            cx: rfft(&dd[..NMAX], NMAX),
        }
    }

    /// ft4_downsample.f90: 18x decimation around f0 (32 samples a symbol).
    pub fn downsample(&self, f0: f32) -> Vec<C32> {
        static WINDOW: OnceLock<Vec<f32>> = OnceLock::new();
        let df = 12000.0f32 / NMAX as f32;
        let baud = 12000.0f32 / NSPS as f32;
        let window = WINDOW.get_or_init(|| {
            let bw_transition = 0.5 * baud;
            let bw_flat = 4.0 * baud;
            let iwt = (bw_transition / df) as usize;
            let iwf = (bw_flat / df) as usize;
            let pi = 4.0f32 * 1f32.atan();
            let mut w = vec![0f32; NFFT2];
            for m in 0..iwt {
                w[m] = 0.5 * (1.0 + (pi * (iwt - 1 - m) as f32 / iwt as f32).cos());
            }
            for m in iwt..iwt + iwf {
                w[m] = 1.0;
            }
            for m in 0..iwt {
                w[iwt + iwf + m] = 0.5 * (1.0 + (pi * m as f32 / iwt as f32).cos());
            }
            let iws = (baud / df) as usize;
            w.rotate_left(iws);
            w
        });
        let i0 = nint(f0 / df);
        let half = (NMAX / 2) as i32;
        let mut c1 = vec![C32::new(0.0, 0.0); NFFT2];
        if i0 >= 0 && i0 <= half {
            c1[0] = self.cx[i0 as usize];
        }
        for i in 1..=(NFFT2 / 2) as i32 {
            if i0 + i >= 0 && i0 + i <= half {
                c1[i as usize] = self.cx[(i0 + i) as usize];
            }
            if i0 - i >= 0 && i0 - i <= half {
                c1[NFFT2 - i as usize] = self.cx[(i0 - i) as usize];
            }
        }
        for (c, w) in c1.iter_mut().zip(window.iter()) {
            *c = *c * *w / NFFT2 as f32;
        }
        fft_inv(&mut c1);
        c1
    }
}

struct Sync4Tables {
    csync: [[C32; 2 * NSS]; 4],
    ctwk2: Vec<[C32; 2 * NSS]>, // idf = -16..16
}

fn sync4_tables() -> &'static Sync4Tables {
    static T: OnceLock<Sync4Tables> = OnceLock::new();
    T.get_or_init(|| {
        let tp = twopi();
        let mut csync = [[C32::new(0.0, 0.0); 2 * NSS]; 4];
        for (a, row) in csync.iter_mut().enumerate() {
            let mut phi = 0f32;
            let mut k = 0;
            for i in 0..4 {
                let dphi = 2.0 * tp * ICOS4[a][i] as f32 / NSS as f32;
                for _ in 0..NSS / 2 {
                    row[k] = C32::new(phi.cos(), phi.sin());
                    phi = (phi + dphi) % tp;
                    k += 1;
                }
            }
        }
        // twkfreq1 on a vector of ones with only a(1)=idf, at fs/2.
        let fs = 12000.0f32 / NDOWN as f32;
        let twopi_t = 6.283_185_5_f32;
        let ctwk2 = (-16..=16)
            .map(|idf: i32| {
                let mut out = [C32::new(0.0, 0.0); 2 * NSS];
                let mut w = C32::new(1.0, 0.0);
                let dphi = idf as f32 * (twopi_t / (fs / 2.0));
                let wstep = C32::new(dphi.cos(), dphi.sin());
                for o in out.iter_mut() {
                    w *= wstep;
                    *o = w;
                }
                out
            })
            .collect();
        Sync4Tables { csync, ctwk2 }
    })
}

/// sync4d.f90 (always with the frequency tweak, as ft4_decode calls it).
pub fn sync4d(cd0: &[C32], i0: i32, idf: i32) -> f32 {
    let t = sync4_tables();
    let ctwk = &t.ctwk2[(idf + 16) as usize];
    let np = NDMAX as i32;
    let fac = 1.0f32 / (2.0 * NSS as f32);
    let p = |z: C32| {
        let z = z * fac;
        (z.re * z.re + z.im * z.im).sqrt()
    };
    let mk = |a: usize| -> [C32; 2 * NSS] {
        let mut c = [C32::new(0.0, 0.0); 2 * NSS];
        for j in 0..2 * NSS {
            c[j] = ctwk[j] * t.csync[a][j];
        }
        c
    };
    let i1 = i0;
    let i2 = i0 + 33 * NSS as i32;
    let i3 = i0 + 66 * NSS as i32;
    let i4 = i0 + 99 * NSS as i32;
    let span = 4 * NSS as i32 - 1;
    let full = |st: i32, cs: &[C32; 2 * NSS]| -> C32 {
        let mut z = C32::new(0.0, 0.0);
        for j in 0..2 * NSS {
            z += cd0[st as usize + 2 * j] * cs[j].conj();
        }
        z
    };
    let c = mk(0);
    let mut z1 = C32::new(0.0, 0.0);
    if i1 >= 0 && i1 + span < np {
        z1 = full(i1, &c);
    } else if i1 < 0 {
        let npts = (i1 + span) / 2;
        if npts > 16 {
            // cd0(0:i1+4*NSS-1:2) against csync2(2*NSS-npts:)
            let mut z = C32::new(0.0, 0.0);
            let mut j = 0i32;
            let mut q = 2 * NSS as i32 - npts - 1; // 0-based start in csync2
            while j <= i1 + span {
                z += cd0[j as usize] * c[q as usize].conj();
                j += 2;
                q += 1;
            }
            z1 = z;
        }
    }
    let c = mk(1);
    let z2 = if i2 >= 0 && i2 + span < np {
        full(i2, &c)
    } else {
        C32::new(0.0, 0.0)
    };
    let c = mk(2);
    let z3 = if i3 >= 0 && i3 + span < np {
        full(i3, &c)
    } else {
        C32::new(0.0, 0.0)
    };
    let c = mk(3);
    let mut z4 = C32::new(0.0, 0.0);
    if i4 >= 0 && i4 + span < np {
        z4 = full(i4, &c);
    } else if i4 + span > np - 1 {
        let npts = (np - 1 - i4 + 1) / 2;
        if npts > 16 {
            let mut z = C32::new(0.0, 0.0);
            for q in 0..npts {
                z += cd0[(i4 + 2 * q) as usize] * c[q as usize].conj();
            }
            z4 = z;
        }
    }
    p(z1) + p(z2) + p(z3) + p(z4)
}

// ---------------------------------------------------------------- stage 3

/// get_ft4_bitmetrics.f90: three columns (1, 2, 4 symbols coherently) of
/// 206 metrics, or None for a bad sync (fewer than 8 of 16 sync tones).
pub fn get_ft4_bitmetrics(cd: &[C32]) -> Option<Vec<[f32; 3]>> {
    let mut cs = vec![[C32::new(0.0, 0.0); 4]; NN];
    let mut s4 = vec![[0f32; 4]; NN];
    let mut csymb = [C32::new(0.0, 0.0); NSS];
    for k in 0..NN {
        csymb.copy_from_slice(&cd[k * NSS..(k + 1) * NSS]);
        fft_fwd(&mut csymb);
        for t in 0..4 {
            cs[k][t] = csymb[t];
            s4[k][t] = csymb[t].norm();
        }
    }
    let mut nsync = 0;
    for k in 0..4 {
        for (a, off) in [0usize, 33, 66, 99].iter().enumerate() {
            if maxloc(&s4[k + off]) == ICOS4[a][k] as usize {
                nsync += 1;
            }
        }
    }
    if nsync < 8 {
        return None;
    }
    let mut bm = vec![[0f32; 3]; 2 * NN];
    let mut s2 = [0f32; 256];
    for nseq in 1..=3usize {
        let nsym = match nseq {
            1 => 1,
            2 => 2,
            _ => 4,
        };
        let nt = 1usize << (2 * nsym);
        let mut ks = 1;
        while ks <= NN - nsym + 1 {
            for i in 0..nt {
                let i1 = i / 64;
                let i2 = (i & 63) / 16;
                let i3 = (i & 15) / 4;
                let i4 = i & 3;
                s2[i] = match nsym {
                    1 => cs[ks - 1][GRAYMAP4[i4] as usize].norm(),
                    2 => (cs[ks - 1][GRAYMAP4[i3] as usize] + cs[ks][GRAYMAP4[i4] as usize]).norm(),
                    _ => (cs[ks - 1][GRAYMAP4[i1] as usize]
                        + cs[ks][GRAYMAP4[i2] as usize]
                        + cs[ks + 1][GRAYMAP4[i3] as usize]
                        + cs[ks + 2][GRAYMAP4[i4] as usize])
                        .norm(),
                };
            }
            let ipt = 1 + (ks - 1) * 2;
            let ibmax = match nsym {
                1 => 1,
                2 => 3,
                _ => 7,
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
                if ipt + ib > 2 * NN {
                    continue;
                }
                bm[ipt + ib - 1][nseq - 1] = m1 - m0;
            }
            ks += nsym;
        }
    }
    for i in 204..206 {
        bm[i][1] = bm[i][0];
        bm[i][2] = bm[i][0];
    }
    for i in 200..204 {
        bm[i][2] = bm[i][1];
    }
    for col in 0..3 {
        let mut v: Vec<f32> = bm.iter().map(|r| r[col]).collect();
        normalizebmet(&mut v);
        for (r, x) in bm.iter_mut().zip(v) {
            r[col] = x;
        }
    }
    Some(bm)
}

// ---------------------------------------------------------------- stage 5

/// gen_ft4wave.f90, complex: no phase table here (unlike FT8's).
pub fn gen_ft4wave_complex(itone: &[u8], f0: f32) -> Vec<C32> {
    let nsym = itone.len();
    let nsps = NSPS;
    let tp = twopi();
    let dt = 1.0f32 / 12000.0;
    let pulse = super::util::gfsk_pulse_table(1.0, nsps);
    let dphi_peak = tp * 1.0 / nsps as f32;
    let n = (nsym + 2) * nsps;
    let mut dphi = vec![0f32; n.max(3 * nsps + nsym * nsps)];
    for j in 0..nsym {
        let ib = j * nsps;
        for t in 0..3 * nsps {
            dphi[ib + t] += dphi_peak * pulse[t] * itone[j] as f32;
        }
    }
    let fstep = tp * f0 * dt;
    for v in dphi.iter_mut() {
        *v += fstep;
    }
    let mut phi = 0f32;
    let mut cw = vec![C32::new(0.0, 0.0); n];
    for j in 0..n {
        cw[j] = C32::new(phi.cos(), phi.sin());
        phi = (phi + dphi[j]) % tp;
    }
    for i in 0..nsps {
        cw[i] *= (1.0 - (tp * i as f32 / (2.0 * nsps as f32)).cos()) / 2.0;
    }
    let k1 = (nsym + 1) * nsps;
    for i in 0..nsps {
        cw[k1 + i] *= (1.0 + (tp * i as f32 / (2.0 * nsps as f32)).cos()) / 2.0;
    }
    cw
}

const NFILT4: usize = 1400;
const NFRAME4: usize = (NN + 2) * NSPS;

fn sub_filter4() -> &'static Vec<C32> {
    static F: OnceLock<Vec<C32>> = OnceLock::new();
    F.get_or_init(|| {
        let pi = 4.0f32 * 1f32.atan();
        let half = (NFILT4 / 2) as i32;
        let window: Vec<f32> = (-half..=half)
            .map(|j| (pi * j as f32 / NFILT4 as f32).cos().powi(2))
            .collect();
        let sum: f32 = window.iter().sum();
        let mut cw = vec![C32::new(0.0, 0.0); NMAX];
        for (t, w) in window.iter().enumerate() {
            cw[t] = C32::new(w / sum, 0.0);
        }
        cw.rotate_left(NFILT4 / 2 + 1);
        fft_fwd(&mut cw);
        let fac = 1.0 / NMAX as f32;
        for v in cw.iter_mut() {
            *v *= fac;
        }
        cw
    })
}

/// subtractft4.f90.
pub fn subtractft4(dd: &mut [f32], itone: &[u8; 103], f0: f32, dt: f32) {
    let nstart = (dt * 12000.0 + 1.0 - NSPS as f32) as i32;
    let cref = gen_ft4wave_complex(itone, f0);
    let mut cfilt = vec![C32::new(0.0, 0.0); NMAX];
    for i in 0..NFRAME4 {
        let id = nstart + i as i32;
        if id >= 1 && id as usize <= NMAX {
            cfilt[i] = dd[id as usize - 1] * cref[i].conj();
        }
    }
    fft_fwd(&mut cfilt);
    for (c, w) in cfilt.iter_mut().zip(sub_filter4().iter()) {
        *c *= *w;
    }
    fft_inv(&mut cfilt);
    for i in 0..NFRAME4 {
        let j = nstart + i as i32;
        if j >= 1 && j as usize <= NMAX {
            dd[j as usize - 1] -= 2.0 * (cfilt[i] * cref[i]).re;
        }
    }
}

// ------------------------------------------------- per candidate + passes

// AP templates (ft4_decode.f90), scrambled with rvec at use.
const MCQ: [u8; 29] = [
    0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0,
];
const NAPPASSES4: [usize; 6] = [2, 2, 2, 2, 2, 3];
const NAPTYPES4: [[i32; 4]; 6] = [
    [1, 2, 0, 0],
    [2, 3, 0, 0],
    [2, 3, 0, 0],
    [3, 6, 0, 0],
    [3, 6, 0, 0],
    [3, 1, 2, 0],
];

pub struct Cand4Out {
    pub decoded: Option<(Ft4Decode, [u8; 103], f32, f32)>, // decode, tones, f1, dt for subtraction
    /// unpack77 failed on a CRC-good decode: WSJT-X gives up on the
    /// candidate (an `exit`), it is not a decode.
    pub rejected: bool,
    pub trace: Vec<String>,
}

pub type UnpackOk<'a> = &'a (dyn Fn(&[u8; 77]) -> bool + Sync);

#[allow(clippy::too_many_arguments)]
fn decode_candidate(
    ds: &Downsampler4,
    p: &Ft4Params,
    icand: usize,
    cand: &Candidate4,
    apbits: Option<&[f32; 174]>,
    have_dx: bool,
    unpack_ok: Option<UnpackOk>,
) -> Cand4Out {
    let doosd = p.ndepth >= 3;
    let mut trace: Vec<String> = Vec::new();
    let f0 = cand.freq;
    let snr = cand.strength - 1.0;
    let mut cd2 = ds.downsample(f0);
    let sum2: f32 = cd2.iter().map(|c| (c * c.conj()).re).sum::<f32>() / (NMAX as f32 / NDOWN as f32);
    if sum2 > 0.0 {
        let s = sum2.sqrt();
        for c in cd2.iter_mut() {
            *c /= s;
        }
    }
    let mut smax1 = 0f32;
    let mut ibest: i32 = -1;
    let mut idfbest: i32 = 0;
    let mut smax: f32 = -99.0;
    for iseg in 1..=3 {
        for isync in 1..=2 {
            let (idfmin, idfmax, idfstp, ibmin, ibmax, ibstp);
            if isync == 1 {
                idfmin = -12;
                idfmax = 12;
                idfstp = 3;
                let (a, b) = match iseg {
                    1 => (108, 560),
                    2 => {
                        smax1 = smax;
                        (560, 1012)
                    }
                    _ => (-344, 108),
                };
                ibmin = a;
                ibmax = b;
                ibstp = 4;
            } else {
                idfmin = idfbest - 4;
                idfmax = idfbest + 4;
                idfstp = 1;
                ibmin = ibest - 5;
                ibmax = ibest + 5;
                ibstp = 1;
            }
            ibest = -1;
            idfbest = 0;
            smax = -99.0;
            let mut idf = idfmin;
            while idf <= idfmax {
                let mut istart = ibmin;
                while istart <= ibmax {
                    let sync = sync4d(&cd2, istart, idf);
                    if sync > smax {
                        smax = sync;
                        ibest = istart;
                        idfbest = idf;
                    }
                    istart += ibstp;
                }
                idf += idfstp;
            }
        }
        if iseg == 1 {
            smax1 = smax;
        }
        if smax < 1.2 {
            continue;
        }
        if iseg > 1 && smax < smax1 {
            continue;
        }
        let f1 = f0 + idfbest as f32;
        if f1 <= 10.0 || f1 >= 4990.0 {
            continue;
        }
        let mut cb = ds.downsample(f1);
        let sum2: f32 = cb.iter().map(|c| c.norm_sqr()).sum::<f32>() / (NSS * NN) as f32;
        if sum2 > 0.0 {
            let s = sum2.sqrt();
            for c in cb.iter_mut() {
                *c /= s;
            }
        }
        let mut cd = vec![C32::new(0.0, 0.0); NN * NSS];
        if ibest >= 0 {
            let it = (NDMAX as i32 - 1).min(ibest + (NN * NSS) as i32 - 1);
            let np = (it - ibest + 1) as usize;
            cd[..np].copy_from_slice(&cb[ibest as usize..ibest as usize + np]);
        } else {
            let len = ((NN * NSS) as i32 + 2 * ibest) as usize;
            let st = (-ibest) as usize;
            cd[st..st + len].copy_from_slice(&cb[..len]);
        }
        let bm = get_ft4_bitmetrics(&cd);
        if p.trace {
            trace.push(format!(
                "FT4BM {} {} {} {} {} {} {}",
                icand,
                iseg,
                f1,
                ibest,
                idfbest,
                smax,
                bm.is_none()
            ));
            if let Some(bm) = &bm {
                let mut l = String::from("FT4BITS");
                for col in 0..3 {
                    for r in bm.iter() {
                        l.push_str(&format!(" {:e}", r[col]));
                    }
                }
                trace.push(l);
            }
        }
        let Some(bm) = bm else { continue };
        let pats: [(usize, [u8; 8]); 4] = [
            (0, [0, 0, 0, 1, 1, 0, 1, 1]),
            (66, [0, 1, 0, 0, 1, 1, 1, 0]),
            (132, [1, 1, 1, 0, 0, 1, 0, 0]),
            (198, [1, 0, 1, 1, 0, 0, 0, 1]),
        ];
        let mut nsync_qual = 0;
        for (off, pat) in pats.iter() {
            for t in 0..8 {
                if ((bm[off + t][0] >= 0.0) as u8) == pat[t] {
                    nsync_qual += 1;
                }
            }
        }
        if nsync_qual < 20 {
            continue;
        }
        let scalefac = 2.83f32;
        let mut llrs = [[0f32; NBITS]; 3];
        for col in 0..3 {
            for i in 0..58 {
                llrs[col][i] = scalefac * bm[8 + i][col];
                llrs[col][58 + i] = scalefac * bm[74 + i][col];
                llrs[col][116 + i] = scalefac * bm[140 + i][col];
            }
        }
        let apmag = llrs[0].iter().fold(0f32, |a, &b| a.max(b.abs())) * 1.1;
        let mut npasses = 3 + NAPPASSES4[p.nqso_progress];
        if p.lapcqonly {
            npasses = 4;
        }
        if p.ndepth == 1 {
            npasses = 3;
        }
        let napwid = 80.0f32;
        let mut nharderror = -1;
        for ipass in 1..=npasses {
            let mut llr = llrs[(ipass.min(3)) - 1];
            let mut apmask = [0u8; NBITS];
            let mut iaptype = 0;
            if ipass > 3 {
                llr = llrs[2];
                iaptype = if p.lapcqonly {
                    1
                } else {
                    NAPTYPES4[p.nqso_progress][ipass - 4]
                };
                if iaptype >= 3 && (f1 - p.nfqso as f32).abs() > napwid {
                    continue;
                }
                if iaptype >= 2 && apbits.is_none() {
                    continue;
                }
                if iaptype >= 3 && !have_dx {
                    continue;
                }
                match iaptype {
                    1 => {
                        for i in 0..29 {
                            apmask[i] = 1;
                            llr[i] = apmag * (2.0 * ((MCQ[i] + FT4_RVEC[i]) % 2) as f32 - 1.0);
                        }
                    }
                    2 => {
                        let ab = apbits.unwrap();
                        for i in 0..29 {
                            apmask[i] = 1;
                            llr[i] = apmag * ab[i];
                        }
                    }
                    3 => {
                        let ab = apbits.unwrap();
                        for i in 0..58 {
                            apmask[i] = 1;
                            llr[i] = apmag * ab[i];
                        }
                    }
                    4..=6 => {
                        for i in 0..77 {
                            apmask[i] = 1;
                        }
                        if iaptype == 6 {
                            let ab = apbits.unwrap();
                            for i in 0..77 {
                                llr[i] = apmag * ab[i];
                            }
                        }
                    }
                    _ => continue,
                }
            }
            let mut maxosd = 2;
            if (p.nfqso as f32 - f1).abs() <= napwid {
                maxosd = 3;
            }
            if !doosd {
                maxosd = -1;
            }
            let r = decode174_91(&llr, maxosd, 2, &apmask);
            nharderror = r.nharderror;
            if r.message91[..77].iter().all(|&b| b == 0) {
                continue;
            }
            if r.nharderror >= 0 {
                let mut m77 = [0u8; 77];
                for i in 0..77 {
                    m77[i] = (r.message91[i] + FT4_RVEC[i]) % 2;
                }
                if let Some(f) = unpack_ok {
                    if !f(&m77) {
                        return Cand4Out {
                            decoded: None,
                            rejected: true,
                            trace,
                        };
                    }
                }
                let tones = ft4_tones(&m77);
                let dt = ibest as f32 / 666.67;
                let xsnr = if snr > 0.0 { 10.0 * snr.log10() - 14.8 } else { -21.0 };
                let d = Ft4Decode {
                    text: String::new(),
                    payload: m77,
                    snr: nint(xsnr.max(-21.0)),
                    dt: ibest as f32 / 666.67 - 0.5,
                    freq: f1,
                    sync: smax,
                    iaptype,
                    nharderrors: r.nharderror,
                    dmin: r.dmin,
                    qual: 1.0 - (r.nharderror as f32 + r.dmin) / 60.0,
                    ipass: 0,
                };
                return Cand4Out {
                    decoded: Some((d, tones, f1, dt)),
                    rejected: false,
                    trace,
                };
            }
        }
        if nharderror >= 0 {
            break;
        }
    }
    Cand4Out {
        decoded: None,
        rejected: false,
        trace,
    }
}

/// Decode one FT4 slot (12 kHz, 16-bit sample units, slot start at 0;
/// WSJT-X reads the first 21 x 3456 = 72576 samples, 6.048 s).
/// `hashes`: the session's call tables, as for ft8::decode_slot.
pub fn decode_slot(audio: &[f32], p: &Ft4Params, hashes: &mut CallHashes) -> (Vec<Ft4Decode>, Vec<f32>) {
    let (d, dd, _) = decode_slot_traced(audio, p, hashes);
    (d, dd)
}

/// decode_slot, plus the stage trace when `p.trace` is set.
pub fn decode_slot_traced(
    audio: &[f32],
    p: &Ft4Params,
    hashes: &mut CallHashes,
) -> (Vec<Ft4Decode>, Vec<f32>, Vec<String>) {
    super::util::with_pool(p.threads, || decode_slot_in_pool(audio, p, hashes))
}

fn decode_slot_in_pool(
    audio: &[f32],
    p: &Ft4Params,
    hashes: &mut CallHashes,
) -> (Vec<Ft4Decode>, Vec<f32>, Vec<String>) {
    let mut tr: Vec<String> = Vec::new();
    let mut dd = vec![0f32; NMAX];
    let n = audio.len().min(NMAX);
    dd[..n].copy_from_slice(&audio[..n]);

    let apbits: Option<[f32; 174]> = p.ap.map(|ap| {
        let cw = encode174_91(&crate::ft4::scramble(&ap.payload));
        let mut a = [0f32; 174];
        for i in 0..174 {
            a[i] = 2.0 * cw[i] as f32 - 1.0;
        }
        a
    });

    let (dosubtract, nsp) = match p.ndepth {
        1 => (false, 1),
        _ => (true, 3),
    };
    let syncmin = 1.2f32;
    let mut out: Vec<Ft4Decode> = Vec::new();
    let mut nd1 = 0;
    for isp in 1..=nsp {
        if isp == 2 {
            if out.is_empty() {
                break;
            }
            nd1 = out.len();
        } else if isp == 3 && out.len() - nd1 == 0 {
            break;
        }
        let cands = getcandidates4(&dd, p.nfa, p.nfb, syncmin, p.nfqso, MAXCAND);
        if p.trace {
            tr.push(format!("FT4NCAND {} {}", isp, cands.len()));
            for (i, c) in cands.iter().enumerate() {
                tr.push(format!("FT4CAND {} {:e} {:e}", i + 1, c.freq, c.strength));
            }
        }
        let ds = Downsampler4::new(&dd);
        // As in ft8::decode_call: the parallel unpack77 test works on a
        // copy of the tables; the real ones are updated in order below.
        let snapshot = hashes.clone();
        let ok = |m: &[u8; 77]| unpack77(m, true, &mut snapshot.clone()).ok;
        let unpack_ok: Option<UnpackOk> = Some(&ok);
        let have_dx = p.ap.map(|a| a.has_dxcall).unwrap_or(false);
        let run =
            |(i, c): (usize, &Candidate4)| decode_candidate(&ds, p, i + 1, c, apbits.as_ref(), have_dx, unpack_ok);
        let results: Vec<Cand4Out> = if p.threads != 1 {
            cands.par_iter().enumerate().map(run).collect()
        } else {
            cands.iter().enumerate().map(run).collect()
        };
        for mut r in results {
            tr.append(&mut r.trace);
            let Some((mut d, tones, f1, dt)) = r.decoded else {
                continue;
            };
            d.text = unpack77(&d.payload, true, hashes).text_lossy();
            if dosubtract {
                subtractft4(&mut dd, &tones, f1, dt);
            }
            // ft4_decode compares the unpacked text, not the bits.
            if out.iter().any(|o| o.text == d.text) || out.len() >= 100 {
                continue;
            }
            d.ipass = isp;
            out.push(d);
        }
    }
    (out, dd, tr)
}
