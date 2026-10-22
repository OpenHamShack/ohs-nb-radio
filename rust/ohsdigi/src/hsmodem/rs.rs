// ohsdigi - HSmodem's Reed-Solomon (255,223) code.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! The code HSmodem takes from Schifra's example (hsmodem/fec.cpp): GF(2^8)
//! from Schifra's primitive_polynomial06 {1,1,1,0,0,0,0,1,1}, which Schifra
//! reads lowest power first - x^8 + x^7 + x^2 + x + 1 (0x187, the CCSDS
//! field polynomial) - primitive element 2 (alpha = x), and a generator
//! with the 32 consecutive roots alpha^120 .. alpha^151. Systematic: the
//! 223 data bytes come first, highest power first, then the 32 parity
//! bytes. EA4GPZ read the same parameters from the source (docs/
//! hsmodem-research.md).
//!
//! Written here from the textbook algorithms (polynomial division to
//! encode; syndromes, Berlekamp-Massey, Chien search and Forney to
//! decode), not translated from Schifra, whose licence is its own; it is
//! held bit for bit against Schifra itself by the harness (HSmodem's
//! frames carry Schifra's parity) and against Schifra's decoder on
//! random error patterns (tests/hsmodem_harness data, harness `hsh rs`).
//! Errors only, no erasures: HSmodem's receiver makes hard decisions.

pub const N: usize = 255;
pub const K: usize = 223;
pub const NROOTS: usize = 32;
pub const FCR: usize = 120;
const POLY: u16 = 0x187;

struct Gf {
    exp: [u8; 512],
    log: [u8; 256],
}

const fn build() -> Gf {
    let mut exp = [0u8; 512];
    let mut log = [0u8; 256];
    let mut x: u16 = 1;
    let mut i = 0;
    while i < 255 {
        exp[i] = x as u8;
        log[x as usize] = i as u8;
        x <<= 1;
        if x & 0x100 != 0 {
            x ^= POLY;
        }
        i += 1;
    }
    while i < 512 {
        exp[i] = exp[i - 255];
        i += 1;
    }
    Gf { exp, log }
}

static GF: Gf = build();

#[inline]
fn mul(a: u8, b: u8) -> u8 {
    if a == 0 || b == 0 {
        0
    } else {
        GF.exp[GF.log[a as usize] as usize + GF.log[b as usize] as usize]
    }
}

#[inline]
fn alpha_pow(e: usize) -> u8 {
    GF.exp[e % 255]
}

#[inline]
fn inv(a: u8) -> u8 {
    GF.exp[255 - GF.log[a as usize] as usize]
}

/// g(x) = prod (x + alpha^(FCR+i)), coefficients highest power first
/// (g[0] = 1).
fn generator() -> [u8; NROOTS + 1] {
    let mut g = [0u8; NROOTS + 1];
    g[0] = 1;
    for (deg, i) in (0..NROOTS).enumerate() {
        let root = alpha_pow(FCR + i);
        // multiply by (x + root)
        let mut next = [0u8; NROOTS + 1];
        for j in 0..=deg {
            next[j] ^= g[j];
            next[j + 1] ^= mul(g[j], root);
        }
        g = next;
    }
    g
}

/// Systematic encoding: data (223 bytes) then the remainder of
/// data(x) x^32 / g(x).
pub fn encode(data: &[u8; K]) -> [u8; N] {
    let g = generator();
    let mut rem = [0u8; NROOTS];
    for &d in data {
        let fb = d ^ rem[0];
        rem.copy_within(1.., 0);
        rem[NROOTS - 1] = 0;
        if fb != 0 {
            for j in 0..NROOTS {
                rem[j] ^= mul(fb, g[j + 1]);
            }
        }
    }
    let mut out = [0u8; N];
    out[..K].copy_from_slice(data);
    out[K..].copy_from_slice(&rem);
    out
}

