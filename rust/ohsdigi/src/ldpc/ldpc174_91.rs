// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// GENERATOR is WSJT-X 2.7.0's lib/ft8/ldpc_174_91_c_generator.f90, and
// encode() ports lib/ft8/encode174_91.f90, copyright (C) 2001-2023 Joe
// Taylor K1JT, Steve Franke K9AN and the WSJT Development Group,
// GPL-3.0-or-later.

//! The (174,91) LDPC code: 77 message bits and a 14-bit CRC in, 83 parity
//! bits added. Systematic, so the codeword starts with the 91 bits it was
//! given.

use crate::crc::crc14;

/// Message bits (77 payload + 14 CRC).
pub const K: usize = 91;
/// Codeword bits.
pub const N: usize = 174;
/// Parity bits.
pub const M: usize = N - K;

/// The generator's parity rows, one per parity bit. WSJT-X stores each as
/// 23 hex digits (92 bits, the last unused); here each is the same 91 bits
/// as an integer whose most significant bit (bit 90) is message bit 1.
/// Parity bit i is the parity of (row i AND the 91 message bits).
pub const GENERATOR: [u128; M] = [
    0x4194e708df98f57a84f93fe,
    0x3b0e132712e12c99aa49899,
    0x6e132c817d93be320850dee,
    0x0d9fa0bc2c6696e99f63fb1,
    0x04fed27f7020cafe81a3c1d,
    0x03be66608dc439f6ae1ea45,
    0x14db157f1e501b7a7f0d4ed,
    0x302a7d7af9aecb69d86461f,
    0x7103cc7218877693c425748,
    0x3bae4e047407136ed72b18c,
    0x585c08814615fccb909a43e,
    0x0c5064918fe3056fae2f519,
    0x3b238f418150390f00d895c,
    0x7fde65c06541a0fd7da3d97,
    0x3353950ac7c992d15fb38b8,
    0x62121b44ff42d8e289b1d0c,
    0x06ffb9ca0a68d0d9a58e138,
    0x0ada441831b645ccc4a4b97,
    0x14d44e069ef40eb32a44d87,
    0x2789379bfd28e5f30deb5ca,
    0x4ce2391ce86cbe9e42704a0,
    0x0c8cdba88cbb2b10dda78f4,
    0x04ed896b98fd7705c36fb5c,
    0x2447e19efa1fdef752757da,
    0x413a11f7205b3afbab75aff,
    0x55f0cbe24265ba3ab8a254d,
    0x15a80725e0762d3695edee8,
    0x623a5529eb810c3b0b349b0,
    0x475d0d09ed99c85eb38c676,
    0x3a9c22339d13bc166210097,
    0x037fc1d0a2e1b81ad2e0934,
    0x1d9ba0bc2c6616e99f61fb1,
    0x4d252d14770be54e1924216,
    0x5e14fa32984e4bbf44b0852,
    0x1331d736efc5ae715d94a44,
    0x237918f7f22b81a60c0a20c,
    0x1fd96742d5f4d86397037df,
    0x6f43a40f94160a9cb8d0517,
    0x7e6be6791e34fd4cddd0a09,
    0x78130a23f4a48654723a676,
    0x220808ac0c0cb7cae6eb809,
    0x0447e18efa5fdef152757da,
    0x5c7f78db183b94fd8503c60,
    0x2d7f53d6665bbdde4eccd48,
    0x24d380b56329fb2f66e483b,
    0x0ca26842df273ed46b663e8,
    0x128fb156e2019787738a001,
    0x2b238fc38150390f005895c,
    0x15c72491f96ea8f16a9bfd0,
    0x35aa85205337a3aaef4ae13,
    0x50c56946a713ff49527b642,
    0x086172c31c465c151ec03ac,
    0x779a520c0bf701099ed9758,
    0x3f4e062a192d4e0ac1b7000,
    0x1b49f2b968fef266f83cf43,
    0x5fd96762d5f0d8639703fdf,
    0x3f70c11862c1e6662bea584,
    0x50336597f6d7e4fa9332093,
    0x5d91b92d5e23e62fa662669,
    0x6f6cedd1df72062cdab04da,
    0x6cd380b56329f36f66e481b,
    0x4d6a3576afb83f94055afe2,
    0x72c90e3bc112c398b6be9e1,
    0x278a6d4121545c36e5399a9,
    0x45c5a83d6a33ea220efbb87,
    0x11418e4e788b4a33d6825b4,
    0x109dc1c7f1572a61c7738c0,
    0x2ec935b6eb8f8428c0d2709,
    0x3355bcea594f73734a84f2b,
    0x4ac0a43416ba451c6eb45d5,
    0x5c6701067834e195391d58a,
    0x7a198eb6a30b03f4aba93a3,
    0x36d11dd2125cacb099e7ce4,
    0x531b5e5e3d9862fdf5733ff,
    0x2e586c3503efb2a54844d10,
    0x788f8834243c07e4f66ec05,
    0x0fdda9b27dc6964eb986add,
    0x7e5c35e3852864e8152e81a,
    0x529a219814f560af99171a6,
    0x64c4ece3e1e9dc62aeba898,
    0x3dd9c59780c36a3321d74b1,
    0x132275d6f5a25ca33e8fa16,
    0x3046642baca5fddaaeb4b00,
];

/// The 91 message bits (payload then CRC) as an integer, bit 90 first.
fn as_u128(bits: &[u8]) -> u128 {
    bits.iter().fold(0u128, |acc, &b| (acc << 1) | (b & 1) as u128)
}

/// encode174_91: 77 payload bits (one per byte, 0/1) to the 174-bit
/// codeword: payload, CRC-14 of the payload, 83 parity bits.
pub fn encode(payload: &[u8; 77]) -> [u8; N] {
    let crc = crc14(payload);
    let mut cw = [0u8; N];
    cw[..77].copy_from_slice(payload);
    for i in 0..14 {
        cw[77 + i] = ((crc >> (13 - i)) & 1) as u8;
    }
    let m = as_u128(&cw[..K]);
    for (i, row) in GENERATOR.iter().enumerate() {
        cw[K + i] = ((row & m).count_ones() & 1) as u8;
    }
    cw
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn codeword_of_cq_g4xyz_io91() {
        // ft8code "CQ G4XYZ IO91" (WSJT-X 2.7.0): its 77 bits, CRC and parity.
        let bits = "00000000000000000000000000100000010010001000001010110100100011111000010011001";
        let mut p = [0u8; 77];
        for (o, c) in p.iter_mut().zip(bits.bytes()) {
            *o = c - b'0';
        }
        let cw = encode(&p);
        let s: String = cw.iter().map(|b| (b'0' + b) as char).collect();
        assert_eq!(&s[77..91], "10001011110111");
        assert_eq!(
            &s[91..],
            "10100101110101010111000110111011010000010101110010111010100100010111111001110010111"
        );
    }
}
