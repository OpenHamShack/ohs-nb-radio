// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0: lib/chkcall.f90 and lib/77bit/packjt77.f90
// (pack28, unpack28), copyright (C) 2001-2023 Joe Taylor K1JT, Steve
// Franke K9AN, Bill Somerville G4WJS and the WSJT Development Group,
// GPL-3.0-or-later.

//! 28-bit callsign fields: standard calls, the CQ/QRZ/DE tokens, and
//! 22-bit hashes of everything else.

use super::hash::{ihashcall, CallHashes};
use crate::fortran::{
    adjustl, adjustr, fixed, index, index1, is_digit, is_letter, len_trim, list_read_int, sub, ListRead,
};

/// Values below this are special tokens (DE, QRZ, CQ, CQ nnn, CQ abcd).
pub const NTOKENS: i64 = 2_063_592;
/// 2^22: the hashed calls come next.
pub const MAX22: i64 = 4_194_304;

/// chkcall: could `w` (a word of up to 13 characters) be a standard or
/// compound callsign? Returns the base call (6 characters) and the verdict.
/// The base call of "PJ4/K1ABC" is "K1ABC", of "K1ABC/P" also "K1ABC".
pub fn chkcall(w: &[u8]) -> (Vec<u8>, bool) {
    let w = fixed(w, 13);
    let mut bc = fixed(&w[..6], 6);
    let fail = |bc: Vec<u8>| (bc, false);
    let n1 = len_trim(&w);
    if n1 > 11 {
        return fail(bc);
    }
    for c in *b".+-?" {
        if index1(&w, c) >= 1 {
            return fail(bc);
        }
    }
    let i0 = index1(&w, b'/') as isize;
    let n1 = n1 as isize;
    if n1 > 6 && i0 <= 0 {
        return fail(bc);
    }
    if (i0 - 1).max(n1 - i0) > 6 {
        return fail(bc);
    }
    if i0 >= 2 && i0 < n1 {
        if i0 - 1 <= n1 - i0 {
            bc = fixed(sub(&w, (i0 + 1) as usize, n1), 6);
        } else {
            bc = fixed(sub(&w, 1, i0 - 1), 6);
        }
    }
    let nbc = len_trim(&bc);
    if nbc > 6 {
        return fail(bc);
    }
    if !is_letter(bc[0]) && !is_letter(bc[1]) {
        return fail(bc);
    }
    // Real calls do not start with Q; QU1RK is WSJT-X's own placeholder.
    if bc[0] == b'Q' && &bc[..5] != b"QU1RK" {
        return fail(bc);
    }
    let mut i1 = 0;
    if is_digit(bc[1]) {
        i1 = 2;
    }
    if is_digit(bc[2]) {
        i1 = 3;
    }
    if i1 == 0 || i1 == nbc {
        return fail(bc);
    }
    let mut n = 0;
    for i in i1 + 1..=nbc {
        let j = bc[i - 1];
        if !j.is_ascii_uppercase() {
            return fail(bc);
        }
        n += 1;
    }
    if (1..=3).contains(&n) {
        (bc, true)
    } else {
        fail(bc)
    }
}

const A1: &[u8] = b" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const A2: &[u8] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
const A3: &[u8] = b"0123456789";
const A4: &[u8] = b" ABCDEFGHIJKLMNOPQRSTUVWXYZ";

fn idx0(alpha: &[u8], c: u8) -> i64 {
    alpha.iter().position(|&x| x == c).map_or(-1, |p| p as i64)
}

/// pack28: a token, a standard call, or the 22-bit hash of anything else,
/// as a 28-bit integer. `c13` is changed as WSJT-X changes it (a "<call>"
/// loses its brackets), and every call packed is remembered in `h`.
///
/// Err(PackError::Crash) where WSJT-X itself stops with a run-time error:
/// "CQ 1.23 K1ABC" makes it READ an integer from "1.2" with no err=.
pub fn pack28(c13: &mut Vec<u8>, h: &mut CallHashes) -> Result<i64, PackError> {
    *c13 = fixed(c13, 13);
    let n28 = pack28_inner(c13, h)?;
    Ok(n28 & ((1i64 << 28) - 1))
}

/// Why a message has no single WSJT-X 2.7.0 result to reproduce.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PackError {
    /// WSJT-X stops with a Fortran run-time error on it.
    Crash,
    /// WSJT-X's result depends on a variable it never set, so it is
    /// whatever was left in memory: ft8code and ft4code give different
    /// answers for the same message, and some are garbage ("<...>
    /// ZZZZZZZZZ/"). The text says which variable.
    Undefined(&'static str),
}

