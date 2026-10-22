// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from JS8Call 2.2.0 varicode.cpp and decodedtext.cpp (and the
// CRC-16/KERMIT, CRC-32/BZIP2 its checksums take from CRCpp), copyright
// (C) 2018-2020 Jordan Sherer KN4CRD, GPL-3.0-or-later.

//! JS8Call's message layer: operator text to 12-character frames for
//! sending, and a received frame back to the text JS8Call shows.
//!
//! A frame is one of five kinds, told apart by its first bits and the
//! "fast data" header bit:
//!
//! - heartbeat / CQ: a callsign, a grid and which CQ ("KN4CRD: @HB
//!   HEARTBEAT EM73", "KN4CRD: @ALLCALL CQ CQ CQ EM73");
//! - compound: a callsign too long or odd for the directed frame
//!   (prefix/suffix calls, groups), with a grid or a command;
//! - directed: from, to, command and a number ("KN4CRD: J1Y SNR -05");
//! - data: free text, Huffman coded or JSC compressed (Normal); the
//!   faster speeds flag data in the header and always use JSC.
//!
//! A transmission is a run of frames whose first and last carry the
//! FIRST and LAST header bits; JS8Call shows the frames of one run joined
//! together, which is left to the caller.
//!
//! Decoding is exact by construction: every frame has one reading. For
//! encoding, JS8Call parses the operator's text with regular expressions;
//! they are copied here verbatim and run with fancy-regex, a backtracking
//! engine like the PCRE inside Qt, so that the same text splits into the
//! same frames. (Its quirks come along: buffered commands such as MSG get
//! a CRC-16 of the rest of the line appended, a lower-case letter passes
//! the Huffman check but is then skipped, and so on.)

use super::jsc;
use super::Submode;
use fancy_regex::Regex;
use std::sync::OnceLock;

/// The base-41 alphabet of checksums (varicode.cpp `alphabet`).
const ALPHABET41: &[u8; 41] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ+-./?";
/// The frame alphabet with genjs8's three unusable extras (`alphabet72`).
const ALPHABET72: &[u8; 67] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-+/?.";
/// Callsign and grid characters (`alphanumeric`).
const ALNUM: &[u8; 39] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ /@";

const NBASECALL: u32 = 37 * 36 * 10 * 27 * 27 * 27;
const NBASEGRID: u16 = 180 * 180;
const NUSERGRID: u16 = NBASEGRID + 10;
const NMAXGRID: u16 = (1 << 15) - 1;

/// Frame types (varicode.h FrameType).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FrameType {
    Heartbeat = 0,
    Compound = 1,
    CompoundDirected = 2,
    Directed = 3,
    Data = 4,
    /// Not a frame JS8Call can read; its text is the raw frame.
    Unknown = 255,
}

impl FrameType {
    pub fn name(self) -> &'static str {
        match self {
            FrameType::Heartbeat => "heartbeat",
            FrameType::Compound => "compound",
            FrameType::CompoundDirected => "compound_directed",
            FrameType::Directed => "directed",
            FrameType::Data => "data",
            FrameType::Unknown => "unknown",
        }
    }
}

/// directed_cmds, in QMap (key) order: what QMap::key(value) searches.
const DIRECTED_CMDS: &[(&str, i32)] = &[
    (" ", 31),
    ("  ", 31),
    (" 73", 28),
    (" ACK", 14),
    (" AGN?", 30),
    (" CMD", 24),
    (" CQ", -1),
    (" DIT DIT", 1),
    (" FB", 18),
    (" GRID", 15),
    (" GRID?", 4),
    (" HB", -1),
    (" HEARING", 8),
    (" HEARING?", 3),
    (" HEARTBEAT", -1),
    (" HEARTBEAT SNR", 29),
    (" HW CPY?", 19),
    (" INFO", 17),
    (" INFO?", 16),
    (" MSG", 9),
    (" MSG TO:", 10),
    (" NACK", 2),
    (" NO", 26),
    (" QSL", 23),
    (" QSL?", 22),
    (" QUERY", 11),
    (" QUERY CALL", 13),
    (" QUERY MSGS", 12),
    (" QUERY MSGS?", 12),
    (" RR", 21),
    (" SK", 20),
    (" SNR", 25),
    (" SNR?", 0),
    (" STATUS", 7),
    (" STATUS?", 6),
    (" YES", 27),
    (">", 5),
    ("?", 0),
];
const BUFFERED_CMDS: &[i32] = &[5, 9, 10, 11, 12, 13, 15, 24];
const SNR_CMDS: &[i32] = &[25, 29];
const CHECKSUM_CMDS: &[(i32, i32)] = &[(5, 16), (9, 16), (10, 16), (11, 16), (12, 16), (13, 16), (15, 0), (24, 16)];

fn cmd_value(key: &str) -> Option<i32> {
    DIRECTED_CMDS.iter().find(|(k, _)| *k == key).map(|&(_, v)| v)
}

fn cmd_key(value: i32) -> &'static str {
    DIRECTED_CMDS.iter().find(|&&(_, v)| v == value).map(|&(k, _)| k).unwrap_or("")
}

/// Group and placeholder "callsigns" with values past every real one.
const BASECALLS: &[&str] = &[
    "<....>", "@ALLCALL", "@JS8NET", "@DX/NA", "@DX/SA", "@DX/EU", "@DX/AS", "@DX/AF", "@DX/OC", "@DX/AN",
    "@REGION/1", "@REGION/2", "@REGION/3", "@GROUP/0", "@GROUP/1", "@GROUP/2", "@GROUP/3", "@GROUP/4", "@GROUP/5",
    "@GROUP/6", "@GROUP/7", "@GROUP/8", "@GROUP/9", "@COMMAND", "@CONTROL", "@NET", "@NTS", "@RESERVE/0",
    "@RESERVE/1", "@RESERVE/2", "@RESERVE/3", "@RESERVE/4", "@APRSIS", "@RAGCHEW", "@JS8", "@EMCOMM", "@ARES",
    "@MARS", "@AMRRON", "@RACES", "@RAYNET", "@RADAR", "@SKYWARN", "@CQ", "@HB", "@QSO", "@QSOPARTY", "@CONTEST",
    "@FIELDDAY", "@SOTA", "@IOTA", "@POTA", "@QRP", "@QRO",
];

