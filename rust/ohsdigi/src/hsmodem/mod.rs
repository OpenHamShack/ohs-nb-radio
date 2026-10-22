// ohsdigi - HSmodem, DJ0ABR's high-speed modem for QO-100.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// A port of HSmodem (github.com/amsat-dl/QO-100-Modem, the tree AMSAT-DL's
// multimedia beacon is built from, commit cbd30059; (c) Kurt Moraw DJ0ABR,
// GPL - v2 or later in its file headers, GPL-3.0 in its LICENSE) and of the
// liquid-dsp objects it is built from (MIT, (c) Joseph Gaeddert). Each file
// names what it follows; docs/hsmodem-research.md has the sources, the
// licences and what is verified.

//! HSmodem: the modem of QO-100's High-Speed Multimedia Beacon
//! (10489.995 MHz, 8APSK, 2400 Bd, 7200 bit/s) and of station-to-station
//! HSmodem links at any of HSmodem's ten speeds. Laid out in layers so the
//! transmitter uses the same framing and FEC as the receiver:
//!
//! - [`frame`]: the 258-byte frame - header, CRC-16, RS(255,223),
//!   scrambler - and bytes to symbols; `pack`, `Packer`, `Deframer`.
//! - [`rs`]: the Reed-Solomon code.
//! - [`liquid`]: the liquid-dsp objects (NCO, AGC, symbol sync, LMS
//!   equaliser, APSK modem, FIR interpolator and decimator).
//! - [`demod`]: HSmodem's tracker (km_symtrack), its audio front end and
//!   its watchdog.
//! - [`speed`]: HSmodem's speed modes (BPSK, QPSK, 8APSK; 1200-7200 bit/s).
//! - [`receiver`]: the whole receive chain for complex baseband (NB's
//!   beacon channel), SSB audio (NB's decoder feed) or HSmodem's own
//!   sound-card audio, with decode statistics.
//! - [`modulator`]: frames to baseband, to HSmodem's sound-card audio, or
//!   to SSB audio at any rate (what NB transmits).
//! - [`resample`]: the arbitrary-ratio resampler between NB's rates and
//!   HSmodem's.
//!
//! What the frames carry (files, DX cluster spots, spectra) is read in
//! Python (ohscore/modes/hsmodem.py): it is a few hundred bytes a second.

pub mod demod;
pub mod frame;
pub mod liquid;
pub mod modulator;
pub mod receiver;
pub mod resample;
pub mod rs;
pub mod speed;

#[cfg(feature = "python")]
pub(crate) mod py;

/// The HSmodem tree this follows.
pub const HSMODEM_SOURCE: &str = "amsat-dl/QO-100-Modem cbd30059";
