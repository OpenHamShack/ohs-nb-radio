// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0 (GPL-3.0-or-later): lib/qra/q65/genq65.f90 (the
// message to tones), widgets/mainwindow.cpp and Modulator/Modulator.cpp
// (tone spacing, start delay and the transmitted waveform). Copyright (C)
// 2001-2023 Joe Taylor K1JT, Nico Palermo IV3NWV, Bill Somerville G4WJS and
// the WSJT Development Group.

//! Q65: WSJT-X's 77-bit messages (the same payload as FT8, pack77) on a
//! 65-tone FSK signal - 63 data symbols from the (15,65) QRA code over
//! GF(64) ([`qra`]) and 22 sync symbols on the lowest tone, 85 in all.
//!
//! Five T/R periods (15, 30, 60, 120 and 300 s; longer means longer
//! symbols and more sensitivity) and five submodes A-E, which multiply the
//! tone spacing by 1, 2, 4, 8 or 16 for paths that spread a signal in
//! frequency (scatter, EME). QO-100 uses Q65-60A.

pub mod decode;
pub mod qra;
pub mod sim;
pub mod tables;

#[cfg(feature = "python")]
pub mod py;

use crate::msg77::{fmtmsg, pack77, unpack77_c77, CallHashes};

/// Channel symbols per transmission.
pub const NSYM: usize = 85;
/// Where the 22 sync symbols (tone 0) go, 1-based as genq65's isync.
pub const ISYNC: [usize; 22] = [1, 9, 12, 13, 15, 22, 23, 26, 27, 33, 35, 38, 46, 50, 55, 60, 62, 66, 69, 74, 76, 85];

/// The T/R periods Q65 has, seconds.
pub const PERIODS: [u32; 5] = [15, 30, 60, 120, 300];

/// Samples per symbol at 12 kHz for a period (q65_decode.f90, mainwindow.cpp).
pub fn nsps(period: u32) -> Option<usize> {
    match period {
        15 => Some(1800),
        30 => Some(3600),
        60 => Some(7200),
        120 => Some(16000),
        300 => Some(41472),
        _ => None,
    }
}

/// Submode letter to its index (A = 0 .. E = 4).
pub fn submode_index(s: &str) -> Option<usize> {
    match s.to_ascii_uppercase().as_str() {
        "A" => Some(0),
        "B" => Some(1),
        "C" => Some(2),
        "D" => Some(3),
        "E" => Some(4),
        _ => None,
    }
}

/// Tone spacing, Hz: 2^submode x the keying rate.
pub fn tone_spacing(period: u32, submode: usize) -> f64 {
    (1u32 << submode) as f64 * 12000.0 / nsps(period).unwrap_or(7200) as f64
}

/// Where in its period a transmission starts (Modulator.cpp's delay_ms:
/// 0.5 s for Q65-15 and -30, 1 s for the longer periods). The decoder's
/// nominal start (DT 0) is the same.
pub fn start_delay(period: u32) -> f64 {
    if nsps(period).unwrap_or(7200) <= 3600 {
        0.5
    } else {
        1.0
    }
}

/// A message ready to send.
#[derive(Debug, Clone)]
pub struct Encoded {
    /// As the encoder read it (fmtmsg: upper case, single blanks).
    pub message: String,
    /// As it will be received (unpack77 of what is sent).
    pub sent: String,
    pub i3: i32,
    pub n3: i32,
    /// The 13 message symbols (77 bits and a zero, six at a time).
    pub symbols: [i32; qra::NK],
    /// The 85 channel symbols: 0 is the sync tone, data symbol v is v + 1.
    pub tones: [u8; NSYM],
}

/// Why a message cannot be sent.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct BadMessage(pub String);

impl std::fmt::Display for BadMessage {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        write!(f, "{:?} cannot be sent in Q65: WSJT-X makes it \"*** bad message ***\"", self.0)
    }
}

impl std::error::Error for BadMessage {}

/// The 13 symbols of a 77-bit payload ('0'/'1' bytes): twelve groups of
/// six bits, then five bits doubled (genq65's 78-bit payload).
pub fn symbols_of_c77(c77: &[u8; 77]) -> [i32; qra::NK] {
    let bit = |i: usize| (c77[i] == b'1') as i32;
    let mut d = [0i32; qra::NK];
    for (k, v) in d.iter_mut().enumerate().take(12) {
        *v = (0..6).fold(0, |a, j| (a << 1) | bit(6 * k + j));
    }
    d[12] = 2 * (0..5).fold(0, |a, j| (a << 1) | bit(72 + j));
    d
}

