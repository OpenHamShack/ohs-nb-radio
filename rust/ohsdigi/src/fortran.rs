// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! The few Fortran semantics WSJT-X's message packing leans on.
//!
//! pack77/unpack77 are defined by what WSJT-X's Fortran does, edge cases
//! included, and a great deal of that behaviour comes from the language
//! rather than from the algorithm: CHARACTER*13 words that truncate and
//! blank-pad on assignment, comparisons that ignore trailing blanks,
//! list-directed READs that accept "+5," and "-12/" but not "+5;", and
//! B edit descriptors that print asterisks when a value does not fit its
//! field (which WSJT-X then reports as "*** bad message ***"). Rather than
//! re-derive each of those at every use, they are written once here, as
//! byte-slice functions with the Fortran names, so the port in msg77 can
//! be read against packjt77.f90 line for line where it has to be, and the
//! corpus test (tests/corpus.rs) is what keeps the two in step.
//!
//! Strings are bytes, as they are to gfortran: a non-ASCII character in a
//! message is several bytes, none of them a letter or digit.

/// A CHARACTER*n value: `s` truncated or blank-padded to `n` bytes.
pub(crate) fn fixed(s: &[u8], n: usize) -> Vec<u8> {
    let mut v: Vec<u8> = s.iter().copied().take(n).collect();
    v.resize(n, b' ');
    v
}

/// LEN_TRIM: length without trailing blanks.
pub(crate) fn len_trim(s: &[u8]) -> usize {
    s.iter().rposition(|&c| c != b' ').map_or(0, |p| p + 1)
}

/// TRIM.
pub(crate) fn trim(s: &[u8]) -> &[u8] {
    &s[..len_trim(s)]
}

/// INDEX(s, pat): 1-based position of the first occurrence, 0 if none.
pub(crate) fn index(s: &[u8], pat: &[u8]) -> usize {
    if pat.is_empty() {
        return 1;
    }
    if pat.len() > s.len() {
        return 0;
    }
    s.windows(pat.len()).position(|w| w == pat).map_or(0, |p| p + 1)
}

/// INDEX(s, c) for a single character.
pub(crate) fn index1(s: &[u8], c: u8) -> usize {
    s.iter().position(|&x| x == c).map_or(0, |p| p + 1)
}

/// The substring s(a:b), 1-based and inclusive; empty when b < a, as in
/// Fortran. Out-of-range ends are clamped (Fortran leaves them undefined;
/// none of the call sites ported here reach that case).
pub(crate) fn sub(s: &[u8], a: usize, b: isize) -> &[u8] {
    if b < a as isize || a == 0 {
        return &[];
    }
    let b = (b as usize).min(s.len());
    if a > b {
        return &[];
    }
    &s[a - 1..b]
}

/// The single character s(i:i), 1-based; a blank past the end.
pub(crate) fn ch(s: &[u8], i: usize) -> u8 {
    if i == 0 {
        return b' ';
    }
    s.get(i - 1).copied().unwrap_or(b' ')
}

/// ADJUSTL: leading blanks moved to the end.
pub(crate) fn adjustl(s: &[u8]) -> Vec<u8> {
    let lead = s.iter().take_while(|&&c| c == b' ').count();
    let mut v = s[lead..].to_vec();
    v.resize(s.len(), b' ');
    v
}

/// ADJUSTR: trailing blanks moved to the front.
pub(crate) fn adjustr(s: &[u8]) -> Vec<u8> {
    let t = trim(s);
    let mut v = vec![b' '; s.len() - t.len()];
    v.extend_from_slice(t);
    v
}

/// a .eq. b for CHARACTER values: the shorter is blank-padded first.
pub(crate) fn feq(a: &[u8], b: &[u8]) -> bool {
    let n = a.len().max(b.len());
    (0..n).all(|i| a.get(i).copied().unwrap_or(b' ') == b.get(i).copied().unwrap_or(b' '))
}