/// Decode a received codeword. Returns the 223 data bytes and how many
/// symbols were corrected, or None if the decoder cannot (more than 16
/// errors, as far as it can tell).
pub fn decode(cw: &[u8; N]) -> Option<([u8; K], usize)> {
    // Syndromes S_j = r(alpha^(FCR+j)), Horner, highest power first.
    let mut s = [0u8; NROOTS];
    let mut any = false;
    for (j, sj) in s.iter_mut().enumerate() {
        let a = alpha_pow(FCR + j);
        let mut acc = 0u8;
        for &c in cw.iter() {
            acc = mul(acc, a) ^ c;
        }
        *sj = acc;
        any |= acc != 0;
    }
    let mut data = [0u8; K];
    data.copy_from_slice(&cw[..K]);
    if !any {
        return Some((data, 0));
    }
    // Berlekamp-Massey: the error locator Lambda(x), lowest power first.
    let mut lambda = [0u8; NROOTS + 1];
    let mut b = [0u8; NROOTS + 1];
    lambda[0] = 1;
    b[0] = 1;
    let mut l = 0usize;
    let mut m = 1usize;
    let mut bb = 1u8;
    for n in 0..NROOTS {
        let mut d = s[n];
        for i in 1..=l {
            d ^= mul(lambda[i], s[n - i]);
        }
        if d == 0 {
            m += 1;
        } else if 2 * l <= n {
            let t = lambda;
            let coef = mul(d, inv(bb));
            for i in 0..=NROOTS - m {
                lambda[i + m] ^= mul(coef, b[i]);
            }
            l = n + 1 - l;
            b = t;
            bb = d;
            m = 1;
        } else {
            let coef = mul(d, inv(bb));
            for i in 0..=NROOTS - m {
                lambda[i + m] ^= mul(coef, b[i]);
            }
            m += 1;
        }
    }
    let deg = (0..=NROOTS).rev().find(|&i| lambda[i] != 0).unwrap_or(0);
    if deg != l || l > NROOTS / 2 {
        return None;
    }
    // Chien search: Lambda(alpha^-p) = 0 marks an error at power p, i.e.
    // codeword index N-1-p.
    let mut locs = Vec::with_capacity(l);
    for p in 0..N {
        let xinv = alpha_pow(255 - p % 255);
        let mut v = 0u8;
        let mut xp = 1u8;
        for &c in lambda.iter().take(l + 1) {
            v ^= mul(c, xp);
            xp = mul(xp, xinv);
        }
        if v == 0 {
            locs.push(p);
        }
    }
    if locs.len() != l {
        return None;
    }
    // Omega(x) = S(x) Lambda(x) mod x^32.
    let mut omega = [0u8; NROOTS];
    for i in 0..NROOTS {
        let mut v = 0u8;
        for j in 0..=i.min(l) {
            v ^= mul(lambda[j], s[i - j]);
        }
        omega[i] = v;
    }
    // Forney: e = X^(1-FCR) Omega(X^-1) / Lambda'(X^-1).
    let mut full = *cw;
    for &p in &locs {
        let x = alpha_pow(p);
        let xinv = inv(x);
        let mut om = 0u8;
        let mut xp = 1u8;
        for &c in omega.iter() {
            om ^= mul(c, xp);
            xp = mul(xp, xinv);
        }
        // Lambda'(x): odd terms only in characteristic 2.
        let mut dl = 0u8;
        let mut i = 1;
        while i <= l {
            dl ^= mul(lambda[i], alpha_pow((255 - p % 255) * (i - 1)));
            i += 2;
        }
        if dl == 0 {
            return None;
        }
        // X^(1-FCR) = alpha^(p (1 - FCR)) = alpha^(p (256 - FCR)) mod 255.
        let xf = alpha_pow((p * (256 - FCR)) % 255);
        let e = mul(mul(om, xf), inv(dl));
        full[N - 1 - p] ^= e;
    }
    // A decoder that thinks it corrected must leave a codeword behind.
    for j in 0..NROOTS {
        let a = alpha_pow(FCR + j);
        let mut acc = 0u8;
        for &c in full.iter() {
            acc = mul(acc, a) ^ c;
        }
        if acc != 0 {
            return None;
        }
    }
    data.copy_from_slice(&full[..K]);
    Some((data, l))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn lcg(seed: &mut u64) -> u64 {
        *seed = seed.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        *seed >> 33
    }

    #[test]
    fn corrects_up_to_sixteen() {
        let mut seed = 7u64;
        for trial in 0..200 {
            let mut d = [0u8; K];
            d.iter_mut().for_each(|b| *b = lcg(&mut seed) as u8);
            let cw = encode(&d);
            let mut r = cw;
            let ne = trial % 17;
            let mut used = vec![];
            while used.len() < ne {
                let p = (lcg(&mut seed) % 255) as usize;
                if !used.contains(&p) {
                    used.push(p);
                    r[p] ^= 1 + (lcg(&mut seed) % 255) as u8;
                }
            }
            let (got, n) = decode(&r).expect("decodes");
            assert_eq!(got, d);
            assert_eq!(n, ne);
        }
    }
}
