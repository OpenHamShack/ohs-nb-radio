// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from JS8Call 2.2.0 lib/ft8/encode174.f90, bpdecode174.f90 and
// osd174.f90 - WSJT-X 1.9's (174,87) code, copyright (C) 2001-2018 Joe
// Taylor K1JT, Steve Franke K9AN and the WSJT Development Group, kept in
// JS8Call by Jordan Sherer KN4CRD; GPL-3.0-or-later.

//! The (174,87) LDPC code JS8 carries: belief propagation, then
//! ordered-statistics decoding, as JS8Call's decoder runs them.
//!
//! This is the code FT8 used before WSJT-X 2.0 and is not the (174,91)
//! one in `crate::decode::ldpc`; the two decoders differ in more than
//! tables (bpdecode174 has no a-priori mask and a different early stop,
//! osd174 has the second pre-processing rule JS8 actually reaches at its
//! usual depth), so this is a port of its own rather than a generic one.
//!
//! The codeword is held in "parity-check order" throughout, as on the
//! air: encode174 builds [87 parity bits, 87 message bits] and then
//! scatters it by COLORDER; the decoders hand back the 87 message bits
//! by gathering through COLORDER again.

use super::ldpc_tables::{COLORDER, GENERATOR, MN, NM, NRW};
use super::KK;
use crate::decode::ldpc::platanh;
use crate::decode::util::indexx;
use std::sync::OnceLock;

pub const N: usize = 174;
pub const K: usize = KK;
pub const M: usize = N - K;

/// gen(i, j): parity bit i takes message bit j (encode174's matrix).
fn gen_rows() -> &'static [[u8; K]; M] {
    static G: OnceLock<[[u8; K]; M]> = OnceLock::new();
    G.get_or_init(|| {
        let mut g = [[0u8; K]; M];
        for (i, hex) in GENERATOR.iter().enumerate() {
            for (j, c) in hex.chars().enumerate() {
                let v = c.to_digit(16).unwrap();
                for jj in 0..4 {
                    let col = 4 * j + jj;
                    if col < K && (v >> (3 - jj)) & 1 == 1 {
                        g[i][col] = 1;
                    }
                }
            }
        }
        g
    })
}

/// encode174: 87 information bits to the 174-bit codeword as sent.
pub fn encode(message: &[u8; K]) -> [u8; N] {
    let g = gen_rows();
    let mut itmp = [0u8; N];
    for i in 0..M {
        let mut s = 0u8;
        for j in 0..K {
            s ^= message[j] & g[i][j];
        }
        itmp[i] = s;
    }
    itmp[M..].copy_from_slice(message);
    let mut cw = [0u8; N];
    for i in 0..N {
        cw[COLORDER[i] as usize] = itmp[i];
    }
    cw
}

/// The 87 message bits of a codeword in channel order.
fn message_of(cw: &[u8; N]) -> [u8; K] {
    let mut d = [0u8; K];
    for i in 0..K {
        d[i] = cw[COLORDER[M + i] as usize];
    }
    d
}

/// What either decoder returns.
#[derive(Clone, Debug)]
pub struct LdpcResult {
    pub decoded: [u8; K],
    /// The codeword, channel order (all zero when BP gave up).
    pub cw: [u8; N],
    /// Disagreements with the channel's hard decisions; -1 = no decode.
    pub nharderror: i32,
    /// OSD's soft distance (0 from BP).
    pub dmin: f32,
}

