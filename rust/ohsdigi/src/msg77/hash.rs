// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0, lib/77bit/packjt77.f90 (hash10/12/22,
// ihashcall, save_hash_call, add_call_to_recent_calls), copyright (C)
// 2001-2023 Joe Taylor K1JT, Steve Franke K9AN, Bill Somerville G4WJS and
// the WSJT Development Group, GPL-3.0-or-later.

//! The callsign hash tables a 77-bit message's hashed calls are looked up in.
//!
//! In WSJT-X these are module globals of packjt77, filled as a side effect
//! of packing and unpacking: a call seen in full is remembered under its
//! 10-, 12- and 22-bit hashes, and a later message that carries only the
//! hash shows the call instead of "<...>". Here they are one value the
//! caller owns and passes in, so an encoder can start from empty (as
//! ft8code does, once per run) and a decoder can keep one for a whole
//! session, with no hidden state shared between the two.

use crate::fortran::{feq, fixed, index1, len_trim, sub};

/// WSJT-X's MAXHASH: how many 22-bit hashes are remembered.
pub const MAXHASH: usize = 1000;
/// WSJT-X's MAXRECENT.
pub const MAXRECENT: usize = 10;

const HASH_ALPHABET: &[u8; 38] = b" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/";

/// The m-bit hash of a callsign (m = 10, 12 or 22): WSJT-X's ihashcall.
/// The first 11 characters, base 38, times a fixed odd constant, top m
/// bits of the 64-bit product. A character outside the alphabet counts as
/// -1, as INDEX()-1 makes it there.
pub fn ihashcall(call: &[u8], m: u32) -> i64 {
    let c0 = fixed(call, 13);
    let mut n8: i64 = 0;
    for &c in &c0[..11] {
        let j = HASH_ALPHABET.iter().position(|&x| x == c).map_or(-1, |p| p as i64);
        n8 = n8.wrapping_mul(38).wrapping_add(j);
    }
    ((47_055_833_459u64.wrapping_mul(n8 as u64)) >> (64 - m)) as i64
}

/// The tables, and the "my call" / "his call" state unpack77 keeps between
/// calls.
#[derive(Clone)]
pub struct CallHashes {
    pub(crate) calls10: Vec<Vec<u8>>,
    pub(crate) calls12: Vec<Vec<u8>>,
    pub(crate) calls22: Vec<Vec<u8>>,
    pub(crate) ihash22: Vec<i64>,
    pub(crate) nzhash: usize,
    pub(crate) recent_calls: Vec<Vec<u8>>,
    pub(crate) mycall13: Vec<u8>,
    pub(crate) dxcall13: Vec<u8>,
    pub(crate) dxbase: Vec<u8>,
    // unpack77's SAVEd locals. hashmy10/12/22 start at 0 because gfortran
    // puts SAVEd variables in zero-initialised static storage, and
    // unpack77's type 5 compares against hashmy12 without first checking
    // that a call was ever set: a type-5 message whose first hash is 0
    // shows "<>" in WSJT-X, and does here.
    pub(crate) mycall13_0: Vec<u8>,
    pub(crate) dxcall13_0: Vec<u8>,
    pub(crate) mycall13_set: bool,
    pub(crate) dxcall13_set: bool,
    pub(crate) hashmy10: i64,
    pub(crate) hashmy12: i64,
    pub(crate) hashmy22: i64,
    pub(crate) hashdx10: i64,
    pub(crate) hashdx12: i64,
    pub(crate) hashdx22: i64,
}

impl Default for CallHashes {
    fn default() -> Self {
        Self::new()
    }
}

impl CallHashes {
    pub fn new() -> Self {
        let blank = vec![b' '; 13];
        CallHashes {
            calls10: vec![blank.clone(); 1024],
            calls12: vec![blank.clone(); 4096],
            calls22: vec![blank.clone(); MAXHASH],
            ihash22: vec![-1; MAXHASH],
            nzhash: 0,
            recent_calls: vec![blank.clone(); MAXRECENT],
            mycall13: blank.clone(),
            dxcall13: blank.clone(),
            dxbase: vec![b' '; 6],
            mycall13_0: blank.clone(),
            dxcall13_0: blank,
            mycall13_set: false,
            dxcall13_set: false,
            hashmy10: 0,
            hashmy12: 0,
            hashmy22: 0,
            hashdx10: 0,
            hashdx12: 0,
            hashdx22: 0,
        }
    }

    /// The operator's own call (WSJT-X's mycall13): a received message
    /// whose hash matches it shows it, and it is never stored in the
    /// 10/12-bit tables (the hash of one's own call is always known).
    pub fn set_mycall(&mut self, call: &str) {
        self.mycall13 = fixed(call.as_bytes(), 13);
    }

    /// The call of the station being worked (dxcall13).
    pub fn set_dxcall(&mut self, call: &str) {
        self.dxcall13 = fixed(call.as_bytes(), 13);
    }

    /// The DXpedition base call that "$DX" in a message stands for.
    pub fn set_dxbase(&mut self, call: &str) {
        self.dxbase = fixed(call.as_bytes(), 6);
    }

