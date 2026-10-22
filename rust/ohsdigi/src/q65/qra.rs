// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0 lib/qra/q65: q65.c, qracodes.c, npfwht.c and
// pdmath.c, copyright (C) 2020 Nico Palermo IV3NWV - Microtelecom Srl,
// GPL-3.0-or-later (the qracodes project), with the q65_subs.c wrappers
// WSJT-X calls them through.

//! The Q65 codec: a (15,65) Q-ary repeat-accumulate code over GF(64),
//! 13 message symbols and a two-symbol CRC-12 that is punctured (not sent),
//! so 63 symbols go on the air. Decoding is message passing in the
//! Walsh-Hadamard domain, fed by "fast-fading" intrinsic probabilities that
//! spread each tone's energy over the bins a Doppler-spread signal fills.
//!
//! Single precision throughout, operation for operation as the C does it:
//! the decoder's accept/reject thresholds sit on these numbers.

use super::tables::*;

/// Information symbols of the code (13 message + 2 CRC).
const K: usize = 15;
/// Symbols in the code's own codeword (CRC included).
const N: usize = 65;
/// Message symbols.
pub const NK: usize = 13;
/// Symbols sent: the codeword without its two CRC symbols.
pub const NN: usize = 63;
/// Alphabet size (GF(64)).
pub const M: usize = 64;
const LOG2M: usize = 6;
const NC: usize = N - K;
const V: usize = 65;
const C: usize = 116;
const NMSG: usize = 216;
const MAXVDEG: usize = 5;
const MAXCDEG: usize = 3;

/// q65.c Q65_LLH_THRESHOLD: the least codeword log-likelihood accepted.
const LLH_THRESHOLD: f32 = -260.0;

pub const DECODE_FAILED: i32 = -2;
pub const DECODE_CRCMISMATCH: i32 = -3;
pub const DECODE_LLHLOW: i32 = -4;

/// _q65_crc12: the two CRC symbols for 13 message symbols.
fn crc12(x: &[i32]) -> [i32; 2] {
    let mut sr: i32 = 0;
    for &v in &x[..NK] {
        let mut t = v;
        for _ in 0..6 {
            if (t ^ sr) & 1 != 0 {
                sr = (sr >> 1) ^ 0xF01;
            } else {
                sr >>= 1;
            }
            t >>= 1;
        }
    }
    [sr & 0x3F, sr >> 6]
}

/// qra_encode for this code (grouping factor 1).
fn qra_encode(x: &[i32; K]) -> [i32; N] {
    let mut y = [0i32; N];
    y[..K].copy_from_slice(x);
    let mut chk = 0i32;
    for k in 0..NC {
        let mut t = x[ACC_INPUT_IDX[k] as usize];
        if t != 0 {
            t = (GF_LOG[t as usize] as i32 + ACC_INPUT_WLOG[k] as i32) % (M as i32 - 1);
            t = GF_EXP[t as usize] as i32;
            chk ^= t;
        }
        y[K + k] = chk;
    }
    y
}

/// q65_encode: 13 message symbols (each 0..63) to the 63 sent.
pub fn encode(msg: &[i32; NK]) -> [i32; NN] {
    let mut x = [0i32; K];
    x[..NK].copy_from_slice(msg);
    let c = crc12(msg);
    x[NK] = c[0];
    x[NK + 1] = c[1];
    let y = qra_encode(&x);
    let mut out = [0i32; NN];
    out[..NK].copy_from_slice(&y[..NK]);
    out[NK..].copy_from_slice(&y[K..]);
    out
}

// ---------------------------------------------------- pdmath, npfwht

/// np_fwht for 64 points, in place: the butterflies in WSJT-X's order
/// (distance 32 first), so each sum and difference is the same float.
fn fwht(x: &mut [f32]) {
    let mut dist = M / 2;
    while dist >= 1 {
        let mut base = 0;
        while base < M {
            for offs in 0..dist {
                let a = x[base + offs];
                let b = x[base + offs + dist];
                x[base + offs] = a + b;
                x[base + offs + dist] = a - b;
            }
            base += 2 * dist;
        }
        dist /= 2;
    }
}

/// pd_norm: scale to sum 1 (uniform if the sum is not positive); returns
/// the sum.
fn pd_norm(p: &mut [f32]) -> f32 {
    let mut t = p[0];
    for &v in &p[1..M] {
        t += v;
    }
    if t <= 0.0 {
        p[..M].iter_mut().for_each(|v| *v = 1.0 / 64.0);
        return t;
    }
    let inv = 1.0f32 / t;
    for v in p[..M].iter_mut() {
        *v *= inv;
    }
    t
}

