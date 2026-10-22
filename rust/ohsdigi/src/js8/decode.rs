// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from JS8Call 2.2.0 (GPL-3.0-or-later; Jordan Sherer KN4CRD, after
// WSJT-X 1.9's FT8 decoder by K1JT, K9AN and the WSJT Development Group):
// lib/js8a_decode.f90 (the pass structure; js8b/c/e/i_decode.f90 are the
// same file with other parameters), lib/js8/syncjs8.f90, baselinejs8.f90,
// js8_downsample.f90, syncjs8d.f90, js8dec.f90, subtractjs8.f90,
// genjs8refsig.f90, lib/ft8/twkfreq1.f90 and lib/db.f90.

//! The JS8 decoder, stage by stage as JS8Call's `js8` runs it on a WAV
//! file: candidates from a sync search over quarter-symbol spectra, each
//! candidate mixed down and peaked up in time and frequency, LDPC decoded
//! (BP, then OSD at depth 3 or 4) under up to six rounds of different
//! soft metrics, and every decode subtracted before the next pass.
//!
//! Its quirks are kept, because the point is to decode what `js8`
//! decodes; each is marked where it happens. The ones that change
//! results: syncjs8d's third Costas reference uses the first one's phase
//! (`phic = mod(phia + dphic, twopi)`), and its bounds check stops the
//! fine time search from ever seeing the end Costas array of a signal
//! that starts after 0 s; js8dec's own buffer length (2812) differs from
//! the downsampler's, so the faster speeds can read past the mixed-down
//! signal (zeros here, whatever was on the stack in Fortran); and the
//! "a-priori" passes 5 and 6 reuse pass 4's metrics at a deeper OSD near
//! the receive frequency, which is the only thing they add (JS8Call never
//! fills in its a-priori bits).
//!
//! One thing is done differently: within a pass every candidate is
//! decoded in parallel. That is exact, not an approximation - js8dec
//! reads the audio only through the mixed-down copy made from the long
//! FFT at the start of the pass, so the subtractions of earlier
//! candidates in the same pass never reach a later one - and the
//! subtractions and duplicate checks are then applied in JS8Call's order.

use super::ldpc::{bpdecode174, osd174, N as NCW};
use super::{tones_from_bits, unpack_bits, Params, Submode, ND, NN};
use crate::decode::util::{fft_fwd, fft_inv, indexx, maxloc, nint, normalizebmet, pctile, polyfit, rfft, with_pool, C32};
use rayon::prelude::*;
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

/// js8dec's own idea of the mixed-down signal's length (`NP2=2812`, "why
/// 3200? not sure..."), used for the frequency tweak and the symbol
/// spectra; syncjs8d uses NN*NDOWNSPS instead.
const JS8DEC_NP2: usize = 2812;
/// Candidates per pass at most (NMAXCAND).
const NMAXCAND: usize = 300;
/// Fine frequency search: +/- NFSRCH half-hertz steps.
const NFSRCH: i32 = 5;
/// Minimum sync (ASYNCMIN), the same for every speed.
const ASYNCMIN: f32 = 1.5;
/// subtractjs8's filter length (NFILT), the same for every speed.
const NFILT: usize = 1400;

fn twopi() -> f32 {
    8.0f32 * 1.0f32.atan()
}

/// What a decode call is told: the `js8` command line's settings, by
/// default (jt9.f90 for js8: -L 200, -H 4000, receive frequency 1500, a
/// 75 Hz "a-priori width", -d 1 unless given).
#[derive(Debug, Clone)]
pub struct Js8Params {
    pub nfa: i32,
    pub nfb: i32,
    pub nfqso: i32,
    /// The transmit frequency; only its distance to a candidate matters
    /// (OSD goes deeper within `napwid` of it). `js8` leaves it 0.
    pub nftx: i32,
    /// 1: BP only, no subtraction, one pass. 2: subtraction, up to three
    /// passes, BP only. 3: three passes and OSD. 4 (and more): four
    /// passes and OSD. JS8Call's GUI default, and NB's, is 3.
    pub ndepth: i32,
    pub napwid: i32,
    /// js8dec's a-priori passes 5 and 6 (`lft8apon`; on in `js8`).
    pub lapon: bool,
    /// "Decode again" near nfqso only (the GUI's double click): narrows
    /// the search to nfqso +/- 10 Hz and runs OSD at depth 5.
    pub nagain: bool,
    /// Threads for the decode's own pool (0 = cores - 1).
    pub threads: usize,
}

impl Default for Js8Params {
    fn default() -> Self {
        Js8Params { nfa: 200, nfb: 4000, nfqso: 1500, nftx: 0, ndepth: 1, napwid: 75, lapon: true, nagain: false, threads: 0 }
    }
}

