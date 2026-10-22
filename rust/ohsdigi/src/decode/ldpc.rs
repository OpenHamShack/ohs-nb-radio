//! (174,91) LDPC decoding: belief propagation, then ordered-statistics
//! decoding (OSD) on what BP leaves, exactly as WSJT-X's hybrid decoder.
//!
//! Ported from WSJT-X 2.7.0 (GPL-3): lib/ft8/decode174_91.f90 (BP + the
//! OSD dispatch), lib/ft8/osd174_91.f90, lib/platanh.f90. Copyright (C)
//! 2001-2024 Joe Taylor K1JT, Steve Franke K9AN and the WSJT-X development
//! team. The algorithms are theirs; this file keeps their decision rules
//! (the early-stopping counter, OSD's ad-hoc `k+20` pivot search, the
//! "nhardmin > 0" acceptance test) because the point of the port is to
//! decode what WSJT-X decodes, no more and no less.
//!
//! Not ported: osd174_91's second pre-processing rule (npre2, `boxit91` /
//! `fetchit91`). It runs only at OSD depth 3 or more, and FT8 (ft8b.f90)
//! and FT4 (ft4_decode.f90) both call with norder=2.

use super::ldpc_tables::{MN, NM, NRW};
use crate::crc::crc14_ok as crc_ok;
use crate::ldpc::ldpc174_91::{GENERATOR, K, M, N};
use std::sync::OnceLock;

/// What decode174_91 returns.
#[derive(Clone, Debug)]
pub struct LdpcResult {
    /// 91 bits: 77 message + 14 CRC. Meaningful only when `nharderror >= 0`.
    pub message91: [u8; K],
    /// The codeword found (BP's last hard decision when nothing was found).
    pub cw: [u8; N],
    /// 0 none, 1 BP, 2 OSD.
    pub ntype: i32,
    /// Hard errors against the channel LLRs; -1 = no decode.
    pub nharderror: i32,
    /// Sum of |llr| over the bits the codeword disagrees with.
    pub dmin: f32,
}

/// platanh.f90: WSJT-X's piecewise-linear atanh, used inside BP. Not
/// replaced by `atanh`: the clamp at 7.0 and the segments change which
/// borderline frames converge.
#[inline]
pub fn platanh(x: f32) -> f32 {
    let (isign, z) = if x < 0.0 { (-1.0f32, x.abs()) } else { (1.0f32, x) };
    if z <= 0.664 {
        x / 0.83
    } else if z <= 0.9217 {
        isign * (z - 0.4064) / 0.322
    } else if z <= 0.9951 {
        isign * (z - 0.8378) / 0.0524
    } else if z <= 0.9998 {
        isign * (z - 0.9914) / 0.0012
    } else {
        isign * 7.0
    }
}