fn pd_max(p: &[f32]) -> f32 {
    let mut cmax = 0f32;
    for k in (0..M).rev() {
        if p[k] >= cmax {
            cmax = p[k];
        }
    }
    cmax
}

/// pd_argmax: scanning down with >=, so the lowest index of a tie.
fn pd_argmax(p: &[f32]) -> i32 {
    let mut cmax = 0f32;
    let mut idx = -1i32;
    for k in (0..M).rev() {
        if p[k] >= cmax {
            cmax = p[k];
            idx = k as i32;
        }
    }
    idx
}

fn pmat(w: usize) -> &'static [i16] {
    &PMAT[w * M..w * M + M]
}

/// qra_extrinsic: message passing; (rc, extrinsics [V][M]). rc is the
/// iteration it converged at, or -1.
fn qra_extrinsic(pix: &[f32], maxiter: usize) -> (i32, Vec<f32>) {
    let mut v2c = vec![0f32; NMSG * M];
    let mut c2v = vec![0f32; NMSG * M];
    c2v[..M * V].copy_from_slice(&pix[..M * V]);
    for nv in 0..V {
        let ndeg = VDEG[nv] as usize;
        let base = nv * MAXVDEG;
        for k in 1..ndeg {
            let imsg = V2CMIDX[base + k] as usize;
            v2c[imsg * M..imsg * M + M].copy_from_slice(&pix[nv * M..nv * M + M]);
        }
    }
    let mut rc = -1;
    let mut msgout = [0f32; M];
    for nit in 0..maxiter {
        for nc in V..C {
            let ndeg = CDEG[nc] as usize;
            let base = nc * MAXCDEG;
            for k in 0..ndeg {
                let imsg = C2VMIDX[base + k] as usize;
                fwht(&mut v2c[imsg * M..imsg * M + M]);
            }
            for k in 0..ndeg {
                msgout.iter_mut().for_each(|v| *v = 1.0 / 64.0);
                for kk in 0..ndeg {
                    if kk != k {
                        let imsg = C2VMIDX[base + kk] as usize;
                        for j in 0..M {
                            msgout[j] *= v2c[imsg * M + j];
                        }
                    }
                }
                msgout[0] += 1e-7;
                fwht(&mut msgout);
                let imsg = C2VMIDX[base + k] as usize;
                let w = MSGW[imsg] as usize;
                let dst = &mut c2v[imsg * M..imsg * M + M];
                if w == 0 {
                    dst.copy_from_slice(&msgout);
                } else {
                    let p = pmat(w);
                    for j in 0..M {
                        dst[p[j] as usize] = msgout[j];
                    }
                }
            }
        }
        for nv in 0..V {
            let ndeg = VDEG[nv] as usize;
            let base = nv * MAXVDEG;
            for k in 0..ndeg {
                msgout.iter_mut().for_each(|v| *v = 1.0 / 64.0);
                for kk in 0..ndeg {
                    if kk != k {
                        let imsg = V2CMIDX[base + kk] as usize;
                        for j in 0..M {
                            msgout[j] *= c2v[imsg * M + j];
                        }
                    }
                }
                pd_norm(&mut msgout);
                let imsg = V2CMIDX[base + k] as usize;
                let w = MSGW[imsg] as usize;
                let dst = &mut v2c[imsg * M..imsg * M + M];
                if w == 0 {
                    dst.copy_from_slice(&msgout);
                } else {
                    let p = pmat(w);
                    for j in 0..M {
                        dst[j] = msgout[p[j] as usize];
                    }
                }
            }
        }
        let mut totex = 0f32;
        for nv in 0..V {
            totex += pd_max(&v2c[nv * M..nv * M + M]);
        }
        if (totex as f64) > 1.0 * V as f64 - 0.01 {
            rc = nit as i32;
            break;
        }
    }
    v2c.truncate(M * V);
    (rc, v2c)
}

// ------------------------------------------------ fast-fading metric

/// What q65_intrinsics_fastfading leaves in the codec for the Es/No
/// estimate that follows a decode.
#[derive(Clone, Debug)]
pub struct Intrinsics {
    /// Symbol-value probabilities, [63][64].
    pub prob: Vec<f32>,
    noise_var: f32,
    esno_metric: f32,
    bins_per_tone: usize,
    bins_per_symbol: usize,
    n_weights: usize,
}