/// One decode, with the numbers `js8` prints for it.
#[derive(Debug, Clone, PartialEq)]
pub struct Js8Decode {
    pub submode: Submode,
    /// The 12-character frame.
    pub frame: String,
    /// Its three header bits (first, last, data).
    pub i3bit: u8,
    pub snr: i32,
    /// Seconds from the nominal start (the period start plus ASTART).
    pub dt: f32,
    /// Frequency of tone 0, Hz.
    pub freq: f32,
    /// The candidate's sync score.
    pub sync: f32,
    pub nharderrors: i32,
    pub dmin: f32,
    /// JS8Call's quality, 1 - (hard errors + dmin) / 60.
    pub qual: f32,
    /// Which of js8dec's rounds decoded it (1..6).
    pub pass: i32,
    /// The channel symbols, for subtraction or a caller's own checks.
    pub tones: [u8; NN],
}

/// Derived sizes for one speed, the rest of js8<x>_params.f90.
#[derive(Clone, Copy)]
struct Dims {
    p: Params,
    nmax: usize,
    nfft1: usize,
    nh1: usize,
    nstep: usize,
    nhsym: usize,
    ndown: usize,
    nqsymbol: i32,
    ndfft1: usize,
    ndfft2: usize,
}

impl Dims {
    fn new(sub: Submode) -> Dims {
        let p = sub.params();
        let nmax = p.ntxdur * 12000;
        let nfft1 = 2 * p.nsps;
        let nstep = p.nsps / 4;
        let ndown = p.nsps / p.ndownsps;
        let ndfft1 = p.nsps * p.ndd;
        Dims {
            p,
            nmax,
            nfft1,
            nh1: nfft1 / 2,
            nstep,
            nhsym: nmax / nstep - 3,
            ndown,
            nqsymbol: (p.ndownsps / 4) as i32,
            ndfft1,
            ndfft2: ndfft1 / ndown,
        }
    }
}

struct Candidate {
    freq: f32,
    dt: f32,
    sync: f32,
}

/// baselinejs8.f90: a 5th-order polynomial through the lowest tenth of
/// each of ten segments of the average spectrum, in dB, plus 0.65.
/// `s` is 1-based (s[0] unused) and converted to dB in place, as there.
fn baseline(s: &mut [f32], nfa: i32, nfb: i32, nsps: usize) -> Vec<f32> {
    let df = 12000.0f64 / (nsps as f64 * 2.0);
    let ia = 1.max((nfa as f64 / df).round() as i64) as usize;
    let ib = (nfb as f64 / df).round() as usize;
    for i in ia..=ib {
        s[i] = 10.0 * s[i].log10();
    }
    let nseg = 10;
    let nlen = (ib - ia + 1) / nseg;
    let i0 = ((ib - ia + 1) / 2) as i64;
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
                x[k - 1] = i as f64 - i0 as f64;
                y[k - 1] = s[i] as f64;
            }
        }
    }
    let a = polyfit(&x[..k], &y[..k], 5);
    let mut sbase = vec![0f32; s.len()];
    for i in ia..=ib {
        let t = i as f64 - i0 as f64;
        sbase[i] = (a[0] + t * (a[1] + t * (a[2] + t * (a[3] + t * a[4]))) + 0.65) as f32;
    }
    sbase
}

