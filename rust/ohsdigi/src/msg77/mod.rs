// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0, lib/77bit/packjt77.f90 (pack77, unpack77,
// split77 and the pack77_* message types) and lib/fmtmsg.f90, copyright
// (C) 2001-2023 Joe Taylor K1JT, Steve Franke K9AN, Bill Somerville G4WJS
// and the WSJT Development Group, GPL-3.0-or-later. WSJT-X's own
// description of the message types is lib/77bit/77bit.txt.

//! The 77-bit message payload shared by FT8, FT4 (and FST4, MSK144, Q65
//! in WSJT-X): text to bits (pack77) and back (unpack77).
//!
//! This is the part of the protocol where "what WSJT-X does" and "what
//! the documentation says" differ most, because so much of the behaviour
//! is in the parsing: which message type a line of text becomes is
//! decided by trying each packer in a fixed order, each with its own idea
//! of a callsign, a report or a grid. So the port follows packjt77.f90's
//! structure and order closely - the same functions, tried in the same
//! sequence, with the same fall-throughs - and leaves idiom for the parts
//! with one obvious meaning (bit fields, base-N arithmetic, tables).
//! tests/corpus.rs holds it to WSJT-X 2.7.0's ft8code and ft4code, edge
//! cases and invalid messages included.

pub mod callsign;
pub mod hash;
pub(crate) mod tables;
pub(crate) mod text;

use crate::fortran::*;
pub use callsign::{chkcall, pack28, unpack28, PackError, MAX22, NTOKENS};
pub use hash::{ihashcall, CallHashes};
use tables::{ARRL_SECTIONS, RTTY_MULTS};

/// The 77 payload bits, one per byte, 0 or 1, most significant first.
pub type Bits77 = [u8; 77];

const MAXGRID4: i64 = 32_400;

/// What pack77 produced: the 77 characters WSJT-X writes ('0', '1', or
/// '*' where a field overflowed), and the message type i3.n3 (n3 is
/// meaningful only for i3 = 0).
#[derive(Debug, Clone)]
pub struct Packed {
    pub c77: [u8; 77],
    pub i3: i32,
    pub n3: i32,
    /// Set when WSJT-X's own result for this message read a variable it
    /// never set, and this one is what ft8code gives in practice (the one
    /// case: pack77_3's nserial, which decides whether a message is tried
    /// as an RTTY Roundup exchange; ft8code behaves as if it were 0,
    /// ft4code often does not). The text says which variable.
    pub undefined: Option<&'static str>,
}

const NSERIAL_UNSET: &str = "pack77_3's nserial (no 5x9 report before the last word)";

impl Packed {
    /// The payload, or None when a field overflowed: WSJT-X then fails to
    /// read its own bits back and sends nothing ("*** bad message ***").
    pub fn bits(&self) -> Option<Bits77> {
        c77_to_bits(&self.c77)
    }
}

/// '0'/'1' characters to bits; None if any character is anything else.
pub fn c77_to_bits(c77: &[u8; 77]) -> Option<Bits77> {
    let mut out = [0u8; 77];
    for (o, &c) in out.iter_mut().zip(c77.iter()) {
        *o = match c {
            b'0' => 0,
            b'1' => 1,
            _ => return None,
        };
    }
    Some(out)
}

/// Bits to the '0'/'1' characters unpack77 reads.
pub fn bits_to_c77(bits: &Bits77) -> [u8; 77] {
    let mut out = [b'0'; 77];
    for (o, &b) in out.iter_mut().zip(bits.iter()) {
        *o = if b & 1 == 1 { b'1' } else { b'0' };
    }
    out
}

/// What ft8code calls each i3.n3 (its "msgtype" column).
pub fn type_name(i3: i32, n3: i32) -> &'static str {
    match (i3, n3) {
        (0, 0) => "Free text",
        (0, 1) => "DXpedition mode",
        (0, 2) => "EU VHF Contest",
        (0, 3) | (0, 4) => "ARRL Field Day",
        (0, 5) => "Telemetry",
        (0, _) => "Undefined type",
        (1, _) => "Standard msg",
        (2, _) => "EU VHF Contest",
        (3, _) => "ARRL RTTY Roundup",
        (4, _) => "Nonstandard call",
        (5, _) => "EU VHF Contest",
        _ => "Undefined type",
    }
}

/// fmtmsg, as WSJT-X's command-line encoders apply it to their argument:
/// the first 37 bytes (a CHARACTER*37), letters upper-cased, and runs of
/// blanks collapsed to one - though a single leading blank survives.
#[allow(clippy::needless_range_loop)] // fmtmsg.f90, index for index
pub fn fmtmsg(msg: &[u8]) -> Vec<u8> {
    let mut m = fixed(msg, 37);
    let mut iz = m.len();
    for i in 0..m.len() {
        if m[i].is_ascii_lowercase() {
            m[i] -= 32;
        }
        if m[i] != b' ' {
            iz = i + 1;
        }
    }
    if m.iter().all(|&c| c == b' ') {
        iz = m.len();
    }
    for _ in 0..37 {
        let ib2 = index(&m[..iz], b"  ");
        if ib2 < 1 {
            break;
        }
        let mut n = m[..ib2].to_vec();
        n.extend_from_slice(&m[ib2 + 1..]);
        m = fixed(&n, 37);
        iz -= 1;
    }
    m
}

/// split77's result: the message (upper-cased, blanks collapsed, leading
/// blanks gone) and its words, each a CHARACTER*13 (longer words are cut).
struct Words {
    msg: Vec<u8>,
    nwords: usize,
    w: Vec<Vec<u8>>, // w[0] unused, so w[i] is Fortran's w(i); 19 words
}

impl Words {
    fn w(&self, i: usize) -> &[u8] {
        &self.w[i]
    }
}

fn split77(msg_in: &[u8]) -> Words {
    let mut msg = fixed(msg_in, 37);
    let iz0 = len_trim(&msg);
    let (mut j, mut k, mut n) = (0usize, 0usize, 0usize);
    let mut c0 = b' ';
    let mut w = vec![vec![b' '; 13]; 20];
    for i in 0..iz0 {
        if msg[i] == 0 {
            msg[i] = b' ';
        }
        let mut c = msg[i];
        if c == b' ' && c0 == b' ' {
            continue;
        }
        if c != b' ' && c0 == b' ' {
            k += 1;
            n = 0;
        }
        j += 1;
        n += 1;
        if c.is_ascii_lowercase() {
            c -= 32;
        }
        msg[j - 1] = c;
        if n <= 13 && k <= 19 {
            w[k][n - 1] = c;
        }
        c0 = c;
    }
    let mut nwords = k;
    if nwords == 0 {
        return Words { msg, nwords, w };
    }
    for c in msg[j..].iter_mut() {
        *c = b' ';
    }
    if nwords >= 3 {
        let (_, ok1) = chkcall(&w[3]);
        if ok1 && &w[1][..3] == b"CQ " {
            // "CQ DX K1ABC FN42" -> "CQ_DX K1ABC FN42": a directed CQ is
            // one 28-bit token. Only words 3..13 move down, as in WSJT-X.
            w[1] = fixed(&cat(&[b"CQ_", &w[2][..10]]), 13);
            let moved: Vec<Vec<u8>> = w[3..=13].to_vec();
            w[2..=12].clone_from_slice(&moved);
            nwords -= 1;
        }
    }
    Words { msg, nwords, w }
}

