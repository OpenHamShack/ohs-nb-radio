// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from JS8Call 2.2.0 (https://github.com/js8call/js8call), copyright
// (C) 2018-2020 Jordan Sherer KN4CRD, GPL-3.0-or-later, which is itself a
// fork of WSJT-X 1.9 (K1JT, K9AN, G4WJS and the WSJT Development Group,
// GPL-3.0-or-later). The files this module follows: lib/js8/genjs8.f90,
// lib/js8/js8{a,b,c,e,i}_params.f90, lib/crc12.cpp, commons.h (start
// delays) and Modulator.cpp (the waveform).

//! JS8: FT8's 8-FSK modem as it was in WSJT-X 1.9 - three 7x7 Costas
//! arrays around 58 data symbols carrying a (174,87) LDPC codeword - with
//! JS8Call's own message layer on top.
//!
//! What the modem carries is a *frame*: 12 characters of a 68-character
//! alphabet (72 bits) and three header bits ("i3bit": first frame, last
//! frame, fast data). Turning operator text into frames and back is the
//! message layer, [`varicode`] (with its word dictionary in [`jsc`]); the
//! modem itself ([`tones`], [`waveform`], [`decode`]) never looks inside a
//! frame.
//!
//! Five speeds share everything but timing and sync. Their letters are
//! the ones JS8Call's own `js8` decoder takes with `-b`:
//!
//! | letter | name   | period | symbol      | Costas      |
//! |--------|--------|--------|-------------|-------------|
//! | A      | Normal | 15 s   | 1920 (6.25 Hz) | FT8's, x3 |
//! | B      | Fast   | 10 s   | 1200 (10 Hz)   | three different |
//! | C      | Turbo  | 6 s    | 600 (20 Hz)    | three different |
//! | E      | Slow   | 30 s   | 3840 (3.125 Hz)| three different |
//! | I      | Ultra  | 4 s    | 384 (31.25 Hz) | three different |
//!
//! Ultra is disabled in JS8Call 2.2.0's GUI (commons.h JS8_ENABLE_JS8I 0)
//! but its decoder is built and runs; it is carried here for the same
//! reason, so a recording made with it still decodes.

pub mod decode;
pub mod jsc;
pub mod ldpc;
pub mod ldpc_tables;
pub mod sim;
pub mod varicode;

#[cfg(feature = "python")]
pub mod py;

use crate::crc::crc_augmented;

/// Channel symbols per transmission.
pub const NN: usize = 79;
/// Data symbols (174 bits / 3).
pub const ND: usize = 58;
/// Information bits: 72 frame bits, 3 header bits, 12 CRC bits.
pub const KK: usize = 87;

/// The 68-character frame alphabet (genjs8.f90, extractmessage174.f90).
pub const ALPHABET: &[u8; 64] = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz-+";
// Only the first 64 characters can occur: each frame character is 6 bits.
// genjs8's alphabet string goes on with "/?." - characters index() can find
// but whose values (64..66) no longer fit in 6 bits, so a frame holding one
// is not one JS8Call can send either. Kept to the 64 here.

/// Normal's Costas array, used three times (NCOSTAS=1).
pub const COSTAS_ORIGINAL: [[u8; 7]; 3] = [[4, 2, 5, 6, 1, 3, 0]; 3];
/// The three arrays every other speed uses (NCOSTAS=2): beginning, middle, end.
pub const COSTAS_SYMMETRIC: [[u8; 7]; 3] = [[0, 6, 2, 3, 5, 4, 1], [1, 5, 0, 2, 3, 6, 4], [2, 5, 0, 6, 4, 1, 3]];

/// A JS8 speed. The discriminants are JS8Call's own submode numbers
/// (varicode.h SubmodeType), which are also bit positions in its
/// "decode these submodes" mask.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Submode {
    Normal = 0,
    Fast = 1,
    Turbo = 2,
    Slow = 4,
    Ultra = 8,
}

