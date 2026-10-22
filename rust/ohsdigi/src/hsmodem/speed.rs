// ohsdigi - HSmodem's speed modes.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Follows HSmodem (github.com/amsat-dl/QO-100-Modem, commit cbd30059),
// (c) Kurt Moraw DJ0ABR, GPL: the table sr[] in hsmodem/hsmodem.cpp and
// getMod() in liquid_if.cpp.

//! HSmodem's ten speed modes, as its own table lists them. A mode is a
//! sound-card rate and two whole numbers: the TX interpolation (sound-card
//! samples a symbol) and the RX pre-decimation (sound-card samples per
//! tracker sample - always a quarter of the interpolation, so the tracker
//! always sees four samples a symbol). The bits a symbol pick the
//! constellation: 1 BPSK, 2 QPSK, 3 8APSK (liquid's 1+7 APSK; the table's
//! comment says "8PSK", getMod() says APSK8).
//!
//! The 44.1 kHz modes have symbol rates (2205, 1837.5 Bd) no 48 kHz card
//! makes; that is why HSmodem has both rates. Away from a sound card (NB
//! makes its signal at 12 kHz) only the symbol rate matters, and the TX
//! filter is the same RRC at every speed.
//!
//! Mode 10 in HSmodem's table is RTTY, not this modem; it is not here.

use super::liquid::Scheme;

/// One row of hsmodem.cpp's sr[].
#[derive(Debug, Clone, Copy, PartialEq)]
pub struct Speed {
    /// HSmodem's speed-mode number (its GUI's combo-box index).
    pub mode: u8,
    /// The sound card's rate, S/s.
    pub audio_rate: f32,
    /// TX interpolation: sound-card samples a symbol.
    pub tx_k: usize,
    /// RX pre-decimation: sound-card samples per tracker sample.
    pub rx_k: usize,
    /// Bits a symbol.
    pub bits: usize,
    /// The line speed HSmodem names the mode by, bit/s (gross).
    pub bitrate: u32,
}

impl Speed {
    pub fn scheme(&self) -> Scheme {
        match self.bits {
            1 => Scheme::Bpsk,
            2 => Scheme::Qpsk,
            _ => Scheme::Apsk8,
        }
    }

    pub fn symbol_rate(&self) -> f32 {
        self.audio_rate / self.tx_k as f32
    }

    /// The tracker's input rate: four samples a symbol.
    pub fn track_rate(&self) -> f32 {
        self.audio_rate / self.rx_k as f32
    }

    /// Symbols in one 258-byte frame.
    pub fn frame_symbols(&self) -> usize {
        super::frame::UDPBLOCKLEN * 8 / self.bits
    }

    /// HSmodem's preamble: how many times modem_sendPSKData() repeats a
    /// frame asked for with repeat > 0 when the transmitter was idle
    /// (hsmodem.cpp: `6 * ((caprate / txinterpolfactor) * bitsPerSymbol
    /// / 8) / 258 + 1`, about six seconds of frames, in integer arithmetic
    /// as there).
    pub fn idle_repetitions(&self) -> usize {
        let bytes_per_s = (self.audio_rate as usize / self.tx_k) * self.bits / 8;
        6 * bytes_per_s / super::frame::UDPBLOCKLEN + 1
    }
}

/// hsmodem.cpp sr[0..10]: {audio, tx, rx, bpsym, linespeed, codecrate}
/// with the codec rate (for its digital voice) left out.
pub const SPEEDS: [Speed; 10] = [
    Speed {
        mode: 0,
        audio_rate: 48000.0,
        tx_k: 40,
        rx_k: 10,
        bits: 1,
        bitrate: 1200,
    },
    Speed {
        mode: 1,
        audio_rate: 48000.0,
        tx_k: 20,
        rx_k: 5,
        bits: 1,
        bitrate: 2400,
    },
    Speed {
        mode: 2,
        audio_rate: 48000.0,
        tx_k: 32,
        rx_k: 8,
        bits: 2,
        bitrate: 3000,
    },
    Speed {
        mode: 3,
        audio_rate: 48000.0,
        tx_k: 24,
        rx_k: 6,
        bits: 2,
        bitrate: 4000,
    },
    Speed {
        mode: 4,
        audio_rate: 44100.0,
        tx_k: 20,
        rx_k: 5,
        bits: 2,
        bitrate: 4410,
    },
    Speed {
        mode: 5,
        audio_rate: 48000.0,
        tx_k: 20,
        rx_k: 5,
        bits: 2,
        bitrate: 4800,
    },
    Speed {
        mode: 6,
        audio_rate: 44100.0,
        tx_k: 24,
        rx_k: 6,
        bits: 3,
        bitrate: 5500,
    },
    Speed {
        mode: 7,
        audio_rate: 48000.0,
        tx_k: 24,
        rx_k: 6,
        bits: 3,
        bitrate: 6000,
    },
    Speed {
        mode: 8,
        audio_rate: 44100.0,
        tx_k: 20,
        rx_k: 5,
        bits: 3,
        bitrate: 6600,
    },
    Speed {
        mode: 9,
        audio_rate: 48000.0,
        tx_k: 20,
        rx_k: 5,
        bits: 3,
        bitrate: 7200,
    },
];

/// The multimedia beacon's mode (8APSK, 2400 Bd, 7200 bit/s).
pub const BEACON: Speed = SPEEDS[9];

pub fn by_mode(mode: u8) -> Option<Speed> {
    SPEEDS.iter().copied().find(|s| s.mode == mode)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_table_is_self_consistent() {
        for s in SPEEDS {
            // Four tracker samples a symbol at every speed.
            assert_eq!(s.tx_k, 4 * s.rx_k, "{s:?}");
            // HSmodem's line speed is what the numbers give, to its
            // rounding (5500 for 5512.5, 6600 for 6615).
            let bps = s.symbol_rate() * s.bits as f32;
            assert!((bps / s.bitrate as f32 - 1.0).abs() < 0.005, "{s:?}: {bps}");
            // Whole frames of whole symbols.
            assert_eq!(super::super::frame::UDPBLOCKLEN * 8 % s.bits, 0);
        }
        // The beacon's: 21 repetitions, as docs/hsmodem-research.md has it.
        assert_eq!(BEACON.idle_repetitions(), 21);
        assert_eq!(by_mode(4).unwrap().idle_repetitions(), 13);
    }
}