/// syncjs8.f90: candidates (frequency, start, sync) sorted by frequency
/// (those within 10 Hz of nfqso first), and the spectrum baseline the SNR
/// estimate needs.
fn syncjs8(dd: &[f32], d: &Dims, nfa: i32, nfb: i32, syncmin: f32, nfqso: i32) -> (Vec<Candidate>, Vec<f32>) {
    let p = &d.p;
    let (nsps, nh1, nhsym, nstep) = (p.nsps, d.nh1, d.nhsym, d.nstep);
    let tstep = nstep as f32 / 12000.0;
    let df = 12000.0f32 / d.nfft1 as f32;
    let fac = 1.0f32 / 300.0;
    // s[j][i]: symbol spectrum j (1-based in the Fortran, 0-based here),
    // bin i 1-based (s[j][0] unused).
    let s: Vec<Vec<f32>> = (0..nhsym)
        .into_par_iter()
        .map(|j| {
            let ia = j * nstep;
            let x: Vec<f32> = dd[ia..ia + nsps].iter().map(|&v| fac * v).collect();
            let cx = rfft(&x, d.nfft1);
            let mut row = vec![0f32; nh1 + 1];
            for i in 1..=nh1 {
                row[i] = cx[i].re * cx[i].re + cx[i].im * cx[i].im;
            }
            row
        })
        .collect();
    let mut savg = vec![0f32; nh1 + 1];
    for row in &s {
        for i in 1..=nh1 {
            savg[i] += row[i];
        }
    }
    let sbase = baseline(&mut savg, nfa, nfb, nsps);

    let ia = 1.max(nint(nfa as f32 / df)) as usize;
    let ib = nint(nfb as f32 / df) as usize;
    let nssy = (nsps / nstep) as i32;
    let nfos = d.nfft1 / nsps;
    let jstrt = (p.astart / tstep) as i32;
    let jz = p.jz;
    let costas = p.costas;

    let sat = |i: usize, syoff: i32| -> f32 { s[syoff as usize - 1][i] };
    let inband = |syoff: i32| syoff >= 1 && syoff <= nhsym as i32;
    // jpeak and red per frequency bin, computed in parallel over bins.
    let rows: Vec<(i32, f32)> = (ia..=ib)
        .into_par_iter()
        .map(|i| {
            let mut best = f32::NEG_INFINITY;
            let mut jbest = -jz;
            let mut first = true;
            for j in -jz..=jz {
                let (mut ta, mut tb, mut tc) = (0f32, 0f32, 0f32);
                let (mut t0a, mut t0b, mut t0c) = (0f32, 0f32, 0f32);
                for n in 0..7 {
                    let k = j + jstrt + nssy * n as i32;
                    let row_sum = |syoff: i32| -> f32 {
                        let mut acc = 0f32;
                        for m in 0..7 {
                            acc += sat(i + nfos * m, syoff);
                        }
                        acc
                    };
                    let syoff = k;
                    if inband(syoff) {
                        ta += sat(i + nfos * costas[0][n] as usize, syoff);
                        t0a += row_sum(syoff);
                    }
                    let syoff = k + nssy * 36;
                    if inband(syoff) {
                        tb += sat(i + nfos * costas[1][n] as usize, syoff);
                        t0b += row_sum(syoff);
                    }
                    let syoff = k + nssy * 72;
                    if inband(syoff) {
                        tc += sat(i + nfos * costas[2][n] as usize, syoff);
                        t0c += row_sum(syoff);
                    }
                }
                let ratio = |t: f32, t0: f32| t / ((t0 - t) / 6.0);
                let sync_abc = ratio(ta + tb + tc, t0a + t0b + t0c);
                let sync_ab = ratio(ta + tb, t0a + t0b);
                let sync_bc = ratio(tb + tc, t0b + t0c);
                // Fortran's max(a, b, c); sync_ac is computed there and
                // then left out of the max.
                let v = fmax(fmax(sync_abc, sync_ab), sync_bc);
                // maxloc: the first largest.
                if first || v > best {
                    best = v;
                    jbest = j;
                    first = false;
                }
            }
            (jbest, best)
        })
        .collect();
    let mut red = vec![0f32; nh1 + 1];
    let mut jpeak = vec![0i32; nh1 + 1];
    for (k, i) in (ia..=ib).enumerate() {
        jpeak[i] = rows[k].0;
        red[i] = rows[k].1;
    }

    let iz = ib - ia + 1;
    let indx = indexx(&red[ia..=ib]);
    let npctile = nint(0.40 * iz as f32);
    if npctile < 1 {
        return (vec![], sbase);
    }
    let ibase = (indx[npctile as usize - 1] + ia).clamp(1, nh1);
    let base = red[ibase];
    for v in red.iter_mut() {
        *v /= base;
    }

    // candidate0(1:3, k): frequency, start, sync.
    let mut c0: Vec<[f32; 3]> = Vec::new();
    for i in 1..=iz.min(NMAXCAND) {
        if c0.len() >= NMAXCAND {
            break;
        }
        let n = ia + indx[iz - i];
        if red[n] < syncmin || red[n].is_nan() {
            break;
        }
        c0.push([n as f32 * df, (jpeak[n] - 1) as f32 * tstep, red[n]]);
    }
    let ncand = c0.len();
    // Keep only the best of near-duplicate frequencies, in this order and
    // with the second test seeing the first's change, as written.
    for i in 1..ncand {
        for j in 0..i {
            let fdiff = c0[i][0].abs() - c0[j][0].abs();
            if fdiff.abs() < p.az {
                if c0[i][2] >= c0[j][2] {
                    c0[j][2] = 0.0;
                }
                if c0[i][2] < c0[j][2] {
                    c0[i][2] = 0.0;
                }
            }
        }
    }
    for c in c0.iter_mut() {
        if (c[0] - nfqso as f32).abs() < 10.0 {
            c[0] = -c[0];
        }
    }
    let freqs: Vec<f32> = c0.iter().map(|c| c[0]).collect();
    let order = indexx(&freqs);
    let mut out = Vec::new();
    for &j in &order {
        if c0[j][2] >= syncmin {
            out.push(Candidate { freq: c0[j][0].abs(), dt: c0[j][1], sync: c0[j][2] });
        }
    }
    (out, sbase)
}