/// One speed's constants, as lib/js8/js8<x>_params.f90 gives them.
#[derive(Debug, Clone, Copy)]
pub struct Params {
    /// Samples per symbol at 12 kHz.
    pub nsps: usize,
    /// Seconds of audio the decoder looks at (NTXDUR; Slow's is 28 of its 30).
    pub ntxdur: usize,
    /// Samples per symbol after downsampling.
    pub ndownsps: usize,
    /// The downsampler's long-FFT length, in symbols (NDD).
    pub ndd: usize,
    /// How far either side of the nominal start the sync search looks,
    /// in quarter symbols (JZ).
    pub jz: i32,
    /// Candidates closer than this many Hz are duplicates (AZ).
    pub az: f32,
    /// Where a transmission starts in its period, seconds (ASTART; the
    /// same figure as commons.h's JS8x_START_DELAY_MS).
    pub astart: f32,
    /// The transmit/receive period, seconds (commons.h JS8x_TX_SECONDS).
    pub period: f64,
    pub costas: &'static [[u8; 7]; 3],
    /// The SNR estimate's baseline offset, dB: js8<x>_decode.f90's
    /// `sbase(...) - 40.0`, which is the one line where those five
    /// otherwise identical files differ (B -39, C -38, E -42, I -36).
    pub xbase_db: f32,
}

impl Submode {
    pub const ALL: [Submode; 5] = [Submode::Normal, Submode::Fast, Submode::Turbo, Submode::Slow, Submode::Ultra];

    /// From JS8Call's letter (A, B, C, E, I - what `js8 -b` takes) or name.
    pub fn from_name(s: &str) -> Option<Submode> {
        match s.to_ascii_lowercase().as_str() {
            "a" | "normal" => Some(Submode::Normal),
            "b" | "fast" => Some(Submode::Fast),
            "c" | "turbo" => Some(Submode::Turbo),
            "e" | "slow" => Some(Submode::Slow),
            "i" | "ultra" => Some(Submode::Ultra),
            _ => None,
        }
    }

    pub fn letter(self) -> char {
        match self {
            Submode::Normal => 'A',
            Submode::Fast => 'B',
            Submode::Turbo => 'C',
            Submode::Slow => 'E',
            Submode::Ultra => 'I',
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Submode::Normal => "normal",
            Submode::Fast => "fast",
            Submode::Turbo => "turbo",
            Submode::Slow => "slow",
            Submode::Ultra => "ultra",
        }
    }

    pub fn params(self) -> Params {
        // AZ = 12000/NSPS * factor (each params file's own factor).
        let p = |nsps: usize, ntxdur, ndownsps, ndd, jz, azf: f64, astart, period, costas, xbase_db| Params {
            nsps,
            ntxdur,
            ndownsps,
            ndd,
            jz,
            az: (12000.0 / (1.0 * nsps as f32) as f64 * azf) as f32,
            astart,
            period,
            costas,
            xbase_db,
        };
        match self {
            Submode::Normal => p(1920, 15, 32, 100, 62, 0.64, 0.5, 15.0, &COSTAS_ORIGINAL, 40.0),
            Submode::Fast => p(1200, 10, 20, 100, 144, 0.8, 0.2, 10.0, &COSTAS_SYMMETRIC, 39.0),
            Submode::Turbo => p(600, 6, 12, 120, 172, 0.6, 0.1, 6.0, &COSTAS_SYMMETRIC, 38.0),
            Submode::Slow => p(3840, 28, 32, 90, 32, 0.64, 0.5, 30.0, &COSTAS_SYMMETRIC, 42.0),
            Submode::Ultra => p(384, 4, 12, 125, 250, 0.64, 0.1, 4.0, &COSTAS_SYMMETRIC, 36.0),
        }
    }

    /// Tone spacing (= keying rate), Hz.
    pub fn tone_spacing(self) -> f64 {
        12000.0 / self.params().nsps as f64
    }
}