fn basecall_value(name: &str) -> Option<u32> {
    BASECALLS.iter().position(|&b| b == name).map(|i| NBASECALL + 1 + i as u32)
}

fn basecall_name(value: u32) -> Option<&'static str> {
    value.checked_sub(NBASECALL + 1).and_then(|i| BASECALLS.get(i as usize)).copied()
}

const CQS: &[&str] = &["CQ CQ CQ", "CQ DX", "CQ QRP", "CQ CONTEST", "CQ FIELD", "CQ FD", "CQ CQ", "CQ"];

/// The Huffman table for Normal's data frames (varicode.cpp hufftable).
const HUFF: &[(&str, &str)] = &[
    (" ", "01"), ("E", "100"), ("T", "1101"), ("A", "0011"), ("O", "11111"), ("I", "11100"), ("N", "10111"),
    ("S", "10100"), ("H", "00011"), ("R", "00000"), ("D", "111011"), ("L", "110011"), ("C", "110001"),
    ("U", "101101"), ("M", "101011"), ("W", "001011"), ("F", "001001"), ("G", "000101"), ("Y", "000011"),
    ("P", "1111011"), ("B", "1111001"), (".", "1110100"), ("V", "1100101"), ("K", "1100100"), ("-", "1100001"),
    ("+", "1100000"), ("?", "1011001"), ("!", "1011000"), ("\"", "1010101"), ("X", "1010100"), ("0", "0010101"),
    ("J", "0010100"), ("1", "0010001"), ("Q", "0010000"), ("2", "0001001"), ("Z", "0001000"), ("3", "0000101"),
    ("5", "0000100"), ("4", "11110101"), ("9", "11110100"), ("8", "11110001"), ("6", "11110000"), ("7", "11101011"),
    ("/", "11101010"),
];

// ------------------------------------------------------------ bits

fn bits_to_int(b: &[u8]) -> u64 {
    b.iter().fold(0u64, |a, &x| (a << 1) | x as u64)
}

use jsc::bits_of as int_to_bits;

fn str_bits(s: &str) -> Vec<u8> {
    s.bytes().map(|c| (c == b'1') as u8).collect()
}

/// QVector::mid(pos, len) as Qt 5 has it: a negative or too-long length
/// means "to the end".
fn qmid(v: &[u8], pos: usize, len: i64) -> Vec<u8> {
    if pos > v.len() {
        return vec![];
    }
    let rest = v.len() - pos;
    let n = if len < 0 || len as usize > rest { rest } else { len as usize };
    v[pos..pos + n].to_vec()
}

fn last_zero(v: &[u8]) -> i64 {
    v.iter().rposition(|&b| b == 0).map_or(-1, |p| p as i64)
}

fn idx72(c: u8) -> u8 {
    ALPHABET72.iter().position(|&a| a == c).map_or(255, |p| p as u8)
}

/// unpack72bits: the first 64 bits and the last 8.
fn unpack72bits(text: &[u8]) -> (u64, u8) {
    let mut value: u64 = 0;
    for i in 0..10 {
        value |= (idx72(text[i]) as u64) << (58 - 6 * i);
    }
    let rem_high = idx72(text[10]);
    value |= (rem_high >> 2) as u64;
    let rem_low = idx72(text[11]);
    let rem = ((rem_high & 3) << 6) | rem_low;
    (value, rem)
}

fn pack72bits(value: u64, rem: u8) -> String {
    let mut packed = [b'0'; 12];
    let rem_high = (((value & 0xF) << 2) as u8) | (rem >> 6);
    let rem_low = rem & 0x3F;
    let mut v = value >> 4;
    packed[11] = ALPHABET72[rem_low as usize];
    packed[10] = ALPHABET72[rem_high as usize];
    for i in 0..10 {
        packed[9 - i] = ALPHABET72[(v & 0x3F) as usize];
        v >>= 6;
    }
    String::from_utf8(packed.to_vec()).unwrap()
}

/// The 72 frame bits of a frame.
fn frame_bits72(text: &[u8]) -> Vec<u8> {
    let (value, rem) = unpack72bits(text);
    let mut b = int_to_bits(value, 64);
    b.extend(int_to_bits(rem as u64, 8));
    b
}

fn pack_bits72(bits: &[u8]) -> String {
    pack72bits(bits_to_int(&bits[..64]), bits_to_int(&bits[64..72]) as u8)
}

// ------------------------------------------------------ fields

fn alnum_at(i: u64) -> char {
    ALNUM[i as usize] as char
}

fn alnum_index(c: char) -> i64 {
    ALNUM.iter().position(|&a| a as char == c).map_or(-1, |p| p as i64)
}

fn unpack_alnum50(mut packed: u64) -> String {
    let mut w = [' '; 11];
    for &(pos, base) in &[(10, 38), (9, 38), (8, 38), (7, 2), (6, 38), (5, 38), (4, 38), (3, 2), (2, 38), (1, 38), (0, 39)] {
        let t = packed % base;
        w[pos] = if base == 2 { if t == 1 { '/' } else { ' ' } } else { alnum_at(t) };
        packed /= base;
    }
    w.iter().filter(|&&c| c != ' ').collect()
}

fn pack_alnum50(value: &str) -> u64 {
    let mut word: Vec<char> = value.chars().filter(|c| c.is_ascii_uppercase() || c.is_ascii_digit() || " /@".contains(*c)).collect();
    if word.len() > 3 && word[3] != '/' {
        word.insert(3, ' ');
    }
    if word.len() > 7 && word[7] != '/' {
        word.insert(7, ' ');
    }
    while word.len() < 11 {
        word.push(' ');
    }
    let ix = |i: usize| alnum_index(word[i]) as u64;
    let sl = |i: usize| (word[i] == '/') as u64;
    let m = |k: &[u64]| k.iter().product::<u64>();
    m(&[38, 38, 38, 2, 38, 38, 38, 2, 38, 38]) * ix(0)
        + m(&[38, 38, 38, 2, 38, 38, 38, 2, 38]) * ix(1)
        + m(&[38, 38, 38, 2, 38, 38, 38, 2]) * ix(2)
        + m(&[38, 38, 38, 2, 38, 38, 38]) * sl(3)
        + m(&[38, 38, 38, 2, 38, 38]) * ix(4)
        + m(&[38, 38, 38, 2, 38]) * ix(5)
        + m(&[38, 38, 38, 2]) * ix(6)
        + m(&[38, 38, 38]) * sl(7)
        + m(&[38, 38]) * ix(8)
        + 38 * ix(9)
        + ix(10)
}