/// decoderEsNoMetric: 6 bits x rate 13/63 x Eb/No 2.8 dB.
fn decoder_esno_metric() -> f32 {
    // (float)pow(10, EbNodBMetric/10): the division in float, pow in double.
    let eb_no_metric = 10f64.powf((2.8f32 / 10.0f32) as f64) as f32;
    let r = 1.0f32 * NK as f32 / NN as f32;
    1.0f32 * LOG2M as f32 * r * eb_no_metric
}

/// q65_intrinsics_fastfading with the Lorentzian model (the only one Q65
/// uses): energies [63][64 x (2 + 2^submode)] to probabilities.
pub fn intrinsics_fastfading(energies: &[f32], submode: usize, b90ts: f32) -> Intrinsics {
    const TS_QRA64: f32 = 0.576;
    let b90 = b90ts / TS_QRA64;
    let mut hidx = (b90.ln() / 1.09f32.ln() - 0.499f32) as i32;
    hidx = hidx.clamp(0, 63);
    let hidx = hidx as usize;
    let hlen = LORENTZ_LEN[hidx];
    let hptr = LORENTZ[hidx];
    let f_temp = 8.0f32 * b90.ln() / 240.0f32.ln();
    let esno_metric = decoder_esno_metric() * 10.0f32.powf(f_temp / 10.0);
    let bins_per_tone = 1usize << submode;
    let bins_per_symbol = M * (2 + bins_per_tone);
    let bins_per_codeword = NN * bins_per_symbol;
    let mut noise_var = 0f32;
    for &e in &energies[..bins_per_codeword] {
        noise_var += e;
    }
    noise_var /= bins_per_codeword as f32;
    noise_var /= 1.0f32 + esno_metric / bins_per_symbol as f32;
    let weight: Vec<f32> = (0..hlen)
        .map(|k| {
            let t = hptr[k] * esno_metric;
            t / (1.0f32 + t) / noise_var
        })
        .collect();
    let mut prob = vec![0f32; NN * M];
    let hhsz = hlen - 1;
    let hlast = 2 * hhsz;
    for n in 0..NN {
        // The central bin of tone 0 of symbol n.
        let cur_sym = n * bins_per_symbol + M;
        let ix = &mut prob[n * M..n * M + M];
        let mut maxlogp = 0f32;
        let mut bin = cur_sym as isize - hlen as isize + 1;
        for k in 0..M {
            let at = |j: usize| energies[(bin + j as isize) as usize];
            let mut t = 0f32;
            for j in 0..hhsz {
                t += weight[j] * (at(j) + at(hlast - j));
            }
            t += weight[hhsz] * at(hhsz);
            if t > maxlogp {
                maxlogp = t;
            }
            ix[k] = t;
            bin += bins_per_tone as isize;
        }
        let mut sumix = 0f32;
        for k in 0..M {
            let x = (ix[k] - maxlogp).clamp(-85.0, 85.0);
            let t = x.exp();
            ix[k] = t;
            sumix += t;
        }
        let s = 1.0f32 / sumix;
        for v in ix.iter_mut() {
            *v *= s;
        }
    }
    Intrinsics { prob, noise_var, esno_metric, bins_per_tone, bins_per_symbol, n_weights: hlen }
}

/// q65_esnodb_fastfading: Es/No (dB) of a decoded codeword.
pub fn esnodb_fastfading(ff: &Intrinsics, ydec: &[i32; NN], energies: &[f32]) -> f32 {
    let ntot = 2 * ff.n_weights - 1;
    let mut es_plus_wno = 0f32;
    for n in 0..NN {
        let tone = n * ff.bins_per_symbol + M + ydec[n] as usize * ff.bins_per_tone;
        let first = tone + 1 - ff.n_weights;
        for j in 0..ntot {
            es_plus_wno += energies[first + j];
        }
    }
    es_plus_wno /= NN as f32;
    let mut u = es_plus_wno / (ff.noise_var * (1.0 + ff.esno_metric / ff.bins_per_symbol as f32));
    let minu = ntot as f32 + 0.316f32;
    if u < minu {
        u = minu;
    }
    u = (u - ntot as f32) / (1.0f32 - u / ff.bins_per_symbol as f32);
    10.0f32 * u.log10()
}

/// q65_check_llh: the codeword's log-likelihood, and whether it clears
/// the threshold.
fn check_llh(ydec: &[i32], prob: &[f32]) -> (f32, bool) {
    let mut t = 0f32;
    for k in 0..NN {
        let mut x = prob[k * M + ydec[k] as usize];
        if x < 1.0e-36 {
            x = 1.0e-36;
        }
        t += x.ln();
    }
    (t, t >= LLH_THRESHOLD)
}