/// pack77: a message's 77 bits and type. Starts nothing afresh: every
/// callsign packed is remembered in `h`, as WSJT-X remembers it.
pub fn pack77(msg0: &[u8], h: &mut CallHashes) -> Result<Packed, PackError> {
    let mut msg = fixed(msg0, 37);
    if &msg[..3] == b"$DX" {
        let i1 = index1(&msg, b' ');
        msg = fixed(&cat(&[trim(&h.dxbase), b" ", sub(&msg, i1 + 1, 37)]), 37);
    }
    let sp = split77(&msg);
    let msg = sp.msg.clone();
    let mut out = Packed {
        c77: [b'*'; 77],
        i3: -1,
        n3: -1,
        undefined: None,
    };

    let skip_to_100 = &msg[..3] == b"CQ " || &msg[..3] == b"DE " || &msg[..4] == b"QRZ ";
    if !skip_to_100 {
        if let Some(p) = pack77_01(&sp, h)? {
            return Ok(p);
        }
        if let Some(p) = pack77_03(&sp, h)? {
            return Ok(p);
        }
        if sp.nwords < 2 {
            match telemetry(&msg) {
                Telemetry::Packed(p) => return Ok(p),
                Telemetry::FreeText => return Ok(free_text(&msg)),
                Telemetry::No => {}
            }
        }
    }
    // Label 100 in packjt77.f90.
    if let Some(p) = pack77_06(&sp, h)? {
        return Ok(p);
    }
    if let Some(p) = pack77_1(&sp, h)? {
        return Ok(p);
    }
    // From here on, whatever the message becomes, WSJT-X first asked
    // whether an unset variable was positive (pack77_3).
    let mut undefined = None;
    match pack77_3(&sp, h)? {
        Rtty::Packed(p) => return Ok(p),
        Rtty::NoUnsetSerial => undefined = Some(NSERIAL_UNSET),
        // WSJT-X sets the type and returns without writing the bits: the
        // buffer then holds whatever it held, which is never a valid
        // payload, so the message is reported bad.
        Rtty::Unwritten => {
            out.i3 = 3;
            out.n3 = 0;
            return Ok(out);
        }
        Rtty::No => {}
    }
    let mut p = if let Some(p) = pack77_4(&sp, h)? {
        p
    } else if let Some(p) = pack77_5(&sp, h) {
        p
    } else {
        free_text(&msg)
    };
    p.undefined = undefined;
    Ok(p)
}

fn free_text(msg: &[u8]) -> Packed {
    let v = text::pack_text(&msg[..13]);
    let mut wtr = C77Writer::new();
    for i in (0..71).rev() {
        wtr.b(((v >> i) & 1) as i64, 1);
    }
    wtr.b(0, 3).b(0, 3);
    Packed {
        c77: wtr.finish(),
        i3: 0,
        n3: 0,
        undefined: None,
    }
}

enum Telemetry {
    Packed(Packed),
    FreeText,
    No,
}

/// Type 0.5: up to 18 hex digits, the first word only, read as three
/// Z6 fields of the right-justified word (so "ABC" is 000000 000000 000ABC).
fn telemetry(msg: &[u8]) -> Telemetry {
    let i0 = index1(msg, b' ');
    let c18 = adjustr(&fixed(sub(msg, 1, i0 as isize - 1), 18));
    let mut ntel = [-99i64; 3];
    let mut err = false;
    for f in 0..3 {
        match read_z6(&c18[f * 6..f * 6 + 6]) {
            Some(v) => ntel[f] = v,
            None => {
                err = true;
                break;
            }
        }
    }
    if !err && ntel[0] >= 1 << 23 {
        return Telemetry::FreeText;
    }
    if ntel.iter().all(|&v| v >= 0) {
        let mut wtr = C77Writer::new();
        wtr.b(ntel[0], 23).b(ntel[1], 24).b(ntel[2], 24).b(5, 3).b(0, 3);
        return Telemetry::Packed(Packed {
            c77: wtr.finish(),
            i3: 0,
            n3: 5,
            undefined: None,
        });
    }
    Telemetry::No
}

/// A Z6 input field as gfortran reads one: blanks ignored (an all-blank
/// field is 0), then an optional sign - "+07" is telemetry 7 and "-07"
/// is -7, so free text - then at least one hex digit.
fn read_z6(f: &[u8]) -> Option<i64> {
    let mut v: i64 = 0;
    let mut neg = false;
    let mut seen_sign = false;
    let mut digits = 0;
    for &c in f {
        let d = match c {
            b' ' => continue,
            b'+' | b'-' if !seen_sign && digits == 0 => {
                seen_sign = true;
                neg = c == b'-';
                continue;
            }
            b'0'..=b'9' => c - b'0',
            b'A'..=b'F' => c - b'A' + 10,
            b'a'..=b'f' => c - b'a' + 10,
            _ => return None,
        };
        digits += 1;
        v = v * 16 + d as i64;
    }
    if seen_sign && digits == 0 {
        return None;
    }
    Some(if neg { -v } else { v })
}

/// Type 0.1, DXpedition mode: "K1ABC RR73; W9XYZ <KH1/KH7Z> -11".
fn pack77_01(sp: &Words, h: &mut CallHashes) -> Result<Option<Packed>, PackError> {
    if sp.nwords != 5 || trim(sp.w(2)) != b"RR73;" || sp.w(4)[0] != b'<' || index1(sp.w(4), b'>') < 1 {
        return Ok(None);
    }
    let mut n = -99i64;
    if let ListRead::Value(v) = list_read_int(sp.w(5)) {
        n = v;
    }
    if n == -99 {
        return Ok(None);
    }
    let n5 = ((n + 30) / 2).clamp(0, 31);
    if !chkcall(sp.w(1)).1 || !chkcall(sp.w(3)).1 {
        return Ok(None);
    }
    let n28a = pack28(&mut sp.w(1).to_vec(), h)?;
    let n28b = pack28(&mut sp.w(3).to_vec(), h)?;
    h.save(sp.w(4));
    let i2 = index1(sp.w(4), b'>');
    let c13 = fixed(sub(sp.w(4), 2, i2 as isize - 1), 13);
    let n10 = ihashcall(&c13, 10);
    let mut wtr = C77Writer::new();
    wtr.b(n28a, 28).b(n28b, 28).b(n10, 10).b(n5, 5).b(1, 3).b(0, 3);
    Ok(Some(Packed {
        c77: wtr.finish(),
        i3: 0,
        n3: 1,
        undefined: None,
    }))
}