fn unpack_callsign(value: u32, portable: bool) -> String {
    if let Some(b) = basecall_name(value) {
        return b.to_string();
    }
    let mut v = value as u64;
    let mut w = [' '; 6];
    for (pos, base, off) in [(5, 27, 10), (4, 27, 10), (3, 27, 10), (2, 10, 0), (1, 36, 0)] {
        w[pos] = alnum_at(v % base + off);
        v /= base;
    }
    w[0] = alnum_at(v.min(38));
    let mut call: String = w.iter().collect();
    if call.starts_with("3D0") {
        call = format!("3DA0{}", &call[3..]);
    }
    let b: Vec<char> = call.chars().collect();
    if b[0] == 'Q' && b[1].is_ascii_uppercase() {
        call = format!("3X{}", &call[1..]);
    }
    if portable {
        call = format!("{}/P", call.trim());
    }
    call.trim().to_string()
}

fn pack_callsign(value: &str) -> (u32, bool) {
    let mut call = value.to_uppercase().trim().to_string();
    if let Some(v) = basecall_value(&call) {
        return (v, false);
    }
    let mut portable = false;
    if call.ends_with("/P") {
        call.truncate(call.len() - 2);
        portable = true;
    }
    if let Some(rest) = call.strip_prefix("3DA0") {
        call = format!("3D0{rest}");
    }
    if call.starts_with("3X") && call.chars().nth(2).is_some_and(|c| c.is_ascii_uppercase()) {
        call = format!("Q{}", &call[2..]);
    }
    let slen = call.chars().count();
    if !(2..=6).contains(&slen) {
        return (0, portable);
    }
    let mut perms = vec![call.clone()];
    match slen {
        2 => perms.push(format!(" {call}   ")),
        3 => {
            perms.push(format!(" {call}  "));
            perms.push(format!("{call}   "));
        }
        4 => {
            perms.push(format!(" {call} "));
            perms.push(format!("{call}  "));
        }
        5 => {
            perms.push(format!(" {call}"));
            perms.push(format!("{call} "));
        }
        _ => {}
    }
    let mut matched = String::new();
    for p in &perms {
        if let Ok(Some(m)) = re(&PACK_CALLSIGN).find(p) {
            matched = m.as_str().to_string();
        }
    }
    if matched.chars().count() < 6 {
        return (0, portable);
    }
    let c: Vec<char> = matched.chars().collect();
    let ix = |i: usize| alnum_index(c[i]);
    let mut packed: i64 = ix(0);
    packed = 36 * packed + ix(1);
    packed = 10 * packed + ix(2);
    packed = 27 * packed + ix(3) - 10;
    packed = 27 * packed + ix(4) - 10;
    packed = 27 * packed + ix(5) - 10;
    (packed as u32, portable)
}

fn deg2grid(mut dlong: f32, dlat: f32) -> String {
    if dlong < -180.0 {
        dlong += 360.0;
    }
    if dlong > 180.0 {
        dlong -= 360.0;
    }
    let nlong = (60.0 * (180.0 - dlong as f64) / 5.0) as i32;
    let n1 = nlong / 240;
    let n2 = (nlong - 240 * n1) / 24;
    let nlat = (60.0 * (dlat as f64 + 90.0) / 2.5) as i32;
    let m1 = nlat / 240;
    let m2 = (nlat - 240 * m1) / 24;
    // Only the four-character grid is ever used.
    format!("{}{}{}{}", (b'A' as i32 + n1) as u8 as char, (b'A' as i32 + m1) as u8 as char, n2, m2)
}

fn grid2deg(grid: &str) -> (f32, f32) {
    let g: Vec<u8> = format!("{}mm", &grid[..4]).to_uppercase().into_bytes();
    let (g4, g5) = (b'm', b'm');
    let nlong = 180 - 20 * (g[0] as i32 - b'A' as i32);
    let n20d = 2 * (g[2] as i32 - b'0' as i32);
    let xminlong = 5.0f32 * ((g4 as i32 - b'a' as i32) as f32 + 0.5);
    let dlong = nlong as f32 - n20d as f32 - xminlong / 60.0;
    let nlat = -90 + 10 * (g[1] as i32 - b'A' as i32) + g[3] as i32 - b'0' as i32;
    let xminlat = 2.5f32 * ((g5 as i32 - b'a' as i32) as f32 + 0.5);
    let dlat = nlat as f32 + xminlat / 60.0;
    (dlong, dlat)
}

fn pack_grid(value: &str) -> u16 {
    let g = value.trim();
    if g.chars().count() < 4 {
        return NMAXGRID;
    }
    let (dlong, dlat) = grid2deg(g);
    let ilong = dlong as i32;
    let ilat = (dlat + 90.0) as i32;
    (((ilong + 180) / 2) * 180 + ilat) as u16
}

fn unpack_grid(value: u16) -> String {
    if value > NBASEGRID {
        return String::new();
    }
    let dlat = (value % 180) as f32 - 90.0;
    let dlong = ((value / 180) * 2) as f32 - 180.0 + 2.0;
    deg2grid(dlong, dlat)
}

/// Varicode::formatSNR: "+05", "-12"; nothing outside +-60.
pub fn format_snr(snr: i32) -> String {
    if !(-60..=60).contains(&snr) {
        return String::new();
    }
    if snr >= 0 {
        format!("+{snr:02}")
    } else {
        format!("-{:02}", -snr)
    }
}

fn pack_num(num: &str) -> Option<u8> {
    if num.is_empty() {
        return None;
    }
    let n: i32 = num.parse().ok()?;
    Some((n.clamp(-30, 31) + 31) as u8)
}

fn is_snr_command(cmd: &str) -> bool {
    cmd_value(cmd).is_some_and(|v| SNR_CMDS.contains(&v))
}