/// What a decode returns: rc (iterations, or the list index, >= 0 on
/// success; a negative error otherwise), the message and the codeword.
#[derive(Clone, Debug)]
pub struct Decoded {
    pub rc: i32,
    pub msg: [i32; NK],
    pub codeword: [i32; NN],
}

/// q65_decode: message passing with an a-priori mask (13 symbols' worth of
/// known bits, `mask` saying which).
pub fn decode(prob: &[f32], mask: &[i32; NK], ap: &[i32; NK], maxiters: usize) -> Decoded {
    let mut out = Decoded { rc: DECODE_FAILED, msg: [0; NK], codeword: [0; NN] };
    // Depuncture: the two CRC symbols are unknown (uniform).
    let mut ix = vec![0f32; N * M];
    ix[..NK * M].copy_from_slice(&prob[..NK * M]);
    ix[NK * M..(NK + 2) * M].iter_mut().for_each(|v| *v = 1.0 / 64.0);
    ix[(NK + 2) * M..].copy_from_slice(&prob[NK * M..NN * M]);
    // _q65_mask.
    for k in 0..NK {
        let smask = mask[k];
        if smask != 0 {
            let row = &mut ix[k * M..k * M + M];
            for kk in 0..M as i32 {
                if ((kk ^ ap[k]) & smask) != 0 {
                    row[kk as usize] = 0.0;
                }
            }
            pd_norm(row);
        }
    }
    let (rc, mut ex) = qra_extrinsic(&ix, maxiters);
    if rc < 0 {
        return out;
    }
    // qra_mapdecode over the 15 information symbols.
    let mut px = [0i32; K];
    for k in 0..K {
        for j in 0..M {
            ex[k * M + j] *= ix[k * M + j];
        }
        px[k] = pd_argmax(&ex[k * M..k * M + M]);
    }
    let c = crc12(&px);
    if c[0] != px[NK] || c[1] != px[NK + 1] {
        out.rc = DECODE_CRCMISMATCH;
        return out;
    }
    out.msg.copy_from_slice(&px[..NK]);
    let y = qra_encode(&px);
    out.codeword[..NK].copy_from_slice(&y[..NK]);
    out.codeword[NK..].copy_from_slice(&y[K..]);
    if !check_llh(&out.codeword, prob).1 {
        out.rc = DECODE_LLHLOW;
        return out;
    }
    out.rc = rc;
    out
}

/// q65_decode_fullaplist: the most likely of a list of whole codewords,
/// if any clears a threshold raised with the list's length. Also returns
/// the best log-likelihood found (q65_llh, WSJT-X's `plog`).
pub fn decode_fullaplist(prob: &[f32], codewords: &[[i32; NN]]) -> (Decoded, f32) {
    let mut out = Decoded { rc: -1, msg: [0; NK], codeword: [0; NN] };
    let ncw = codewords.len();
    if ncw < 1 || ncw > 256 {
        return (out, 0.0);
    }
    let llh_threshold = LLH_THRESHOLD + (1.0f32 * ncw as f32 / 3.0).ln();
    let mut maxllh = llh_threshold;
    let mut maxcw: i32 = -1;
    for (k, cw) in codewords.iter().enumerate() {
        let (llh, ok) = check_llh(cw, prob);
        if ok && llh > maxllh {
            maxllh = llh;
            maxcw = k as i32;
        }
    }
    if maxcw < 0 {
        out.rc = DECODE_FAILED;
        return (out, maxllh);
    }
    let cw = codewords[maxcw as usize];
    out.codeword = cw;
    out.msg.copy_from_slice(&cw[..NK]);
    out.rc = maxcw;
    (out, maxllh)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn fwht_twice_is_64_times_identity() {
        let mut x: Vec<f32> = (0..64).map(|i| (i * 7 % 13) as f32).collect();
        let orig = x.clone();
        fwht(&mut x);
        fwht(&mut x);
        for i in 0..64 {
            assert!((x[i] - 64.0 * orig[i]).abs() < 1e-3);
        }
    }

    #[test]
    fn a_clean_codeword_decodes_and_a_wrong_crc_is_caught() {
        let msg = [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 14];
        let cw = encode(&msg);
        let mut prob = vec![0.002f32; NN * M];
        for n in 0..NN {
            prob[n * M + cw[n] as usize] = 0.9;
        }
        let d = decode(&prob, &[0; NK], &[0; NK], 40);
        assert!(d.rc >= 0, "rc {}", d.rc);
        assert_eq!(d.msg, msg);
        assert_eq!(d.codeword, cw);
        let (l, _) = decode_fullaplist(&prob, &[encode(&[0; NK]), cw]);
        assert_eq!(l.rc, 1);
    }
}