/// Fortran MAX for reals as gfortran evaluates it: the second argument
/// when the first is NaN.
#[inline]
fn fmax(a: f32, b: f32) -> f32 {
    if b > a || a.is_nan() {
        b
    } else {
        a
    }
}

/// js8_downsample.f90's long FFT of the whole slot (made once per pass:
/// the `newdat` flag).
struct LongFft {
    cx: Vec<C32>,
}

fn taper(ndd: usize) -> Vec<f32> {
    let pi = 4.0f32 * 1.0f32.atan();
    (0..=ndd).map(|i| 0.5 * (1.0 + (i as f32 * pi / ndd as f32).cos())).collect()
}

impl LongFft {
    fn new(dd: &[f32], d: &Dims) -> LongFft {
        LongFft { cx: rfft(&dd[..d.nmax], d.ndfft1) }
    }

    /// The signal at `f0` mixed to baseband at NDOWNSPS samples a symbol.
    /// Returns js8dec's buffer: NDFFT2 samples, zero beyond (see the
    /// module notes on its length).
    fn downsample(&self, f0: f32, d: &Dims) -> Vec<C32> {
        let (ndfft1, ndfft2, ndd) = (d.ndfft1, d.ndfft2, d.p.ndd);
        let df = 12000.0f32 / ndfft1 as f32;
        let baud = 12000.0f32 / d.p.nsps as f32;
        let i0 = nint(f0 / df);
        let ft = f0 + 8.5 * baud;
        let it = nint(ft / df).min((ndfft1 / 2) as i32);
        let fb = f0 - 1.5 * baud;
        let ib = 1.max(nint(fb / df));
        let mut c1 = vec![C32::new(0.0, 0.0); ndfft2];
        let mut k = 0usize;
        for i in ib..=it {
            c1[k] = self.cx[i as usize];
            k += 1;
        }
        let tp = taper(ndd);
        for m in 0..=ndd {
            c1[m] *= tp[ndd - m];
        }
        for m in 0..=ndd {
            c1[k - 1 - ndd + m] *= tp[m];
        }
        // cshift(c1, i0-ib): element m takes element m + shift.
        let shift = (i0 - ib).rem_euclid(ndfft2 as i32) as usize;
        c1.rotate_left(shift);
        fft_inv(&mut c1);
        let fac = 1.0f32 / (ndfft1 as f32 * ndfft2 as f32).sqrt();
        for v in c1.iter_mut() {
            *v *= fac;
        }
        let mut out = vec![C32::new(0.0, 0.0); ndfft2.max(JS8DEC_NP2)];
        out[..ndfft2].copy_from_slice(&c1);
        out
    }
}

/// syncjs8d's reference waveforms, computed once per speed as its `save`d
/// arrays are - with the third array's phase quirk.
fn csync(sub: Submode) -> Arc<[Vec<Vec<C32>>; 3]> {
    static CACHE: OnceLock<Mutex<HashMap<Submode, Arc<[Vec<Vec<C32>>; 3]>>>> = OnceLock::new();
    let m = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    if let Some(v) = m.lock().unwrap().get(&sub) {
        return v.clone();
    }
    let d = Dims::new(sub);
    let tp = twopi();
    let fs2 = 12000.0f32 / d.ndown as f32;
    let dt2 = 1.0f32 / fs2;
    let taus = d.p.ndownsps as f32 * dt2;
    let baud = 1.0f32 / taus;
    let c = d.p.costas;
    let n = d.p.ndownsps;
    let mut a = vec![vec![C32::new(0.0, 0.0); n]; 7];
    let mut b = a.clone();
    let mut cc = a.clone();
    for i in 0..7 {
        let (mut phia, mut phib, mut phic) = (0f32, 0f32, 0f32);
        let dphia = tp * c[0][i] as f32 * baud * dt2;
        let dphib = tp * c[1][i] as f32 * baud * dt2;
        let dphic = tp * c[2][i] as f32 * baud * dt2;
        for j in 0..n {
            a[i][j] = C32::new(phia.cos(), phia.sin());
            b[i][j] = C32::new(phib.cos(), phib.sin());
            cc[i][j] = C32::new(phic.cos(), phic.sin());
            phia = fmod(phia + dphia, tp);
            phib = fmod(phib + dphib, tp);
            // As syncjs8d.f90 has it: phia, not phic.
            phic = fmod(phia + dphic, tp);
        }
    }
    let v = Arc::new([a, b, cc]);
    m.lock().unwrap().insert(sub, v.clone());
    v
}