/// bpdecode174: log-domain belief propagation, at most `maxiterations`
/// rounds, with its early stop (five rounds without fewer unsatisfied
/// checks, after ten, with more than fifteen still unsatisfied).
pub fn bpdecode174(llr: &[f32; N], maxiterations: usize) -> LdpcResult {
    let mut toc = [[0f32; 7]; M];
    let mut tov = [[0f32; 3]; N];
    let mut tanhtoc = [[0f32; 7]; M];
    let mut zn = [0f32; N];
    let mut cw = [0u8; N];
    for j in 0..M {
        for i in 0..NRW[j] as usize {
            toc[j][i] = llr[NM[j][i] as usize - 1];
        }
    }
    let mut ncnt = 0;
    let mut nclast = 0i32;
    for iter in 0..=maxiterations {
        for i in 0..N {
            zn[i] = llr[i] + tov[i][0] + tov[i][1] + tov[i][2];
        }
        for i in 0..N {
            cw[i] = (zn[i] > 0.0) as u8;
        }
        let mut ncheck = 0i32;
        for i in 0..M {
            let mut s = 0u8;
            for k in 0..NRW[i] as usize {
                s += cw[NM[i][k] as usize - 1];
            }
            if s % 2 != 0 {
                ncheck += 1;
            }
        }
        if ncheck == 0 {
            let mut nerr = 0;
            for i in 0..N {
                if (2.0 * cw[i] as f32 - 1.0) * llr[i] < 0.0 {
                    nerr += 1;
                }
            }
            return LdpcResult { decoded: message_of(&cw), cw, nharderror: nerr, dmin: 0.0 };
        }
        if iter > 0 {
            let nd = ncheck - nclast;
            if nd < 0 {
                ncnt = 0;
            } else {
                ncnt += 1;
            }
            if ncnt >= 5 && iter >= 10 && ncheck > 15 {
                break;
            }
        }
        nclast = ncheck;
        for j in 0..M {
            for i in 0..NRW[j] as usize {
                let ibj = NM[j][i] as usize - 1;
                let mut t = zn[ibj];
                for kk in 0..3 {
                    if MN[ibj][kk] as usize == j + 1 {
                        t -= tov[ibj][kk];
                    }
                }
                toc[j][i] = t;
            }
        }
        for i in 0..M {
            for k in 0..7 {
                tanhtoc[i][k] = (-toc[i][k] / 2.0).tanh();
            }
        }
        for j in 0..N {
            for i in 0..3 {
                let ichk = MN[j][i] as usize - 1;
                let mut tmn = 1.0f32;
                for k in 0..NRW[ichk] as usize {
                    if NM[ichk][k] as usize != j + 1 {
                        tmn *= tanhtoc[ichk][k];
                    }
                }
                tov[j][i] = 2.0 * platanh(-tmn);
            }
        }
    }
    LdpcResult { decoded: [0; K], cw, nharderror: -1, dmin: 0.0 }
}

/// osd174's generator: [parity | identity], one row per message bit,
/// columns in encode174's own (parity, message) order.
fn osd_gen() -> &'static Vec<[u8; N]> {
    static G: OnceLock<Vec<[u8; N]>> = OnceLock::new();
    G.get_or_init(|| {
        let g = gen_rows();
        let mut rows = vec![[0u8; N]; K];
        for i in 0..M {
            for irow in 0..K {
                rows[irow][i] = g[i][irow];
            }
        }
        for irow in 0..K {
            rows[irow][M + irow] = 1;
        }
        rows
    })
}

fn mrbencode(me: &[u8], g2: &[[u8; N]]) -> [u8; N] {
    let mut cw = [0u8; N];
    for (i, &b) in me.iter().enumerate() {
        if b == 1 {
            for c in 0..N {
                cw[c] ^= g2[i][c];
            }
        }
    }
    cw
}

/// nextpat: the next error pattern of weight `iorder` over `mi` (1-based
/// semantics; returns the new iflag, the lowest set position, or -1).
fn nextpat(mi: &mut [u8], k: usize, iorder: usize) -> i64 {
    let mut ind: i64 = -1;
    for i in 0..k - 1 {
        if mi[i] == 0 && mi[i + 1] == 1 {
            ind = i as i64;
        }
    }
    if ind < 0 {
        return -1;
    }
    let ind = ind as usize;
    let mut ms = vec![0u8; k];
    ms[..ind].copy_from_slice(&mi[..ind]);
    ms[ind] = 1;
    ms[ind + 1] = 0;
    if ind + 2 < k {
        let nz = iorder - ms.iter().map(|&x| x as usize).sum::<usize>();
        for x in ms[k - nz..].iter_mut() {
            *x = 1;
        }
    }
    mi.copy_from_slice(&ms);
    mi.iter().position(|&x| x == 1).map(|p| p as i64 + 1).unwrap_or(-1)
}

