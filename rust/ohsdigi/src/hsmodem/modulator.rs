// ohsdigi - HSmodem's modulator.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Follows HSmodem (github.com/amsat-dl/QO-100-Modem, commit cbd30059),
// (c) Kurt Moraw DJ0ABR, GPL: hsmodem/liquid_if.cpp init_modulator(),
// _sendToModulator(), modulator(); ams_extension.cpp ams_testTX().

//! Frames to symbols to signal, three ways:
//!
//! - `Baseband`: liquid's modem map, then an RRC interpolator (beta 0.2,
//!   15 symbols' delay - HSmodem's modulator filter) at any whole number
//!   of samples a symbol. The simulator's beacon is made this way, at 5
//!   samples a symbol (12 kHz). On the air the beacon's filtering is done
//!   by AMSAT-DL's Pluto driver, which is not published: its modulator
//!   hands the driver one unfiltered complex sample per symbol
//!   (ams_testTX); EA4GPZ measured RRC 0.2 on the received signal.
//! - `Audio`: HSmodem's own sound-card modulator, sample for sample - the
//!   RRC interpolator at the sound card's rate, mixed up to 1500 Hz by
//!   liquid's NCO, real part plus imaginary part, times 0.1, with the
//!   100 Hz tuning marker added when asked. For the comparison with
//!   HSmodem, and for anyone feeding a transceiver's audio input.
//! - `ssb_audio`: what OpenHamShack NB transmits - the same pulse shaping and
//!   the same re + im, at NB's 12 kHz audio rate, for its SSB modulator.
//!
//! Nothing here transmits: these make samples.

use super::frame::{bytes_to_symbols, gray};
use super::liquid::{firdes_rrcos, FirInterp, Modem, Nco, Scheme, C32};
use super::resample::Resampler;
use super::speed::Speed;

/// HSmodem's TX filter: RRC, beta 0.2, delay 15 symbols, dt 0 (its tau of
/// -0.2 works out to a whole number of samples at every interpolation it
/// uses, so the fractional part liquid gets is 0).
pub const TX_BETA: f32 = 0.2;
pub const TX_DELAY: usize = 15;

/// Symbols to complex baseband at `k` samples a symbol.
pub struct Baseband {
    scheme: Scheme,
    modem: Modem,
    interp: FirInterp,
    k: usize,
}

impl Baseband {
    pub fn new(scheme: Scheme, k: usize) -> Baseband {
        let h = firdes_rrcos(k, TX_DELAY, TX_BETA, 0.0);
        Baseband {
            scheme,
            modem: Modem::new(scheme),
            interp: FirInterp::new(k, &h),
            k,
        }
    }

    /// One HSmodem symbol (as constellation.cpp makes them from bytes).
    pub fn symbol(&mut self, sym: u8, out: &mut Vec<C32>) {
        let x = self.modem.modulate(gray(self.scheme, sym));
        let mut y = vec![C32::ZERO; self.k];
        self.interp.execute(x, &mut y);
        out.extend_from_slice(&y);
    }

    /// Frames (any number of 258-byte frames back to back) to samples.
    pub fn frames(&mut self, bytes: &[u8], out: &mut Vec<C32>) {
        for s in bytes_to_symbols(self.scheme, bytes) {
            self.symbol(s, out);
        }
    }

    /// Run the filter out: `n` symbols of nothing (the constellation's
    /// zero is not a symbol, so this pushes 0 into the filter directly).
    pub fn flush(&mut self, n: usize, out: &mut Vec<C32>) {
        for _ in 0..n {
            let mut y = vec![C32::ZERO; self.k];
            self.interp.execute(C32::ZERO, &mut y);
            out.extend_from_slice(&y);
        }
    }
}

/// The constellation point of each symbol, one sample a symbol: what
/// HSmodem's beacon build hands its Pluto driver (ams_testTX, before its
/// 0.9 scaling).
pub fn points(scheme: Scheme, bytes: &[u8]) -> Vec<C32> {
    let m = Modem::new(scheme);
    bytes_to_symbols(scheme, bytes)
        .into_iter()
        .map(|s| m.modulate(gray(scheme, s)))
        .collect()
}