/// Types 0.3 and 0.4, ARRL Field Day: "WA9XYZ KA1ABC R 16A EMA".
fn pack77_03(sp: &Words, h: &mut CallHashes) -> Result<Option<Packed>, PackError> {
    let nw = sp.nwords;
    if !(4..=5).contains(&nw) {
        return Ok(None);
    }
    if !chkcall(sp.w(1)).1 || !chkcall(sp.w(2)).1 {
        return Ok(None);
    }
    let last = sp.w(nw);
    let isec = match ARRL_SECTIONS.iter().position(|s| s[..] == last[..3]) {
        Some(i) => i as i64 + 1,
        None => return Ok(None),
    };
    if nw == 5 && trim(sp.w(3)) != b"R" {
        return Ok(None);
    }
    let cls = sp.w(nw - 1);
    let j = len_trim(cls) as isize - 1;
    let mut ntx = -1i64;
    if let ListRead::Value(v) = list_read_int(sub(cls, 1, j)) {
        ntx = v;
    }
    if !(1..=32).contains(&ntx) {
        return Ok(None);
    }
    let nclass = ch(cls, (j + 1) as usize) as i64 - b'A' as i64;
    let m = len_trim(last);
    if !(2..=3).contains(&m) {
        return Ok(None);
    }
    let (mut n3, mut intx) = (3, ntx - 1);
    if intx >= 16 {
        n3 = 4;
        intx = ntx - 17;
    }
    let n28a = pack28(&mut sp.w(1).to_vec(), h)?;
    let n28b = pack28(&mut sp.w(2).to_vec(), h)?;
    let ir = (&sp.w(3)[..2] == b"R ") as i64;
    let mut wtr = C77Writer::new();
    wtr.b(n28a, 28)
        .b(n28b, 28)
        .b(ir, 1)
        .b(intx, 4)
        .b(nclass, 3)
        .b(isec, 7)
        .b(n3, 3)
        .b(0, 3);
    Ok(Some(Packed {
        c77: wtr.finish(),
        i3: 0,
        n3: n3 as i32,
        undefined: None,
    }))
}

fn is_grid4(g: &[u8]) -> bool {
    let g = fixed(g, 4);
    len_trim(&g) == 4
        && (b'A'..=b'R').contains(&g[0])
        && (b'A'..=b'R').contains(&g[1])
        && g[2].is_ascii_digit()
        && g[3].is_ascii_digit()
}

fn is_grid6(g: &[u8]) -> bool {
    let g = fixed(g, 6);
    len_trim(&g) == 6
        && (b'A'..=b'R').contains(&g[0])
        && (b'A'..=b'R').contains(&g[1])
        && g[2].is_ascii_digit()
        && g[3].is_ascii_digit()
        && (b'A'..=b'X').contains(&g[4])
        && (b'A'..=b'X').contains(&g[5])
}

fn grid4_value(g: &[u8]) -> i64 {
    (g[0] - b'A') as i64 * 18 * 10 * 10
        + (g[1] - b'A') as i64 * 10 * 10
        + (g[2] - b'0') as i64 * 10
        + (g[3] - b'0') as i64
}

/// Type 0.6, WSPR messages carried in 77 bits ("K1ABC FN42 37",
/// "PJ4/K1ABC 37"). WSJT-X reaches its third form only when the caller
/// hints for it, which no FT8/FT4 encoder does, so it is not ported.
fn pack77_06(sp: &Words, h: &mut CallHashes) -> Result<Option<Packed>, PackError> {
    let (w1, w2, w3) = (sp.w(1), sp.w(2), sp.w(3));
    let (m1, m2, m3) = (len_trim(w1), len_trim(w2), len_trim(w3));
    let dbm = |w: &[u8]| -> i64 {
        // Only digits reach here (checked by the caller), so the READ,
        // which has no err=, cannot fail.
        let v = match list_read_int(w) {
            ListRead::Value(v) => v,
            _ => 0,
        };
        // 0.3 is a default REAL in WSJT-X: 0.3*15 rounds to 5 in single
        // precision, to 4 in double.
        nint32(0.3f32 * v.clamp(0, 60) as f32)
    };
    if sp.nwords == 3 && (3..=6).contains(&m1) && m2 == 4 && m3 <= 2 {
        if !is_grid4(&w2[..4]) || !is_digit(w3[0]) || (m3 == 2 && !is_digit(w3[1])) {
            return Ok(None);
        }
        let n28 = pack28(&mut w1.to_vec(), h)?;
        let igrid4 = grid4_value(&w2[..4]);
        let idbm = dbm(w3);
        let mut wtr = C77Writer::new();
        wtr.b(n28, 28)
            .b(igrid4, 15)
            .b(idbm, 5)
            .i1(0)
            .i1(0)
            .b(0, 21)
            .b(6, 3)
            .b(0, 3);
        return Ok(Some(Packed {
            c77: wtr.finish(),
            i3: 0,
            n3: 6,
            undefined: None,
        }));
    }
    if sp.nwords == 2 && (5..=10).contains(&m1) && m2 <= 2 {
        let a2: &[u8] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
        let ix = |c: u8| -> i64 { index1(a2, c) as i64 - 1 };
        let i1 = index1(w1, b'/');
        if i1 < 2 || i1 == m1 {
            return Ok(None);
        }
        if !is_digit(w2[0]) {
            return Ok(None);
        }
        if i1 + 3 == m1 && !is_digit(ch(w1, m1)) {
            return Ok(None);
        }
        if m2 == 2 && !is_digit(w2[1]) {
            return Ok(None);
        }
        let (bcall, ok) = chkcall(w1);
        if !ok {
            return Ok(None);
        }
        let mut npfx: i64;
        if i1 <= 4 {
            npfx = ix(ch(w1, 1));
            if i1 >= 3 {
                npfx = 36 * npfx + ix(ch(w1, 2));
            }
            if i1 == 4 {
                npfx = 36 * npfx + ix(ch(w1, 3));
            }
        } else {
            npfx = match m1 - i1 {
                1 => ix(ch(w1, i1 + 1)),
                2 => 36 * ix(ch(w1, i1 + 1)) + ix(ch(w1, i1 + 2)),
                3 => {
                    if !is_digit(ch(w1, i1 + 3)) {
                        return Ok(None);
                    }
                    36 * 10 * ix(ch(w1, i1 + 1)) + 10 * ix(ch(w1, i1 + 2)) + ix(ch(w1, i1 + 3))
                }
                _ => {
                    return Err(PackError::Undefined(
                        "pack77_06's npfx (a suffix of four or more characters)",
                    ))
                }
            };
            npfx += 46656;
        }
        let n28 = pack28(&mut cat(&[&bcall, b"       "]), h)?;
        let idbm = dbm(w2);
        let mut wtr = C77Writer::new();
        wtr.b(n28, 28).b(npfx, 16).b(idbm, 5).i1(1).b(0, 21).b(6, 3).b(0, 3);
        return Ok(Some(Packed {
            c77: wtr.finish(),
            i3: 0,
            n3: 6,
            undefined: None,
        }));
    }
    Ok(None)
}