/// Fortran MOD for reals: the remainder with the dividend's sign.
#[inline]
fn fmod(a: f32, p: f32) -> f32 {
    a % p
}

/// syncjs8d.f90: summed power of the three Costas correlations at sample
/// `i0` of the mixed-down signal, `delf` Hz off.
fn syncjs8d(cd0: &[C32], i0: i32, delf: f32, d: &Dims, cs: &[Vec<Vec<C32>>; 3]) -> f32 {
    let n = d.p.ndownsps;
    // syncjs8d's own NP2: NN*NDOWNSPS (see the module notes).
    let np2 = (NN * n) as i32;
    let mut ctwk = vec![C32::new(1.0, 0.0); n];
    if delf != 0.0 {
        let fs2 = 12000.0f32 / d.ndown as f32;
        let dt2 = 1.0f32 / fs2;
        let tp = twopi();
        let dphi = tp * delf * dt2;
        let mut phi = 0f32;
        for v in ctwk.iter_mut() {
            *v = C32::new(phi.cos(), phi.sin());
            phi = fmod(phi + dphi, tp);
        }
    }
    let corr = |start: i32, refs: &Vec<C32>| -> C32 {
        let mut z = C32::new(0.0, 0.0);
        if start >= 0 && start + n as i32 - 1 <= np2 - 1 {
            let s = start as usize;
            for j in 0..n {
                let r = if delf != 0.0 { ctwk[j] * refs[j] } else { refs[j] };
                z += cd0[s + j] * r.conj();
            }
        }
        z
    };
    let p = |z: C32| z.re * z.re + z.im * z.im;
    let mut sync = 0f32;
    for i in 0..7 {
        let i1 = i0 + (i * n) as i32;
        let i2 = i1 + (36 * n) as i32;
        let i3 = i1 + (72 * n) as i32;
        let z1 = corr(i1, &cs[0][i]);
        let z2 = corr(i2, &cs[1][i]);
        let z3 = corr(i3, &cs[2][i]);
        sync = sync + p(z1) + p(z2) + p(z3);
    }
    sync
}

/// twkfreq1.f90 with only a(1) set: shift by `a1` Hz, the phase starting
/// at one step.
fn twkfreq(c: &mut [C32], npts: usize, fsample: f32, a1: f32) {
    let tp = 6.283185307f32;
    let mut w = C32::new(1.0, 0.0);
    for i in 1..=npts {
        // The Legendre terms (x, p2, p3, p4) multiply a(2..5), all zero
        // here; a1 + 0 + 0... is a1 exactly, so they are left out.
        let dphi = a1 * (tp / fsample);
        let wstep = C32::new(dphi.cos(), dphi.sin());
        w *= wstep;
        c[i - 1] = w * c[i - 1];
    }
}

/// What js8dec found for one candidate, before the caller's subtraction
/// and duplicate check.
struct Found {
    frame: String,
    i3bit: u8,
    tones: [u8; NN],
    f1: f32,
    xdt2: f32,
    xsnr: f32,
    nharderrors: i32,
    dmin: f32,
    pass: i32,
}

/// lib/db.f90.
fn db(x: f32) -> f32 {
    if x > 1.259e-10 {
        10.0 * x.log10()
    } else {
        -99.0
    }
}