fn pack_cmd(cmd: i32, num: u8) -> u8 {
    let s = cmd_key(cmd);
    if is_snr_command(s) {
        let mut v = ((1u8 << 1) | (s == " HEARTBEAT SNR") as u8) << 6;
        v = v.wrapping_add(num & 0x3F);
        v
    } else {
        (cmd & 0x7F) as u8
    }
}

fn unpack_cmd(value: u8) -> (i32, u8) {
    if value & 0x80 != 0 {
        let num = value & 0x3F;
        let cmd = if value & 0x40 != 0 { 29 } else { 25 };
        (cmd, num)
    } else {
        ((value & 0x7F) as i32, 0)
    }
}

// --------------------------------------------------- unpacking

/// unpackCompoundFrame: (callsign, type, num, bits3).
fn unpack_compound_frame(text: &[u8]) -> Option<(String, u8, u16, u8)> {
    if text.len() < 12 || text.contains(&b' ') {
        return None;
    }
    let (value, packed8) = unpack72bits(text);
    let bits = int_to_bits(value, 64);
    let packed5 = packed8 >> 3;
    let packed3 = packed8 & 7;
    let flag = bits_to_int(&bits[0..3]) as u8;
    if flag == FrameType::Data as u8 || flag == FrameType::Directed as u8 {
        return None;
    }
    let call = unpack_alnum50(bits_to_int(&bits[3..53]));
    let packed11 = bits_to_int(&bits[53..64]) as u16;
    let num = (packed11 << 5) | packed5 as u16;
    Some((call, flag, num, packed3))
}

fn huff_decode(bits: &[u8]) -> String {
    let mut text = String::new();
    let mut rest: &[u8] = bits;
    // Prefix-free, so trying each code in turn at the current position is
    // the same as JS8Call's "naive" loop over the table.
    'outer: while !rest.is_empty() {
        for &(ch, code) in HUFF {
            let c = str_bits(code);
            if rest.starts_with(&c) {
                text.push_str(ch);
                rest = &rest[c.len()..];
                continue 'outer;
            }
        }
        break;
    }
    text
}

fn unpack_data(text: &[u8]) -> String {
    if text.len() < 12 || text.contains(&b' ') {
        return String::new();
    }
    let bits = frame_bits72(text);
    if bits[0] == 0 {
        return String::new();
    }
    let bits = &bits[1..];
    let compressed = bits[0] == 1;
    let n = last_zero(bits);
    let payload = qmid(bits, 1, n - 1);
    if compressed {
        jsc::decompress(&payload)
    } else {
        huff_decode(&payload)
    }
}

fn unpack_fast_data(text: &[u8]) -> String {
    if text.len() < 12 || text.contains(&b' ') {
        return String::new();
    }
    let bits = frame_bits72(text);
    let n = last_zero(&bits);
    jsc::decompress(&qmid(&bits, 0, n))
}

/// A received frame as JS8Call shows it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Unpacked {
    /// DecodedText's message: "KN4CRD: J1Y SNR -05 ", "HELLO WORLD", or
    /// the frame itself when it is none of JS8Call's kinds.
    pub text: String,
    pub kind: FrameType,
    /// The sending station, when the frame names one.
    pub from: Option<String>,
    /// Who a directed frame is for.
    pub to: Option<String>,
    /// A heartbeat's or compound frame's grid, when it has one.
    pub grid: Option<String>,
    pub first: bool,
    pub last: bool,
}

/// DecodedText::tryUnpack for a frame and its header bits.
pub fn unpack_frame(frame: &str, i3bit: u8) -> Unpacked {
    let t = frame.as_bytes();
    let mut u = Unpacked {
        text: frame.to_string(),
        kind: FrameType::Unknown,
        from: None,
        to: None,
        grid: None,
        first: i3bit & super::FRAME_FIRST != 0,
        last: i3bit & super::FRAME_LAST != 0,
    };
    let data_flag = i3bit & super::FRAME_DATA != 0;
    if t.len() < 12 || frame.contains(' ') {
        return u;
    }
    if data_flag {
        let d = unpack_fast_data(t);
        if !d.is_empty() {
            u.text = d;
            u.kind = FrameType::Data;
        }
        return u;
    }
    let d = unpack_data(t);
    if !d.is_empty() {
        u.text = d;
        u.kind = FrameType::Data;
        return u;
    }
    if let Some((call, ty, num, bits3)) = unpack_compound_frame(t) {
        if ty == FrameType::Heartbeat as u8 {
            let grid = unpack_grid(num & 0x7FFF);
            let is_alt = num & 0x8000 != 0;
            u.text = if is_alt {
                format!("{call}: @ALLCALL {} {grid} ", CQS[bits3 as usize])
            } else {
                // hbString: every value is "HB" since 2.2.
                format!("{call}: @HB HEARTBEAT {grid} ")
            };
            u.kind = FrameType::Heartbeat;
            u.from = Some(call);
            u.grid = (!grid.is_empty()).then_some(grid);
            return u;
        }
        if ty == FrameType::Compound as u8 || ty == FrameType::CompoundDirected as u8 {
            let mut extra: Vec<String> = Vec::new();
            if num <= NBASEGRID {
                let g = unpack_grid(num);
                extra.push(format!(" {g}"));
                u.grid = (!g.is_empty()).then_some(g);
            } else if (NUSERGRID..NMAXGRID).contains(&num) {
                let (cmd, n) = unpack_cmd((num - NUSERGRID) as u8);
                let s = cmd_key(cmd);
                extra.push(s.to_string());
                if is_snr_command(s) {
                    extra.push(format_snr(n as i32 - 31));
                }
            }
            if ty == FrameType::Compound as u8 {
                u.text = format!("{call}: ");
                u.kind = FrameType::Compound;
            } else {
                u.text = format!("{call}{} ", extra.join(" "));
                u.kind = FrameType::CompoundDirected;
            }
            u.from = Some(call);
            return u;
        }
    }
    // tryUnpackDirected.
    let (value, extra) = unpack72bits(t);
    let bits = int_to_bits(value, 64);
    if bits_to_int(&bits[0..3]) as u8 == FrameType::Directed as u8 {
        let from = unpack_callsign(bits_to_int(&bits[3..31]) as u32, (extra >> 7) & 1 == 1);
        let to = unpack_callsign(bits_to_int(&bits[31..59]) as u32, (extra >> 6) & 1 == 1);
        let cmd = cmd_key(bits_to_int(&bits[59..64]) as i32 % 32);
        let num = extra % 64;
        u.text = if num != 0 {
            let n = if is_snr_command(cmd) { format_snr(num as i32 - 31) } else { format!("{}", num as i32 - 31) };
            format!("{from}: {to}{cmd} {n} ")
        } else {
            format!("{from}: {to}{cmd} ")
        };
        u.kind = FrameType::Directed;
        u.from = Some(from);
        u.to = Some(to);
    }
    u
}

