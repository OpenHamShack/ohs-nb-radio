// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0 (GPL-3.0-or-later): lib/q65_decode.f90,
// lib/qra/q65/q65.f90, q65_loops.f90, q65_set_list.f90 (with its
// stdcall), q65_ap.f90, lib/spec64.f90, lib/ana64.f90, lib/twkfreq.f90 and
// lib/smo121.f90. Copyright (C) 2001-2024 Joe Taylor K1JT, Nico Palermo
// IV3NWV, Bill Somerville G4WJS, Charles Suckling G3WDG, Roger Rehr W3SZ and
// the WSJT Development Group.

//! The Q65 decoder, as WSJT-X's `jt9 -3` runs it on one WAV file:
//!
//! 1. symbol spectra at eighth-symbol steps; with the other station's call
//!    known, a "q3" list decode first - 206 likely whole messages (their
//!    CQ, the reports -50..+49 with and without R, RRR, RR73, 73) tried
//!    against all 85 symbols;
//! 2. sync on the 22 sync symbols near the receive frequency, then the
//!    general decoder (q0) and a-priori passes (CQ, then MyCall) on the
//!    best sync, with a small search in frequency, time and Doppler width;
//! 3. the same for every other sync candidate in the band.
//!
//! What jt9 run once per file never reaches is not ported: averaging over
//! several periods (q65_dec0's iavg 1/2 and the s1a array), the contest
//! caller list (ncontest 1), the drift search (max_drift 50) and the
//! "decode again" double click. The quirks it does reach are kept and
//! marked, so that a period decodes as jt9 decodes it.

use super::qra::{self, Intrinsics, NK, NN};
use super::{c77_of_symbols, encode as genq65, nsps as nsps_of, ISYNC, NSYM};
use crate::decode::ap::ft8_ap;
use crate::decode::util::{fft_fwd, fft_inv, indexx, nint, pctile, rfft, with_pool, C32};
use crate::msg77::{unpack77_c77, CallHashes};

/// NSTEP: time bins per symbol in the symbol spectra.
const NSTEP: usize = 8;
/// PLOG_MIN: list decodes need at least this log-likelihood.
const PLOG_MIN: f32 = -242.0;
const MAX_NCW: usize = 206;

/// What `jt9 -3` is told on its command line, and its defaults: receive
/// frequency 1500 Hz, tolerance 10 Hz around it (jt9's Q65 default when
/// -F is not given), band 200-4000 Hz, depth 1, MyCall K1ABC, DxCall W9XYZ
/// and DX grid EN37 (jt9.f90's own when -c/-x/-g are not given - with a
/// DxCall the q3 list decode runs, and the grid is in two of its
/// messages), and for 60 s periods the EME delay jt9 sets ("temporary,
/// for MAP65"), which widens the time search to +5.5 s.
#[derive(Debug, Clone)]
pub struct Q65Params {
    pub period: u32,
    /// 0..4 for A..E.
    pub submode: usize,
    pub nfqso: i32,
    pub ntol: i32,
    pub nfa: i32,
    pub nfb: i32,
    /// 1 (fast), 2 (normal), 3 (deep), as WSJT-X's -d.
    pub ndepth: i32,
    pub mycall: String,
    pub hiscall: String,
    pub hisgrid: String,
    /// WSJT-X's QSO progress (0 calling .. 5 signing off): which a-priori
    /// passes are tried.
    pub nqso_progress: usize,
    /// Seconds of extra time search for EME echoes (jt9: 2.5 at 60 s).
    pub emedelay: f32,
    /// Only the decode at nfqso, not the rest of the band.
    pub single_decode: bool,
    pub threads: usize,
}

impl Q65Params {
    pub fn jt9(period: u32, submode: usize) -> Self {
        Q65Params {
            period,
            submode,
            nfqso: 1500,
            ntol: 10,
            nfa: 200,
            nfb: 4000,
            ndepth: 1,
            mycall: crate::decode::ft8::JT9_MYCALL.to_string(),
            hiscall: crate::decode::ft8::JT9_DXCALL.to_string(),
            hisgrid: "EN37".to_string(),
            nqso_progress: 0,
            emedelay: if period == 60 { 2.5 } else { 0.0 },
            single_decode: false,
            threads: 0,
        }
    }
}

/// One decode, as jt9 prints it.
#[derive(Debug, Clone, PartialEq)]
pub struct Q65Decode {
    pub text: String,
    pub snr: i32,
    pub dt: f32,
    pub freq: f32,
    /// How it decoded: 0 no a-priori information, 1 assumed a CQ, 2
    /// assumed MyCall, 3 a whole message from the list ("q3").
    pub idec: i32,
    /// Periods averaged (always 1 here).
    pub nused: i32,
    /// The 77-bit payload as '0'/'1'.
    pub bits: String,
}

/// The state Fortran keeps in module q65 for one decode call.
struct St {
    nsps: usize,
    mode_q65: usize,
    nsubmode: usize,
    ntrperiod: usize,
    nfa: i32,
    nfb: i32,
    ndepth: i32,
    ibwa: i32,
    ibwb: i32,
    maxiters: usize,
    codewords: Vec<[i32; NN]>,
    istep: usize,
    nsmo: i32,
    lag1: i32,
    lag2: i32,
    j0: i32,
    i0: i32,
    df: f32,
    dtstep: f32,
    ftol: f32,
    drift: f32,
    npasses: usize,
    apsym0: [i32; 58],
    apmask1: [i32; 78],
    apsymbols1: [i32; 78],
    apmask: [i32; NK],
    apsymbols: [i32; NK],
    candidates: Vec<[f32; 3]>,
    iz: usize,
    jz: usize,
    /// s1(iz, jz), column-major, 1-based through s1i().
    s1: Vec<f32>,
    ccf2: Vec<f32>,
    sync: [f32; NSYM],
}

impl St {
    #[inline]
    fn s1i(&self, i: usize, j: usize) -> usize {
        (j - 1) * self.iz + (i - 1)
    }
}

