// ohsdigi - HSmodem's frame: header, CRC, Reed-Solomon, scrambler, symbols.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Follows HSmodem (github.com/amsat-dl/QO-100-Modem, commit cbd30059),
// (c) Kurt Moraw DJ0ABR, GPL: hsmodem/frameformat.h, frame_packer.cpp,
// constellation.cpp, scrambler.cpp (its table is reproduced below) and
// crc16.cpp. Every fact is cited in docs/hsmodem-research.md.

//! One HSmodem frame on the air is 258 bytes:
//!
//! ```text
//!  3 bytes  header 53 E1 A6 (not scrambled, not protected)
//!  255      RS(255,223) codeword, scrambled:
//!             223 data = counter LSB, status, 219 payload, CRC16 MSB, LSB
//!             32 parity
//! ```
//!
//! status = counter bits 8-9 (<<6) | first/next/last/single (<<4) | type.
//! At 3 bits a symbol that is 688 symbols, taken MSB first (8 symbols to
//! 3 bytes). The receiver slides a frame-long window over the hard
//! symbols, looks for the header's 8 symbols at the start under each of
//! the constellation's rotations (2 symbol errors allowed - HSmodem's Linux
//! value), and for each hit undoes the rotation, descrambles, decodes the
//! RS code and checks the CRC. It never assumes where the next frame is:
//! every symbol is a candidate start, as in HSmodem.

use super::liquid::Scheme;
use super::rs;

pub const HEADER: [u8; 3] = [0x53, 0xe1, 0xa6];
pub const HEADERLEN: usize = 3;
pub const FECBLOCKLEN: usize = 255;
pub const UDPBLOCKLEN: usize = HEADERLEN + FECBLOCKLEN; // 258
pub const FECLEN: usize = 32;
pub const PAYLOADLEN: usize = FECBLOCKLEN - FECLEN - 2 - 2; // 219
pub const DATALEN: usize = PAYLOADLEN + 4; // 223: counter, status, payload, crc
/// Linux build: MAXHEADERRS 2 (the Windows build allows 5).
pub const MAX_HEADER_ERRORS: usize = 2;

/// scrambler.cpp's table: 400 bytes that are this 100-byte sequence four
/// times over; a frame uses the first 255.
pub const SCRAMBLE: [u8; 100] = [
    130, 239, 223, 19, 146, 254, 12, 86, 106, 68, 77, 213, 243, 216, 102, 227, 108, 113, 229, 89, 26, 64, 138, 216,
    225, 121, 194, 137, 152, 64, 51, 175, 68, 200, 37, 104, 247, 68, 193, 50, 19, 14, 196, 81, 4, 236, 191, 249, 83,
    25, 161, 171, 167, 29, 33, 139, 7, 152, 230, 144, 125, 206, 34, 236, 112, 78, 219, 34, 181, 161, 7, 45, 198, 235,
    62, 115, 194, 100, 209, 95, 186, 161, 53, 10, 110, 246, 122, 246, 207, 194, 178, 63, 232, 93, 158, 234, 231, 73,
    214, 64,
];

pub fn scramble(data: &mut [u8]) {
    for (i, b) in data.iter_mut().enumerate() {
        *b ^= SCRAMBLE[i % SCRAMBLE.len()];
    }
}

/// crc16.cpp: reflected CCITT (poly 0x8408), initial 0xffff, no final XOR
/// (CRC-16/MCRF4XX). HSmodem uses it for the frame and as a file's ID.
pub fn crc16(data: &[u8]) -> u16 {
    let mut reg: u16 = 0xffff;
    for &b in data {
        let mut byt = b;
        for _ in 0..8 {
            if (reg & 1) != (byt as u16 & 1) {
                reg = (reg >> 1) ^ 0x8408;
            } else {
                reg >>= 1;
            }
            byt >>= 1;
        }
    }
    reg
}

