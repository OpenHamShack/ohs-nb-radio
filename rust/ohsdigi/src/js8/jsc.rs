// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from JS8Call 2.2.0 jsc.cpp, with its dictionary (jsc_map.cpp,
// jsc_list.cpp) carried as data in jsc.bin.gz; copyright (C) 2018 Jordan
// Sherer KN4CRD, GPL-3.0-or-later.

//! JSC, JS8Call's word compression: text as a sequence of (s,c)-dense
//! codes (s = 7, c = 9, four-bit digits) indexing a 262 144-entry
//! dictionary of words and word fragments, most frequent first.
//!
//! The dictionary is jsc.bin.gz, written by harness/gen_js8_tables.py from
//! JS8Call's own jsc_map.cpp, and unpacked the first time a data frame is
//! decoded or encoded (about 3 MB once in memory). Layout: "JSC2", then
//! 262 144 entries of (u8 size, u8 length, bytes), Latin-1 as JSC::map's
//! strings are.
//!
//! The compressor's lookup order (JSC::list and JSC::prefix, another 6 MB
//! of C++ in JS8Call) is rebuilt from the map the first time something is
//! compressed: per first character, the entries in descending byte order,
//! with "@ALLCALL" filed under "ALLCALL". gen_js8_tables.py checks that
//! this is the order jsc_list.cpp holds, entry for entry, before writing
//! the file.

use std::io::Read;
use std::sync::OnceLock;

const BLOB: &[u8] = include_bytes!("jsc.bin.gz");
pub const SIZE: usize = 262_144;

const B: u32 = 4;
const S: u32 = 7;
const C: u32 = (1 << B) - S;

/// jsc_list.cpp gives ROSIDS (the last entry) size 6 where jsc_map.cpp
/// says 1; the lookup compares by the list's.
const ROSIDS: usize = 262_143;

pub struct Entry {
    /// The stored size, which is the string's length except where
    /// JS8Call's table says otherwise (gen_js8_tables.py).
    pub size: u8,
    pub text: Vec<u8>,
}

pub fn map() -> &'static Vec<Entry> {
    static T: OnceLock<Vec<Entry>> = OnceLock::new();
    T.get_or_init(|| {
        let mut raw = Vec::new();
        flate2::read::GzDecoder::new(BLOB).read_to_end(&mut raw).expect("jsc.bin.gz is part of the crate");
        assert_eq!(&raw[..4], b"JSC2");
        let mut p = 4;
        let mut map = Vec::with_capacity(SIZE);
        for _ in 0..SIZE {
            let size = raw[p];
            let len = raw[p + 1] as usize;
            map.push(Entry { size, text: raw[p + 2..p + 2 + len].to_vec() });
            p += 2 + len;
        }
        assert_eq!(p, raw.len());
        map
    })
}

/// JSC::list grouped by first character: groups[c] is the lookup order
/// of the entries filed under byte c.
fn groups() -> &'static Vec<Vec<u32>> {
    static G: OnceLock<Vec<Vec<u32>>> = OnceLock::new();
    G.get_or_init(|| {
        let m = map();
        let key = |i: usize| -> &[u8] {
            if m[i].text == b"@ALLCALL" {
                b"ALLCALL"
            } else {
                &m[i].text
            }
        };
        let mut g: Vec<Vec<u32>> = vec![Vec::new(); 256];
        for i in 0..SIZE {
            if let Some(&c) = key(i).first() {
                g[c as usize].push(i as u32);
            }
        }
        for v in g.iter_mut() {
            v.sort_by(|&a, &b| key(b as usize).cmp(key(a as usize)));
        }
        g
    })
}

fn latin1(b: &[u8]) -> String {
    b.iter().map(|&c| c as char).collect()
}