/// Types 1 and 2: two calls (either may be "/R", or for type 2 "/P"),
/// then a grid, a report, R and a report, RRR, RR73 or 73.
fn pack77_1(sp: &Words, h: &mut CallHashes) -> Result<Option<Packed>, PackError> {
    let nw = sp.nwords;
    if !(2..=4).contains(&nw) {
        return Ok(None);
    }
    let (w1, w2) = (sp.w(1), sp.w(2));
    let (bcall_1, mut ok1) = chkcall(w1);
    let (bcall_2, mut ok2) = chkcall(w2);
    if &w1[..3] == b"DE " || &w1[..3] == b"CQ_" || &w1[..3] == b"CQ " || &w1[..4] == b"QRZ " {
        ok1 = true;
    }
    if w1[0] == b'<' && index1(w1, b'>') >= 5 {
        ok1 = true;
    }
    if w2[0] == b'<' && index1(w2, b'>') >= 5 {
        ok2 = true;
    }
    if !ok1 || !ok2 {
        return Ok(None);
    }
    if w1[0] == b'<' && index1(w2, b'/') > 0 {
        return Ok(None);
    }
    if w2[0] == b'<' && index1(w1, b'/') > 0 {
        return Ok(None);
    }
    if nw == 2 && (!ok2 || index1(w2, b'/') >= 2) {
        return Ok(None);
    }
    let mut ir = 0i64;
    let mut irpt = 0i64;
    let last = sp.w(nw);
    if nw != 2 {
        let c1 = last[0];
        let c2 = &last[..2];
        let tl = trim(last);
        if !is_grid4(&last[..4])
            && c1 != b'+'
            && c1 != b'-'
            && c2 != b"R+"
            && c2 != b"R-"
            && tl != b"RRR"
            && tl != b"RR73"
            && tl != b"73"
        {
            return Ok(None);
        }
        let report = |s: &[u8]| -> Option<i64> {
            match list_read_int(s) {
                ListRead::Value(v) => {
                    let v = if (-50..=-31).contains(&v) { v + 101 } else { v };
                    Some(v + 35)
                }
                _ => None,
            }
        };
        if c1 == b'+' || c1 == b'-' {
            ir = 0;
            irpt = match report(last) {
                Some(v) => v,
                None => return Ok(None),
            };
        } else if c2 == b"R+" || c2 == b"R-" {
            ir = 1;
            irpt = match report(&last[1..]) {
                Some(v) => v,
                None => return Ok(None),
            };
        } else if tl == b"RRR" {
            irpt = 2;
        } else if tl == b"RR73" {
            irpt = 3;
        } else if tl == b"73" {
            irpt = 4;
        }
    }
    // Label 10.
    let i1psuffix = index(&cat(&[w1, b" "]), b"/P ");
    let i2psuffix = index(&cat(&[w2, b" "]), b"/P ");
    let mut i3 = -1;
    if nw == 2 || nw == 3 || (nw == 4 && &sp.w(3)[..2] == b"R ") {
        i3 = 1;
        if i1psuffix >= 4 || i2psuffix >= 4 {
            i3 = 2;
        }
    }
    let mut c13 = fixed(&bcall_1, 13);
    if &c13[..3] == b"CQ_" || w1[0] == b'<' {
        c13 = w1.to_vec();
    }
    let n28a = pack28(&mut c13, h)?;
    let mut c13 = fixed(&bcall_2, 13);
    if w2[0] == b'<' {
        c13 = w2.to_vec();
    }
    let n28b = pack28(&mut c13, h)?;
    let ipa = (i1psuffix >= 4 || index(&cat(&[w1, b" "]), b"/R ") >= 4) as i64;
    let ipb = (i2psuffix >= 4 || index(&cat(&[w2, b" "]), b"/R ") >= 4) as i64;
    let mut igrid4;
    if is_grid4(&last[..4]) {
        ir = (sp.w(3) == &fixed(b"R", 13)[..]) as i64;
        igrid4 = grid4_value(&last[..4]);
    } else {
        igrid4 = MAXGRID4 + irpt;
    }
    if nw == 2 {
        ir = 0;
        igrid4 = MAXGRID4 + 1;
    }
    if i3 < 0 {
        return Ok(None);
    }
    let mut wtr = C77Writer::new();
    wtr.b(n28a, 28)
        .b(ipa, 1)
        .b(n28b, 28)
        .b(ipb, 1)
        .b(ir, 1)
        .b(igrid4, 15)
        .b(i3 as i64, 3);
    Ok(Some(Packed {
        c77: wtr.finish(),
        i3,
        n3: 0,
        undefined: None,
    }))
}

enum Rtty {
    Packed(Packed),
    Unwritten,
    No,
    /// Not RTTY Roundup, by the reading ft8code shows of an unset nserial.
    NoUnsetSerial,
}

/// Type 3, ARRL RTTY Roundup: "TU; W9XYZ K1ABC R 579 MA", or a serial
/// number in place of the state.
fn pack77_3(sp: &Words, h: &mut CallHashes) -> Result<Rtty, PackError> {
    let nw = sp.nwords;
    if sp.w(1)[0] == b'<' && sp.w(2)[0] == b'<' {
        return Ok(Rtty::No);
    }
    if !(4..=6).contains(&nw) {
        return Ok(Rtty::No);
    }
    let i1 = if trim(sp.w(1)) == b"TU;" { 2 } else { 1 };
    if !chkcall(sp.w(i1)).1 || !chkcall(sp.w(i1 + 1)).1 {
        return Ok(Rtty::No);
    }
    let crpt = &sp.w(nw - 1)[..3];
    if index1(crpt, b'-') >= 1 || index1(crpt, b'+') >= 1 {
        return Ok(Rtty::No);
    }
    // nserial is read only after a 5x9 report; otherwise WSJT-X leaves it
    // unset, and then tests it. ft8code behaves as if it were 0.
    let mut nserial = 0i64;
    let five_x_nine = crpt[0] == b'5' && (b'2'..=b'9').contains(&crpt[1]) && crpt[2] == b'9';
    if five_x_nine {
        if let ListRead::Value(v) = list_read_int(sp.w(nw)) {
            nserial = v;
        }
    }
    let imult = RTTY_MULTS
        .iter()
        .position(|m| feq(&m[..], sp.w(nw)))
        .map(|i| i as i64 + 1);
    if !five_x_nine && imult.is_none() {
        return Ok(Rtty::NoUnsetSerial);
    }
    let mut nexch = 0;
    if nserial > 0 {
        nexch = nserial;
    }
    if let Some(m) = imult {
        nexch = 8000 + m;
    }
    if imult.is_none() && nserial <= 0 {
        return Ok(Rtty::No);
    }
    let itu = (trim(sp.w(1)) == b"TU;") as usize;
    let n28a = pack28(&mut sp.w(1 + itu).to_vec(), h)?;
    let n28b = pack28(&mut sp.w(2 + itu).to_vec(), h)?;
    let ir = (&sp.w(3 + itu)[..2] == b"R ") as usize;
    let mut irpt = match list_read_int(sp.w(3 + itu + ir)) {
        ListRead::Value(v) => v,
        ListRead::Error => return Ok(Rtty::Unwritten),
        ListRead::Null => return Err(PackError::Undefined("pack77_3's irpt (the report read as null)")),
    };
    irpt = ((irpt - 509) / 10 - 2).clamp(0, 7);
    let mut wtr = C77Writer::new();
    wtr.b(itu as i64, 1)
        .b(n28a, 28)
        .b(n28b, 28)
        .b(ir as i64, 1)
        .b(irpt, 3)
        .b(nexch, 13)
        .b(3, 3);
    Ok(Rtty::Packed(Packed {
        c77: wtr.finish(),
        i3: 3,
        n3: 0,
        undefined: None,
    }))
}