/// boxit/fetchit's hash of two-column syndrome patterns (osd174's second
/// pre-processing rule): Fortran common-block state made into a struct,
/// fetchit's `save`d cursor included, because which pairs are tried
/// depends on it carrying over between calls exactly as it does there.
struct Boxes {
    indexes: Vec<[i32; 2]>,
    fp: Vec<i32>,
    np: Vec<i32>,
    lastpat: i64,
    inext: i32,
}

impl Boxes {
    fn new() -> Self {
        Boxes { indexes: vec![[-1, -1]; 4001], fp: vec![-1; 525001], np: vec![-1; 4001], lastpat: -1, inext: -1 }
    }

    fn pattern(e2: &[u8]) -> usize {
        let ntau = e2.len();
        let mut ipat = 0usize;
        for i in 0..ntau {
            if e2[i] == 1 {
                ipat += 1 << (ntau - 1 - i);
            }
        }
        ipat
    }

    fn boxit(&mut self, e2: &[u8], npindex: usize, i1: usize, i2: usize) {
        self.indexes[npindex] = [i1 as i32, i2 as i32];
        let ipat = Self::pattern(e2);
        let ip = self.fp[ipat];
        if ip == -1 {
            self.fp[ipat] = npindex as i32;
        } else {
            let mut ip = ip as usize;
            while self.np[ip] != -1 {
                ip = self.np[ip] as usize;
            }
            self.np[ip] = npindex as i32;
        }
    }

    fn fetchit(&mut self, e2: &[u8]) -> (i32, i32) {
        let ipat = Self::pattern(e2) as i64;
        let index = self.fp[ipat as usize];
        let r;
        if self.lastpat != ipat && index > 0 {
            let ix = index as usize;
            r = (self.indexes[ix][0], self.indexes[ix][1]);
            self.inext = self.np[ix];
        } else if self.lastpat == ipat && self.inext > 0 {
            let ix = self.inext as usize;
            r = (self.indexes[ix][0], self.indexes[ix][1]);
            self.inext = self.np[ix];
        } else {
            r = (-1, -1);
            self.inext = -1;
        }
        self.lastpat = ipat;
        r
    }
}