    /// Remember a callsign under its three hashes (save_hash_call). Returns
    /// (n10, n12, n22), or None when the call is too short or a "<...>"
    /// placeholder and nothing was stored.
    pub fn save(&mut self, call: &[u8]) -> Option<(i64, i64, i64)> {
        let mut cw = fixed(call, 13);
        if cw[0] == b' ' || &cw[..5] == b"<...>" {
            return None;
        }
        if cw[0] == b'<' {
            cw = fixed(&cw[1..], 13);
        }
        let i = index1(&cw, b'>');
        if i > 0 {
            for c in cw[i - 1..].iter_mut() {
                *c = b' ';
            }
        }
        if len_trim(&cw) < 3 {
            return None;
        }
        let n10 = ihashcall(&cw, 10);
        if (0..=1023).contains(&n10) && !feq(&cw, &self.mycall13) {
            self.calls10[n10 as usize] = cw.clone();
        }
        let n12 = ihashcall(&cw, 12);
        if (0..=4095).contains(&n12) && !feq(&cw, &self.mycall13) {
            self.calls12[n12 as usize] = cw.clone();
        }
        let n22 = ihashcall(&cw, 22);
        if self.ihash22.contains(&n22) {
            for k in 0..MAXHASH {
                if self.ihash22[k] == n22 {
                    self.calls22[k] = cw.clone();
                }
            }
        } else {
            self.ihash22.rotate_right(1);
            self.calls22.rotate_right(1);
            self.ihash22[0] = n22;
            self.calls22[0] = cw;
            if self.nzhash < MAXHASH {
                self.nzhash += 1;
            }
        }
        Some((n10, n12, n22))
    }

    fn bracket(call: &[u8]) -> Vec<u8> {
        let mut v = vec![b'<'];
        v.extend_from_slice(&call[..len_trim(call)]);
        v.push(b'>');
        fixed(&v, 13)
    }

    /// hash10: "<CALL>" or "<...>".
    pub(crate) fn lookup10(&self, n10: i64) -> Vec<u8> {
        if (0..=1023).contains(&n10) && len_trim(&self.calls10[n10 as usize]) > 0 {
            return Self::bracket(&self.calls10[n10 as usize]);
        }
        fixed(b"<...>", 13)
    }

    /// hash12.
    pub(crate) fn lookup12(&self, n12: i64) -> Vec<u8> {
        if (0..=4095).contains(&n12) && len_trim(&self.calls12[n12 as usize]) > 0 {
            return Self::bracket(&self.calls12[n12 as usize]);
        }
        fixed(b"<...>", 13)
    }

    /// hash22: the most recently stored call with this hash.
    pub(crate) fn lookup22(&self, n22: i64) -> Vec<u8> {
        for i in 0..self.nzhash {
            if self.ihash22[i] == n22 {
                return Self::bracket(&self.calls22[i]);
            }
        }
        fixed(b"<...>", 13)
    }

    /// add_call_to_recent_calls: kept because WSJT-X keeps it (its a-priori
    /// decoding uses the list); nothing in encoding reads it.
    pub(crate) fn add_recent(&mut self, call: &[u8]) {
        let call = fixed(call, 13);
        let present = self.recent_calls[..MAXRECENT - 1].iter().any(|c| feq(c, &call));
        if !present {
            self.recent_calls.rotate_right(1);
            self.recent_calls[0] = call;
        }
    }

    /// The most recently heard calls, newest first.
    pub fn recent(&self) -> Vec<String> {
        self.recent_calls
            .iter()
            .filter(|c| len_trim(c) > 0)
            .map(|c| String::from_utf8_lossy(&c[..len_trim(c)]).into_owned())
            .collect()
    }

    /// The call stored under a 22-bit hash, if any (for a decoder's display).
    pub fn call_for_hash22(&self, n22: i64) -> Option<String> {
        let c = self.lookup22(n22);
        if feq(&c, b"<...>") {
            None
        } else {
            let t = &c[1..len_trim(&c)];
            let t = sub(t, 1, t.len() as isize - if t.last() == Some(&b'>') { 1 } else { 0 });
            Some(String::from_utf8_lossy(t).into_owned())
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn save_then_lookup() {
        let mut h = CallHashes::new();
        let (n10, n12, n22) = h.save(b"<PJ4/K1ABC>").unwrap();
        assert_eq!(&h.lookup10(n10)[..], b"<PJ4/K1ABC>  ");
        assert_eq!(&h.lookup12(n12)[..], b"<PJ4/K1ABC>  ");
        assert_eq!(&h.lookup22(n22)[..], b"<PJ4/K1ABC>  ");
        assert_eq!(h.call_for_hash22(n22).as_deref(), Some("PJ4/K1ABC"));
        assert!(h.save(b"AB").is_none());
    }

    #[test]
    fn hash_widths() {
        for m in [10u32, 12, 22] {
            let v = ihashcall(b"K1ABC", m);
            assert!(v >= 0 && v < (1 << m));
        }
    }
}