/// Type 4: one hashed call and one nonstandard call of up to 11
/// characters, or "CQ" and a nonstandard call: "<WA9XYZ> PJ4/KA1ABC RR73".
fn pack77_4(sp: &Words, h: &mut CallHashes) -> Result<Option<Packed>, PackError> {
    let nw = sp.nwords;
    if nw != 2 && nw != 3 {
        return Ok(None);
    }
    let (w1, w2) = (sp.w(1), sp.w(2));
    let unbracket = |w: &[u8]| -> Vec<u8> {
        if w[0] == b'<' {
            fixed(sub(w, 2, len_trim(w) as isize - 1), 13)
        } else {
            w.to_vec()
        }
    };
    let call_1 = unbracket(w1);
    let call_2 = unbracket(w2);
    let (bcall_1, ok1) = chkcall(&call_1);
    let (bcall_2, ok2) = chkcall(&call_2);
    if feq(&call_1, &bcall_1) && feq(&call_2, &bcall_2) && ok1 && ok2 {
        return Ok(None);
    }
    let mut i3 = -1;
    let mut icq = 0;
    let is_cq = trim(w1) == b"CQ";
    if is_cq || (ok1 && ok2) {
        if is_cq && len_trim(w2) <= 4 {
            return Ok(None);
        }
        i3 = 4;
        if is_cq {
            icq = 1;
        }
    }
    // Two unbracketed calls (not a CQ) leave WSJT-X's n12 and c11 unset;
    // so does a bracketed call too short to hash, for n12. What it then
    // sends is whatever was in memory ("<...> ZZZZZZZZZ/" is typical).
    const N12_UNSET: &str = "pack77_4's n12 and c11 (two unbracketed nonstandard calls)";
    const N12_SHORT: &str = "pack77_4's n12 (a bracketed call of fewer than three characters)";
    let mut n12: i64 = 0;
    let c11: Vec<u8>;
    let mut iflip = 0;
    if icq == 1 {
        c11 = adjustr(&call_2[..11]);
        if let Some((_, h12, _)) = h.save(w2) {
            n12 = h12;
        }
    } else if w1[0] == b'<' {
        n12 = h.save(w1).ok_or(PackError::Undefined(N12_SHORT))?.1;
        c11 = adjustr(&call_2[..11]);
    } else if w2[0] == b'<' {
        iflip = 1;
        n12 = h.save(w2).ok_or(PackError::Undefined(N12_SHORT))?.1;
        c11 = adjustr(&call_1[..11]);
    } else if i3 == 4 {
        return Err(PackError::Undefined(N12_UNSET));
    } else {
        return Ok(None);
    }
    const C38: &[u8] = b" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/";
    let mut n58: i64 = 0;
    for &c in &c11 {
        n58 = n58 * 38 + index1(C38, c) as i64 - 1;
    }
    let tl = trim(sp.w(3));
    let mut nrpt = match tl {
        b"RRR" => 1,
        b"RR73" => 2,
        b"73" => 3,
        _ => 0,
    };
    if icq == 1 {
        iflip = 0;
        nrpt = 0;
    }
    let mut wtr = C77Writer::new();
    wtr.b(n12, 12).b(n58, 58).b(iflip, 1).b(nrpt, 2).b(icq, 1).b(4, 3);
    // WSJT-X then turns any overflow asterisks into zeros.
    let mut c77 = wtr.finish();
    for c in c77.iter_mut() {
        if *c == b'*' {
            *c = b'0';
        }
    }
    Ok(Some(Packed {
        c77,
        i3: 4,
        n3: 0,
        undefined: None,
    }))
}

/// Type 5, EU VHF contest with both calls hashed:
/// "<PA3XYZ> <G4ABC/P> R 590003 IO91NP".
fn pack77_5(sp: &Words, h: &mut CallHashes) -> Option<Packed> {
    let nw = sp.nwords;
    if !(4..=5).contains(&nw) {
        return None;
    }
    let (w1, w2) = (sp.w(1), sp.w(2));
    if w1[0] != b'<' || w2[0] != b'<' {
        return None;
    }
    let mut nx = -1i64;
    if let ListRead::Value(v) = list_read_int(sp.w(nw - 1)) {
        nx = v;
    }
    if !(520_001..=594_095).contains(&nx) {
        return None;
    }
    let g = &sp.w(nw)[..6];
    if !is_grid6(g) {
        return None;
    }
    h.save(w1);
    let i2 = index1(w1, b'>');
    let n12 = ihashcall(&fixed(sub(w1, 2, i2 as isize - 1), 13), 12);
    h.save(w2);
    let i2 = index1(w2, b'>');
    let n22 = ihashcall(&fixed(sub(w2, 2, i2 as isize - 1), 13), 22);
    let ir = (&sp.w(3)[..2] == b"R ") as i64;
    let irpt = nx / 10000 - 52;
    let iserial = (nx % 10000).min(2047);
    let igrid6 = (g[0] - b'A') as i64 * 18 * 10 * 10 * 24 * 24
        + (g[1] - b'A') as i64 * 10 * 10 * 24 * 24
        + (g[2] - b'0') as i64 * 10 * 24 * 24
        + (g[3] - b'0') as i64 * 24 * 24
        + (g[4] - b'A') as i64 * 24
        + (g[5] - b'A') as i64;
    let mut wtr = C77Writer::new();
    wtr.b(n12, 12)
        .b(n22, 22)
        .b(ir, 1)
        .b(irpt, 3)
        .b(iserial, 11)
        .b(igrid6, 25)
        .b(5, 3);
    Some(Packed {
        c77: wtr.finish(),
        i3: 5,
        n3: 0,
        undefined: None,
    })
}

/// What unpack77 made of 77 bits.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Unpacked {
    /// The message as WSJT-X shows it (up to 37 characters, trailing
    /// blanks removed).
    pub text: Vec<u8>,
    /// WSJT-X's unpk77_success: false for bits that are not a message
    /// WSJT-X would display (a decoder drops them; an encoder refuses).
    pub ok: bool,
}

impl Unpacked {
    pub fn text_lossy(&self) -> String {
        String::from_utf8_lossy(&self.text).into_owned()
    }
}

fn to_grid4(n: i64) -> Option<Vec<u8>> {
    let mut n = n;
    let j1 = n / (18 * 10 * 10);
    if !(0..=17).contains(&j1) {
        return None;
    }
    n -= j1 * 18 * 10 * 10;
    let j2 = n / (10 * 10);
    if !(0..=17).contains(&j2) {
        return None;
    }
    n -= j2 * 10 * 10;
    let j3 = n / 10;
    if !(0..=9).contains(&j3) {
        return None;
    }
    let j4 = n - j3 * 10;
    if !(0..=9).contains(&j4) {
        return None;
    }
    Some(vec![b'A' + j1 as u8, b'A' + j2 as u8, b'0' + j3 as u8, b'0' + j4 as u8])
}