/// smo121: one pass of a (1/4, 1/2, 1/4) smoother, in place.
fn smo121(x: &mut [f32]) {
    let nz = x.len();
    if nz < 3 {
        return;
    }
    let mut x0 = x[0];
    for i in 1..nz - 1 {
        let x1 = x[i];
        x[i] = 0.5 * x[i] + 0.25 * (x0 + x[i + 1]);
        x0 = x1;
    }
}

/// q65_symspec.
fn symspec(st: &mut St, iwave: &[f32]) {
    let nsps = st.nsps;
    let fac = 1.0f32 / 32767.0;
    let (iz, jz) = (st.iz, st.jz);
    let mut nsmo = st.nsmo;
    if nsmo <= 1 {
        nsmo = 0;
    }
    st.nsmo = nsmo;
    let mut j = 1;
    while j <= jz {
        let i1 = (j - 1) * st.istep;
        let x: Vec<f32> = (0..nsps).map(|m| fac * iwave[i1 + m]).collect();
        let c = rfft(&x, nsps);
        let mut col: Vec<f32> = (1..=iz).map(|i| c[i].re * c[i].re + c[i].im * c[i].im).collect();
        for _ in 0..nsmo {
            smo121(&mut col);
        }
        let base = st.s1i(1, j);
        st.s1[base..base + iz].copy_from_slice(&col);
        if j >= 3 {
            for i in 1..=iz {
                let a = st.s1[st.s1i(i, j - 2)];
                let b = st.s1[st.s1i(i, j)];
                let k = st.s1i(i, j - 1);
                st.s1[k] = 0.5 * (a + b);
            }
        }
        j += 2;
    }
}

/// q65_ccf_85: sync on all 85 symbols of each list message. Returns
/// (ipk, jpk, f0, xdt, better, found) and fills ccf1(-ia2..ia2).
#[allow(clippy::too_many_arguments)]
fn ccf_85(st: &St, nfqso: i32, ia: i32, ia2: i32, ccf1: &mut [f32]) -> (i32, i32, f32, f32, f32) {
    let (iz, jz) = (st.iz as i32, st.jz as i32);
    let nlag = (st.lag2 - st.lag1 + 1) as usize;
    let w = (2 * ia2 + 1) as usize;
    let mut ipk = 0;
    let mut jpk = 0;
    let mut f0 = 0f32;
    let mut xdt = 0f32;
    let mut ccf_best = 0f32;
    let mut imsg_best: i32 = -1;
    let mut best = vec![0f32; st.codewords.len()];
    let iia = (200.0f32 / st.df) as i32;
    for (imsg, cw) in st.codewords.iter().enumerate() {
        let mut itone = [0i32; NSYM];
        let mut i = 0;
        let mut k = 0;
        for j in 1..=NSYM {
            if i < ISYNC.len() && j == ISYNC[i] {
                i += 1;
                itone[j - 1] = 0;
            } else {
                itone[j - 1] = cw[k] + 1;
                k += 1;
            }
        }
        // ccf(-ia2:ia2, lag1:lag2)
        let mut ccf = vec![0f32; w * nlag];
        for lag in st.lag1..=st.lag2 {
            let li = (lag - st.lag1) as usize;
            for k in 1..=NSYM as i32 {
                let j = st.j0 + NSTEP as i32 * (k - 1) + 1 + lag;
                if j >= 1 && j <= jz {
                    for i in -ia2..=ia2 {
                        let ii = st.i0 + st.mode_q65 as i32 * itone[(k - 1) as usize] + i;
                        if ii >= iia && ii <= iz {
                            ccf[li * w + (i + ia2) as usize] += st.s1[st.s1i(ii as usize, j as usize)];
                        }
                    }
                }
            }
        }
        // maxval / maxloc over ccf(-ia:ia, :): column-major order, first max.
        let mut ccfmax = f32::NEG_INFINITY;
        let (mut bi, mut bl) = (0i32, 0usize);
        for li in 0..nlag {
            for i in -ia..=ia {
                let v = ccf[li * w + (i + ia2) as usize];
                if v > ccfmax {
                    ccfmax = v;
                    bi = i;
                    bl = li;
                }
            }
        }
        if ccfmax > ccf_best {
            ccf_best = ccfmax;
            ipk = bi;
            // jpk = ijpk(2) - 53 - 1, ccf's lag dimension being declared
            // -53:214: that is the lag itself.
            jpk = st.lag1 + bl as i32;
            f0 = nfqso as f32 + ipk as f32 * st.df;
            xdt = jpk as f32 * st.dtstep;
            imsg_best = imsg as i32;
            for i in 0..w {
                ccf1[i] = ccf[(jpk - st.lag1) as usize * w + i];
            }
        }
        best[imsg] = ccfmax;
    }
    let mut better = 0f32;
    if imsg_best >= 0 {
        best[imsg_best as usize] = 0.0;
        let mx = best.iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        better = ccf_best / mx;
    }
    (ipk, jpk, f0, xdt, better)
}