/// js8dec.f90 for one candidate.
#[allow(clippy::too_many_arguments)]
fn js8dec(
    lf: &LongFft,
    sub: Submode,
    d: &Dims,
    p: &Js8Params,
    f1_in: f32,
    xdt_in: f32,
    xbase: f32,
    cs: &[Vec<Vec<C32>>; 3],
) -> Option<Found> {
    let fs2 = 12000.0f32 / d.ndown as f32;
    let dt2 = 1.0f32 / fs2;
    let n = d.p.ndownsps;
    let mut cd0 = lf.downsample(f1_in, d);

    let i0 = nint((xdt_in + d.p.astart) * fs2);
    let mut smax = 0f32;
    let mut ibest = 0i32;
    for idt in (i0 - d.nqsymbol)..=(i0 + d.nqsymbol) {
        let sync = syncjs8d(&cd0, idt, 0.0, d, cs);
        if sync > smax {
            smax = sync;
            ibest = idt;
        }
    }
    let xdt2 = ibest as f32 * dt2;
    let i0 = nint(xdt2 * fs2);
    smax = 0.0;
    let mut delfbest = 0f32;
    for ifr in -NFSRCH..=NFSRCH {
        let delf = ifr as f32 * 0.5;
        let sync = syncjs8d(&cd0, i0, delf, d, cs);
        if sync > smax {
            smax = sync;
            delfbest = delf;
        }
    }
    twkfreq(&mut cd0, JS8DEC_NP2, fs2, -delfbest);
    let f1 = f1_in + delfbest;
    // js8dec's local `sync` from here on is this, not the candidate's
    // sync score (that one is its argument sync0); it is what the
    // "sync < 2" acceptance rule below reads.
    let sync = syncjs8d(&cd0, i0, 0.0, d, cs);

    // Symbol spectra s2(0:7, 1:NN).
    let mut s2 = [[0f32; 8]; NN];
    for k in 0..NN {
        let i1 = ibest + (k * n) as i32;
        let mut csymb = vec![C32::new(0.0, 0.0); n];
        if i1 >= 0 && i1 + n as i32 - 1 <= JS8DEC_NP2 as i32 - 1 {
            csymb.copy_from_slice(&cd0[i1 as usize..i1 as usize + n]);
        }
        fft_fwd(&mut csymb);
        for t in 0..8 {
            s2[k][t] = csymb[t].norm() / 1e3;
        }
    }

    let costas = d.p.costas;
    let mut nsync = 0;
    for k in 0..7 {
        if costas[0][k] as usize == maxloc(&s2[k]) {
            nsync += 1;
        }
        if costas[1][k] as usize == maxloc(&s2[k + 36]) {
            nsync += 1;
        }
        if costas[2][k] as usize == maxloc(&s2[k + 72]) {
            nsync += 1;
        }
    }
    if nsync <= 6 {
        return None;
    }

    let mut s1 = [[0f32; 8]; ND];
    let mut j = 0;
    for k in 0..NN {
        if k < 7 || (36..43).contains(&k) || k >= 72 {
            continue;
        }
        s1[j] = s2[k];
        j += 1;
    }
    let flat: Vec<f32> = s1.iter().flat_map(|r| r.iter().copied()).collect();
    let ix = indexx(&flat);
    let xmeds1 = flat[ix[nint(0.5 * 8.0 * ND as f32) as usize - 1]];
    for r in s1.iter_mut() {
        for v in r.iter_mut() {
            *v /= xmeds1;
        }
    }

    let mut bmeta = [0f32; 3 * ND];
    let mut bmetb = [0f32; 3 * ND];
    let mx4 = |a: f32, b: f32, c: f32, d: f32| fmax(fmax(fmax(a, b), c), d);
    for j in 0..ND {
        let ps = s1[j];
        let r1 = mx4(ps[1], ps[3], ps[5], ps[7]) - mx4(ps[0], ps[2], ps[4], ps[6]);
        let r2 = mx4(ps[2], ps[3], ps[6], ps[7]) - mx4(ps[0], ps[1], ps[4], ps[5]);
        let r4 = mx4(ps[4], ps[5], ps[6], ps[7]) - mx4(ps[0], ps[1], ps[2], ps[3]);
        bmeta[3 * j] = r4;
        bmeta[3 * j + 1] = r2;
        bmeta[3 * j + 2] = r1;
        let psl: Vec<f32> = ps.iter().map(|v| (v + 1e-32).ln()).collect();
        let r1 = mx4(psl[1], psl[3], psl[5], psl[7]) - mx4(psl[0], psl[2], psl[4], psl[6]);
        let r2 = mx4(psl[2], psl[3], psl[6], psl[7]) - mx4(psl[0], psl[1], psl[4], psl[5]);
        let r4 = mx4(psl[4], psl[5], psl[6], psl[7]) - mx4(psl[0], psl[1], psl[2], psl[3]);
        bmetb[3 * j] = r4;
        bmetb[3 * j + 1] = r2;
        bmetb[3 * j + 2] = r1;
    }
    normalizebmet(&mut bmeta);
    normalizebmet(&mut bmetb);
    let scalefac = 2.83f32;
    let mut llr0 = [0f32; NCW];
    let mut llr1 = [0f32; NCW];
    for i in 0..NCW {
        llr0[i] = scalefac * bmeta[i];
        llr1[i] = scalefac * bmetb[i];
    }

    // nappasses(nQSOProgress=0) = 2: passes 5 and 6 when lapon.
    let npasses = if p.lapon { 6 } else { 4 };
    let mut llrap = llr0;
    for ipass in 1..=npasses {
        if ipass <= 4 {
            let mut llr = if ipass == 2 { llr1 } else { llr0 };
            if ipass == 3 {
                llr[..24].iter_mut().for_each(|v| *v = 0.0);
            }
            if ipass == 4 {
                llr[..48].iter_mut().for_each(|v| *v = 0.0);
            }
            llrap = llr;
        }
        let mut r = bpdecode174(&llrap, 30);
        if p.ndepth >= 3 && r.nharderror < 0 {
            let mut ndeep = 3;
            if (p.nfqso as f32 - f1).abs() <= p.napwid as f32 || (p.nftx as f32 - f1).abs() <= p.napwid as f32 {
                ndeep = if (ipass == 3 || ipass == 4) && !p.nagain { 3 } else { 4 };
            }
            if p.nagain {
                ndeep = 5;
            }
            r = osd174(&llrap, ndeep);
        }
        let nh = r.nharderror;
        if r.cw.iter().all(|&b| b == 0) {
            continue;
        }
        let ok = nh >= 0
            && (nh as f32 + r.dmin) < 60.0
            && !(sync < 2.0 && nh > 35)
            && !(ipass > 2 && nh > 39)
            && !(ipass == 4 && nh > 30);
        if !ok {
            continue;
        }
        let Some((frame, i3bit)) = unpack_bits(&r.decoded) else { continue };
        let tones = tones_from_bits(&r.decoded, sub);
        let mut xsig = 0f32;
        let mut xnoi = 0f32;
        for i in 0..NN {
            xsig += s2[i][tones[i] as usize].powi(2);
            let ios = (tones[i] as usize + 4) % 7;
            xnoi += s2[i][ios].powi(2);
        }
        let mut xsnr = 0.001f32;
        if xnoi > 0.0 && xnoi < xsig {
            xsnr = xsig / xnoi - 1.0;
        }
        xsnr = 10.0 * xsnr.log10() - 27.0;
        let xsnr2 = db(xsig / xbase - 1.0) - 32.0;
        if !p.nagain {
            xsnr = xsnr2;
        }
        if xsnr < -28.0 {
            xsnr = -28.0;
        }
        return Some(Found {
            frame,
            i3bit,
            tones,
            f1,
            xdt2,
            xsnr,
            nharderrors: nh,
            dmin: r.dmin,
            pass: ipass,
        });
    }
    None
}