/// The 77-bit payload a decode's 13 symbols carry.
pub fn c77_of_symbols(d: &[i32; qra::NK]) -> [u8; 77] {
    let mut c = [b'0'; 77];
    for k in 0..12 {
        for j in 0..6 {
            if (d[k] >> (5 - j)) & 1 == 1 {
                c[6 * k + j] = b'1';
            }
        }
    }
    let last = d[12] / 2;
    for j in 0..5 {
        if (last >> (4 - j)) & 1 == 1 {
            c[72 + j] = b'1';
        }
    }
    c
}

/// The 85 tones for a codeword (genq65's sync insertion).
pub fn tones_of_codeword(cw: &[i32; qra::NN]) -> [u8; NSYM] {
    let mut t = [0u8; NSYM];
    let mut j = 0;
    let mut k = 0;
    for i in 1..=NSYM {
        if j < ISYNC.len() && i == ISYNC[j] {
            j += 1;
            t[i - 1] = 0;
        } else {
            t[i - 1] = (cw[k] + 1) as u8;
            k += 1;
        }
    }
    t
}

/// genq65: a message to its tones, as WSJT-X's Q65 transmitter makes them
/// (including its one rewrite: a grid field that packed as the square
/// "RR73" becomes the RR73 sign-off, ng15 32373 to 32403).
pub fn encode(text: &str) -> Result<Encoded, BadMessage> {
    let norm = fmtmsg(text.as_bytes());
    let message = String::from_utf8_lossy(&norm).trim_end().to_string();
    let mut h = CallHashes::new();
    let p = pack77(&norm, &mut h).map_err(|_| BadMessage(message.clone()))?;
    let mut c77 = p.c77;
    if !c77.iter().all(|&c| c == b'0' || c == b'1') {
        return Err(BadMessage(message));
    }
    let ng15 = c77[59..74].iter().fold(0u32, |a, &c| (a << 1) | (c == b'1') as u32);
    if ng15 == 32373 {
        c77[59..74].copy_from_slice(b"111111010010011");
    }
    let u = unpack77_c77(&c77, false, &mut h);
    if !u.ok {
        return Err(BadMessage(message));
    }
    let symbols = symbols_of_c77(&c77);
    let cw = qra::encode(&symbols);
    Ok(Encoded { message, sent: u.text_lossy().trim_end().to_string(), i3: p.i3, n3: p.n3, symbols, tones: tones_of_codeword(&cw) })
}

/// The transmitted audio for `tones` as WSJT-X's Modulator plays it:
/// continuous-phase FSK with no shaping, tone 0 at `f0`, the spacing of
/// `period`/`submode`, and over the last 1.7 % of the final symbol the
/// amplitude decaying by 0.98 per 48 kHz sample (scaled to `fs`). Full
/// scale; phase in double precision as Modulator.cpp keeps it.
pub fn waveform(tones: &[u8], f0: f64, fs: f64, period: u32, submode: usize) -> Vec<f32> {
    let nsps = nsps(period).unwrap_or(7200) as f64 * fs / 12000.0;
    let spacing = tone_spacing(period, submode);
    let n = (tones.len() as f64 * nsps).round() as usize;
    let twopi = 2.0 * std::f64::consts::PI;
    let i0 = ((tones.len() as f64 - 0.017) * nsps) as usize;
    let decay = 0.98f64.powf(48000.0 / fs);
    let mut out = Vec::with_capacity(n);
    let mut phi = 0.0f64;
    let mut amp = 1.0f64;
    for ic in 0..n {
        let isym = ((ic as f64 / nsps) as usize).min(tones.len() - 1);
        phi += twopi * (f0 + tones[isym] as f64 * spacing) / fs;
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
    fn sync_symbols_are_tone_zero_and_data_never_is() {
        let e = encode("CQ G4XYZ IO91").unwrap();
        for (i, &t) in e.tones.iter().enumerate() {
            assert_eq!(t == 0, ISYNC.contains(&(i + 1)), "symbol {}", i + 1);
        }
        assert_eq!(e.sent, "CQ G4XYZ IO91");
    }

    #[test]
    fn payload_symbols_round_trip() {
        let e = encode("K1ABC W9XYZ -15").unwrap();
        let c = c77_of_symbols(&e.symbols);
        assert_eq!(symbols_of_c77(&c), e.symbols);
    }

    #[test]
    fn rr73_is_sent_as_the_sign_off_not_a_grid() {
        let e = encode("K1ABC W9XYZ RR73").unwrap();
        assert_eq!(e.sent, "K1ABC W9XYZ RR73");
        let c = c77_of_symbols(&e.symbols);
        assert_eq!(&c[59..74], b"111111010010011");
    }
}