/// q65_ccf_22: sync on the 22 sync symbols; the best near nfqso, ccf2 (the
/// "orange curve") and the band's candidates. Returns (ipk, jpk, f0, xdt).
fn ccf_22(st: &mut St, nfqso: i32, ntol: i32) -> (i32, i32, f32, f32) {
    let (iz, jz) = (st.iz, st.jz);
    let df = st.df;
    let mut ia = (st.nfa.max(100) as f32 / df) as i32;
    let ib = (st.nfb.min(4900) as f32 / df) as i32;
    if ia >= ib {
        ia = (ib as f32 - ntol as f32 / df) as i32;
    }
    let (ia, ib) = (ia as usize, ib as usize);
    let mut s1avg = vec![0f32; iz + 1];
    for i in ia..=ib {
        let mut s = 0f32;
        for j in 1..=jz {
            s += st.s1[st.s1i(i, j)];
        }
        s1avg[i] = s;
    }
    let mut xdt2 = vec![0f32; iz + 1];
    let mut ccfbest = 0f32;
    let mut ibest = 0usize;
    // lagpk is not reset per frequency: a bin with no positive CCF keeps
    // the previous bin's lag for its xdt2, as in the Fortran.
    let mut lagpk = 0i32;
    let mut lagbest = 0i32;
    let ccf2 = &mut st.ccf2;
    let s1 = &st.s1;
    for i in ia..=ib {
        let mut ccfmax = 0f32;
        for lag in st.lag1..=st.lag2 {
            // idrift 0 only: max_drift is 0.
            let mut ccft = 0f32;
            for &k in ISYNC.iter() {
                let n = NSTEP as i32 * (k as i32 - 1) + 1;
                let j = n + lag + st.j0;
                if j >= 1 && j <= jz as i32 {
                    ccft += s1[(j as usize - 1) * iz + (i - 1)];
                }
            }
            ccft -= (22.0f32 / jz as f32) * s1avg[i];
            if ccft > ccfmax {
                ccfmax = ccft;
                lagpk = lag;
            }
        }
        ccf2[i] = ccfmax;
        xdt2[i] = lagpk as f32 * st.dtstep;
        if ccfmax > ccfbest && (i as f32 * df - nfqso as f32).abs() <= st.ftol {
            ccfbest = ccfmax;
            ibest = i;
            lagbest = lagpk;
        }
    }
    let ipk = ibest as i32 - st.i0;
    let jpk = lagbest;
    let f0 = nfqso as f32 + ipk as f32 * df;
    let xdt = jpk as f32 * st.dtstep;
    st.drift = 0.0;
    for v in st.ccf2[1..=ia].iter_mut() {
        *v = 0.0;
    }
    for v in st.ccf2[ib..=iz].iter_mut() {
        *v = 0.0;
    }
    // Candidates: the 20 strongest local maxima at least 6 "sigma" up.
    let jzz = ib - ia + 1;
    let seg: Vec<f32> = st.ccf2[ia..=ib].to_vec();
    let indx = indexx(&seg);
    let ave = pctile(&seg, 50);
    let base = pctile(&seg, 84);
    let rms = base - ave;
    let mut cands: Vec<[f32; 3]> = Vec::new();
    for j in 1..=20usize {
        if j > jzz {
            continue;
        }
        let k = jzz - j + 1;
        if k < 1 || k > iz {
            continue;
        }
        let i = indx[k - 1] + ia;
        let f = i as f32 * df;
        let i3 = 1.max(i as i32 - st.mode_q65 as i32) as usize;
        let i4 = (iz as i32).min(i as i32 + st.mode_q65 as i32) as usize;
        let biggest = st.ccf2[i3..=i4].iter().cloned().fold(f32::NEG_INFINITY, f32::max);
        if st.ccf2[i] != biggest {
            continue;
        }
        let snr = (st.ccf2[i] - ave) / rms;
        if snr < 6.0 {
            break;
        }
        cands.push([snr, xdt2[i], f]);
        if cands.len() >= 20 {
            break;
        }
    }
    let freqs: Vec<f32> = cands.iter().map(|c| c[2]).collect();
    let order = indexx(&freqs);
    st.candidates = order.iter().map(|&o| cands[o]).collect();
    (ipk, jpk, f0, xdt)
}

/// q65_bzap: a bin that is the strongest in more than 15 of the 63 symbols
/// is a birdie; set it to 1 everywhere. `s3` is [63][ll].
fn bzap(s3: &mut [f32], ll: usize) {
    let mut hist = vec![0i32; ll];
    for j in 0..NN {
        let col = &s3[j * ll..j * ll + ll];
        let mut ip = 0;
        for i in 1..ll {
            if col[i] > col[ip] {
                ip = i;
            }
        }
        hist[ip] += 1;
    }
    if hist.iter().any(|&h| h > 15) {
        for (i, &h) in hist.iter().enumerate() {
            if h > 15 {
                for j in 0..NN {
                    s3[j * ll + i] = 1.0;
                }
            }
        }
    }
}

/// q65_s1_to_s3: the synchronized data symbols' energies, ll bins each.
fn s1_to_s3(st: &St, ipk: i32, jpk: i32, ll: usize, s3: &mut [f32]) {
    let i1 = st.i0 + ipk - 64 + st.mode_q65 as i32;
    let i2 = i1 + ll as i32 - 1;
    if i1 >= 1 && i2 <= st.iz as i32 {
        let mut j = st.j0 + jpk - 7;
        let mut n = 0usize;
        for k in 0..NSYM {
            j += 8;
            if st.sync[k] > 0.0 {
                continue;
            }
            n += 1;
            if j >= 1 && j <= st.jz as i32 {
                let src = st.s1i(i1 as usize, j as usize);
                s3[(n - 1) * ll..n * ll].copy_from_slice(&st.s1[src..src + ll]);
            }
        }
    }
    bzap(s3, ll);
}

fn db(x: f32) -> f32 {
    if x > 1.259e-10 {
        10.0 * x.log10()
    } else {
        -99.0
    }
}

/// 1.72**ibw, as gfortran's real**integer (repeated multiplication).
fn b90_of(ibw: i32) -> f32 {
    1.72f32.powi(ibw)
}

/// q65_dec1: a list decode. (irc, symbols, esnodb).
fn dec1(st: &St, s3: &[f32], b90ts: f32) -> (i32, [i32; NK], f32) {
    let ff = qra::intrinsics_fastfading(s3, st.nsubmode, b90ts);
    let (d, plog) = qra::decode_fullaplist(&ff.prob, &st.codewords);
    let mut irc = d.rc;
    let mut esnodb = 0.0;
    if irc >= 0 {
        esnodb = qra::esnodb_fastfading(&ff, &d.codeword, s3);
    }
    if d.msg.iter().sum::<i32>() <= 0 {
        irc = -2;
    }
    if !(irc >= 0 && plog > PLOG_MIN) {
        irc = -1;
    }
    (irc, d.msg, esnodb)
}

/// q65_dec2: the general decoder with the current a-priori mask.
fn dec2(st: &St, s3: &[f32], b90ts: f32) -> (i32, [i32; NK], f32) {
    let ff: Intrinsics = qra::intrinsics_fastfading(s3, st.nsubmode, b90ts);
    let d = qra::decode(&ff.prob, &st.apmask, &st.apsymbols, st.maxiters);
    let mut irc = d.rc;
    let mut esnodb = 0.0;
    if irc >= 0 {
        esnodb = qra::esnodb_fastfading(&ff, &d.codeword, s3);
    }
    if d.msg.iter().sum::<i32>() <= 0 {
        irc = -2;
    }
    (irc, d.msg, esnodb)
}

