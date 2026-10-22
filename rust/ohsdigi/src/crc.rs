// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Equivalent to WSJT-X 2.7.0's lib/crc14.cpp (boost::augmented_crc<14,
// 0x2757>) as lib/ft8/encode174_91.f90 calls it, copyright (C) 2001-2023
// Joe Taylor K1JT, Bill Somerville G4WJS and the WSJT Development Group,
// GPL-3.0-or-later.

//! Cyclic redundancy checks over bit arrays.
//!
//! WSJT-X computes FT8's CRC with Boost's "augmented" CRC over 12 bytes:
//! the 77 payload bits, three zero bits to fill the tenth byte, and two
//! zero bytes. An augmented CRC is plain polynomial division with no
//! initial value, reflection or final XOR, so it is written here as that
//! division over the same 96 bits. That needs no byte packing and serves
//! any width: JS8's CRC-12 (JS8Call lib/crc12.cpp: polynomial 0xC06 over
//! its 75 bits and zero padding, then XORed with 42) is
//! `crc_augmented(bits, 12, 0xC06) ^ 42`.

/// Polynomial division of `bits` (one per byte, most significant first)
/// by x^width + `poly`: Boost's augmented_crc<width, poly> over the same
/// bits.
pub fn crc_augmented(bits: &[u8], width: u32, poly: u32) -> u32 {
    let top = 1u32 << width;
    let mut r: u32 = 0;
    for &b in bits {
        r = (r << 1) | (b & 1) as u32;
        if r & top != 0 {
            r ^= top | poly;
        }
    }
    r & (top - 1)
}

/// FT8/FT4's CRC-14 of a 77-bit payload, as encode174_91 appends it.
pub fn crc14(payload: &[u8; 77]) -> u16 {
    let mut b = [0u8; 96];
    b[..77].copy_from_slice(payload);
    crc_augmented(&b, 14, 0x2757) as u16
}

/// Does a 91-bit block (77 payload bits then 14 CRC bits) check? For a
/// decoder: the CRC of the payload must equal the received CRC.
pub fn crc14_ok(block91: &[u8]) -> bool {
    if block91.len() < 91 {
        return false;
    }
    let mut p = [0u8; 77];
    p.copy_from_slice(&block91[..77]);
    let got = block91[77..91].iter().fold(0u16, |acc, &b| (acc << 1) | (b & 1) as u16);
    crc14(&p) == got
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc14_of_cq_g4xyz_io91() {
        let bits = "00000000000000000000000000100000010010001000001010110100100011111000010011001";
        let mut p = [0u8; 77];
        for (o, c) in p.iter_mut().zip(bits.bytes()) {
            *o = c - b'0';
        }
        // ft8code "CQ G4XYZ IO91" prints 10001011110111.
        assert_eq!(crc14(&p), 0b10001011110111);
        let mut blk: Vec<u8> = p.to_vec();
        blk.extend((0..14).rev().map(|i| ((0b10001011110111u16 >> i) & 1) as u8));
        assert!(crc14_ok(&blk));
        blk[3] ^= 1;
        assert!(!crc14_ok(&blk));
    }
}