/// to_grid6 (type 5's 24x24 subsquares) or to_grid (WSPR's, where 24/24
/// means "no subsquare"), by `sub`, the subsquare base.
fn to_grid6(n: i64, sub: i64) -> Option<Vec<u8>> {
    let mut n = n;
    let s2 = sub * sub;
    let j1 = n / (18 * 10 * 10 * s2);
    if !(0..=17).contains(&j1) {
        return None;
    }
    n -= j1 * 18 * 10 * 10 * s2;
    let j2 = n / (10 * 10 * s2);
    if !(0..=17).contains(&j2) {
        return None;
    }
    n -= j2 * 10 * 10 * s2;
    let j3 = n / (10 * s2);
    if !(0..=9).contains(&j3) {
        return None;
    }
    n -= j3 * 10 * s2;
    let j4 = n / s2;
    if !(0..=9).contains(&j4) {
        return None;
    }
    n -= j4 * s2;
    let j5 = n / sub;
    if !(0..=sub - 1).contains(&j5) {
        return None;
    }
    let j6 = n - j5 * sub;
    if !(0..=sub - 1).contains(&j6) {
        return None;
    }
    let mut g = vec![b'A' + j1 as u8, b'A' + j2 as u8, b'0' + j3 as u8, b'0' + j4 as u8];
    if sub == 24 || j5 != 24 || j6 != 24 {
        g.push(b'A' + j5 as u8);
        g.push(b'A' + j6 as u8);
    } else {
        g.extend_from_slice(b"  ");
    }
    Some(g)
}

/// unpack77. `received` is WSJT-X's nrx: true for a decoded message (my
/// call may then be shown for a matching hash), false for one about to be
/// sent. Calls seen in full are remembered in `h`.
pub fn unpack77(bits: &Bits77, received: bool, h: &mut CallHashes) -> Unpacked {
    unpack77_c77(&bits_to_c77(bits), received, h)
}