/// q65_ap, for ncontest 0: sets apmask1/apsymbols1 for this pass and
/// returns iaptype. As in the Fortran, an early exit leaves the previous
/// pass's apmask1 in place (only apsymbols1 is cleared), so an unusable
/// MyCall pass runs with the CQ pass's mask and zero symbols.
fn q65_ap(st: &mut St, nqso_progress: usize, ipass: usize, lapcqonly: bool) -> i32 {
    const NAPTYPES: [[i32; 4]; 6] = [[1, 2, 0, 0], [2, 3, 0, 0], [2, 3, 0, 0], [3, 4, 5, 6], [3, 4, 5, 6], [3, 1, 2, 0]];
    const MCQ: [i32; 29] = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 1, 0, 0];
    const MRRR: [i32; 19] = [0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 0, 1];
    const M73: [i32; 19] = [0, 1, 1, 1, 1, 1, 1, 0, 1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1];
    const MRR73: [i32; 19] = [0, 1, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 1, 0, 0, 1];
    st.apsymbols1 = [0; 78];
    let mut iaptype = NAPTYPES[nqso_progress][ipass - 1];
    if lapcqonly {
        iaptype = 1;
    }
    if iaptype >= 2 && st.apsym0[0] > 1 {
        return iaptype;
    }
    if iaptype >= 3 && st.apsym0[29] > 1 {
        return iaptype;
    }
    if iaptype == 1 {
        st.apmask1 = [0; 78];
        st.apmask1[..29].iter_mut().for_each(|v| *v = 1);
        st.apsymbols1[..29].copy_from_slice(&MCQ);
        st.apmask1[74..78].iter_mut().for_each(|v| *v = 1);
        st.apsymbols1[74..78].copy_from_slice(&[0, 0, 1, 0]);
    }
    if iaptype == 2 {
        st.apmask1 = [0; 78];
        st.apmask1[..29].iter_mut().for_each(|v| *v = 1);
        st.apsymbols1[..29].copy_from_slice(&st.apsym0[..29]);
        st.apmask1[74..78].iter_mut().for_each(|v| *v = 1);
        st.apsymbols1[74..78].copy_from_slice(&[0, 0, 1, 0]);
    }
    if iaptype == 3 {
        st.apmask1 = [0; 78];
        st.apmask1[..58].iter_mut().for_each(|v| *v = 1);
        st.apsymbols1[..58].copy_from_slice(&st.apsym0);
        st.apmask1[74..78].iter_mut().for_each(|v| *v = 1);
        st.apsymbols1[74..78].copy_from_slice(&[0, 0, 1, 0]);
    }
    if (4..=6).contains(&iaptype) {
        st.apmask1 = [1; 78];
        st.apmask1[71..74].iter_mut().for_each(|v| *v = 0);
        st.apsymbols1[..58].copy_from_slice(&st.apsym0);
        let tail = match iaptype {
            4 => &MRRR,
            5 => &M73,
            _ => &MRR73,
        };
        st.apsymbols1[58..77].copy_from_slice(tail);
    }
    iaptype
}

/// 78 bits to 13 six-bit symbols (the Fortran's '(78i1)' / '(13b6.6)').
fn pack_bits6(bits: &[i32; 78]) -> [i32; NK] {
    let mut out = [0i32; NK];
    for (k, v) in out.iter_mut().enumerate() {
        *v = (0..6).fold(0, |a, j| (a << 1) | (bits[6 * k + j] & 1));
    }
    out
}

/// Set apmask/apsymbols for pass `ipass` (0 = none); returns iaptype.
fn set_ap(st: &mut St, nqso_progress: usize, ipass: usize, lapcqonly: bool, iaptype: i32) -> i32 {
    st.apmask = [0; NK];
    st.apsymbols = [0; NK];
    if ipass >= 1 {
        let t = q65_ap(st, nqso_progress, ipass, lapcqonly);
        st.apmask = pack_bits6(&st.apmask1);
        st.apsymbols = pack_bits6(&st.apsymbols1);
        return t;
    }
    iaptype
}

/// q65_dec_q012: q0, then the a-priori passes, on s3.
fn dec_q012(st: &mut St, s3: &[f32]) -> Option<(i32, [i32; NK], f32)> {
    let baud = 12000.0f32 / st.nsps as f32;
    let mut iaptype = 0;
    for ipass in 0..=st.npasses {
        // dec_q012 sets nQSOprogress to 0 ("### TEMPORARY ? ###").
        iaptype = set_ap(st, 0, ipass, false, iaptype);
        for ibw in st.ibwa..=st.ibwb {
            let b90ts = b90_of(ibw) / baud;
            let (irc, dat4, esnodb) = dec2(st, s3, b90ts);
            if irc >= 0 {
                let snr2 = esnodb - db(2500.0 / baud) + 3.0;
                return Some((iaptype, dat4, snr2));
            }
        }
    }
    None
}

