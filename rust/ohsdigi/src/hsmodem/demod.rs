// ohsdigi - HSmodem's demodulator.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Follows HSmodem (github.com/amsat-dl/QO-100-Modem, commit cbd30059),
// (c) Kurt Moraw DJ0ABR, GPL: hsmodem/symboltracker.cpp (km_symtrack, his
// version of liquid-dsp's symtrack), liquid_if.cpp (init_demodulator,
// demodulator) and hsmodem.cpp (GRdata_rxdata's modem reset).

//! Two front ends, one tracker:
//!
//! - **Audio** (`AudioFront`): HSmodem's own receive path, sample for
//!   sample - 48 kHz sound-card audio taken as the complex value f + jf,
//!   mixed down from 1500 Hz by liquid's NCO, decimated by 5 through
//!   liquid's Kaiser decimator (8 symbols' delay, 40 dB), at any speed
//!   mode's rate and decimation. This is what the stage-by-stage
//!   comparison with HSmodem runs on.
//! - **IQ** (`Receiver` in receiver.rs): OpenHamShack NB already has the beacon
//!   as complex baseband in its own channel, so it skips the audio and
//!   hands the tracker complex samples at four per symbol (9600 S/s for
//!   the beacon). A station's SSB audio (NB's decoder feed) reaches the same
//!   path through receiver.rs's own mixer and filter.
//!
//! The tracker (`SymTrack`) is km_symtrack_cccf: AGC (bandwidth 0.018),
//! symsync with a 16-filter RRC bank (k 4, m 7, beta 0.2, loop 0.0009, two
//! outputs a symbol), a carrier NCO run as a PLL (bandwidth 0.0009) from
//! the demodulator's phase error, and a 9-tap LMS equaliser (initially a
//! Kaiser low-pass at 0.45, learning rate 0.018) that starts adapting -
//! decision directed - after 200 symbols. All of it is liquid's code
//! (liquid.rs); the wiring and the numbers are HSmodem's.

use super::liquid::{Agc, EqLms, FirDecim, Modem, Nco, Scheme, SymSync, C32};

/// Per-symbol values the comparison with HSmodem reads (and the decode
/// quality is computed from).
#[derive(Debug, Clone, Copy, Default)]
pub struct SymOut {
    /// The equaliser's output: the soft symbol.
    pub d_hat: C32,
    /// The demodulator's decision (liquid's symbol number, before any
    /// QPSK Gray undo).
    pub sym: u8,
    /// The constellation point decided on.
    pub x_hat: C32,
    pub tau: f32,
    pub nco_freq: f32,
    pub nco_phase: f32,
    pub agc_gain: f32,
}

/// km_symtrack_cccf.
pub struct SymTrack {
    agc: Agc,
    symsync: SymSync,
    eq: EqLms,
    nco: Nco,
    demod: Modem,
    symsync_index: u64,
    num_syms_rx: u64,
    buf: Vec<C32>,
}

impl SymTrack {
    /// km_symtrack_cccf_create(LIQUID_FIRFILT_RRC, k, m, beta, scheme) and
    /// km_symtrack_cccf_set_bandwidth(bw), as init_demodulator() calls them
    /// (k 4, m 7, beta 0.2, bandwidth 0.9).
    pub fn new(scheme: Scheme, k: usize, m: usize, beta: f32, bw: f32) -> SymTrack {
        let mut symsync = SymSync::rrc(k, m, beta, 16);
        symsync.set_output_rate(2);
        let mut t = SymTrack {
            agc: Agc::new(),
            symsync,
            eq: EqLms::lowpass(2 * 4 + 1, 0.45),
            nco: Nco::new(),
            demod: Modem::new(scheme),
            symsync_index: 0,
            num_syms_rx: 0,
            buf: Vec::with_capacity(8),
        };
        t.set_bandwidth(0.9);
        t.reset();
        t.set_bandwidth(bw);
        t
    }

    pub fn hsmodem(scheme: Scheme) -> SymTrack {
        SymTrack::new(scheme, 4, 7, 0.2, 0.9)
    }

    pub fn set_bandwidth(&mut self, bw: f32) {
        self.agc.set_bandwidth(0.02 * bw);
        self.symsync.set_lf_bw(0.001 * bw);
        self.eq.set_bw(0.02 * bw);
        self.nco.pll_set_bandwidth(0.001 * bw);
    }

    /// km_symtrack_cccf_reset(q, 0xff): everything.
    pub fn reset(&mut self) {
        self.agc.reset();
        self.symsync.reset();
        self.eq.reset();
        self.nco.reset();
        self.demod.reset();
        self.symsync_index = 0;
        self.num_syms_rx = 0;
    }

