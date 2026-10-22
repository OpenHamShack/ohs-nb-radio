// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0, lib/ft8/genft8.f90 and lib/ft8/ft8_params.f90,
// copyright (C) 2001-2023 Joe Taylor K1JT, Steve Franke K9AN and the WSJT
// Development Group, GPL-3.0-or-later.

//! FT8's frame: 8-GFSK, 79 symbols of 0.16 s, 6.25 Hz apart - three 7x7
//! Costas arrays for sync around two blocks of 29 data symbols, each data
//! symbol three codeword bits through a Gray code.

use crate::ldpc::ldpc174_91;
use crate::msg77::Bits77;

/// Channel symbols per transmission.
pub const NN: usize = 79;
/// Data symbols (174 bits / 3).
pub const ND: usize = 58;
/// Sync symbols (3 x 7).
pub const NS: usize = 21;
/// Samples per symbol at 12 000 samples/s.
pub const NSPS: usize = 1920;
/// The transmit cycle, seconds.
pub const SLOT_S: f64 = 15.0;
/// The Gaussian filter's bandwidth-time product (gen_ft8wave's bt).
pub const BT: f64 = 2.0;

/// The Costas array at symbols 0, 36 and 72.
pub const COSTAS: [u8; 7] = [3, 1, 4, 0, 6, 5, 2];
/// Three codeword bits (b0*4 + b1*2 + b2) to a tone.
pub const GRAY: [u8; 8] = [0, 1, 3, 2, 5, 6, 4, 7];
/// Where each Costas array starts.
pub const SYNC_AT: [usize; 3] = [0, 36, 72];

/// The 79 channel symbols (tones 0..7) for a 77-bit payload:
/// get_ft8_tones_from_77bits.
pub fn tones(payload: &Bits77) -> [u8; NN] {
    let cw = ldpc174_91::encode(payload);
    let mut t = [0u8; NN];
    for &s in &SYNC_AT {
        t[s..s + 7].copy_from_slice(&COSTAS);
    }
    let mut k = 7;
    for j in 0..ND {
        if j == 29 {
            k += 7;
        }
        let i = 3 * j;
        t[k] = GRAY[(cw[i] * 4 + cw[i + 1] * 2 + cw[i + 2]) as usize];
        k += 1;
    }
    t
}