/// q65_dec0 for a single period (iavg 0): (idec, dat4, xdt, f0).
fn dec0(st: &mut St, iwave: &[f32], nfqso: i32, ntol: i32, emedelay: f32) -> (i32, [i32; NK], f32, f32) {
    let mode = st.mode_q65;
    let ll = 64 * (2 + mode);
    let nsps = st.nsps;
    st.df = 12000.0f32 / nsps as f32;
    st.istep = nsps / NSTEP;
    st.iz = (5000.0f32 / st.df) as usize;
    let txt = 85.0f32 * nsps as f32 / 12000.0;
    let mut jz = ((txt + 1.0) * 12000.0 / st.istep as f32) as usize;
    if nsps >= 6912 {
        jz = ((txt + 2.0) * 12000.0 / st.istep as f32) as usize;
    }
    st.jz = jz;
    st.ftol = ntol as f32;
    let ia = (ntol as f32 / st.df) as i32;
    let ia2 = ia.max(10 * mode as i32).max(nint(100.0 / st.df));
    st.nsmo = (0.5 * (mode * mode) as f32) as i32;
    if st.nsmo < 1 {
        st.nsmo = 1;
    }
    st.sync = [-22.0 / 63.0; NSYM];
    for &k in ISYNC.iter() {
        st.sync[k - 1] = 1.0;
    }
    st.s1 = vec![0f32; st.iz * st.jz];
    st.ccf2 = vec![0f32; st.iz + 1];
    let mut s3 = vec![0f32; ll * NN];
    let mut ccf1 = vec![0f32; (2 * ia2 + 1) as usize];
    st.dtstep = nsps as f32 / (NSTEP as f32 * 12000.0);
    st.lag1 = (-1.0f32 / st.dtstep) as i32;
    st.lag2 = (1.0f32 / st.dtstep + 0.9999) as i32;
    if nsps >= 3600 && emedelay > 0.0 {
        st.lag2 = (5.5f32 / st.dtstep + 0.9999) as i32;
    }
    st.j0 = (0.5f32 / st.dtstep) as i32;
    if nsps >= 7200 {
        st.j0 = (1.0f32 / st.dtstep) as i32;
    }
    symspec(st, iwave);
    st.i0 = nint(nfqso as f32 / st.df);

    let mut idec = -1;
    let mut dat4 = [0i32; NK];
    let mut f0 = 0f32;
    let mut xdt = 0f32;
    let mut ipk;
    let mut jpk;
    if !st.codewords.is_empty() {
        let r = ccf_85(st, nfqso, ia, ia2, &mut ccf1);
        ipk = r.0;
        jpk = r.1;
        f0 = r.2;
        xdt = r.3;
        let better = r.4;
        if better >= 1.10 || mode >= 8 {
            // q65_dec_q3.
            s1_to_s3(st, ipk, jpk, ll, &mut s3);
            let baud = 12000.0f32 / nsps as f32;
            for ibw in st.ibwa..=st.ibwb {
                let b90ts = b90_of(ibw) / baud;
                let (irc, d, _esnodb) = dec1(st, &s3, b90ts);
                if irc >= 0 {
                    dat4 = d;
                    idec = 3;
                    break;
                }
            }
        }
    }
    let r = ccf_22(st, nfqso, ntol);
    ipk = r.0;
    jpk = r.1;
    if idec < 0 {
        f0 = r.2;
        xdt = r.3;
    }
    if idec <= 0 {
        s1_to_s3(st, ipk, jpk, ll, &mut s3);
    }
    if idec < 0 {
        if let Some((t, d, _snr2)) = dec_q012(st, &s3) {
            idec = t;
            dat4 = d;
        }
    }
    (idec, dat4, xdt, f0)
}

/// ana64: the analytic signal at 6000 samples/s.
fn ana64(iwave: &[f32], npts: usize) -> Vec<C32> {
    let nfft1 = npts;
    let nfft2 = nfft1 / 2;
    let fac = 2.0f32 / (32767.0 * nfft1 as f32);
    let mut c0: Vec<C32> = iwave[..npts].iter().map(|&v| C32::new(fac * v, 0.0)).collect();
    fft_fwd(&mut c0);
    for v in c0[nfft2 / 2 + 1..nfft2].iter_mut() {
        *v = C32::new(0.0, 0.0);
    }
    c0[0] *= 0.5;
    c0.truncate(nfft2);
    fft_inv(&mut c0);
    c0
}

/// twkfreq: shift by a(1) Hz plus a(2) Hz across the file (a(3) zero).
fn twkfreq(c3: &[C32], npts: usize, fsample: f32, a1: f32, a2: f32) -> Vec<C32> {
    let twopi = 6.283185307f32;
    let mut out = vec![C32::new(0.0, 0.0); npts];
    let mut w = C32::new(1.0, 0.0);
    let x0 = 0.5 * (npts as f32 + 1.0);
    let s = 2.0f32 / npts as f32;
    for i in 1..=npts {
        let x = s * (i as f32 - x0);
        let p2 = 1.5 * x * x - 0.5;
        let dphi = (a1 + x * a2 + p2 * 0.0) * (twopi / fsample);
        let wstep = C32::new(dphi.cos(), dphi.sin());
        w *= wstep;
        out[i - 1] = w * c3[i - 1];
    }
    out
}

/// spec64: the 63 data symbols' spectra from the time-aligned analytic
/// signal, flattened by a smoothed passband shape. Returns [63][ll].
fn spec64(c0: &[C32], nsps: usize, mode: usize, jpk: i32, ll: usize) -> Vec<f32> {
    let npts = c0.len();
    let mut s3 = vec![0f32; ll * NN];
    let mut j = 0;
    let mut n = 0;
    for k in 1..=84usize {
        if n < ISYNC.len() && k == ISYNC[n] {
            n += 1;
            continue;
        }
        j += 1;
        let mut ja = (k as i32 - 1) * nsps as i32 + jpk;
        let mut jb = ja + nsps as i32 - 1;
        if ja < 0 {
            ja = 0;
        }
        if jb > npts as i32 - 1 {
            jb = npts as i32 - 1;
        }
        let nz = jb - ja;
        let mut cs = vec![C32::new(0.0, 0.0); nsps];
        if nz >= 0 {
            cs[..=(nz as usize)].copy_from_slice(&c0[ja as usize..=jb as usize]);
        }
        fft_fwd(&mut cs);
        for ii in 1..=ll {
            let mut i = ii as i32 - 65 + mode as i32;
            if i < 0 {
                i += nsps as i32;
            }
            // Q65-15E's 1152 bins outrun its 900-point FFT; the Fortran
            // reads on into cs's never-written (static, zero) tail.
            if i as usize >= nsps {
                continue;
            }
            let v = cs[i as usize];
            s3[(j - 1) * ll + ii - 1] = v.re * v.re + v.im * v.im;
        }
    }
    let mut xbase0 = vec![0f32; ll];
    for i in 0..ll {
        let row: Vec<f32> = (0..NN).map(|jj| s3[jj * ll + i]).collect();
        xbase0[i] = pctile(&row, 45);
    }
    let nh = 25;
    let mut xbase = vec![0f32; ll];
    let lo: f32 = {
        let mut s = 0f32;
        for &v in &xbase0[..nh - 1] {
            s += v;
        }
        s
    } / (nh as f32 - 1.0);
    for v in xbase[..nh - 1].iter_mut() {
        *v = lo;
    }
    // The upper end sums 25 values and divides by 24, the middle 50 and
    // divides by 51, as the Fortran does.
    let hi: f32 = {
        let mut s = 0f32;
        for &v in &xbase0[ll - nh..] {
            s += v;
        }
        s
    } / (nh as f32 - 1.0);
    for v in xbase[ll - nh..].iter_mut() {
        *v = hi;
    }
    for i in nh..=ll - nh {
        let mut s = 0f32;
        for &v in &xbase0[i - nh..i + nh] {
            s += v;
        }
        xbase[i - 1] = s / (2 * nh + 1) as f32;
    }
    for i in 0..ll {
        for jj in 0..NN {
            s3[jj * ll + i] /= xbase[i] + 0.001;
        }
    }
    s3
}