/// osd174: ordered-statistics decoding at depth `ndeep` (0..5; JS8 calls
/// it with 3, 4 or 5).
pub fn osd174(llr: &[f32; N], ndeep: i32) -> LdpcResult {
    let gen = osd_gen();
    // Received word in (parity, message) order.
    let mut rx = [0f32; N];
    for i in 0..N {
        rx[i] = llr[COLORDER[i] as usize];
    }
    let mut hdec = [0u8; N];
    for i in 0..N {
        hdec[i] = (rx[i] >= 0.0) as u8;
    }
    let mut absrx: Vec<f32> = rx.iter().map(|x| x.abs()).collect();
    let indx = indexx(&absrx);

    let mut genmrb = vec![[0u8; N]; K];
    let mut indices = [0usize; N];
    for i in 0..N {
        let src = indx[N - 1 - i];
        for r in 0..K {
            genmrb[r][i] = gen[r][src];
        }
        indices[i] = src;
    }
    for id in 0..K {
        for icol in id..(K + 20).min(N) {
            if genmrb[id][icol] == 1 {
                if icol != id {
                    for r in 0..K {
                        genmrb[r].swap(id, icol);
                    }
                    indices.swap(id, icol);
                }
                let pivot = genmrb[id];
                for ii in 0..K {
                    if ii != id && genmrb[ii][id] == 1 {
                        for c in 0..N {
                            genmrb[ii][c] ^= pivot[c];
                        }
                    }
                }
                break;
            }
        }
    }
    // g2(:, i) is genmrb's row i; kept as rows.
    let g2 = &genmrb;

    let hdec0 = hdec;
    for i in 0..N {
        hdec[i] = hdec0[indices[i]];
    }
    let m0: Vec<u8> = hdec[..K].to_vec();
    let absrx0 = absrx.clone();
    for i in 0..N {
        absrx[i] = absrx0[indices[i]];
    }

    let c0 = mrbencode(&m0, g2);
    let mut nhardmin: i32 = (0..N).map(|i| (c0[i] ^ hdec[i]) as i32).sum();
    let mut dmin: f32 = (0..N).map(|i| (c0[i] ^ hdec[i]) as f32 * absrx[i]).sum();
    let mut cw = c0;

    let ndeep = ndeep.min(5);
    if ndeep > 0 {
        let (nord, npre1, npre2, nt, ntheta, ntau) = match ndeep {
            1 => (1, 0, 0, 40, 12, 0),
            2 => (1, 1, 0, 40, 12, 0),
            3 => (1, 1, 1, 40, 12, 14),
            4 => (2, 1, 0, 40, 12, 19),
            _ => (2, 1, 1, 40, 12, 19),
        };
        let mut misub = vec![0u8; K];
        let mut e2sub = vec![0u8; N - K];
        let mut d1 = 0f32;
        for iorder in 1..=nord {
            misub.iter_mut().for_each(|x| *x = 0);
            for x in misub[K - iorder..].iter_mut() {
                *x = 1;
            }
            let mut iflag: i64 = (K - iorder + 1) as i64;
            while iflag >= 0 {
                let iend: i64 = if iorder == nord && npre1 == 0 { iflag } else { 1 };
                let mut n1 = iflag;
                while n1 >= iend {
                    let n1u = n1 as usize - 1;
                    let mut mi = misub.clone();
                    mi[n1u] = 1;
                    let me: Vec<u8> = (0..K).map(|i| m0[i] ^ mi[i]).collect();
                    let e2: Vec<u8>;
                    let nd1kpt: i32;
                    if n1 == iflag {
                        let ce = mrbencode(&me, g2);
                        e2sub = (0..N - K).map(|i| ce[K + i] ^ hdec[K + i]).collect();
                        e2 = e2sub.clone();
                        nd1kpt = e2sub[..nt].iter().map(|&x| x as i32).sum::<i32>() + 1;
                        d1 = (0..K).map(|i| (me[i] ^ hdec[i]) as f32 * absrx[i]).sum();
                    } else {
                        e2 = (0..N - K).map(|i| e2sub[i] ^ g2[n1u][K + i]).collect();
                        nd1kpt = e2[..nt].iter().map(|&x| x as i32).sum::<i32>() + 2;
                    }
                    if nd1kpt <= ntheta {
                        let ce = mrbencode(&me, g2);
                        let dd = if n1 == iflag {
                            d1 + (0..N - K).map(|i| e2sub[i] as f32 * absrx[K + i]).sum::<f32>()
                        } else {
                            d1 + (ce[n1u] ^ hdec[n1u]) as f32 * absrx[n1u]
                                + (0..N - K).map(|i| e2[i] as f32 * absrx[K + i]).sum::<f32>()
                        };
                        if dd < dmin {
                            dmin = dd;
                            cw = ce;
                            nhardmin = (0..N).map(|i| (ce[i] ^ hdec[i]) as i32).sum();
                        }
                    }
                    n1 -= 1;
                }
                iflag = nextpat(&mut misub, K, iorder);
            }
        }

        if npre2 == 1 {
            let mut bx = Boxes::new();
            let mut ntotal = 0usize;
            for i1 in (1..=K).rev() {
                for i2 in (1..i1).rev() {
                    ntotal += 1;
                    let mi: Vec<u8> = (0..ntau).map(|t| g2[i1 - 1][K + t] ^ g2[i2 - 1][K + t]).collect();
                    bx.boxit(&mi, ntotal, i1, i2);
                }
            }
            misub.iter_mut().for_each(|x| *x = 0);
            for x in misub[K - nord..].iter_mut() {
                *x = 1;
            }
            let mut iflag: i64 = (K - nord + 1) as i64;
            while iflag >= 0 {
                let me: Vec<u8> = (0..K).map(|i| m0[i] ^ misub[i]).collect();
                let ce = mrbencode(&me, g2);
                let e2sub: Vec<u8> = (0..N - K).map(|i| ce[K + i] ^ hdec[K + i]).collect();
                'i2: for i2 in 0..=ntau {
                    let mut r2pat = e2sub.clone();
                    if i2 > 0 {
                        r2pat[i2 - 1] ^= 1;
                    }
                    loop {
                        let (in1, in2) = bx.fetchit(&r2pat[..ntau]);
                        if !(in1 > 0 && in2 > 0) {
                            break;
                        }
                        let mut mi = misub.clone();
                        mi[in1 as usize - 1] = 1;
                        mi[in2 as usize - 1] = 1;
                        if mi.iter().map(|&x| x as usize).sum::<usize>() < nord + npre1 + npre2 {
                            continue 'i2;
                        }
                        let me: Vec<u8> = (0..K).map(|i| m0[i] ^ mi[i]).collect();
                        let ce = mrbencode(&me, g2);
                        let dd: f32 = (0..N).map(|i| (ce[i] ^ hdec[i]) as f32 * absrx[i]).sum();
                        if dd < dmin {
                            dmin = dd;
                            cw = ce;
                            nhardmin = (0..N).map(|i| (ce[i] ^ hdec[i]) as i32).sum();
                        }
                    }
                }
                iflag = nextpat(&mut misub, K, nord);
            }
        }
    }

    // Back to (parity, message) order, then to channel order.
    let mut cw_pm = [0u8; N];
    for i in 0..N {
        cw_pm[indices[i]] = cw[i];
    }
    let mut decoded = [0u8; K];
    decoded.copy_from_slice(&cw_pm[M..]);
    let mut out = [0u8; N];
    for i in 0..N {
        out[COLORDER[i] as usize] = cw_pm[i];
    }
    LdpcResult { decoded, cw: out, nharderror: nhardmin, dmin }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn llr_of(cw: &[u8; N], mag: f32) -> [f32; N] {
        let mut l = [0f32; N];
        for i in 0..N {
            l[i] = if cw[i] == 1 { mag } else { -mag };
        }
        l
    }

    fn some_message(seed: u32) -> [u8; K] {
        let mut m = [0u8; K];
        let mut x = seed.wrapping_mul(2654435761).wrapping_add(12345);
        for b in m.iter_mut() {
            x ^= x << 13;
            x ^= x >> 17;
            x ^= x << 5;
            *b = (x & 1) as u8;
        }
        m
    }

    #[test]
    fn every_codeword_satisfies_every_check() {
        for seed in 0..20 {
            let cw = encode(&some_message(seed));
            for j in 0..M {
                let s: u8 = (0..NRW[j] as usize).map(|i| cw[NM[j][i] as usize - 1]).sum();
                assert_eq!(s % 2, 0, "check {j} fails for seed {seed}");
            }
        }
    }

    #[test]
    fn bp_corrects_a_few_errors() {
        let m = some_message(7);
        let cw = encode(&m);
        let mut l = llr_of(&cw, 4.0);
        for &i in &[3usize, 50, 99, 140, 170] {
            l[i] = -l[i] * 0.3;
        }
        let r = bpdecode174(&l, 30);
        assert_eq!(r.decoded, m);
        assert_eq!(r.nharderror, 5);
    }

    #[test]
    fn osd_recovers_what_bp_cannot() {
        let m = some_message(11);
        let cw = encode(&m);
        // Erase 48 bits (llr 0) and weaken the rest: BP stalls, OSD at
        // depth 3 finds the codeword from the reliable half.
        let mut l = llr_of(&cw, 1.0);
        for i in 0..48 {
            l[(i * 7) % N] = 0.0;
        }
        for &i in &[1usize, 60, 130] {
            l[i] = -0.2 * l[i];
        }
        let r = osd174(&l, 3);
        assert_eq!(r.decoded, m);
        assert_eq!(r.cw, cw);
    }
}