// ----------------------------------------------------- packing

/// JS8Call's patterns, verbatim from varicode.cpp.
const CALLSIGN_PATTERN: &str = r"(?<callsign>[@]?[A-Z0-9/]+)";
const OPTIONAL_CMD_PATTERN: &str = r"(?<cmd>\s?(?:AGN[?]|QSL[?]|HW CPY[?]|MSG TO[:]|SNR[?]|INFO[?]|GRID[?]|STATUS[?]|QUERY MSGS[?]|HEARING[?]|(?:(?:STATUS|HEARING|QUERY CALL|QUERY MSGS|QUERY|CMD|MSG|NACK|ACK|73|YES|NO|HEARTBEAT SNR|SNR|QSL|RR|SK|FB|INFO|GRID|DIT DIT)(?=[ ]|$))|[?> ]))?";
const OPTIONAL_GRID_PATTERN: &str = r"(?<grid>\s?[A-R]{2}[0-9]{2})?";
const OPTIONAL_NUM_PATTERN: &str = r"(?<num>(?<=SNR)\s?[-+]?(?:3[01]|[0-2]?[0-9]))?";
const GRID_PATTERN: &str = r"(?<grid>[A-X]{2}[0-9]{2}(?:[A-X]{2}(?:[0-9]{2})?)*)+";
const BASE_CALLSIGN_PATTERN: &str =
    r"(?<callsign>\b(?<base>([0-9A-Z])?([0-9A-Z])([0-9])([A-Z])?([A-Z])?([A-Z])?)(?<portable>[/][P])?\b)";
const COMPOUND_CALLSIGN_PATTERN: &str = r"(?<callsign>(?:[@]?|\b)(?<extended>[A-Z0-9\/@][A-Z0-9\/]{0,2}[\/]?[A-Z0-9\/]{0,3}[\/]?[A-Z0-9\/]{0,3})\b)";
const PACK_CALLSIGN_PATTERN: &str = r"([0-9A-Z ])([0-9A-Z])([0-9])([A-Z ])([A-Z ])([A-Z ])";
const HEARTBEAT_PATTERN: &str = r"^\s*(?<callsign>[@](?:ALLCALL|HB)\s+)?(?<type>CQ CQ CQ|CQ DX|CQ QRP|CQ CONTEST|CQ FIELD|CQ FD|CQ CQ|CQ|HB|HEARTBEAT(?!\s+SNR))(?:\s(?<grid>[A-R]{2}[0-9]{2}))?\b";
const CALLSIGN_CHARS_PATTERN: &str = "[0-9][A-Z]|[A-Z][0-9]";

struct Lazy(OnceLock<Regex>, fn() -> String);

impl Lazy {
    const fn new(f: fn() -> String) -> Self {
        Lazy(OnceLock::new(), f)
    }
}