/// q65_loops: the general decoder around (xdt0, f0), over small offsets
/// in frequency and time and the Doppler widths. (idec, dat4, xdt1, f1).
#[allow(clippy::too_many_arguments)]
fn loops(st: &St, c00: &[C32], nsps2: usize, jpk0: i32, xdt0: f32, f0: f32, iaptype: i32) -> Option<(i32, [i32; NK], f32, f32)> {
    let ll = 64 * (st.mode_q65 + 2);
    let npts2 = c00.len();
    let s3lim = 20.0f32;
    let baud = 6000.0f32 / nsps2 as f32;
    let (mut idfmax, mut idtmax, mut maxdist) = (1, 1, 4);
    let ibw0 = (st.ibwa + st.ibwb) / 2;
    if st.ndepth & 3 == 2 {
        idfmax = 3;
        idtmax = 3;
        maxdist = 5;
    }
    if st.ndepth & 3 == 3 {
        idfmax = 5;
        idtmax = 5;
        maxdist = 5;
    }
    for idf in 1..=idfmax {
        let mut ndf = idf / 2;
        if idf % 2 == 0 {
            ndf = -ndf;
        }
        let a1 = -(f0 + 0.5 * baud * ndf as f32);
        let a2 = -0.5 * st.drift;
        let c0 = twkfreq(c00, npts2, 6000.0, a1, a2);
        for idt in 1..=idtmax {
            let mut ndt = idt / 2;
            if idt % 2 == 0 {
                ndt = -ndt;
            }
            let jpk = (jpk0 + nsps2 as i32 * ndt / 16).clamp(0, 29000);
            let mut s3 = spec64(&c0, nsps2, st.mode_q65, jpk, ll);
            let base = pctile(&s3, 40);
            for v in s3.iter_mut() {
                *v /= base;
                if *v > s3lim {
                    *v = s3lim;
                }
            }
            bzap(&mut s3, ll);
            for ibw in st.ibwa..=st.ibwb {
                let ndist = ndf * ndf + ndt * ndt + (ibw - ibw0) * (ibw - ibw0);
                if ndist > maxdist {
                    continue;
                }
                let b90 = b90_of(ibw);
                if b90 > 345.0 {
                    continue;
                }
                let b90ts = b90 / baud;
                let (irc, dat4, _esnodb) = dec2(st, &s3, b90ts);
                if irc >= 0 {
                    let xdt1 = xdt0 + nsps2 as f32 * ndt as f32 / (16.0 * 6000.0);
                    let f1 = f0 + 0.5 * baud * ndf as f32;
                    return Some((iaptype, dat4, xdt1, f1));
                }
            }
        }
    }
    None
}

/// q65_snr: SNR of a decode from all 85 symbols' spectra lined up.
fn q65_snr(st: &St, dat4: &[i32; NK], dtdec: f32, f0dec: f32) -> f32 {
    let (iz, jz) = (st.iz, st.jz);
    let cw = qra::encode(dat4);
    let mut itone = [0i32; NSYM];
    let (mut i, mut k) = (0, 0);
    for j in 1..=NSYM {
        if i < ISYNC.len() && j == ISYNC[i] {
            i += 1;
            itone[j - 1] = 0;
        } else {
            itone[j - 1] = cw[k] + 1;
            k += 1;
        }
    }
    let mut spec = vec![0f32; iz + 1];
    let lagpk = nint(dtdec / st.dtstep);
    for k in 1..=NSYM as i32 {
        let j = st.j0 + NSTEP as i32 * (k - 1) + 1 + lagpk;
        if j >= 1 && j <= jz as i32 {
            for i in 1..=iz {
                let ii = i as i32 + st.mode_q65 as i32 * itone[(k - 1) as usize];
                if ii >= 1 && ii <= iz as i32 {
                    spec[i] += st.s1[st.s1i(ii as usize, j as usize)];
                }
            }
        }
    }
    let i0 = nint(f0dec / st.df);
    let nsum = (10 * st.mode_q65 as i32).max(nint(50.0 / st.df));
    let ia = 1.max(i0 - 2 * nsum) as usize;
    let ib = (iz as i32).min(i0 + 2 * nsum) as usize;
    let nsum = nsum as usize;
    let mut sum1 = 0f32;
    for &v in &spec[ia..ia + nsum] {
        sum1 += v;
    }
    let mut sum2 = 0f32;
    for &v in &spec[ib - nsum + 1..=ib] {
        sum2 += v;
    }
    let avg = (sum1 + sum2) / (2.0 * nsum as f32);
    for v in spec.iter_mut() {
        *v /= avg;
    }
    let mut sig_area = 0f32;
    for &v in &spec[ia + nsum..=ib - nsum] {
        sig_area += v - 1.0;
    }
    db(sig_area.max(1.0)) - db(2500.0 / st.df)
}

/// stdcall (q65_set_list.f90): a "standard" callsign.
fn stdcall(call: &str) -> bool {
    let c: Vec<u8> = call.trim_end().bytes().collect();
    let n = c.len();
    let isd = |b: u8| b.is_ascii_digit();
    let isl = |b: u8| b.is_ascii_uppercase();
    let mut iarea = 1usize;
    let mut i = n;
    while i >= 2 {
        if isd(c[i - 1]) {
            break;
        }
        i -= 1;
    }
    if n >= 2 {
        iarea = i;
    }
    let npdig = c[..iarea.saturating_sub(1)].iter().filter(|&&b| isd(b)).count();
    let nplet = c[..iarea.saturating_sub(1)].iter().filter(|&&b| isl(b)).count();
    let nslet = if iarea < n { c[iarea..].iter().filter(|&&b| isl(b)).count() } else { 0 };
    !(iarea < 2 || iarea > 3 || nplet == 0 || npdig + 1 >= iarea || nslet > 3)
}

