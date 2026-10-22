// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0, lib/77bit/packjt77.f90 (packtext77,
// unpacktext77), copyright (C) 2001-2023 Joe Taylor K1JT and the WSJT
// Development Group, GPL-3.0-or-later.

//! Free text (type 0.0): 13 characters, base 42, in 71 bits.
//!
//! WSJT-X does this with a hand-rolled byte-array bignum (mp_short_*),
//! because Fortran has no integer wide enough; 42^13 < 2^71 fits a u128.

use crate::fortran::{adjustr, fixed};

pub(crate) const TEXT_ALPHABET: &[u8; 42] = b" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./?";

/// packtext77: right-justify, then base 42. A character outside the
/// alphabet is sent as a blank.
pub(crate) fn pack_text(c13: &[u8]) -> u128 {
    let w = adjustr(&fixed(c13, 13));
    let mut v: u128 = 0;
    for &c in &w {
        let j = TEXT_ALPHABET.iter().position(|&x| x == c).unwrap_or(0) as u128;
        v = v * 42 + j;
    }
    v
}

/// unpacktext77: the 13 characters (right-justified, as sent) of a
/// 71-bit value. Values past 42^13 lose their top quotient, as in WSJT-X.
pub(crate) fn unpack_text(v71: u128) -> Vec<u8> {
    let mut v = v71;
    let mut out = vec![b' '; 13];
    for i in (0..13).rev() {
        out[i] = TEXT_ALPHABET[(v % 42) as usize];
        v /= 42;
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn round_trip() {
        let v = pack_text(b"TNX BOB 73 GL");
        assert!(v < (1u128 << 71));
        assert_eq!(unpack_text(v), b"TNX BOB 73 GL");
        assert_eq!(unpack_text(pack_text(b"HI")), b"           HI");
        assert_eq!(unpack_text(pack_text(b"A#B")), b"          A B");
    }
}