/// JSC::decompress: bits (one per byte) to text.
pub fn decompress(bits: &[u8]) -> String {
    let m = map();
    let mut base = [0u32; 8];
    for k in 1..8 {
        base[k] = base[k - 1] + S * C.pow(k as u32 - 1);
    }
    let mut bytes: Vec<u64> = Vec::new();
    let mut separators: std::collections::VecDeque<usize> = std::collections::VecDeque::new();
    let count = bits.len();
    let mut i = 0;
    while i < count {
        if count - i < 4 {
            break;
        }
        let byte = bits[i..i + 4].iter().fold(0u64, |a, &b| (a << 1) | b as u64);
        bytes.push(byte);
        i += 4;
        if byte < S as u64 {
            if count > i && bits[i] == 1 {
                separators.push_back(bytes.len() - 1);
            }
            i += 1;
        }
    }
    let mut out = String::new();
    let mut start = 0usize;
    while start < bytes.len() {
        let mut k = 0usize;
        let mut j: u64 = 0;
        while start + k < bytes.len() && bytes[start + k] >= S as u64 {
            j = j * C as u64 + (bytes[start + k] - S as u64);
            k += 1;
        }
        if j >= SIZE as u64 {
            break;
        }
        if start + k >= bytes.len() {
            break;
        }
        // base[k]: JS8Call indexes base[8] up to k = 7; a longer run of
        // continuation digits has already overflowed SIZE above.
        if k >= base.len() {
            break;
        }
        j = j * S as u64 + bytes[start + k] + base[k] as u64;
        if j >= SIZE as u64 {
            break;
        }
        out.push_str(&latin1(&m[j as usize].text));
        if separators.front() == Some(&(start + k)) {
            out.push(' ');
            separators.pop_front();
        }
        start += k + 1;
    }
    out
}

/// JSC::lookup: the dictionary index for the longest-listed entry that
/// starts `w`, as JS8Call's list order finds it.
pub fn lookup(w: &[u8]) -> Option<u32> {
    let &c = w.first()?;
    let g = &groups()[c as usize];
    let m = map();
    // One entry for this character: JS8Call returns it without comparing.
    if g.len() == 1 {
        return Some(g[0]);
    }
    for &ix in g {
        let s = &m[ix as usize].text;
        let n = if ix as usize == ROSIDS { 6 } else { m[ix as usize].size as usize };
        // strncmp(b, str, size): equal over `size` bytes, stopping early
        // at a NUL in either - so a shorter `w` matches only an entry it
        // equals in full.
        let mut eq = true;
        for k in 0..n {
            let a = w.get(k).copied().unwrap_or(0);
            let b = s.get(k).copied().unwrap_or(0);
            if a != b {
                eq = false;
                break;
            }
            if a == 0 {
                break;
            }
        }
        if eq {
            return Some(ix);
        }
    }
    None
}

/// JSC::codeword.
fn codeword(index: u32, separate: bool) -> Vec<u8> {
    let mut groups: Vec<Vec<u8>> = Vec::new();
    let v = ((index % S) << 1) + separate as u32;
    groups.push(bits_of(v as u64, B as usize + 1));
    let mut x = index / S;
    while x > 0 {
        x -= 1;
        groups.insert(0, bits_of(((x % C) + S) as u64, B as usize));
        x /= C;
    }
    groups.concat()
}

/// Varicode::intToBits(value, expected): at least `n` bits, more if the
/// value needs them.
pub fn bits_of(value: u64, n: usize) -> Vec<u8> {
    let mut v = Vec::new();
    let mut x = value;
    while x > 0 {
        v.insert(0, (x & 1) as u8);
        x >>= 1;
    }
    while v.len() < n {
        v.insert(0, 0);
    }
    v
}

/// JSC::compress: text (Latin-1 bytes) to (codeword, characters covered)
/// pairs, a word at a time.
pub fn compress(text: &[u8]) -> Vec<(Vec<u8>, usize)> {
    let m = map();
    let mut out = Vec::new();
    let words: Vec<&[u8]> = text.split(|&c| c == b' ').collect();
    let len = words.len();
    for (i, &w0) in words.iter().enumerate() {
        let is_last_word = i == len - 1;
        let mut w: &[u8] = w0;
        let mut is_space = false;
        if w.is_empty() && !is_last_word {
            w = b" ";
            is_space = true;
        }
        while !w.is_empty() {
            let Some(index) = lookup(w) else { break };
            let e = &m[index as usize];
            w = &w[(e.size as usize).min(w.len())..];
            let is_last = w.is_empty();
            let append_space = is_last && !is_space && !is_last_word;
            out.push((codeword(index, append_space), e.size as usize + append_space as usize));
        }
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn compress_then_decompress() {
        for text in ["HELLO WORLD", "THE QUICK BROWN FOX", "CQ CQ DE GM4BRI IO75"] {
            let bits: Vec<u8> = compress(text.as_bytes()).into_iter().flat_map(|(b, _)| b).collect();
            assert_eq!(decompress(&bits), text, "{text}");
        }
    }

    #[test]
    fn most_frequent_words_are_shortest() {
        // "E" is entry 0: one five-bit code.
        assert_eq!(&map()[0].text, b"E");
        assert_eq!(codeword(0, false).len(), 5);
    }
}