/// subtractjs8's low-pass filter in the frequency domain, once per slot
/// length (its `first` block).
fn sub_filter(nmax: usize) -> Arc<Vec<C32>> {
    static CACHE: OnceLock<Mutex<HashMap<usize, Arc<Vec<C32>>>>> = OnceLock::new();
    let m = CACHE.get_or_init(|| Mutex::new(HashMap::new()));
    if let Some(v) = m.lock().unwrap().get(&nmax) {
        return v.clone();
    }
    let pi = 4.0f32 * 1.0f32.atan();
    let fac = 1.0f32 / nmax as f32;
    let h = NFILT / 2;
    // window(-h..=h) at window[j + h].
    let mut window: Vec<f32> = (0..=NFILT).map(|k| (pi * (k as f32 - h as f32) / NFILT as f32).cos().powi(2)).collect();
    let mut sum = 0f32;
    for w in &window {
        sum += *w;
    }
    for w in window.iter_mut() {
        *w /= sum;
    }
    // The NSHIFT=0 branch, 1-based: cw(1:h)=window(1:h);
    // cw(h:NFILT+1)=0; cw(NMAX-h:NMAX)=window(-h:0) - which leaves the
    // window's centre in the last element and window(h) overwritten.
    let mut cw = vec![C32::new(0.0, 0.0); nmax];
    for m in 0..h {
        cw[m] = C32::new(window[h + m + 1], 0.0);
    }
    for v in cw[h - 1..=NFILT].iter_mut() {
        *v = C32::new(0.0, 0.0);
    }
    for (k, m) in (nmax - h - 1..nmax).enumerate() {
        cw[m] = C32::new(window[k], 0.0);
    }
    fft_fwd(&mut cw);
    for v in cw.iter_mut() {
        *v *= fac;
    }
    let v = Arc::new(cw);
    m.lock().unwrap().insert(nmax, v.clone());
    v
}