/// unpack77 on WSJT-X's character form, where a '*' (an overflowed
/// field) makes the whole message fail.
pub fn unpack77_c77(c77: &[u8; 77], received: bool, h: &mut CallHashes) -> Unpacked {
    let nrx = received;
    // The "my call" and "his call" hashes, refreshed when either changes.
    if !feq(&h.mycall13, &h.mycall13_0) {
        if len_trim(&h.mycall13) > 2 {
            h.mycall13_set = true;
            h.mycall13_0 = h.mycall13.clone();
            let mc = h.mycall13.clone();
            if let Some((a, b, c)) = h.save(&mc) {
                h.hashmy10 = a;
                h.hashmy12 = b;
                h.hashmy22 = c;
            }
        } else {
            h.mycall13_set = false;
        }
    }
    if !feq(&h.dxcall13, &h.dxcall13_0) && len_trim(&h.dxcall13) > 2 {
        h.dxcall13_set = true;
        h.dxcall13_0 = h.dxcall13.clone();
        h.hashdx10 = ihashcall(&h.dxcall13, 10);
        h.hashdx12 = ihashcall(&h.dxcall13, 12);
        h.hashdx22 = ihashcall(&h.dxcall13, 22);
    }
    if c77.iter().any(|&c| c != b'0' && c != b'1') {
        return Unpacked {
            text: b"failed unpack".to_vec(),
            ok: false,
        };
    }
    let rb = |a: usize, w: usize| read_b(c77, a, w);
    let n3 = rb(72, 3);
    let i3 = rb(75, 3);
    let mut ok = true;
    let mut msg: Vec<u8> = Vec::new();
    let t = |s: &[u8]| -> Vec<u8> { trim(s).to_vec() };
    let mycall = trim(&h.mycall13).to_vec();
    let bracket_my = || -> Vec<u8> { fixed(&cat(&[b"<", &mycall, b">"]), 13) };

    if i3 == 0 && n3 == 0 {
        let v = (0..71).fold(0u128, |acc, i| (acc << 1) | (c77[i] == b'1') as u128);
        let txt = text::unpack_text(v);
        let txt = adjustl(&txt);
        if txt[0] == b' ' {
            return Unpacked {
                text: Vec::new(),
                ok: false,
            };
        }
        msg = txt;
    } else if i3 == 0 && n3 == 1 {
        let n28a = rb(1, 28);
        let n28b = rb(29, 28);
        let n10 = rb(57, 10);
        let n5 = rb(67, 5);
        let irpt = 2 * n5 - 30;
        let mut crpt = fmt_i(irpt, 3, 2);
        if irpt >= 0 {
            crpt[0] = b'+';
        }
        let (call_1, s1) = unpack28(n28a, h);
        if !s1 || n28a <= 2 {
            ok = false;
        }
        let (call_2, s2) = unpack28(n28b, h);
        if !s2 || n28b <= 2 {
            ok = false;
        }
        let mut call_3 = h.lookup10(n10);
        if nrx && h.dxcall13_set && h.hashdx10 == n10 {
            call_3 = fixed(&cat(&[b"<", trim(&h.dxcall13), b">"]), 13);
        }
        if !nrx && h.mycall13_set && n10 == h.hashmy10 {
            call_3 = bracket_my();
        }
        msg = cat(&[
            trim(&call_1),
            b" RR73; ",
            trim(&call_2),
            b" ",
            trim(&call_3),
            b" ",
            &crpt,
        ]);
    } else if i3 == 0 && n3 == 2 {
        ok = false;
    } else if i3 == 0 && (n3 == 3 || n3 == 4) {
        let n28a = rb(1, 28);
        let n28b = rb(29, 28);
        let ir = rb(57, 1);
        let intx = rb(58, 4);
        let nclass = rb(62, 3);
        let mut isec = rb(65, 7);
        if !(1..=86).contains(&isec) {
            ok = false;
            isec = 1;
        }
        let (call_1, s1) = unpack28(n28a, h);
        if !s1 || n28a <= 2 {
            ok = false;
        }
        let (call_2, s2) = unpack28(n28b, h);
        if !s2 || n28b <= 2 {
            ok = false;
        }
        let mut ntx = intx + 1;
        if n3 == 4 {
            ntx += 16;
        }
        let mut cntx = fmt_i(ntx, 2, 0);
        cntx.push(b'A' + nclass as u8);
        let sec = &ARRL_SECTIONS[(isec - 1) as usize][..];
        let (c1, c2) = (t(&call_1), t(&call_2));
        msg = match (ir, ntx < 10) {
            (0, true) => cat(&[&c1, b" ", &c2, &cntx, b" ", sec]),
            (1, true) => cat(&[&c1, b" ", &c2, b" R", &cntx, b" ", sec]),
            (0, false) => cat(&[&c1, b" ", &c2, b" ", &cntx, b" ", sec]),
            _ => cat(&[&c1, b" ", &c2, b" R ", &cntx, b" ", sec]),
        };
    } else if i3 == 0 && n3 == 5 {
        let ntel = [rb(1, 23), rb(24, 24), rb(48, 24)];
        let mut s: Vec<u8> = ntel.iter().flat_map(|v| format!("{:06X}", v).into_bytes()).collect();
        for c in s.iter_mut() {
            if *c != b'0' {
                break;
            }
            *c = b' ';
        }
        msg = adjustl(&s);
    } else if i3 == 0 && n3 == 6 {
        let (j48, j49, j50) = (rb(48, 1), rb(49, 1), rb(50, 1));
        let itype = if j50 == 1 {
            2
        } else if j49 == 0 {
            1
        } else if j48 == 0 {
            3
        } else {
            ok = false;
            -1
        };
        let dbm = |v: i64| nint32(v as f32 * 10.0f32 / 3.0f32);
        if itype == 1 {
            let n28 = rb(1, 28);
            let igrid4 = rb(29, 15);
            let idbm = dbm(rb(44, 5));
            if !(0..=60).contains(&idbm) {
                ok = false;
            }
            let (call_1, s1) = unpack28(n28, h);
            if !s1 {
                ok = false;
            }
            let grid4 = match to_grid4(igrid4) {
                Some(g) => g,
                None => {
                    ok = false;
                    b"    ".to_vec()
                }
            };
            let crpt = fmt_i(idbm, 3, 0);
            msg = cat(&[trim(&call_1), b" ", &grid4, b" ", trim(&adjustl(&crpt))]);
            if ok {
                h.save(&call_1);
            }
        } else if itype == 2 {
            let n28 = rb(1, 28);
            let mut npfx = rb(29, 16);
            let idbm = dbm(rb(45, 5));
            if !(0..=60).contains(&idbm) {
                ok = false;
            }
            let (call_1, s1) = unpack28(n28, h);
            if !s1 {
                ok = false;
            }
            let crpt = fmt_i(idbm, 3, 0);
            let a2: &[u8] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ";
            let mut cpfx = vec![b' '; 3];
            let nzzz = 46656;
            if npfx < nzzz {
                for i in (0..3).rev() {
                    cpfx[i] = a2[(npfx % 36) as usize];
                    npfx /= 36;
                    if npfx == 0 {
                        break;
                    }
                }
                let p = trim(&adjustl(&cpfx)).to_vec();
                msg = cat(&[&p, b"/", trim(&call_1), b" ", trim(&adjustl(&crpt))]);
                let call_1a = cat(&[&p, b"/", trim(&call_1)]);
                h.save(&call_1a);
            } else {
                npfx -= nzzz;
                if npfx <= 35 {
                    cpfx[0] = a2[npfx as usize];
                } else if npfx <= 1295 {
                    cpfx[0] = a2[(npfx / 36) as usize];
                    cpfx[1] = a2[(npfx % 36) as usize];
                } else if npfx <= 12959 {
                    cpfx[0] = a2[(npfx / 360) as usize];
                    cpfx[1] = a2[((npfx / 10) % 36) as usize];
                    cpfx[2] = a2[(npfx % 10) as usize];
                } else {
                    return Unpacked {
                        text: Vec::new(),
                        ok: false,
                    };
                }
                let p = trim(&adjustl(&cpfx)).to_vec();
                msg = cat(&[trim(&call_1), b"/", &p, b" ", trim(&adjustl(&crpt))]);
                let call_1a = cat(&[trim(&call_1), b"/", &p]);
                h.save(&call_1a);
            }
        } else if itype == 3 {
            let n22 = rb(1, 22);
            let igrid6 = rb(23, 25);
            let (call_1, s1) = unpack28(n22 + NTOKENS, h);
            if !s1 {
                ok = false;
            }
            let grid6 = match to_grid6(igrid6, 25) {
                Some(g) => g,
                None => {
                    ok = false;
                    b"      ".to_vec()
                }
            };
            msg = cat(&[trim(&call_1), b" ", &grid6]);
        }
    } else if i3 == 0 && n3 > 6 {
        ok = false;
    } else if i3 == 1 || i3 == 2 {
        let n28a = rb(1, 28);
        let ipa = rb(29, 1);
        let n28b = rb(30, 28);
        let ipb = rb(58, 1);
        let ir = rb(59, 1);
        let igrid4 = rb(60, 15);
        let (mut call_1, mut s1) = unpack28(n28a, h);
        if nrx && h.mycall13_set && h.hashmy22 == n28a - NTOKENS {
            call_1 = bracket_my();
            s1 = true;
        }
        if !s1 {
            ok = false;
        }
        let (mut call_2, s2) = unpack28(n28b, h);
        if !s2 {
            ok = false;
        }
        if &call_1[..3] == b"CQ_" {
            call_1[2] = b' ';
        }
        let suffix = |c: &mut Vec<u8>, ip: i64| {
            let i = index1(c, b' ');
            if i >= 4 && ip == 1 {
                let s: &[u8] = if i3 == 1 { b"/R" } else { b"/P" };
                c[i - 1] = s[0];
                if i < c.len() {
                    c[i] = s[1];
                }
            }
            i
        };
        if index1(&call_1, b'<') == 0 {
            let i = suffix(&mut call_1, ipa);
            if i >= 4 {
                h.add_recent(&call_1);
            }
        }
        if index1(&call_2, b'<') == 0 {
            let i = suffix(&mut call_2, ipb);
            if i >= 4 {
                h.add_recent(&call_2);
                h.save(&call_2);
            }
        }
        let (c1, c2) = (t(&call_1), t(&call_2));
        if igrid4 <= MAXGRID4 {
            let grid4 = match to_grid4(igrid4) {
                Some(g) => g,
                None => {
                    ok = false;
                    b"    ".to_vec()
                }
            };
            msg = if ir == 0 {
                cat(&[&c1, b" ", &c2, b" ", &grid4])
            } else {
                cat(&[&c1, b" ", &c2, b" R ", &grid4])
            };
            if fixed(&msg, 3) == b"CQ " && ir == 1 {
                ok = false;
            }
        } else {
            let irpt = igrid4 - MAXGRID4;
            msg = match irpt {
                1 => cat(&[&c1, b" ", &c2]),
                2 => cat(&[&c1, b" ", &c2, b" RRR"]),
                3 => cat(&[&c1, b" ", &c2, b" RR73"]),
                4 => cat(&[&c1, b" ", &c2, b" 73"]),
                _ => {
                    let mut isnr = irpt - 35;
                    if isnr > 50 {
                        isnr -= 101;
                    }
                    let mut crpt = fmt_i(isnr, 3, 2);
                    if crpt[0] == b' ' {
                        crpt[0] = b'+';
                    }
                    if ir == 0 {
                        cat(&[&c1, b" ", &c2, b" ", &crpt])
                    } else {
                        cat(&[&c1, b" ", &c2, b" R", &crpt])
                    }
                }
            };
            if fixed(&msg, 3) == b"CQ " && irpt >= 2 {
                ok = false;
            }
        }
    } else if i3 == 3 {
        let itu = rb(1, 1);
        let n28a = rb(2, 28);
        let n28b = rb(30, 28);
        let ir = rb(58, 1);
        let irpt = rb(59, 3);
        let nexch = rb(62, 13);
        let crpt = vec![b'5', b'0' + (irpt + 2) as u8, b'9'];
        let (call_1, s1) = unpack28(n28a, h);
        if !s1 {
            ok = false;
        }
        let (call_2, s2) = unpack28(n28b, h);
        if !s2 {
            ok = false;
        }
        let imult = if nexch > 8000 { nexch - 8000 } else { 0 };
        let nserial = if nexch < 8000 { nexch } else { 0 };
        let (c1, c2) = (t(&call_1), t(&call_2));
        let tail: Option<Vec<u8>> = if (1..=171).contains(&imult) {
            Some(RTTY_MULTS[(imult - 1) as usize].to_vec())
        } else if (1..=7999).contains(&nserial) {
            Some(fmt_i(nserial, 4, 4))
        } else {
            None
        };
        if let Some(tail) = tail {
            let tu: &[u8] = if itu == 1 { b"TU; " } else { b"" };
            let r: &[u8] = if ir == 1 { b" R " } else { b" " };
            msg = cat(&[tu, &c1, b" ", &c2, r, &crpt, b" ", &tail]);
        }
    } else if i3 == 4 {
        let n12 = rb(1, 12);
        let mut n58 = rb(13, 58);
        let iflip = rb(71, 1);
        let nrpt = rb(72, 2);
        let icq = rb(74, 1);
        const C38: &[u8] = b" 0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ/";
        let mut c11 = vec![b' '; 11];
        for i in (0..11).rev() {
            c11[i] = C38[(n58 % 38) as usize];
            n58 /= 38;
        }
        let call_3 = h.lookup12(n12);
        let (call_1, call_2);
        if iflip == 0 {
            let mut c1 = call_3;
            let c2 = fixed(&adjustl(&c11), 13);
            h.add_recent(&c2);
            h.save(&c2);
            if nrx && h.dxcall13_set && h.mycall13_set && feq(&c2, &h.dxcall13) && n12 == h.hashmy12 {
                c1 = bracket_my();
            }
            if nrx && h.mycall13_set && index(&c1, b"<...>") > 0 && n12 == h.hashmy12 {
                c1 = bracket_my();
            }
            call_1 = c1;
            call_2 = c2;
        } else {
            let c1 = fixed(&adjustl(&c11), 13);
            let mut c2 = call_3;
            h.add_recent(&c1);
            if !nrx && h.mycall13_set && n12 == h.hashmy12 {
                c2 = bracket_my();
            }
            call_1 = c1;
            call_2 = c2;
        }
        let (c1, c2) = (t(&call_1), t(&call_2));
        msg = if icq == 0 {
            match nrpt {
                0 => cat(&[&c1, b" ", &c2]),
                1 => cat(&[&c1, b" ", &c2, b" RRR"]),
                2 => cat(&[&c1, b" ", &c2, b" RR73"]),
                _ => cat(&[&c1, b" ", &c2, b" 73"]),
            }
        } else {
            cat(&[b"CQ ", &c2])
        };
    } else if i3 == 5 {
        let n12 = rb(1, 12);
        let n22 = rb(13, 22);
        let ir = rb(35, 1);
        let irpt = rb(36, 3);
        let iserial = rb(39, 11);
        let igrid6 = rb(50, 25);
        if !(0..=18_662_399).contains(&igrid6) {
            return Unpacked {
                text: Vec::new(),
                ok: false,
            };
        }
        let mut call_1 = h.lookup12(n12);
        // No "is my call set" test here in WSJT-X (see CallHashes).
        if n12 == h.hashmy12 {
            call_1 = bracket_my();
        }
        let call_2 = h.lookup22(n22);
        let nrs = 52 + irpt;
        let cexch = cat(&[&fmt_i(nrs, 2, 0), &fmt_i(iserial, 4, 4)]);
        let grid6 = match to_grid6(igrid6, 24) {
            Some(g) => g,
            None => {
                ok = false;
                b"      ".to_vec()
            }
        };
        let (c1, c2) = (t(&call_1), t(&call_2));
        msg = if ir == 0 {
            cat(&[&c1, b" ", &c2, b" ", &cexch, b" ", &grid6])
        } else {
            cat(&[&c1, b" ", &c2, b" R ", &cexch, b" ", &grid6])
        };
    } else {
        ok = false;
    }
    let msg = fixed(&msg, 37);
    if &msg[..4] == b"CQ <" {
        ok = false;
    }
    Unpacked {
        text: trim(&msg).to_vec(),
        ok,
    }
}