    /// km_symtrack_execute: one input sample, at most one symbol out.
    pub fn execute(&mut self, x: C32) -> Option<SymOut> {
        let v = self.agc.execute(x);
        self.buf.clear();
        let mut buf = std::mem::take(&mut self.buf);
        self.symsync.step(v, &mut buf);
        let mut out = None;
        for &s in &buf {
            self.nco.step();
            let v = self.nco.mix_down(s);
            self.eq.push(v);
            self.symsync_index += 1;
            if self.symsync_index % 2 == 0 {
                continue;
            }
            self.num_syms_rx += 1;
            let d_hat = self.eq.execute();
            let sym = self.demod.demodulate(d_hat);
            let phase_error = self.demod.phase_error();
            self.nco.pll_step(phase_error);
            if self.num_syms_rx > 200 {
                let d_prime = self.demod.x_hat;
                self.eq.step(d_prime, d_hat);
            }
            out = Some(SymOut {
                d_hat,
                sym,
                x_hat: self.demod.x_hat,
                tau: self.symsync.tau_decim,
                nco_freq: self.nco.get_frequency(),
                nco_phase: self.nco.get_phase(),
                agc_gain: self.agc.g,
            });
        }
        self.buf = buf;
        out
    }
}

/// liquid_if.cpp demodulator()'s path from sound-card samples to the
/// tracker's input: the f + jf "complex" sample, the 1500 Hz NCO (stepped
/// before it mixes, as there), and the decimator.
pub struct AudioFront {
    nco: Nco,
    decim: FirDecim,
    ccol: [C32; 16],
    idx: usize,
    factor: usize,
}

impl AudioFront {
    /// HSmodem speed mode: `rate` the sound card's rate (48000 or 44100),
    /// `factor` its RX pre-decimation (5 for 7200 bit/s), `centre` the
    /// audio frequency of the signal (1500 Hz in HSmodem).
    pub fn new(rate: f32, factor: usize, centre: f32) -> AudioFront {
        let mut nco = Nco::new();
        nco.set_phase(0.0);
        nco.set_frequency(2.0 * std::f32::consts::PI * centre / rate);
        let mut decim = FirDecim::kaiser(factor, 8, 40.0);
        decim.set_scale(1.0 / factor as f32);
        AudioFront {
            nco,
            decim,
            ccol: [C32::ZERO; 16],
            idx: 0,
            factor,
        }
    }

    /// One sound-card sample in; a tracker input out every `factor` samples.
    #[inline]
    pub fn push(&mut self, f: f32) -> Option<C32> {
        self.nco.step();
        let c = self.nco.mix_down(C32::new(f, f));
        self.ccol[self.idx] = c;
        self.idx += 1;
        if self.idx < self.factor {
            return None;
        }
        self.idx = 0;
        Some(self.decim.execute(&self.ccol[..self.factor]))
    }
}

/// hsmodem.cpp GRdata_rxdata()'s watchdog, counted in symbols: when no
/// frame has decoded for more than 5 s and more than two frames' time has
/// passed, the tracker is reset (it may have locked to a wrong rotation
/// of nothing, or drifted off). HSmodem counts wall-clock milliseconds;
/// offline and in the IQ path, symbols are the clock.
#[derive(Debug, Clone)]
pub struct Watchdog {
    last: Option<u64>,
    symbol_rate: f32,
    frame_ms: u64,
    pub in_sync: bool,
}

impl Watchdog {
    pub fn new(symbol_rate: f32, bits_per_second: f32) -> Watchdog {
        let frame_ms = (super::frame::UDPBLOCKLEN as f32 * 8.0 * 1000.0 / bits_per_second) as u64;
        Watchdog {
            last: None,
            symbol_rate,
            frame_ms,
            in_sync: false,
        }
    }

    /// Called once a symbol; returns true when the tracker must be reset.
    pub fn on_symbol(&mut self, n: u64, frame: bool) -> bool {
        if frame {
            self.last = Some(n);
            self.in_sync = true;
            return false;
        }
        let Some(last) = self.last else {
            self.last = Some(n);
            return false;
        };
        let tdiff = ((n - last) as f32 * 1000.0 / self.symbol_rate) as u64;
        let elapsed = tdiff / self.frame_ms.max(1);
        let mut reset = false;
        if tdiff > 5000 && elapsed > 2 {
            self.in_sync = false;
            self.last = Some(n);
            reset = true;
        }
        if elapsed > 5 {
            self.in_sync = false;
        }
        reset
    }
}