fn pack28_inner(c13: &mut Vec<u8>, h: &mut CallHashes) -> Result<i64, PackError> {
    // (packjt77.f90's Swaziland and Guinea prefix work-arounds assign a
    // variable that is overwritten before it is read, so they change
    // nothing and are not ported.)
    if &c13[..3] == b"DE " {
        return Ok(0);
    }
    if &c13[..4] == b"QRZ " {
        return Ok(1);
    }
    if &c13[..3] == b"CQ " {
        return Ok(2);
    }
    if &c13[..3] == b"CQ_" {
        let n = len_trim(c13);
        if (4..=7).contains(&n) {
            let (mut nlet, mut nnum) = (0, 0);
            for i in 4..=n {
                let c = c13[i - 1];
                if c.is_ascii_uppercase() {
                    nlet += 1;
                }
                if c.is_ascii_digit() {
                    nnum += 1;
                }
            }
            if nnum == 3 && nlet == 0 {
                // read(c13(4:3+nnum),*) nqsy, with no err=: "1/2" reads
                // as 1, but "1.2" stops WSJT-X with a run-time error.
                match list_read_int(sub(c13, 4, 3 + nnum)) {
                    ListRead::Value(nqsy) => return Ok(3 + nqsy),
                    ListRead::Error => return Err(PackError::Crash),
                    ListRead::Null => return Err(PackError::Undefined("pack28's nqsy (a CQ number read as null)")),
                }
            }
            if (1..=4).contains(&nlet) && nnum == 0 {
                let c4 = adjustr(&fixed(sub(c13, 4, n as isize), 4));
                let mut m: i64 = 0;
                for &c in &c4 {
                    let j = if c.is_ascii_uppercase() {
                        (c - b'A' + 1) as i64
                    } else {
                        0
                    };
                    m = 27 * m + j;
                }
                return Ok(3 + 1000 + m);
            }
        }
    }
    if c13[0] == b'<' {
        h.save(c13);
        let i2 = index1(c13, b'>');
        *c13 = fixed(sub(c13, 2, i2 as isize - 1), 13);
        let n22 = ihashcall(c13, 22);
        return Ok(NTOKENS + n22);
    }
    // A standard call: one or two characters before the call-area digit
    // (at least one a letter), the digit second or third, then at most
    // three letters.
    let n = len_trim(c13);
    let mut i = n;
    let mut found = false;
    while i >= 2 {
        if is_digit(c13[i - 1]) {
            found = true;
            break;
        }
        i -= 1;
    }
    // A Fortran DO loop that runs to completion leaves its variable one
    // step past the end (1 here); one that never starts leaves it at n.
    let iarea = if found {
        i
    } else if n >= 2 {
        1
    } else {
        n
    };
    let (mut npdig, mut nplet) = (0, 0);
    for i in 1..iarea {
        if is_digit(c13[i - 1]) {
            npdig += 1;
        }
        if is_letter(c13[i - 1]) {
            nplet += 1;
        }
    }
    let mut nslet = 0;
    for i in iarea + 1..=n {
        if is_letter(c13[i - 1]) {
            nslet += 1;
        }
    }
    if !(2..=3).contains(&iarea) || nplet == 0 || npdig + 1 >= iarea || nslet > 3 {
        h.save(c13);
        let n22 = ihashcall(c13, 22);
        return Ok(NTOKENS + n22);
    }
    h.save(c13);
    let callsign: Vec<u8> = if iarea == 2 {
        let mut v = vec![b' '];
        v.extend_from_slice(&c13[..5]);
        v
    } else {
        c13[..6].to_vec()
    };
    let i1 = idx0(A1, callsign[0]);
    let i2 = idx0(A2, callsign[1]);
    let i3 = idx0(A3, callsign[2]);
    let i4 = idx0(A4, callsign[3]);
    let i5 = idx0(A4, callsign[4]);
    let i6 = idx0(A4, callsign[5]);
    let n28 = 36 * 10 * 27 * 27 * 27 * i1 + 10 * 27 * 27 * 27 * i2 + 27 * 27 * 27 * i3 + 27 * 27 * i4 + 27 * i5 + i6;
    // 32-bit arithmetic in WSJT-X; the masked result is the same.
    Ok(n28 + NTOKENS + MAX22)
}