/// q65_set_list's 206 messages: the other station's CQ, both calls with
/// RRR, RR73, 73, the grid, and the reports -50..+49 with and without R.
fn list_messages(my: &str, his: &str, hisgrid: &str) -> Vec<String> {
    let my_std = stdcall(my);
    let his_std = stdcall(his);
    let g4: String = format!("{hisgrid:<6}").chars().take(4).collect();
    let mut out = Vec::with_capacity(MAX_NCW);
    for i in 1..=MAX_NCW {
        let mut msg = format!("{my} {his}");
        if !my_std {
            if i == 1 || i >= 6 {
                msg = format!("<{my}> {his}");
            }
            if (2..=4).contains(&i) {
                msg = format!("{my} <{his}>");
            }
        } else if !his_std {
            if i <= 4 || i == 6 {
                msg = format!("<{my}> {his}");
            }
            if i >= 7 {
                msg = format!("{my} <{his}>");
            }
        }
        let base = msg.clone();
        match i {
            2 => msg = format!("{base} RRR"),
            3 => msg = format!("{base} RR73"),
            4 => msg = format!("{base} 73"),
            5 => msg = if his_std { format!("CQ {his} {g4}") } else { format!("CQ {his}") },
            6 if his_std => msg = format!("{base} {g4}"),
            7..=206 => {
                let isnr = -50 + (i as i32 - 7) / 2;
                let r = format!("{:03}", isnr.abs());
                let num = if isnr < 0 { format!("-{}", &r[1..]) } else { format!("+{}", &r[1..]) };
                msg = if i & 1 == 1 { format!("{base} {num}") } else { format!("{base} R{num}") };
            }
            _ => {}
        }
        out.push(msg);
    }
    out
}

/// q65_set_list: the list's messages as codewords.
fn set_list(mycall: &str, hiscall: &str, hisgrid: &str) -> Vec<[i32; NN]> {
    let my = mycall.trim();
    let his = hiscall.trim();
    if his.is_empty() {
        return vec![];
    }
    list_messages(my, his, hisgrid)
        .iter()
        .map(|msg| {
            let tones = match genq65(msg) {
                Ok(e) => e.tones,
                // genq65 sends whatever pack77 made of it; a message ohsdigi
                // refuses never matches a real signal, so an all-zero
                // codeword stands in for it.
                Err(_) => [0u8; NSYM],
            };
            let mut cw = [0i32; NN];
            let (mut i0, mut j) = (0, 0);
            for k in 1..=NSYM {
                if i0 < ISYNC.len() && k == ISYNC[i0] {
                    i0 += 1;
                    continue;
                }
                cw[j] = tones[k - 1] as i32 - 1;
                j += 1;
            }
            cw
        })
        .collect()
}

/// The hashed-call table as jt9 has it when it unpacks a period's
/// decodes (q65_decode.f90, in its order): MyCall and DxCall set, the
/// list's 206 messages packed and unpacked by genq65 (when there is a
/// DxCall), then ft8apset's "MYCALL DXCALL RRR" (MyCall in <> when it is
/// not standard, a dummy KA1ABC without a DxCall) with the DxCall's hash
/// saved. Without it a message to or from a hashed call shows "<...>"
/// where jt9 shows the call.
pub fn jt9_hashes(mycall: &str, hiscall: &str) -> CallHashes {
    use crate::msg77::pack77;
    let my = mycall.trim().to_ascii_uppercase();
    let his = hiscall.trim().to_ascii_uppercase();
    let mut h = CallHashes::new();
    if !my.is_empty() {
        h.set_mycall(&my);
    }
    if !his.is_empty() {
        h.set_dxcall(&his);
    }
    let pack_unpack = |h: &mut CallHashes, msg: &str, received: bool| {
        let norm = crate::msg77::fmtmsg(msg.as_bytes());
        if let Ok(p) = pack77(&norm, h) {
            let _ = unpack77_c77(&p.c77, received, h);
        }
    };
    if !his.is_empty() {
        for msg in list_messages(&my, &his, "") {
            pack_unpack(&mut h, &msg, false);
        }
    }
    if my.len() >= 3 {
        let dx = if his.len() >= 3 {
            h.save(his.as_bytes());
            his.clone()
        } else {
            "KA1ABC".to_string()
        };
        let msg = if stdcall(&my) { format!("{my} {dx} RRR") } else { format!("<{my}> {dx} RRR") };
        pack_unpack(&mut h, &msg, true);
    }
    h
}

/// Unpack a decode and report it unless its text was reported already
/// (q65_decode.f90's `decodes` list).
#[allow(clippy::too_many_arguments)]
fn emit(
    st: &St,
    dat4: &[i32; NK],
    idec: i32,
    dtdec: f32,
    f0dec: f32,
    out: &mut Vec<Q65Decode>,
    decodes: &mut Vec<String>,
    f0decodes: &mut Vec<f32>,
    hashes: &mut CallHashes,
) {
    let c77 = c77_of_symbols(dat4);
    let u = unpack77_c77(&c77, true, hashes);
    let text = u.text_lossy().trim_end().to_string();
    if decodes.contains(&text) {
        return;
    }
    decodes.push(text.clone());
    f0decodes.push(f0dec);
    let snr2 = q65_snr(st, dat4, dtdec, f0dec);
    out.push(Q65Decode {
        text,
        snr: nint(snr2),
        dt: dtdec,
        freq: f0dec,
        idec,
        nused: 1,
        bits: c77.iter().map(|&b| b as char).collect(),
    });
}

/// One period of 12 kHz audio (int16 units, from the period start) in;
/// decodes out, in jt9's order.
pub fn decode_period(audio: &[f32], p: &Q65Params, hashes: &mut CallHashes) -> Vec<Q65Decode> {
    with_pool(p.threads, || decode_in_pool(audio, p, hashes))
}