/// The frame header bits (varicode.h TransmissionType). A frame's i3bit is
/// any combination of these.
pub const FRAME_FIRST: u8 = 1;
pub const FRAME_LAST: u8 = 2;
/// "Fast data": a data frame of the faster speeds, which uses all 72 bits
/// because this flag (not a type prefix) says it is data.
pub const FRAME_DATA: u8 = 4;

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FrameError {
    /// Not 12 characters.
    Length(usize),
    /// A character outside the 64 a frame can carry.
    Character(char),
    /// i3bit is three bits.
    Header(u8),
}

impl std::fmt::Display for FrameError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            FrameError::Length(n) => write!(f, "a JS8 frame is 12 characters, not {n}"),
            FrameError::Character(c) => write!(f, "{c:?} cannot be sent in a JS8 frame"),
            FrameError::Header(b) => write!(f, "a JS8 frame header is three bits, not {b}"),
        }
    }
}

impl std::error::Error for FrameError {}

/// The 87 information bits for a frame: genjs8's 72 frame bits, i3bit,
/// then CRC-12 (Boost's augmented CRC with polynomial 0xC06 over the 75
/// bits padded to 11 bytes, XORed with 42 - "could change the crc here",
/// says the original, which is what makes a JS8 codeword never an FT8 one).
pub fn frame_bits(frame: &str, i3bit: u8) -> Result<[u8; KK], FrameError> {
    let b = frame.as_bytes();
    if frame.chars().count() != 12 {
        return Err(FrameError::Length(frame.chars().count()));
    }
    if i3bit > 7 {
        return Err(FrameError::Header(i3bit));
    }
    let mut bits = [0u8; KK];
    for (i, &c) in b.iter().enumerate() {
        let v = ALPHABET.iter().position(|&a| a == c).ok_or(FrameError::Character(c as char))?;
        for k in 0..6 {
            bits[6 * i + k] = ((v >> (5 - k)) & 1) as u8;
        }
    }
    for k in 0..3 {
        bits[72 + k] = (i3bit >> (2 - k)) & 1;
    }
    let crc = crc12(&bits[..75]);
    for k in 0..12 {
        bits[75 + k] = ((crc >> (11 - k)) & 1) as u8;
    }
    Ok(bits)
}

/// JS8's CRC of the 75 frame and header bits (see [`frame_bits`]).
pub fn crc12(bits75: &[u8]) -> u16 {
    let mut b = [0u8; 88];
    b[..75].copy_from_slice(&bits75[..75]);
    (crc_augmented(&b, 12, 0xC06) ^ 42) as u16
}

/// The frame and header a decoded 87-bit block carries, if its CRC checks
/// (extractmessage174.f90).
pub fn unpack_bits(bits: &[u8; KK]) -> Option<(String, u8)> {
    let got = bits[75..].iter().fold(0u16, |a, &b| (a << 1) | b as u16);
    if crc12(&bits[..75]) != got {
        return None;
    }
    let frame = (0..12)
        .map(|i| {
            let v = bits[6 * i..6 * i + 6].iter().fold(0usize, |a, &b| (a << 1) | b as usize);
            ALPHABET[v] as char
        })
        .collect();
    let i3 = bits[72] * 4 + bits[73] * 2 + bits[74];
    Some((frame, i3))
}

/// The 79 channel symbols (tones 0..7) for 87 information bits (genjs8):
/// no Gray code, unlike FT8 - three codeword bits are the tone number.
pub fn tones_from_bits(bits: &[u8; KK], sub: Submode) -> [u8; NN] {
    let cw = ldpc::encode(bits);
    let costas = sub.params().costas;
    let mut t = [0u8; NN];
    t[0..7].copy_from_slice(&costas[0]);
    t[36..43].copy_from_slice(&costas[1]);
    t[72..79].copy_from_slice(&costas[2]);
    let mut k = 7;
    for j in 0..ND {
        if j == 29 {
            k += 7;
        }
        t[k] = cw[3 * j] * 4 + cw[3 * j + 1] * 2 + cw[3 * j + 2];
        k += 1;
    }
    t
}