/// What genft8/genft4 do before the channel coding: pack, unpack the
/// result "as sent", and refuse a message WSJT-X would refuse.
#[derive(Debug, Clone)]
pub struct Message {
    /// The message as WSJT-X shows it will be received.
    pub sent: String,
    pub i3: i32,
    pub n3: i32,
    /// None for a message WSJT-X reports as "*** bad message ***".
    pub bits: Option<Bits77>,
    /// See Packed::undefined.
    pub undefined: Option<&'static str>,
}

/// genft8's front half (pack77, then unpack77 with nrx=0) on an already
/// normalised message, with a hash table the caller provides.
pub fn prepare(msg: &[u8], h: &mut CallHashes) -> Result<Message, PackError> {
    let p = pack77(msg, h)?;
    let u = unpack77_c77(&p.c77, false, h);
    let bits = if u.ok { p.bits() } else { None };
    let sent = if bits.is_some() {
        u.text_lossy()
    } else {
        "*** bad message ***".to_string()
    };
    Ok(Message {
        sent,
        i3: p.i3,
        n3: p.n3,
        bits,
        undefined: p.undefined,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    fn enc(m: &str) -> Message {
        let mut h = CallHashes::new();
        prepare(&fmtmsg(m.as_bytes()), &mut h).unwrap()
    }

    #[test]
    fn standard_cq() {
        let m = enc("CQ G4XYZ IO91");
        assert_eq!(m.sent, "CQ G4XYZ IO91");
        assert_eq!((m.i3, m.n3), (1, 0));
        let bits: String = m.bits.unwrap().iter().map(|b| (b'0' + b) as char).collect();
        // ft8code "CQ G4XYZ IO91", WSJT-X 2.7.0.
        assert_eq!(
            bits,
            "00000000000000000000000000100000010010001000001010110100100011111000010011001"
        );
    }

    #[test]
    fn each_type_round_trips() {
        for (m, i3, n3) in [
            ("TNX BOB 73 GL", 0, 0),
            ("K1ABC RR73; W9XYZ <KH1/KH7Z> -12", 0, 1),
            ("K1ABC W9XYZ 6A WI", 0, 3),
            ("W9XYZ K1ABC R 17B EMA", 0, 4),
            ("123456789ABCDEF012", 0, 5),
            ("K1ABC/R W9XYZ/R R FN42", 1, 0),
            ("PA3XYZ/P GM4ABC/P R JO22", 2, 0),
            ("TU; W9XYZ K1ABC R 579 MA", 3, 0),
            ("<W9XYZ> PJ4/K1ABC RR73", 4, 0),
            ("<PA3XYZ> <G4ABC> R 590003 IO91NP", 5, 0),
        ] {
            let e = enc(m);
            assert_eq!((e.i3, e.n3), (i3, n3), "{m}");
            assert_eq!(e.sent, m, "{m}");
        }
    }

    #[test]
    fn wsjtx_own_type5_example_collides() {
        // 77bit.txt's type-5 example: PA3XYZ and G4ABC/P share the 12-bit
        // hash 3211, and the second call stored wins, so ft8code shows
        // the second call twice. Reproduced, not corrected.
        let e = enc("<PA3XYZ> <G4ABC/P> R 590003 IO91NP");
        assert_eq!(e.sent, "<G4ABC/P> <G4ABC/P> R 590003 IO91NP");
        assert_eq!(ihashcall(b"PA3XYZ", 12), ihashcall(b"G4ABC/P", 12));
    }

    #[test]
    fn bad_messages() {
        assert!(enc("K1ABC W9XYZ +999").bits.is_none());
        assert!(enc("CQ K1ABC R FN42").bits.is_none());
    }

    #[test]
    fn fmtmsg_collapses() {
        assert_eq!(trim(&fmtmsg(b"cq  k1abc   fn42")), b"CQ K1ABC FN42");
        assert_eq!(trim(&fmtmsg(b"  cq")), b" CQ");
    }
}
