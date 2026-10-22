// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0, lib/ft4/genft4.f90 and lib/ft4/ft4_params.f90,
// copyright (C) 2001-2023 Joe Taylor K1JT, Steve Franke K9AN and the WSJT
// Development Group, GPL-3.0-or-later.

//! FT4's frame: 4-GFSK, 103 symbols of 48 ms (576 samples), 20.833 Hz
//! apart - four 4x4 Costas arrays around three blocks of 29 data symbols,
//! each two codeword bits through a Gray code. The payload is scrambled
//! with a fixed vector first, so that a message of mostly zeros (a short
//! free text) does not become a long run of one tone. On the air the frame
//! has a ramp-up and a ramp-down symbol added either side (105 in all);
//! those are part of the waveform, not of the symbols (gfsk::ft4_waveform).

use crate::ldpc::ldpc174_91;
use crate::msg77::Bits77;

/// Sync and data symbols.
pub const NN: usize = 103;
/// Symbols on the air, with the ramp-up and ramp-down.
pub const NN2: usize = 105;
/// Data symbols (174 bits / 2).
pub const ND: usize = 87;
/// Sync symbols (4 x 4).
pub const NS: usize = 16;
/// Samples per symbol at 12 000 samples/s.
pub const NSPS: usize = 576;
/// The transmit cycle, seconds.
pub const SLOT_S: f64 = 7.5;
/// The Gaussian filter's bandwidth-time product (gen_ft4wave's).
pub const BT: f64 = 1.0;

/// The four Costas arrays, at symbols 0, 33, 66 and 99.
pub const COSTAS: [[u8; 4]; 4] = [[0, 1, 3, 2], [1, 0, 2, 3], [2, 3, 1, 0], [3, 2, 0, 1]];
/// Where each Costas array starts.
pub const SYNC_AT: [usize; 4] = [0, 33, 66, 99];
/// Two codeword bits (b0*2 + b1) to a tone.
pub const GRAY: [u8; 4] = [0, 1, 3, 2];

/// The scrambling vector XORed into the payload before coding (rvec).
pub const RVEC: [u8; 77] = [
    0, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 1, 1, 1, 1, 0, 1, 0, 0, 0, 1, 0, 0, 1, 1, 0, 1, 1, 0, //
    1, 0, 0, 1, 0, 1, 1, 0, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 0, 1, //
    0, 1, 0, 1, 0, 1, 1, 0, 1, 1, 1, 1, 1, 0, 0, 0, 1, 0, 1,
];

/// The payload as coded: XORed with RVEC (its own inverse).
pub fn scramble(payload: &Bits77) -> Bits77 {
    let mut s = *payload;
    for (b, r) in s.iter_mut().zip(RVEC.iter()) {
        *b ^= r;
    }
    s
}

/// The 103 channel symbols (tones 0..3) for a 77-bit payload (before
/// scrambling): get_ft4_tones_from_77bits.
pub fn tones(payload: &Bits77) -> [u8; NN] {
    let cw = ldpc174_91::encode(&scramble(payload));
    let mut t = [0u8; NN];
    for (c, &s) in COSTAS.iter().zip(SYNC_AT.iter()) {
        t[s..s + 4].copy_from_slice(c);
    }
    for i in 0..ND {
        let tone = GRAY[(cw[2 * i] * 2 + cw[2 * i + 1]) as usize];
        // Data blocks follow each of the first three sync arrays.
        let block = i / 29;
        t[SYNC_AT[block] + 4 + i % 29] = tone;
    }
    t
}