/// decode174_91.f90.
///
/// maxosd < 0: BP only. maxosd = 0: BP, then one OSD on the channel LLRs.
/// maxosd > 0: BP, then OSD on up to `maxosd` (max 3) of BP's accumulated
/// soft outputs. `norder` is OSD's depth.
pub fn decode174_91(llr: &[f32; N], maxosd: i32, norder: i32, apmask: &[u8; N]) -> LdpcResult {
    let maxiterations = 30;
    let maxosd = maxosd.min(3);
    let mut zsave: Vec<[f32; N]> = Vec::new();
    let nosd: usize;
    if maxosd == 0 {
        nosd = 1;
        zsave.push(*llr);
    } else if maxosd > 0 {
        nosd = maxosd as usize;
        zsave.resize(nosd, [0.0; N]);
    } else {
        nosd = 0;
    }

    let mut toc = [[0f32; 7]; M];
    let mut tov = [[0f32; 3]; N];
    let mut tanhtoc = [[0f32; 7]; M];
    for j in 0..M {
        for i in 0..NRW[j] as usize {
            toc[j][i] = llr[NM[j][i] as usize - 1];
        }
    }

    let mut ncnt = 0;
    let mut nclast = 0;
    let mut zsum = [0f32; N];
    let mut zn = [0f32; N];
    let mut cw = [0u8; N];

    for iter in 0..=maxiterations {
        for i in 0..N {
            zn[i] = if apmask[i] != 1 {
                llr[i] + tov[i][0] + tov[i][1] + tov[i][2]
            } else {
                llr[i]
            };
        }
        for i in 0..N {
            zsum[i] += zn[i];
        }
        if iter > 0 && (iter as i32) <= maxosd {
            zsave[iter - 1] = zsum;
        }
        for i in 0..N {
            cw[i] = (zn[i] > 0.0) as u8;
        }
        let mut ncheck = 0;
        for i in 0..M {
            let mut s = 0;
            for t in 0..NRW[i] as usize {
                s += cw[NM[i][t] as usize - 1] as u32;
            }
            if s % 2 != 0 {
                ncheck += 1;
            }
        }
        if ncheck == 0 && crc_ok(&cw[..K]) {
            let nharderror = (0..N).filter(|&i| (2.0 * cw[i] as f32 - 1.0) * llr[i] < 0.0).count() as i32;
            let mut message91 = [0u8; K];
            message91.copy_from_slice(&cw[..K]);
            let dmin = dmin_against(llr, &cw);
            return LdpcResult {
                message91,
                cw,
                ntype: 1,
                nharderror,
                dmin,
            };
        }

        if iter > 0 {
            let nd = ncheck - nclast;
            if nd < 0 {
                ncnt = 0;
            } else {
                ncnt += 1;
            }
            if ncnt >= 5 && iter >= 10 && ncheck > 15 {
                // Not converging: stop BP (WSJT-X's early-stopping rule);
                // OSD below still gets its turn.
                break;
            }
        }
        nclast = ncheck;

        // Bits -> checks.
        for j in 0..M {
            for i in 0..NRW[j] as usize {
                let ibj = NM[j][i] as usize - 1;
                let mut v = zn[ibj];
                for kk in 0..3 {
                    if MN[ibj][kk] as usize == j + 1 {
                        v -= tov[ibj][kk];
                    }
                }
                toc[j][i] = v;
            }
        }
        // Checks -> bits.
        for i in 0..M {
            for t in 0..7 {
                tanhtoc[i][t] = (-toc[i][t] / 2.0).tanh();
            }
        }
        for j in 0..N {
            for i in 0..3 {
                let ichk = MN[j][i] as usize - 1;
                let mut tmn = 1.0f32;
                for t in 0..NRW[ichk] as usize {
                    if NM[ichk][t] as usize != j + 1 {
                        tmn *= tanhtoc[ichk][t];
                    }
                }
                tov[j][i] = 2.0 * platanh(-tmn);
            }
        }
    }

    for i in 0..nosd {
        let r = osd174_91(&zsave[i], apmask, norder);
        if r.nhardmin > 0 {
            let dmin = dmin_against(llr, &r.cw);
            let mut message91 = [0u8; K];
            message91.copy_from_slice(&r.cw[..K]);
            return LdpcResult {
                message91,
                cw: r.cw,
                ntype: 2,
                nharderror: r.nhardmin,
                dmin,
            };
        }
    }
    LdpcResult {
        message91: [0; K],
        cw,
        ntype: 0,
        nharderror: -1,
        dmin: 0.0,
    }
}

fn dmin_against(llr: &[f32; N], cw: &[u8; N]) -> f32 {
    let mut d = 0.0f32;
    for i in 0..N {
        let hdec = (llr[i] >= 0.0) as u8;
        if hdec != cw[i] {
            d += llr[i].abs();
        }
    }
    d
}

pub struct OsdResult {
    pub cw: [u8; N],
    /// Hard errors of the chosen codeword; negated when its CRC fails.
    pub nhardmin: i32,
    pub dmin: f32,
}

/// encode174_91_nocrc.f90: 91 message bits (CRC included) to the codeword,
/// with the crate's generator rows (bit 90 of a row is message bit 0).
fn encode174_91_nocrc(m91: &[u8; K]) -> [u8; N] {
    let m = m91.iter().fold(0u128, |acc, &b| (acc << 1) | (b & 1) as u128);
    let mut cw = [0u8; N];
    cw[..K].copy_from_slice(m91);
    for (i, row) in GENERATOR.iter().enumerate() {
        cw[K + i] = ((row & m).count_ones() & 1) as u8;
    }
    let _ = M;
    cw
}

/// osd174_91's generator: with Keff = 91 (the only value WSJT-X's FT8 and
/// FT4 pass) row i is simply the codeword of the unit message e_i - the
/// Fortran computes CRC bits for the first 77 rows and then zeroes
/// message91(78:k), which for k = 91 is all of them.
fn osd_gen() -> &'static Vec<[u8; N]> {
    static G: OnceLock<Vec<[u8; N]>> = OnceLock::new();
    G.get_or_init(|| {
        (0..K)
            .map(|i| {
                let mut m = [0u8; K];
                m[i] = 1;
                encode174_91_nocrc(&m)
            })
            .collect()
    })
}