/// subtractjs8.f90 (with genjs8refsig.f90): take a decoded signal out of
/// `dd`, its tones starting at `dt` seconds from the slot start, tone 0 at
/// `f0`.
pub fn subtract(dd: &mut [f32], tones: &[u8; NN], f0: f32, dt: f32, sub: Submode) {
    let d = Dims::new(sub);
    let nsps = d.p.nsps;
    let nframe = nsps * NN;
    let nmax = d.nmax;
    let nstart = (dt * 12000.0 + 1.0) as i64;
    // genjs8refsig: phase in double precision.
    let twopi = 8.0f64 * 1.0f64.atan();
    let dtt = 1.0f64 / 12000.0;
    let xnsps = nsps as f64;
    let mut cref = Vec::with_capacity(nframe);
    let mut phi = 0f64;
    for &t in tones.iter() {
        let dphi = twopi * (f0 as f64 * dtt + t as f64 / xnsps);
        for _ in 0..nsps {
            cref.push(C32::new(phi.cos() as f32, phi.sin() as f32));
            phi = (phi + dphi) % twopi;
        }
    }
    let mut cfilt = vec![C32::new(0.0, 0.0); nmax];
    for i in 0..nframe {
        let id = nstart + i as i64; // 1-based nstart-1+i+1
        if id >= 1 && id <= nmax as i64 {
            cfilt[i] = dd[id as usize - 1] * cref[i].conj();
        }
    }
    let cw = sub_filter(nmax);
    fft_fwd(&mut cfilt);
    for (c, w) in cfilt.iter_mut().zip(cw.iter()) {
        *c *= *w;
    }
    fft_inv(&mut cfilt);
    for i in 0..nframe {
        let j = nstart + i as i64;
        if j >= 1 && j <= nmax as i64 {
            dd[j as usize - 1] -= 2.0 * (cfilt[i] * cref[i]).re;
        }
    }
}

/// js8<x>_decode: decode one speed in one slot. `audio` is the slot from
/// its start, 12 kHz, in int16 units; only the first NTXDUR seconds are
/// used (zeros if shorter).
pub fn decode_slot(audio: &[f32], sub: Submode, p: &Js8Params) -> Vec<Js8Decode> {
    with_pool(p.threads, || decode_in_pool(audio, sub, p))
}

fn decode_in_pool(audio: &[f32], sub: Submode, p: &Js8Params) -> Vec<Js8Decode> {
    let d = Dims::new(sub);
    let mut dd = vec![0f32; d.nmax];
    let n = audio.len().min(d.nmax);
    dd[..n].copy_from_slice(&audio[..n]);
    let cs = csync(sub);

    let (ifa, ifb) = if p.nagain { (p.nfqso - 10, p.nfqso + 10) } else { (p.nfa, p.nfb) };
    let npass = match p.ndepth {
        1 => 1,
        2 => 3,
        _ => 4,
    };
    let mut out: Vec<Js8Decode> = Vec::new();
    let mut allmessages: Vec<(String, u8, i32)> = Vec::new();
    let (mut n2, mut n3) = (0usize, 0usize);
    for ipass in 1..=npass {
        let lsubtract = match ipass {
            1 => p.ndepth != 1,
            2 => {
                n2 = allmessages.len();
                if allmessages.is_empty() {
                    continue;
                }
                true
            }
            3 => {
                n3 = allmessages.len();
                if allmessages.len() == n2 {
                    continue;
                }
                true
            }
            _ => {
                if allmessages.len() == n3 {
                    continue;
                }
                false
            }
        };
        let (cands, sbase) = syncjs8(&dd, &d, ifa, ifb, ASYNCMIN, p.nfqso);
        if cands.is_empty() {
            continue;
        }
        let lf = LongFft::new(&dd, &d);
        let df1 = 12000.0f32 / d.nfft1 as f32;
        let found: Vec<Option<(Found, f32)>> = cands
            .par_iter()
            .map(|c| {
                let ib = nint(c.freq / df1) as usize;
                let xbase = 10.0f32.powf(0.1 * (sbase[ib] - d.p.xbase_db));
                js8dec(&lf, sub, &d, p, c.freq, c.dt, xbase, &cs).map(|f| (f, c.sync))
            })
            .collect();
        for (f, sync) in found.into_iter().flatten() {
            let nsnr = nint(f.xsnr);
            if lsubtract {
                subtract(&mut dd, &f.tones, f.f1, f.xdt2, sub);
            }
            let ldupe = allmessages.iter().any(|(fr, i3, snr)| *fr == f.frame && *i3 == f.i3bit && nsnr <= *snr);
            if !ldupe {
                if allmessages.len() < 100 {
                    allmessages.push((f.frame.clone(), f.i3bit, nsnr));
                }
                out.push(Js8Decode {
                    submode: sub,
                    frame: f.frame,
                    i3bit: f.i3bit,
                    snr: nsnr,
                    dt: f.xdt2 - d.p.astart,
                    freq: f.f1,
                    sync,
                    nharderrors: f.nharderrors,
                    dmin: f.dmin,
                    qual: 1.0 - (f.nharderrors as f32 + f.dmin) / 60.0,
                    pass: f.pass,
                    tones: f.tones,
                });
            }
        }
    }
    out
}