/// Frame status: where a frame sits in a file (frameformat.h; the wiki's
/// "Frame Status").
pub mod status {
    pub const FIRST: u8 = 0;
    pub const NEXT: u8 = 1;
    pub const LAST: u8 = 2;
    pub const SINGLE: u8 = 3;
}

/// A deframed frame: what getPayload() hands the application.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Frame {
    /// 4-bit frame type (2 image, 3 ASCII, 4 HTML, 5 binary, 8 external data, ...).
    pub ftype: u8,
    /// 2-bit first/next/last/single.
    pub status: u8,
    /// 10-bit frame counter.
    pub counter: u16,
    pub payload: [u8; PAYLOADLEN],
    /// How many symbol errors the RS decoder corrected (byte errors).
    pub corrected: usize,
    /// Constellation rotation the header was found at.
    pub rotation: usize,
}

/// frame_packer.cpp Pack(): the 258 bytes for one payload. `counter` is the
/// caller's (Pack() keeps it in a global; Packer below reproduces its rules).
pub fn pack(payload: &[u8; PAYLOADLEN], ftype: u8, status: u8, counter: u16) -> [u8; UDPBLOCKLEN] {
    let mut data = [0u8; DATALEN];
    data[0] = (counter & 0xff) as u8;
    data[1] = ((((counter >> 8) & 3) as u8) << 6) | ((status & 3) << 4) | (ftype & 0x0f);
    data[2..2 + PAYLOADLEN].copy_from_slice(payload);
    let crc = crc16(&data[..PAYLOADLEN + 2]);
    data[PAYLOADLEN + 2] = (crc >> 8) as u8;
    data[PAYLOADLEN + 3] = (crc & 0xff) as u8;
    let cw = rs::encode(&data);
    let mut out = [0u8; UDPBLOCKLEN];
    out[..HEADERLEN].copy_from_slice(&HEADER);
    out[HEADERLEN..].copy_from_slice(&cw);
    scramble(&mut out[HEADERLEN..]);
    out
}

/// Pack()'s frame counter: incremented for each new frame (not for a
/// repeat, except type 1, the BER test), reset to 0 by a file's first
/// frame, left alone by type 8 (external data) frames.
#[derive(Debug, Clone, Default)]
pub struct Packer {
    pub counter: u16,
}

impl Packer {
    pub fn pack(&mut self, payload: &[u8; PAYLOADLEN], ftype: u8, status: u8, repeat: bool) -> [u8; UDPBLOCKLEN] {
        if ftype != 8 {
            if !repeat || ftype == 1 {
                self.counter = self.counter.wrapping_add(1);
            }
            if status == self::status::FIRST {
                self.counter = 0;
            }
        }
        pack(payload, ftype, status, self.counter & 0x3ff)
    }
}

// ------------------------------------------------------------ symbols

/// Bytes to symbols, MSB first (constellation.cpp convertBytesToSyms_*).
/// For QPSK these are the symbols before HSmodem's Gray twist (`gray`),
/// which only the modulator and demodulator apply.
pub fn bytes_to_symbols(scheme: Scheme, bytes: &[u8]) -> Vec<u8> {
    let m = scheme.bits();
    let mut out = Vec::with_capacity(bytes.len() * 8 / m);
    match scheme {
        Scheme::Apsk8 => {
            for c in bytes.chunks(3) {
                if c.len() < 3 {
                    break;
                }
                let v = ((c[0] as u32) << 16) | ((c[1] as u32) << 8) | c[2] as u32;
                for k in (0..8).rev() {
                    out.push(((v >> (3 * k)) & 7) as u8);
                }
            }
        }
        Scheme::Qpsk => {
            for &b in bytes {
                for k in (0..4).rev() {
                    out.push((b >> (2 * k)) & 3);
                }
            }
        }
        Scheme::Bpsk => {
            for &b in bytes {
                for k in (0..8).rev() {
                    out.push((b >> k) & 1);
                }
            }
        }
    }
    out
}