/// osd174_91.f90 for Keff = 91 and ndeep <= 2 (see the module note).
pub fn osd174_91(llr: &[f32; N], apmask: &[u8; N], ndeep: i32) -> OsdResult {
    let k = K;
    let gen = osd_gen();
    let mut hdec = [0u8; N];
    for i in 0..N {
        hdec[i] = (llr[i] >= 0.0) as u8;
    }
    let absrx0: Vec<f32> = llr.iter().map(|x| x.abs()).collect();
    let indx = super::util::indexx(&absrx0);

    // Columns in order of decreasing reliability. genmrb[row][col], k rows.
    let mut genmrb = vec![[0u8; N]; k];
    let mut indices = [0usize; N];
    for i in 0..N {
        let src = indx[N - 1 - i];
        for r in 0..k {
            genmrb[r][i] = gen[r][src];
        }
        indices[i] = src;
    }

    // Gaussian elimination, searching for a pivot only up to k+20 columns
    // ("The 20 is ad hoc - beware", says the original).
    for id in 0..k {
        let lim = (k + 20).min(N);
        for icol in id..lim {
            if genmrb[id][icol] == 1 {
                if icol != id {
                    for r in 0..k {
                        genmrb[r].swap(id, icol);
                    }
                    indices.swap(id, icol);
                }
                let pivot = genmrb[id];
                for ii in 0..k {
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

    // g2 = transpose: g2[col i] is the codeword contribution of MRB bit i,
    // i.e. row i of genmrb. Kept as rows for mrbencode.
    let g2 = &genmrb;

    let hdec_p: Vec<u8> = indices.iter().map(|&i| hdec[i]).collect();
    let absrx: Vec<f32> = indices.iter().map(|&i| absrx0[i]).collect();
    let apmaskr: Vec<u8> = indices.iter().map(|&i| apmask[i]).collect();
    let m0: Vec<u8> = hdec_p[..k].to_vec();

    let mrbencode = |me: &[u8]| -> [u8; N] {
        let mut cw = [0u8; N];
        for i in 0..k {
            if me[i] == 1 {
                for c in 0..N {
                    cw[c] ^= g2[i][c];
                }
            }
        }
        cw
    };

    let c0 = mrbencode(&m0);
    let mut nhardmin: i32 = 0;
    let mut dmin = 0.0f32;
    for i in 0..N {
        if c0[i] != hdec_p[i] {
            nhardmin += 1;
            dmin += absrx[i];
        }
    }
    let mut cw = c0;

    if ndeep > 0 {
        let ndeep = ndeep.min(6);
        // (nord, npre1, nt, ntheta) per depth, from osd174_91.f90. npre2 is
        // not ported (only depths >= 3 use it).
        let (nord, npre1, nt, ntheta) = match ndeep {
            1 => (1, 0, 40, 12),
            2 => (1, 1, 40, 10),
            3 => (1, 1, 40, 12),
            4 => (2, 1, 40, 12),
            5 => (3, 1, 40, 12),
            _ => (4, 1, 95, 12),
        };
        let mut misub = vec![0u8; k];
        let mut mi = vec![0u8; k];
        let mut me = vec![0u8; k];
        let mut e2sub = vec![0u8; N - k];
        let mut e2 = vec![0u8; N - k];
        for iorder in 1..=nord {
            for v in misub.iter_mut() {
                *v = 0;
            }
            for v in misub[k - iorder..].iter_mut() {
                *v = 1;
            }
            // 1-based iflag as in the Fortran.
            let mut iflag: isize = (k - iorder + 1) as isize;
            while iflag >= 0 {
                let iend: isize = if iorder == nord && npre1 == 0 { iflag } else { 1 };
                let mut d1 = 0.0f32;
                let mut n1 = iflag;
                while n1 >= iend {
                    mi.copy_from_slice(&misub);
                    mi[n1 as usize - 1] = 1;
                    let blocked = (0..k).any(|t| apmaskr[t] & mi[t] == 1);
                    if !blocked {
                        for t in 0..k {
                            me[t] = m0[t] ^ mi[t];
                        }
                        let nd1kpt;
                        if n1 == iflag {
                            let ce = mrbencode(&me);
                            for t in 0..N - k {
                                e2sub[t] = ce[k + t] ^ hdec_p[k + t];
                                e2[t] = e2sub[t];
                            }
                            nd1kpt = e2sub[..nt].iter().map(|&b| b as i32).sum::<i32>() + 1;
                            d1 = 0.0;
                            for t in 0..k {
                                if me[t] != hdec_p[t] {
                                    d1 += absrx[t];
                                }
                            }
                        } else {
                            let col = n1 as usize - 1;
                            for t in 0..N - k {
                                e2[t] = e2sub[t] ^ g2[col][k + t];
                            }
                            nd1kpt = e2[..nt].iter().map(|&b| b as i32).sum::<i32>() + 2;
                        }
                        if nd1kpt <= ntheta {
                            let ce = mrbencode(&me);
                            let dd = if n1 == iflag {
                                let mut s = d1;
                                for t in 0..N - k {
                                    s += e2sub[t] as f32 * absrx[k + t];
                                }
                                s
                            } else {
                                let col = n1 as usize - 1;
                                let mut s = d1 + (ce[col] ^ hdec_p[col]) as f32 * absrx[col];
                                for t in 0..N - k {
                                    s += e2[t] as f32 * absrx[k + t];
                                }
                                s
                            };
                            if dd < dmin {
                                dmin = dd;
                                cw = ce;
                                nhardmin = (0..N).filter(|&t| ce[t] != hdec_p[t]).count() as i32;
                            }
                        }
                    }
                    n1 -= 1;
                }
                iflag = nextpat91(&mut misub, k, iorder);
            }
        }
    }

    // Back to [message][parity] order.
    let mut out = [0u8; N];
    for i in 0..N {
        out[indices[i]] = cw[i];
    }
    if !crc_ok(&out[..K]) {
        nhardmin = -nhardmin;
    }
    OsdResult {
        cw: out,
        nhardmin,
        dmin,
    }
}

/// nextpat91: the next test-error pattern of the same weight; returns the
/// new 1-based `iflag` (lowest set position), or -1 when exhausted.
fn nextpat91(mi: &mut [u8], k: usize, iorder: usize) -> isize {
    let mut ind: isize = -1;
    for i in 0..k - 1 {
        if mi[i] == 0 && mi[i + 1] == 1 {
            ind = i as isize + 1; // 1-based
        }
    }
    if ind < 0 {
        return -1;
    }
    let ind = ind as usize;
    let mut ms = vec![0u8; k];
    ms[..ind - 1].copy_from_slice(&mi[..ind - 1]);
    ms[ind - 1] = 1;
    ms[ind] = 0;
    if ind + 1 < k {
        let nz = iorder as isize - ms.iter().map(|&b| b as isize).sum::<isize>();
        if nz > 0 {
            for v in ms[k - nz as usize..].iter_mut() {
                *v = 1;
            }
        }
    }
    mi.copy_from_slice(&ms);
    for i in 0..k {
        if mi[i] == 1 {
            return i as isize + 1;
        }
    }
    -1
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::decode::sim::hex_to_bits77;
    use crate::ldpc::ldpc174_91::encode as encode174_91;

    fn llr_from_cw(cw: &[u8; N], flip: &[usize], mag: f32) -> [f32; N] {
        let mut l = [0f32; N];
        for i in 0..N {
            l[i] = if cw[i] == 1 { mag } else { -mag };
        }
        for &f in flip {
            l[f] = -l[f] * 0.3;
        }
        l
    }

    #[test]
    fn bp_corrects_a_few_errors() {
        let m = hex_to_bits77("000000204def1a8a1988").unwrap();
        let cw = encode174_91(&m);
        let llr = llr_from_cw(&cw, &[3, 50, 120, 170], 4.0);
        let r = decode174_91(&llr, -1, 2, &[0; N]);
        assert_eq!(r.ntype, 1);
        assert_eq!(&r.message91[..77], &m[..]);
    }

    #[test]
    fn osd_rescues_what_bp_cannot() {
        let m = hex_to_bits77("000000204def1a8a1988").unwrap();
        let cw = encode174_91(&m);
        // Many confidently wrong bits among the least reliable: BP gives up,
        // OSD (which flips patterns over the most reliable basis) does not.
        let mut llr = [0f32; N];
        for i in 0..N {
            let s = if cw[i] == 1 { 1.0 } else { -1.0 };
            llr[i] = s * (0.5 + (i % 13) as f32 * 0.4);
        }
        for i in (0..N).step_by(9) {
            llr[i] = -llr[i] * 0.2;
        }
        let r = decode174_91(&llr, 2, 2, &[0; N]);
        assert!(r.nharderror >= 0, "no decode");
        assert_eq!(&r.message91[..77], &m[..]);
    }
}
