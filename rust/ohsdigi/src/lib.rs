// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
//
// This program is free software: you can redistribute it and/or modify it
// under the terms of the GNU General Public License as published by the
// Free Software Foundation, either version 3 of the License, or (at your
// option) any later version. It is distributed WITHOUT ANY WARRANTY; see
// the GNU General Public License (LICENSE at the top of this repository).
//
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Much of this crate is ported from WSJT-X 2.7.0 (https://wsjt.sourceforge.io/),
// copyright (C) 2001-2023 Joe Taylor K1JT, Steve Franke K9AN, Bill
// Somerville G4WJS, Nico Palermo IV3NWV and the WSJT Development Group,
// GPL-3.0-or-later; each ported file names the WSJT-X files it follows.

//! Digital-mode signal processing for OpenHamShack NB and OpenHamShack HAM, in Rust
//! and called from Python (docs/digimodes-rust.md has the design).
//!
//! Phase 1 is FT8 and FT4 encoding, bit-exact with WSJT-X 2.7.0's ft8code
//! and ft4code. The modules follow what the protocols actually share, so
//! JS8 and the other WSJT-family modes can be added beside them:
//!
//! - [`msg77`]: the 77-bit message payload (pack77/unpack77) and its
//!   callsign hash tables - FT8, FT4 (and FST4, Q65, MSK144 in WSJT-X).
//! - [`crc`]: CRCs as polynomial division over bits (CRC-14 here; JS8's
//!   CRC-12 is the same function with another polynomial).
//! - [`ldpc`]: LDPC codes, one module of tables per code.
//! - [`ft8`], [`ft4`]: each mode's frame - sync arrays, Gray mapping,
//!   scrambling, symbol layout.
//! - [`gfsk`]: channel symbols to audio.
//! - [`decode`]: the FT8 and FT4 decoders (phase 2), a stage-by-stage port
//!   of WSJT-X's.
//! - [`js8`]: JS8Call's JS8 - its (174,87) modem in all five speeds, the
//!   decoder, and the message layer (frames, Varicode, JSC compression).
//! - [`q65`]: WSJT-X's Q65 - the QRA codec, encoder and decoder.
//! - [`hsmodem`]: DJ0ABR's HSmodem - QO-100's multimedia beacon - ported
//!   from its own source and from the liquid-dsp objects it is made of
//!   (docs/hsmodem-research.md).

pub mod crc;
pub mod decode;
mod fortran;
pub mod ft4;
pub mod ft8;
pub mod gfsk;
pub mod hsmodem;
pub mod js8;
pub mod ldpc;
pub mod msg77;
pub mod q65;

#[cfg(feature = "python")]
mod python;
#[cfg(feature = "python")]
mod pyapi;

use msg77::{fmtmsg, prepare, Bits77, CallHashes, PackError};

/// WSJT-X release whose behaviour this crate reproduces.
pub const WSJTX_VERSION: &str = "2.7.0";

/// Audio sample rate the modes are defined at.
pub const SAMPLE_RATE: f64 = 12_000.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Mode {
    Ft8,
    Ft4,
}

impl Mode {
    pub fn from_name(name: &str) -> Option<Mode> {
        match name.to_ascii_lowercase().as_str() {
            "ft8" => Some(Mode::Ft8),
            "ft4" => Some(Mode::Ft4),
            _ => None,
        }
    }

    pub fn name(self) -> &'static str {
        match self {
            Mode::Ft8 => "ft8",
            Mode::Ft4 => "ft4",
        }
    }

    /// Channel symbols for a payload.
    pub fn tones(self, payload: &Bits77) -> Vec<u8> {
        match self {
            Mode::Ft8 => ft8::tones(payload).to_vec(),
            Mode::Ft4 => ft4::tones(payload).to_vec(),
        }
    }

    /// The transmitted audio for a mode's channel symbols.
    pub fn waveform(self, tones: &[u8], f0: f64, fs: f64) -> Vec<f32> {
        match self {
            Mode::Ft8 => gfsk::ft8_waveform(tones, f0, fs),
            Mode::Ft4 => gfsk::ft4_waveform(tones, f0, fs),
        }
    }
}