/// Concatenation (//).
pub(crate) fn cat(parts: &[&[u8]]) -> Vec<u8> {
    parts.concat()
}

pub(crate) fn is_digit(c: u8) -> bool {
    c.is_ascii_digit()
}

pub(crate) fn is_letter(c: u8) -> bool {
    c.is_ascii_uppercase()
}

/// What a list-directed integer READ (`read(s,*) n`) does with a field.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(crate) enum ListRead {
    /// A value was read.
    Value(i64),
    /// A null value ("," or "/" first, or "r*" with nothing after the
    /// star): the variable keeps whatever it held.
    Null,
    /// The READ's err= (or end=) branch is taken; the variable keeps
    /// whatever it held.
    Error,
}

/// gfortran's list-directed read of one default (32-bit) INTEGER from the
/// start of `field`. Blanks, a comma or a slash end the value; a
/// semicolon does not (that is a separator only under DECIMAL='COMMA'),
/// so "+5;" is an error, as WSJT-X 2.7.0's ft8code shows. A repeat count
/// "r*v" is honoured. Anything else - a sign alone, a decimal point, a
/// letter, a value outside 32 bits - is an error.
pub(crate) fn list_read_int(field: &[u8]) -> ListRead {
    let s: &[u8] = {
        let lead = field.iter().take_while(|&&c| c == b' ').count();
        &field[lead..]
    };
    if s.is_empty() {
        return ListRead::Error; // end of record: the end= / err= branch
    }
    if s[0] == b',' || s[0] == b'/' {
        return ListRead::Null;
    }
    let end = s
        .iter()
        .position(|&c| c == b' ' || c == b',' || c == b'/')
        .unwrap_or(s.len());
    let mut tok = &s[..end];
    if let Some(star) = tok.iter().position(|&c| c == b'*') {
        let r = &tok[..star];
        if r.is_empty() || !r.iter().all(|c| c.is_ascii_digit()) {
            return ListRead::Error;
        }
        match parse_i32(r) {
            Some(n) if n > 0 => {}
            _ => return ListRead::Error,
        }
        tok = &tok[star + 1..];
        if tok.is_empty() {
            return ListRead::Null;
        }
    }
    match parse_i32(tok) {
        Some(v) => ListRead::Value(v),
        None => ListRead::Error,
    }
}

fn parse_i32(tok: &[u8]) -> Option<i64> {
    let (neg, digits) = match tok.first() {
        Some(b'+') => (false, &tok[1..]),
        Some(b'-') => (true, &tok[1..]),
        _ => (false, tok),
    };
    if digits.is_empty() || !digits.iter().all(|c| c.is_ascii_digit()) {
        return None;
    }
    let mut v: i64 = 0;
    for &d in digits {
        v = v.checked_mul(10)?.checked_add((d - b'0') as i64)?;
        if v > i32::MAX as i64 + 1 {
            return None;
        }
    }
    let v = if neg { -v } else { v };
    if v < i32::MIN as i64 || v > i32::MAX as i64 {
        return None;
    }
    Some(v)
}

/// A 77-character buffer written field by field with Bw.w descriptors,
/// as packjt77.f90's `write(c77,fmt)` statements fill it.
pub(crate) struct C77Writer {
    buf: Vec<u8>,
}

impl C77Writer {
    pub(crate) fn new() -> Self {
        C77Writer {
            buf: Vec::with_capacity(77),
        }
    }

    /// Bw.w: `v` in binary, zero-filled to `w` digits. A value that does
    /// not fit - negative, or 2^w or more - prints as w asterisks, which
    /// is how gfortran answers an overflowing field; WSJT-X then fails
    /// to read the bits back and reports a bad message.
    pub(crate) fn b(&mut self, v: i64, w: usize) -> &mut Self {
        if v < 0 || (w < 63 && v >= (1i64 << w)) {
            self.buf.extend(std::iter::repeat(b'*').take(w));
        } else {
            for i in (0..w).rev() {
                self.buf.push(if (v >> i) & 1 == 1 { b'1' } else { b'0' });
            }
        }
        self
    }