/// unpack28: the text of a 28-bit field and whether it is a valid one.
pub fn unpack28(n28_0: i64, h: &CallHashes) -> (Vec<u8>, bool) {
    let c1: &[u8] = b" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let c2: &[u8] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let c3: &[u8] = b"0123456789";
    let c4: &[u8] = b" ABCDEFGHIJKLMNOPQRSTUVWXYZ";
    let mut n28 = n28_0;
    let c13: Vec<u8> = 'done: {
        if n28 < NTOKENS {
            if n28 == 0 {
                break 'done fixed(b"DE", 13);
            }
            if n28 == 1 {
                break 'done fixed(b"QRZ", 13);
            }
            if n28 == 2 {
                break 'done fixed(b"CQ", 13);
            }
            if n28 <= 1002 {
                let mut v = b"CQ_".to_vec();
                v.extend_from_slice(&crate::fortran::fmt_i(n28 - 3, 3, 3));
                break 'done fixed(&v, 13);
            }
            if n28 <= 532_443 {
                let mut n = n28 - 1003;
                let i1 = n / (27 * 27 * 27);
                n -= 27 * 27 * 27 * i1;
                let i2 = n / (27 * 27);
                n -= 27 * 27 * i2;
                let i3 = n / 27;
                let i4 = n - 27 * i3;
                let s = [c4[i1 as usize], c4[i2 as usize], c4[i3 as usize], c4[i4 as usize]];
                let s = adjustl(&fixed(&s, 13));
                let mut v = b"CQ_".to_vec();
                v.extend_from_slice(&s[..10]);
                break 'done fixed(&v, 13);
            }
        }
        n28 -= NTOKENS;
        if n28 < MAX22 {
            break 'done h.lookup22(n28);
        }
        let mut n = n28 - MAX22;
        let i1 = n / (36 * 10 * 27 * 27 * 27);
        n -= 36 * 10 * 27 * 27 * 27 * i1;
        let i2 = n / (10 * 27 * 27 * 27);
        n -= 10 * 27 * 27 * 27 * i2;
        let i3 = n / (27 * 27 * 27);
        n -= 27 * 27 * 27 * i3;
        let i4 = n / (27 * 27);
        n -= 27 * 27 * i4;
        let i5 = n / 27;
        let i6 = n - 27 * i5;
        let s = [
            c1[i1 as usize],
            c2[i2 as usize],
            c3[i3 as usize],
            c4[i4 as usize],
            c4[i5 as usize],
            c4[i6 as usize],
        ];
        adjustl(&fixed(&s, 13))
    };
    // A blank inside the call (not just after it) means these bits were
    // never a callsign: WSJT-X says QU1RK and fails the unpack.
    let i0 = index(&c13, b" ");
    if i0 != 0 && i0 < len_trim(&c13) {
        return (fixed(b"QU1RK", 13), false);
    }
    (c13, true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn chkcall_examples() {
        assert_eq!(chkcall(b"K1ABC"), (b"K1ABC ".to_vec(), true));
        assert_eq!(chkcall(b"PJ4/K1ABC"), (b"K1ABC ".to_vec(), true));
        assert_eq!(chkcall(b"G4ABC/P"), (b"G4ABC ".to_vec(), true));
        assert!(!chkcall(b"FN42").1);
        assert!(!chkcall(b"QA1ABC").1);
        assert!(chkcall(b"QU1RK").1);
    }

    #[test]
    fn standard_call_round_trip() {
        let mut h = CallHashes::new();
        for call in ["K1ABC", "G4XYZ", "W9XYZ", "3DA0XYZ", "VK2RG", "2E0ABC"] {
            let mut c = call.as_bytes().to_vec();
            let n = pack28(&mut c, &mut h).unwrap();
            let (u, ok) = unpack28(n, &h);
            assert!(ok, "{call}");
            let u = String::from_utf8(u).unwrap();
            let shown = u.trim_end().trim_start_matches('<').trim_end_matches('>');
            assert_eq!(shown, call);
        }
    }

    #[test]
    fn tokens() {
        let h = CallHashes::new();
        let mut h2 = CallHashes::new();
        let mut c = b"CQ_DX".to_vec();
        let n = pack28(&mut c, &mut h2).unwrap();
        assert_eq!(&unpack28(n, &h).0[..5], b"CQ_DX");
        let mut c = b"CQ_123".to_vec();
        let n = pack28(&mut c, &mut h2).unwrap();
        assert_eq!(n, 126);
        assert_eq!(&unpack28(n, &h).0[..6], b"CQ_123");
    }
}