/// The channel symbols for a frame and header.
pub fn tones(frame: &str, i3bit: u8, sub: Submode) -> Result<[u8; NN], FrameError> {
    Ok(tones_from_bits(&frame_bits(frame, i3bit)?, sub))
}

/// The transmitted audio for a transmission's tones, `f0` the frequency of
/// tone 0: what JS8Call's Modulator plays, at sample rate `fs`.
///
/// Plain continuous-phase FSK, tone spacing equal to the keying rate - JS8
/// kept FT8's original unshaped tones when WSJT-X 2.0 moved FT8 to GFSK -
/// with Modulator.cpp's one concession to the spectrum: over the last
/// 1.7 % of the final symbol the amplitude decays by 0.98 per 48 kHz
/// sample (to about 7 %), then stops. That decay is scaled here to `fs`
/// so the envelope is the same in time at any rate. The level is full
/// scale; the caller sets the drive.
///
/// The phase is accumulated in double precision as Modulator.cpp does
/// (m_phi, m_dphi are doubles), then the sine taken: there is no
/// single-precision quirk to carry, unlike FT8's waveform (gfsk.rs).
pub fn waveform(tones: &[u8], f0: f64, fs: f64, sub: Submode) -> Vec<f32> {
    let nsps = sub.params().nsps as f64 * fs / 12000.0;
    let baud = 12000.0 / sub.params().nsps as f64;
    let n = (tones.len() as f64 * nsps).round() as usize;
    let twopi = 2.0 * std::f64::consts::PI;
    // Modulator.cpp: i0 = (m_symbolsLength - 0.017) * 4.0 * m_nsps at its
    // 48 kHz frame rate (4 x 12 kHz); here at fs.
    let i0 = ((tones.len() as f64 - 0.017) * nsps) as usize;
    let decay = 0.98f64.powf(48000.0 / fs);
    let mut out = Vec::with_capacity(n);
    let mut phi = 0.0f64;
    let mut amp = 1.0f64;
    for ic in 0..n {
        let isym = ((ic as f64 / nsps) as usize).min(tones.len() - 1);
        let f = f0 + tones[isym] as f64 * baud;
        phi += twopi * f / fs;
        if phi > twopi {
            phi -= twopi;
        }
        if ic > i0 {
            amp *= decay;
        }
        out.push((amp * phi.sin()) as f32);
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc_round_trip_and_rejects_a_flipped_bit() {
        let mut b = frame_bits("SIUT18l+CDqE", 3).unwrap();
        assert_eq!(unpack_bits(&b), Some(("SIUT18l+CDqE".to_string(), 3)));
        b[10] ^= 1;
        assert_eq!(unpack_bits(&b), None);
    }

    #[test]
    fn frames_are_checked() {
        assert!(matches!(frame_bits("SHORT", 0), Err(FrameError::Length(5))));
        assert!(matches!(frame_bits("ABCDEFGHIJK/", 0), Err(FrameError::Character('/'))));
        assert!(matches!(frame_bits("ABCDEFGHIJKL", 8), Err(FrameError::Header(8))));
    }

    #[test]
    fn sync_arrays_sit_where_each_speed_puts_them() {
        let t = tones("SIUT18l+CDqE", 3, Submode::Normal).unwrap();
        assert_eq!(&t[0..7], &COSTAS_ORIGINAL[0]);
        assert_eq!(&t[36..43], &COSTAS_ORIGINAL[1]);
        let t = tones("SIUT18l+CDqE", 3, Submode::Fast).unwrap();
        assert_eq!(&t[72..79], &COSTAS_SYMMETRIC[2]);
    }
}