/// liquid_if.cpp: QPSK symbols are XORed with themselves shifted right
/// before modulation and again after demodulation ("this adds gray code,
/// liquid adds it again which removes it"). Its own inverse.
pub fn gray(scheme: Scheme, s: u8) -> u8 {
    if scheme == Scheme::Qpsk {
        s ^ (s >> 1)
    } else {
        s
    }
}

/// Symbols back to bytes (convert*SymToBytes), the inverse of the above
/// after the receiver's Gray undo for QPSK.
fn symbols_to_bytes(scheme: Scheme, syms: &[u8], out: &mut [u8]) {
    match scheme {
        Scheme::Apsk8 => {
            for (i, c) in syms.chunks(8).enumerate() {
                let mut v = 0u32;
                for &s in c {
                    v = (v << 3) | (s & 7) as u32;
                }
                out[3 * i] = (v >> 16) as u8;
                out[3 * i + 1] = (v >> 8) as u8;
                out[3 * i + 2] = v as u8;
            }
        }
        Scheme::Qpsk => {
            for (i, c) in syms.chunks(4).enumerate() {
                out[i] = c.iter().fold(0u8, |a, &s| (a << 2) | (s & 3));
            }
        }
        Scheme::Bpsk => {
            for (i, c) in syms.chunks(8).enumerate() {
                out[i] = c.iter().fold(0u8, |a, &s| (a << 1) | (s & 1));
            }
        }
    }
}

/// rotate8APSKsyms: what a symbol reads as after the carrier phase slips by
/// one outer-ring step (2pi/7); the centre point never moves.
pub const APSK8_ROTATE: [u8; 8] = [0, 4, 3, 1, 5, 7, 2, 6];

fn rotate(scheme: Scheme, s: u8) -> u8 {
    match scheme {
        Scheme::Apsk8 => APSK8_ROTATE[s as usize],
        Scheme::Qpsk => (s + 1) % 4,
        Scheme::Bpsk => s ^ 1,
    }
}

/// The inverse of `rotate`, applied `n` times (rotateBack*).
fn rotate_back(scheme: Scheme, s: u8, n: usize) -> u8 {
    let mut v = s;
    for _ in 0..n {
        v = match scheme {
            Scheme::Apsk8 => APSK8_ROTATE.iter().position(|&r| r == v).unwrap() as u8,
            Scheme::Qpsk => (v + 3) % 4,
            Scheme::Bpsk => v ^ 1,
        };
    }
    v
}

/// Outcome of looking at one position of the symbol stream. (A frame is
/// returned by value: at most one per symbol, and most looks are Nothing.)
#[allow(clippy::large_enum_variant)]
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Look {
    Nothing,
    Frame(Frame),
    /// The header matched but the RS decoder gave up.
    FecFailed,
    /// RS decoded but the CRC disagreed.
    CrcFailed,
}

/// frame_packer.cpp unpack_data(): a frame-long window of hard symbols.
pub struct Deframer {
    scheme: Scheme,
    buf: Vec<u8>,
    filled: usize,
    headers: Vec<Vec<u8>>,
    max_header_errors: usize,
    work: Vec<u8>,
    bytes: [u8; UDPBLOCKLEN],
}

impl Deframer {
    pub fn new(scheme: Scheme) -> Deframer {
        let n = UDPBLOCKLEN * 8 / scheme.bits();
        let h0 = bytes_to_symbols(scheme, &HEADER);
        // init_packer(): the header under each rotation (2, 4, or 8 tables;
        // 8APSK's eighth equals its first, the ring having 7 points).
        let ntab = match scheme {
            Scheme::Bpsk => 2,
            Scheme::Qpsk => 4,
            Scheme::Apsk8 => 8,
        };
        let mut headers = vec![h0];
        for i in 1..ntab {
            let prev = headers[i - 1].clone();
            headers.push(prev.iter().map(|&s| rotate(scheme, s)).collect());
        }
        Deframer {
            scheme,
            buf: vec![0; n],
            filled: 0,
            headers,
            max_header_errors: MAX_HEADER_ERRORS,
            work: vec![0; n],
            bytes: [0; UDPBLOCKLEN],
        }
    }