/// A message ready to send.
#[derive(Debug, Clone)]
pub struct Encoded {
    pub mode: Mode,
    /// The message as the encoder read it: the first 37 characters,
    /// upper case, blanks collapsed (WSJT-X's fmtmsg).
    pub message: String,
    /// The message as it will be received ("CQ K1ABC FN42"; a hashed call
    /// shows as "<...>" unless it is in the message itself).
    pub sent: String,
    /// The message type, i3.n3 (n3 only meaningful when i3 is 0).
    pub i3: i32,
    pub n3: i32,
    pub bits: Bits77,
    /// Channel symbols: 79 tones 0..7 (FT8) or 103 tones 0..3 (FT4).
    pub tones: Vec<u8>,
    /// Set when WSJT-X's own answer for this message depends on a variable
    /// it never set, and this is the answer its FT8 encoder gives in
    /// practice (msg77::Packed::undefined says which).
    pub undefined_in_wsjtx: Option<&'static str>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EncodeError {
    /// WSJT-X would answer "*** bad message ***" and send nothing usable
    /// (all-zero tones for FT8; for FT4, whatever was in memory).
    BadMessage { message: String, i3: i32, n3: i32 },
    /// WSJT-X itself stops with a run-time error on this message.
    Unencodable { message: String },
    /// WSJT-X sends whatever was left in memory for this message (two
    /// unbracketed nonstandard calls, for instance): there is nothing
    /// meaningful to reproduce, so it is refused.
    Undefined { message: String, why: &'static str },
}

impl std::fmt::Display for EncodeError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            EncodeError::BadMessage { message, .. } => {
                write!(f, "{message:?} cannot be sent: WSJT-X makes it \"*** bad message ***\"")
            }
            EncodeError::Unencodable { message } => {
                write!(f, "{message:?} cannot be sent: WSJT-X 2.7.0 stops with an error on it")
            }
            EncodeError::Undefined { message, why } => {
                write!(
                    f,
                    "{message:?} cannot be sent: WSJT-X 2.7.0 would send whatever was in memory ({why})"
                )
            }
        }
    }
}

impl std::error::Error for EncodeError {}

/// Encode a message as WSJT-X 2.7.0's ft8code / ft4code would given it as
/// their argument: same normalisation, same payload, same symbols, same
/// "as received" text, and a fresh hash table each time (so a hashed call
/// the message does not spell out shows as "<...>").
pub fn encode(mode: Mode, text: &str) -> Result<Encoded, EncodeError> {
    let norm = fmtmsg(text.as_bytes());
    let message = String::from_utf8_lossy(msg_trim(&norm)).into_owned();
    let mut h = CallHashes::new();
    let crash = |e: PackError| match e {
        PackError::Crash => EncodeError::Unencodable {
            message: message.clone(),
        },
        PackError::Undefined(why) => EncodeError::Undefined {
            message: message.clone(),
            why,
        },
    };
    let (m, i3, n3) = match mode {
        Mode::Ft8 => {
            let m = prepare(&norm, &mut h).map_err(crash)?;
            let (i3, n3) = (m.i3, m.n3);
            (m, i3, n3)
        }
        Mode::Ft4 => {
            // ft4code packs the message once itself (the type it prints,
            // and calls remembered as a side effect), then genft4 packs
            // it again after cutting at a NUL and dropping leading blanks.
            let first = msg77::pack77(&norm, &mut h).map_err(crash)?;
            let mut s = norm.clone();
            if let Some(z) = s.iter().position(|&c| c == 0) {
                for c in s[z..].iter_mut() {
                    *c = b' ';
                }
            }
            let lead = s.iter().take_while(|&&c| c == b' ').count();
            let s = msg77_fixed(&s[lead..]);
            let m = prepare(&s, &mut h).map_err(crash)?;
            (m, first.i3, first.n3)
        }
    };
    let bits = m.bits.ok_or(EncodeError::BadMessage {
        message: message.clone(),
        i3,
        n3,
    })?;
    Ok(Encoded {
        mode,
        message,
        sent: m.sent,
        i3,
        n3,
        bits,
        tones: mode.tones(&bits),
        undefined_in_wsjtx: m.undefined,
    })
}

fn msg_trim(s: &[u8]) -> &[u8] {
    let n = s.iter().rposition(|&c| c != b' ').map_or(0, |p| p + 1);
    &s[..n]
}

fn msg77_fixed(s: &[u8]) -> Vec<u8> {
    let mut v = s.to_vec();
    v.resize(37, b' ');
    v
}

#[cfg(test)]
mod tests {
    use super::*;

    fn digits(t: &[u8]) -> String {
        t.iter().map(|d| (b'0' + d) as char).collect()
    }

    #[test]
    fn ft8_cq_matches_ft8code() {
        let e = encode(Mode::Ft8, "CQ G4XYZ IO91").unwrap();
        assert_eq!(
            digits(&e.tones),
            "3140652000000001005530366107405420673140652245646370472303643735537714373140652"
        );
    }

    #[test]
    fn ft4_cq_matches_ft4code() {
        let e = encode(Mode::Ft4, "CQ G4XYZ IO91").unwrap();
        // ft4code's 105 symbols less its two ramp placeholders.
        assert_eq!(
            digits(&e.tones),
            "0132103311233031311022300030202121023133023323031212322012213001002310012202210103011011112103311313201"
        );
    }

    #[test]
    fn bad_message_is_refused() {
        assert!(matches!(
            encode(Mode::Ft8, "K1ABC W9XYZ +999"),
            Err(EncodeError::BadMessage { .. })
        ));
    }
}