fn decode_in_pool(audio: &[f32], p: &Q65Params, hashes: &mut CallHashes) -> Vec<Q65Decode> {
    let Some(nsps) = nsps_of(p.period) else { return vec![] };
    let npts = p.period as usize * 12000;
    let mut iwave = vec![0f32; npts];
    let n = audio.len().min(npts);
    iwave[..n].copy_from_slice(&audio[..n]);
    let mode_q65 = 1usize << p.submode;
    let mut st = St {
        nsps,
        mode_q65,
        nsubmode: p.submode,
        ntrperiod: p.period as usize,
        nfa: p.nfa,
        nfb: p.nfb,
        ndepth: p.ndepth,
        ibwa: 1,
        ibwb: 0,
        maxiters: 40,
        codewords: vec![],
        istep: 0,
        nsmo: 0,
        lag1: 0,
        lag2: 0,
        j0: 0,
        i0: 0,
        df: 0.0,
        dtstep: 0.0,
        ftol: 0.0,
        drift: 0.0,
        npasses: 2,
        apsym0: [0; 58],
        apmask1: [0; 78],
        apsymbols1: [0; 78],
        apmask: [0; NK],
        apsymbols: [0; NK],
        candidates: vec![],
        iz: 0,
        jz: 0,
        s1: vec![],
        ccf2: vec![],
        sync: [0.0; NSYM],
    };
    st.ibwa = match mode_q65 {
        1 => 1,
        2 => 3,
        _ => 8,
    };
    st.ibwb = 15.min(st.ibwa + 6);
    if p.ndepth & 3 == 2 {
        st.maxiters = 60;
    }
    if p.ndepth & 3 == 3 {
        st.ibwa = 1.max(st.ibwa - 2);
        st.ibwb = 15.min(st.ibwb + 2);
        st.maxiters = 100;
    }
    // nqd is 1 for jt9's first call, so the list is built whenever the
    // other station's call is known.
    st.codewords = set_list(&p.mycall, &p.hiscall, &p.hisgrid);
    // ft8apset, then "where(apsym0.eq.-1) apsym0=0" (99 marks unusable).
    st.apsym0 = [0; 58];
    st.apsym0[0] = 99;
    st.apsym0[29] = 99;
    if let Some(a) = ft8_ap(&p.mycall, &p.hiscall) {
        for i in 0..58 {
            st.apsym0[i] = a.payload[i] as i32;
        }
        if !a.has_dxcall {
            st.apsym0[29] = 99;
        }
    }
    st.npasses = if p.nqso_progress == 5 { 3 } else { 2 };
    let lapcqonly = false;
    let nsps2 = nsps / 2;
    let baud = 12000.0f32 / nsps as f32;

    let mut out: Vec<Q65Decode> = Vec::new();
    let mut decodes: Vec<String> = Vec::new();
    let mut f0decodes: Vec<f32> = Vec::new();
    let mut c00: Option<Vec<C32>> = None;
    let (idec0, dat40, xdt, f0) = dec0(&mut st, &iwave, p.nfqso, p.ntol, p.emedelay);
    let mut found = if idec0 >= 0 { Some((idec0, dat40, xdt, f0)) } else { None };
    if found.is_none() {
        let mut jpk0 = ((xdt + 1.0) * 6000.0) as i32;
        if st.ntrperiod <= 30 {
            jpk0 = ((xdt + 0.5) * 6000.0) as i32;
        }
        jpk0 = jpk0.max(0);
        let c = c00.get_or_insert_with(|| ana64(&iwave, npts));
        let npasses = if lapcqonly { 1 } else { st.npasses };
        let mut iaptype = 0;
        for ipass in 0..=npasses {
            iaptype = set_ap(&mut st, p.nqso_progress, ipass, lapcqonly, iaptype);
            if let Some(r) = loops(&st, c, nsps2, jpk0, xdt, f0, iaptype) {
                found = Some(r);
                break;
            }
        }
    }
    if let Some((idec, dat4, dtdec, f0dec)) = found {
        emit(&st, &dat4, idec, dtdec, f0dec, &mut out, &mut decodes, &mut f0decodes, hashes);
    }
    if p.single_decode {
        return out;
    }
    let candidates = st.candidates.clone();
    'cand: for cand in candidates {
        let (xdt, f0) = (cand[1], cand[2]);
        for &fd in &f0decodes {
            let fdiff = f0 - fd;
            if fdiff > -baud * mode_q65 as f32 && fdiff < 65.0 * baud * mode_q65 as f32 {
                continue 'cand;
            }
        }
        let mut jpk0 = ((xdt + 1.0) * 6000.0) as i32;
        if st.ntrperiod <= 30 {
            jpk0 = ((xdt + 0.5) * 6000.0) as i32;
        }
        jpk0 = jpk0.max(0);
        let c = c00.get_or_insert_with(|| ana64(&iwave, npts));
        let npasses = if lapcqonly { 1 } else { st.npasses };
        let mut iaptype = 0;
        for ipass in 0..=npasses {
            iaptype = set_ap(&mut st, p.nqso_progress, ipass, lapcqonly, iaptype);
            if let Some((idec, dat4, dtdec, f0dec)) = loops(&st, c, nsps2, jpk0, xdt, f0, iaptype) {
                emit(&st, &dat4, idec, dtdec, f0dec, &mut out, &mut decodes, &mut f0decodes, hashes);
                break;
            }
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn stdcall_as_q65_set_list_has_it() {
        assert!(stdcall("K1ABC"));
        assert!(stdcall("GM4BRI"));
        assert!(stdcall("2E0ABC"));
        assert!(!stdcall("PJ4/K1ABC"));
        assert!(!stdcall("K1ABCDE"));
    }

    #[test]
    fn the_list_holds_the_reports_both_ways() {
        let l = set_list("K1ABC", "W9XYZ", "EN37");
        assert_eq!(l.len(), 206);
        let want = genq65("K1ABC W9XYZ R-15").unwrap().tones;
        let mut cw = [0i32; NN];
        let mut j = 0;
        for (k, &t) in want.iter().enumerate() {
            if !ISYNC.contains(&(k + 1)) {
                cw[j] = t as i32 - 1;
                j += 1;
            }
        }
        assert!(l.contains(&cw));
    }
}