    pub fn set_max_header_errors(&mut self, n: usize) {
        self.max_header_errors = n;
    }

    pub fn reset(&mut self) {
        self.buf.iter_mut().for_each(|v| *v = 0);
        self.filled = 0;
    }

    /// Shift one hard symbol in (after the QPSK Gray undo, as GRdata_rxdata
    /// receives it) and look for a frame starting at the window's start.
    pub fn push(&mut self, sym: u8) -> Look {
        let n = self.buf.len();
        self.buf.copy_within(1.., 0);
        self.buf[n - 1] = sym;
        self.filled = (self.filled + 1).min(n);
        let hl = self.headers[0].len();
        let mut rotation = None;
        for (tab, h) in self.headers.iter().enumerate() {
            let errs = h.iter().zip(&self.buf[..hl]).filter(|(a, b)| a != b).count();
            if errs <= self.max_header_errors {
                rotation = Some(tab);
                break;
            }
        }
        let Some(rot) = rotation else { return Look::Nothing };
        for (w, &s) in self.work.iter_mut().zip(&self.buf) {
            *w = rotate_back(self.scheme, s, rot);
        }
        symbols_to_bytes(self.scheme, &self.work, &mut self.bytes);
        let mut cw = [0u8; FECBLOCKLEN];
        cw.copy_from_slice(&self.bytes[HEADERLEN..]);
        scramble(&mut cw);
        let Some((data, corrected)) = rs::decode(&cw) else {
            return Look::FecFailed;
        };
        let crc = crc16(&data[..PAYLOADLEN + 2]);
        if crc != u16::from_be_bytes([data[PAYLOADLEN + 2], data[PAYLOADLEN + 3]]) {
            return Look::CrcFailed;
        }
        let mut payload = [0u8; PAYLOADLEN];
        payload.copy_from_slice(&data[2..2 + PAYLOADLEN]);
        Look::Frame(Frame {
            ftype: data[1] & 0x0f,
            status: (data[1] >> 4) & 3,
            counter: (((data[1] >> 6) as u16) << 8) | data[0] as u16,
            payload,
            corrected,
            rotation: rot,
        })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn crc_is_mcrf4xx() {
        // CRC-16/MCRF4XX check value for "123456789".
        assert_eq!(crc16(b"123456789"), 0x6f91);
    }

    #[test]
    fn header_symbols_as_hsmodem_lists_them() {
        // frame_packer.cpp's comment: 8PSK syms 2 4 7 6 0 6 4 6, and its
        // printed rotation table (second row 03 05 06 02 00 02 05 02 is
        // HSmodem's own run of rotate8APSKsyms; we only need the first).
        assert_eq!(bytes_to_symbols(Scheme::Apsk8, &HEADER), vec![2, 4, 7, 6, 0, 6, 4, 6]);
        let d = Deframer::new(Scheme::Apsk8);
        assert_eq!(d.headers[7], d.headers[0]);
    }

    #[test]
    fn pack_then_deframe_under_every_rotation() {
        let mut p = [0u8; PAYLOADLEN];
        for (i, b) in p.iter_mut().enumerate() {
            *b = (i * 7 + 3) as u8;
        }
        let frame = pack(&p, 3, status::NEXT, 517);
        let syms = bytes_to_symbols(Scheme::Apsk8, &frame);
        for rot in 0..7 {
            let mut d = Deframer::new(Scheme::Apsk8);
            let mut got = None;
            for &s in &syms {
                let mut r = s;
                for _ in 0..rot {
                    r = rotate(Scheme::Apsk8, r);
                }
                if let Look::Frame(f) = d.push(r) {
                    got = Some(f);
                }
            }
            let f = got.expect("frame");
            assert_eq!((f.ftype, f.status, f.counter, f.payload), (3, status::NEXT, 517, p));
        }
    }
}