fn re(l: &'static Lazy) -> &'static Regex {
    l.0.get_or_init(|| Regex::new(&(l.1)()).expect("JS8Call's pattern compiles"))
}

static DIRECTED: Lazy = Lazy::new(|| format!("^{CALLSIGN_PATTERN}{OPTIONAL_CMD_PATTERN}{OPTIONAL_NUM_PATTERN}"));
static HEARTBEAT: Lazy = Lazy::new(|| HEARTBEAT_PATTERN.to_string());
static COMPOUND: Lazy = Lazy::new(|| {
    format!("^\\s*[`]{CALLSIGN_PATTERN}(?<extra>{OPTIONAL_GRID_PATTERN}{OPTIONAL_CMD_PATTERN}{OPTIONAL_NUM_PATTERN})")
});
static GRID: Lazy = Lazy::new(|| GRID_PATTERN.to_string());
static BASE_CALLSIGN: Lazy = Lazy::new(|| BASE_CALLSIGN_PATTERN.to_string());
static COMPOUND_CALLSIGN: Lazy = Lazy::new(|| COMPOUND_CALLSIGN_PATTERN.to_string());
static COMPOUND_CALLSIGN_ANCHORED: Lazy = Lazy::new(|| format!("^{COMPOUND_CALLSIGN_PATTERN}"));
static PACK_CALLSIGN: Lazy = Lazy::new(|| PACK_CALLSIGN_PATTERN.to_string());
static CALLSIGN_CHARS: Lazy = Lazy::new(|| CALLSIGN_CHARS_PATTERN.to_string());

fn has_match(l: &'static Lazy, s: &str) -> bool {
    matches!(re(l).is_match(s), Ok(true))
}

/// The length (in characters) of the first match of `l` in `s`, if any.
fn first_match_len(l: &'static Lazy, s: &str) -> Option<usize> {
    match re(l).find(s) {
        Ok(Some(m)) => Some(m.as_str().chars().count()),
        _ => None,
    }
}

fn is_valid_compound_callsign(call: &str) -> bool {
    if call.replace('/', "").chars().count() > 9 {
        return false;
    }
    if let Some(i) = call.find('/') {
        return basecall_value(&call[..i]).is_none();
    }
    if call.starts_with('@') {
        return true;
    }
    call.chars().count() > 2 && has_match(&CALLSIGN_CHARS, call)
}

/// Varicode::isValidCallsign: (valid, compound).
pub fn is_valid_callsign(call: &str) -> (bool, bool) {
    if basecall_value(call).is_some() {
        return (true, false);
    }
    let n = call.chars().count();
    if first_match_len(&BASE_CALLSIGN, call) == Some(n) {
        return (n > 2 && has_match(&CALLSIGN_CHARS, call), false);
    }
    if let Ok(Some(m)) = re(&COMPOUND_CALLSIGN_ANCHORED).find(call) {
        if m.as_str().chars().count() == n {
            let v = is_valid_compound_callsign(m.as_str());
            return (v, v);
        }
    }
    (false, false)
}

/// Varicode::isCompoundCallsign.
pub fn is_compound_callsign(call: &str) -> bool {
    if basecall_value(call).is_some() && !call.starts_with('@') {
        return false;
    }
    let n = call.chars().count();
    if first_match_len(&BASE_CALLSIGN, call) == Some(n) {
        return false;
    }
    match re(&COMPOUND_CALLSIGN_ANCHORED).find(call) {
        Ok(Some(m)) if m.as_str().chars().count() == n => is_valid_compound_callsign(m.as_str()),
        _ => false,
    }
}

/// Varicode::parseCallsigns.
fn parse_callsigns(input: &str) -> Vec<String> {
    let mut out = Vec::new();
    for m in re(&COMPOUND_CALLSIGN).captures_iter(input).flatten() {
        let Some(c) = m.name("callsign") else { continue };
        let call = c.as_str().trim();
        if !is_valid_callsign(call).0 || has_match(&GRID, call) {
            continue;
        }
        out.push(call.to_string());
    }
    out
}

fn pack_compound_frame(callsign: &str, ty: u8, num: u16, bits3: u8) -> String {
    if ty == FrameType::Data as u8 || ty == FrameType::Directed as u8 {
        return String::new();
    }
    let packed_call = pack_alnum50(callsign);
    if packed_call == 0 {
        return String::new();
    }
    let packed11 = (num & (((1 << 11) - 1) << 5)) >> 5;
    let packed5 = (num & 0x1F) as u8;
    let packed8 = (packed5 << 3) | bits3;
    let mut bits = int_to_bits(ty as u64, 3);
    bits.extend(int_to_bits(packed_call, 50));
    bits.extend(int_to_bits(packed11 as u64, 11));
    pack72bits(bits_to_int(&bits), packed8)
}

/// Characters of `s` from character `n` on (QString::mid).
fn mid(s: &str, n: usize) -> String {
    s.chars().skip(n).collect()
}

fn lstrip(s: &str) -> String {
    s.trim_start().to_string()
}

fn pack_heartbeat_message(text: &str, callsign: &str) -> (String, usize) {
    let Ok(Some(caps)) = re(&HEARTBEAT).captures(text) else { return (String::new(), 0) };
    let extra = caps.name("grid").map_or("", |m| m.as_str());
    let ty = caps.name("type").map_or("", |m| m.as_str());
    let is_alt = ty.starts_with("CQ");
    if callsign.is_empty() {
        return (String::new(), 0);
    }
    let mut packed_extra = NMAXGRID;
    if extra.chars().count() == 4 && has_match(&GRID, extra) {
        packed_extra = pack_grid(extra);
    }
    // hbs.key(type, 0): every hbs value is "HB", whose first key is 0.
    let mut number = 0u8;
    if is_alt {
        packed_extra |= 1 << 15;
        number = CQS.iter().position(|&c| c == ty).unwrap_or(0) as u8;
    }
    let frame = pack_compound_frame(callsign, FrameType::Heartbeat as u8, packed_extra, number);
    if frame.is_empty() {
        return (frame, 0);
    }
    let n = caps.get(0).unwrap().as_str().chars().count();
    (frame, n)
}

fn pack_compound_message(text: &str) -> (String, usize) {
    let Ok(Some(caps)) = re(&COMPOUND).captures(text) else { return (String::new(), 0) };
    let g = |k: &str| caps.name(k).map_or(String::new(), |m| m.as_str().to_string());
    let (callsign, grid, cmd, num) = (g("callsign"), g("grid"), g("cmd"), g("num").trim().to_string());
    if callsign.is_empty() {
        return (String::new(), 0);
    }
    let mut ty = FrameType::Compound as u8;
    let mut extra = NMAXGRID;
    if let Some(v) = (!cmd.is_empty()).then(|| cmd_value(&cmd)).flatten() {
        let inum = pack_num(&num).unwrap_or(0);
        extra = NUSERGRID + pack_cmd(v, inum) as u16;
        ty = FrameType::CompoundDirected as u8;
    } else if !grid.is_empty() {
        extra = pack_grid(&grid);
    }
    let frame = pack_compound_frame(&callsign, ty, extra, 0);
    (frame, caps.get(0).unwrap().as_str().chars().count())
}

/// packDirectedMessage's results: the frame and characters used, then
/// what it found on the way (set even when it then gave up, as there).
#[derive(Default)]
struct Directed {
    frame: String,
    n: usize,
    to: String,
    to_compound: bool,
    cmd: String,
    num: String,
}

fn pack_directed_message(text: &str, mycall: &str) -> Directed {
    let mut d = Directed::default();
    let Ok(Some(caps)) = re(&DIRECTED).captures(text) else { return d };
    let mut from = mycall.to_string();
    if is_compound_callsign(&from) {
        from = "<....>".into();
    }
    let g = |k: &str| caps.name(k).map_or(String::new(), |m| m.as_str().to_string());
    let (mut to, cmd, num) = (g("callsign"), g("cmd"), g("num"));
    if cmd.is_empty() {
        return d;
    }
    let (valid, to_compound) = if to != mycall { is_valid_callsign(&to) } else { (false, false) };
    if !valid {
        return d;
    }
    d.to = to.clone();
    d.to_compound = to_compound;
    if to_compound {
        to = "<....>".into();
    }
    if cmd_value(&cmd).is_none() && cmd_value(cmd.trim()).is_none() {
        return d;
    }
    let inum = pack_num(num.trim());
    if inum.is_some() {
        d.num = num.clone();
    }
    let (packed_from, portable_from) = pack_callsign(&from);
    let (packed_to, portable_to) = pack_callsign(&to);
    if packed_from == 0 || packed_to == 0 {
        return d;
    }
    let mut cmd_out = String::new();
    let mut packed_cmd = 0i32;
    if let Some(v) = cmd_value(&cmd) {
        cmd_out = cmd.clone();
        packed_cmd = v;
    }
    if let Some(v) = cmd_value(cmd.trim()) {
        cmd_out = cmd.trim().to_string();
        packed_cmd = v;
    }
    let packed_extra = ((portable_from as u8) << 7) + ((portable_to as u8) << 6) + inum.unwrap_or(0);
    let mut bits = int_to_bits(FrameType::Directed as u64, 3);
    bits.extend(int_to_bits(packed_from as u64, 28));
    bits.extend(int_to_bits(packed_to as u64, 28));
    bits.extend(int_to_bits(packed_cmd.rem_euclid(32) as u64, 5));
    d.cmd = cmd_out;
    d.n = caps.get(0).unwrap().as_str().chars().count();
    d.frame = pack72bits(bits_to_int(&bits), packed_extra);
    d
}

fn pad_frame(mut bits: Vec<u8>) -> String {
    let pad = 72 - bits.len();
    for i in 0..pad {
        bits.push((i != 0) as u8);
    }
    pack_bits72(&bits)
}

fn pack_huff_message(input: &str, prefix: &[u8]) -> (String, usize) {
    if !input.chars().all(|c| HUFF.iter().any(|(k, _)| k.chars().next() == c.to_uppercase().next())) {
        return (String::new(), 0);
    }
    let mut bits = prefix.to_vec();
    let mut n = 0;
    // huffEncode: every table entry is one character, tried in
    // descending order; a character none matches (lower case) is skipped
    // without being counted.
    let mut keys: Vec<&(&str, &str)> = HUFF.iter().collect();
    keys.sort_by(|a, b| b.0.cmp(a.0));
    for c in input.chars() {
        if let Some((_, code)) = keys.iter().find(|(k, _)| k.chars().next() == Some(c)) {
            let cb = str_bits(code);
            if bits.len() + cb.len() < 72 {
                bits.extend(cb);
                n += 1;
                continue;
            }
            break;
        }
    }
    (pad_frame(bits), n)
}

fn latin1(text: &str) -> Vec<u8> {
    text.chars().map(|c| if (c as u32) < 256 { c as u32 as u8 } else { b'?' }).collect()
}

fn pack_compressed_message(input: &str, prefix: &[u8]) -> (String, usize) {
    let mut bits = prefix.to_vec();
    let mut n = 0;
    for (cw, chars) in jsc::compress(&latin1(input)) {
        if bits.len() + cw.len() < 72 {
            bits.extend(cw);
            n += chars;
            continue;
        }
        break;
    }
    (pad_frame(bits), n)
}

fn pack_data_message(input: &str) -> (String, usize) {
    let (hf, hn) = pack_huff_message(input, &[1, 0]);
    let (cf, cn) = pack_compressed_message(input, &[1, 1]);
    if hn > cn {
        (hf, hn)
    } else {
        (cf, cn)
    }
}

fn pack_fast_data_message(input: &str) -> (String, usize) {
    pack_compressed_message(input, &[])
}

/// CRC-16/KERMIT (CRCpp's CRC_16_KERMIT): reflected 0x1021, init 0.
fn crc16_kermit(data: &[u8]) -> u16 {
    let mut crc: u16 = 0;
    for &b in data {
        crc ^= b as u16;
        for _ in 0..8 {
            crc = if crc & 1 != 0 { (crc >> 1) ^ 0x8408 } else { crc >> 1 };
        }
    }
    crc
}

/// CRC-32/BZIP2 (CRCpp's CRC_32_BZIP2): 0x04C11DB7, not reflected,
/// init and final XOR 0xFFFFFFFF.
fn crc32_bzip2(data: &[u8]) -> u32 {
    let mut crc: u32 = 0xFFFF_FFFF;
    for &b in data {
        crc ^= (b as u32) << 24;
        for _ in 0..8 {
            crc = if crc & 0x8000_0000 != 0 { (crc << 1) ^ 0x04C1_1DB7 } else { crc << 1 };
        }
    }
    crc ^ 0xFFFF_FFFF
}

fn pack16bits(packed: u16) -> String {
    let n = 41u32;
    let p = packed as u32;
    let a = p / (n * n);
    let b = (p - a * n * n) / n;
    let c = p % n;
    [a, b, c].iter().map(|&i| ALPHABET41[i as usize] as char).collect()
}

/// Varicode::checksum16 of a line (its Latin-1 bytes; JS8Call takes the
/// local 8-bit encoding, which is that for anything JS8 can send).
pub fn checksum16(input: &str) -> String {
    pack16bits(crc16_kermit(&latin1(input)))
}

/// Varicode::checksum32.
pub fn checksum32(input: &str) -> String {
    let c = crc32_bzip2(&latin1(input));
    pack16bits((c >> 16) as u16) + &pack16bits(c as u16)
}

fn starts_with_cq(text: &str) -> bool {
    CQS.iter().any(|c| text.starts_with(c))
}

/// Varicode::buildMessageFrames: operator text to the frames JS8Call
/// would send, each with its header bits (FIRST on the first, LAST on the
/// last, DATA on the faster speeds' data frames).
///
/// `selected_call` is the station picked in JS8Call's list ("" for
/// none): text not already addressed gets it put in front. Returns an
/// error rather than looping when part of the text cannot be put into
/// any frame, which in JS8Call would never finish.
#[allow(clippy::too_many_arguments)]
pub fn build_frames(
    mycall: &str,
    mygrid: &str,
    selected_call: &str,
    text: &str,
    mut force_identify: bool,
    force_data: bool,
    sub: Submode,
) -> Result<Vec<(String, u8)>, String> {
    let mycall_compound = is_compound_callsign(mycall);
    let mut frames: Vec<(String, u8)> = Vec::new();
    let mut line = text.to_string();
    let mut has_directed = false;
    let mut has_data = false;
    if force_data {
        force_identify = false;
        has_data = true;
    }
    if line.starts_with(&format!("{mycall}:")) || line.starts_with(&format!("{mycall} ")) {
        line = lstrip(&mid(&line, mycall.chars().count() + 1));
    }
    if !selected_call.is_empty() && !line.starts_with(selected_call) && !line.starts_with('`') && !force_data {
        let base = line.starts_with("@ALLCALL") || starts_with_cq(&line) || line.starts_with("HB");
        let calls = parse_callsigns(&line);
        let standard = calls.first().is_some_and(|c| line.starts_with(c.as_str()) && c.chars().count() > 3);
        if !(base || standard) {
            let sep = if line.starts_with(' ') { "" } else { " " };
            line = format!("{selected_call}{sep}{line}");
        }
    }
    while !line.is_empty() {
        let before = line.clone();
        let (bcn_frame, l) = pack_heartbeat_message(&line, mycall);
        let (cmp_frame, o) = pack_compound_message(&line);
        let dir = pack_directed_message(&line, mycall);
        let likely_data = frames.is_empty() && selected_call.is_empty() && dir.to.is_empty() && l == 0 && o == 0;
        if force_identify && likely_data && !line.contains(mycall) {
            line = format!("{mycall}: {line}");
        }
        let (dat_frame, m, fast) = if sub == Submode::Normal {
            let (f, m) = pack_data_message(&line);
            (f, m, false)
        } else {
            let (f, m) = pack_fast_data_message(&line);
            (f, m, true)
        };
        if !has_directed && !has_data && l > 0 {
            frames.push((bcn_frame, 0));
            line = mid(&line, l);
        } else if !has_directed && !has_data && o > 0 {
            frames.push((cmp_frame, 0));
            line = mid(&line, o);
        } else if !has_directed && !has_data && dir.n > 0 {
            has_directed = true;
            if mycall_compound || dir.to_compound {
                let de = pack_compound_message(&format!("`{mycall} {mygrid}")).0;
                if !de.is_empty() {
                    frames.push((de, 0));
                }
                let dc = pack_compound_message(&format!("`{}{}{}", dir.to, dir.cmd, dir.num)).0;
                if !dc.is_empty() {
                    frames.push((dc, 0));
                }
            } else {
                frames.push((dir.frame.clone(), 0));
            }
            line = mid(&line, dir.n);
            let buffered = cmd_value(&dir.cmd)
                .is_some_and(|v| dir.cmd.contains(' ') || BUFFERED_CMDS.contains(&v));
            if buffered && !line.is_empty() {
                line = lstrip(&line);
                let size = cmd_value(&dir.cmd)
                    .and_then(|v| CHECKSUM_CMDS.iter().find(|(c, _)| *c == v))
                    .map_or(0, |&(_, s)| s);
                if size == 32 {
                    line = format!("{line} {}", checksum32(&line));
                } else if size == 16 {
                    line = format!("{line} {}", checksum16(&line));
                }
            }
        } else if m > 0 {
            has_data = true;
            frames.push((dat_frame, if fast { super::FRAME_DATA } else { 0 }));
            line = mid(&line, m);
        }
        if line == before {
            return Err(format!("JS8 cannot send {line:?}"));
        }
    }
    if let Some(f) = frames.first_mut() {
        f.1 |= super::FRAME_FIRST;
    }
    if let Some(f) = frames.last_mut() {
        f.1 |= super::FRAME_LAST;
    }
    Ok(frames)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn texts(frames: &[(String, u8)]) -> String {
        frames.iter().map(|(f, b)| unpack_frame(f, *b).text).collect()
    }

    #[test]
    fn huffman_table_is_prefix_free() {
        for (a, ca) in HUFF {
            for (b, cb) in HUFF {
                assert!(a == b || !cb.starts_with(ca), "{a:?} {ca} prefixes {b:?} {cb}");
            }
        }
    }

    #[test]
    fn heartbeat_and_cq_round_trip() {
        let f = build_frames("KN4CRD", "EM73", "", "HB EM73", false, false, Submode::Normal).unwrap();
        assert_eq!(f.len(), 1);
        assert_eq!(f[0].1, FRAME_FIRST_LAST);
        let u = unpack_frame(&f[0].0, f[0].1);
        assert_eq!(u.text, "KN4CRD: @HB HEARTBEAT EM73 ");
        assert_eq!(u.kind, FrameType::Heartbeat);
        let f = build_frames("KN4CRD", "EM73", "", "CQ CQ CQ EM73", false, false, Submode::Normal).unwrap();
        assert_eq!(unpack_frame(&f[0].0, f[0].1).text, "KN4CRD: @ALLCALL CQ CQ CQ EM73 ");
    }

    const FRAME_FIRST_LAST: u8 = super::super::FRAME_FIRST | super::super::FRAME_LAST;

    #[test]
    fn directed_then_data() {
        let f = build_frames("KN4CRD", "EM73", "", "J1Y SNR -05", false, false, Submode::Normal).unwrap();
        assert_eq!(texts(&f), "KN4CRD: J1Y SNR -05 ");
        let f = build_frames("KN4CRD", "EM73", "", "J1Y HELLO WORLD", false, false, Submode::Normal).unwrap();
        assert_eq!(texts(&f), "KN4CRD: J1Y  HELLO WORLD");
        let f = build_frames("KN4CRD", "EM73", "", "@ALLCALL HELLO TO ALL", false, false, Submode::Fast).unwrap();
        assert!(f.iter().skip(1).all(|(_, b)| b & super::super::FRAME_DATA != 0));
        assert_eq!(texts(&f), "KN4CRD: @ALLCALL  HELLO TO ALL");
    }

    #[test]
    fn compound_calls_use_compound_frames() {
        // A /P suffix still fits the directed frame (its portable flag)...
        let f = build_frames("KN4CRD/P", "EM73", "", "J1Y ACK", false, false, Submode::Normal).unwrap();
        assert_eq!(unpack_frame(&f[0].0, f[0].1).kind, FrameType::Directed);
        assert_eq!(texts(&f), "KN4CRD/P: J1Y ACK ");
        // ...a prefix does not: our call and grid, then the command.
        let f = build_frames("VE3/KN4CRD", "EM73", "", "J1Y ACK", false, false, Submode::Normal).unwrap();
        let k: Vec<FrameType> = f.iter().map(|(fr, b)| unpack_frame(fr, *b).kind).collect();
        assert_eq!(k, [FrameType::Compound, FrameType::CompoundDirected]);
        assert_eq!(texts(&f), "VE3/KN4CRD: J1Y ACK ");
    }

    #[test]
    fn buffered_messages_carry_a_checksum() {
        let f = build_frames("KN4CRD", "EM73", "", "J1Y MSG HELLO", false, false, Submode::Normal).unwrap();
        let t = texts(&f);
        assert_eq!(t, format!("KN4CRD: J1Y MSG HELLO {}", checksum16("HELLO")));
    }
}