    /// I1 for a single digit.
    pub(crate) fn i1(&mut self, v: i64) -> &mut Self {
        if (0..=9).contains(&v) {
            self.buf.push(b'0' + v as u8);
        } else {
            self.buf.push(b'*');
        }
        self
    }

    pub(crate) fn finish(&self) -> [u8; 77] {
        let mut out = [b'*'; 77];
        for (o, &c) in out.iter_mut().zip(self.buf.iter()) {
            *o = c;
        }
        out
    }
}

/// Read a binary field of `c77` (1-based start, width w) as `read(c77,'(bw)')`
/// would, for a buffer already known to hold only '0' and '1'.
pub(crate) fn read_b(c77: &[u8; 77], start: usize, w: usize) -> i64 {
    let mut v: i64 = 0;
    for i in 0..w {
        v = (v << 1) | (c77[start - 1 + i] == b'1') as i64;
    }
    v
}

/// Iw.m: right-justified in w columns, at least m digits, '-' for
/// negatives; asterisks when it does not fit.
pub(crate) fn fmt_i(v: i64, w: usize, m: usize) -> Vec<u8> {
    let mut digits = v.unsigned_abs().to_string();
    while digits.len() < m {
        digits.insert(0, '0');
    }
    if v < 0 {
        digits.insert(0, '-');
    }
    if digits.len() > w {
        return vec![b'*'; w];
    }
    let mut out = vec![b' '; w - digits.len()];
    out.extend_from_slice(digits.as_bytes());
    out
}

/// Fortran NINT for a default REAL: round half away from zero.
pub(crate) fn nint32(x: f32) -> i64 {
    x.round() as i64
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn list_read_matches_gfortran() {
        // Each of these was checked against ft8code (WSJT-X 2.7.0) through
        // the report field of a standard message.
        assert_eq!(list_read_int(b"+5,"), ListRead::Value(5));
        assert_eq!(list_read_int(b"+5/"), ListRead::Value(5));
        assert_eq!(list_read_int(b"-05"), ListRead::Value(-5));
        assert_eq!(list_read_int(b"+5;"), ListRead::Error);
        assert_eq!(list_read_int(b"+5."), ListRead::Error);
        assert_eq!(list_read_int(b"+2*3"), ListRead::Error);
        assert_eq!(list_read_int(b"-"), ListRead::Error);
        assert_eq!(list_read_int(b"+"), ListRead::Error);
        assert_eq!(list_read_int(b"2*13"), ListRead::Value(13));
        assert_eq!(list_read_int(b"2*"), ListRead::Null);
        assert_eq!(list_read_int(b",5"), ListRead::Null);
        assert_eq!(list_read_int(b"99999999999"), ListRead::Error);
    }

    #[test]
    fn b_descriptor_overflows_to_asterisks() {
        let mut w = C77Writer::new();
        w.b(5, 3).b(8, 3).b(-1, 2);
        assert_eq!(&w.buf, b"101*****");
    }

    #[test]
    fn i_descriptor() {
        assert_eq!(fmt_i(5, 3, 2), b" 05");
        assert_eq!(fmt_i(-5, 3, 2), b"-05");
        assert_eq!(fmt_i(231, 3, 2), b"231");
        assert_eq!(fmt_i(-231, 3, 2), b"***");
        assert_eq!(fmt_i(7, 2, 0), b" 7");
    }

    #[test]
    fn strings() {
        assert_eq!(fixed(b"AB", 4), b"AB  ");
        assert_eq!(adjustr(b"AB  "), b"  AB");
        assert_eq!(adjustl(b"  AB"), b"AB  ");
        assert!(feq(b"AB", b"AB   "));
        assert_eq!(index(b"K1ABC/P ", b"/P "), 6);
        assert_eq!(sub(b"ABC", 2, 1), b"");
    }
}