/// liquid_if.cpp's sound-card modulator.
pub struct Audio {
    base: Baseband,
    up: Nco,
    marker: Option<Nco>,
}

impl Audio {
    /// `rate` the sound card (48000), `k` its TX interpolation (20 for
    /// 7200 bit/s), `marker`: add tuning.cpp's 100 Hz tone at a quarter
    /// of full scale (HSmodem's default; the beacon build has none).
    pub fn new(scheme: Scheme, rate: f32, k: usize, marker: bool) -> Audio {
        let mut up = Nco::new();
        up.set_phase(0.0);
        up.set_frequency(2.0 * std::f32::consts::PI * 1500.0 / rate);
        let marker = marker.then(|| {
            let mut m = Nco::new();
            m.set_frequency(2.0 * std::f32::consts::PI * 100.0 / rate);
            m
        });
        Audio {
            base: Baseband::new(scheme, k),
            up,
            marker,
        }
    }

    pub fn frames(&mut self, bytes: &[u8], out: &mut Vec<f32>) {
        let mut bb = Vec::new();
        self.base.frames(bytes, &mut bb);
        for y in bb {
            self.up.step();
            let c = self.up.mix_up(y);
            let mut usb = c.re + c.im;
            if let Some(m) = &mut self.marker {
                m.step();
                usb += m.sin() / 4.0;
            }
            out.push(usb * 0.1);
        }
    }
}

/// What NB transmits: frames to real SSB audio at `rate` (12 kHz), the
/// signal centred at `centre` (1500 Hz, where HSmodem puts it, so an
/// HSmodem station tuned to the same dial hears it where it expects).
///
/// HSmodem's own pulse shaping (RRC 0.2, 15 symbols, `Baseband`) at four
/// samples a symbol, resampled to `rate`, mixed up to `centre`, and the
/// real audio taken as HSmodem's modulator() takes it: re + im of the
/// mixed signal (a 45-degree turn of the real part, times root 2). The
/// symbol rates of the 44.1 kHz modes (2205, 1837.5 Bd) are not a whole
/// number of 12 kHz samples, hence the resampler; four samples a symbol
/// put the pulse's first image at 4 Rs - 0.6 Rs, far outside what the
/// resampler passes.
///
/// `lead` and `tail` symbols of silence pad either end (the tail also
/// runs the filters out). The audio is scaled so its envelope - the
/// magnitude of the analytic signal, what an SSB transmitter's ALC
/// measures - peaks at `peak`: HSmodem's fixed x0.1 suits a sound card's
/// mixer, not a transmitter whose ALC would otherwise ride the modem's
/// peaks and put its gain changes on the constellation.
pub fn ssb_audio(
    speed: &Speed,
    frames: &[u8],
    rate: f32,
    centre: f32,
    peak: f32,
    lead: usize,
    tail: usize,
) -> Vec<f32> {
    let mut bb = Vec::new();
    let mut m = Baseband::new(speed.scheme(), 4);
    m.flush(lead, &mut bb);
    m.frames(frames, &mut bb);
    m.flush(tail + 2 * TX_DELAY, &mut bb);
    let bb_rate = 4.0 * speed.symbol_rate();
    let mut y = Vec::with_capacity((bb.len() as f32 * rate / bb_rate) as usize + 8);
    Resampler::new(bb_rate, rate).process(&bb, &mut y);
    let mut up = Nco::new();
    up.set_frequency(2.0 * std::f32::consts::PI * centre / rate);
    let mut env = 0.0f32;
    let mut out = Vec::with_capacity(y.len());
    for c in y {
        up.step();
        let z = up.mix_up(c);
        env = env.max(z.abs());
        out.push(z.re + z.im);
    }
    // re + im is root 2 times the real part of z turned by 45 degrees,
    // whose analytic signal has the magnitude of z: the envelope is root 2 |z|.
    let k = if env > 0.0 {
        peak / (env * std::f32::consts::SQRT_2)
    } else {
        1.0
    };
    out.iter_mut().for_each(|v| *v *= k);
    out
}
