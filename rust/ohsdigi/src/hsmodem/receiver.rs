// ohsdigi - an HSmodem receiver for complex baseband (and for audio).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! What OpenHamShack NB runs on the multimedia beacon and on HSmodem stations:
//! complex baseband at whatever rate the engine's channel gives (or the
//! 12 kHz audio of an SSB receiver), resampled to four samples a symbol,
//! into HSmodem's tracker and deframer, with HSmodem's watchdog. Any of
//! HSmodem's ten speed modes (speed.rs); the beacon is mode 9. Two things
//! are ours rather than HSmodem's, and both can be switched off so the
//! chain is HSmodem's exactly (the comparison does that):
//!
//! - the **resampler** (an IQ input does not arrive at four samples a
//!   symbol), and for SSB audio a mixer and low-pass ahead of it;
//! - **coarse frequency acquisition**. HSmodem's carrier loop is narrow
//!   (bandwidth 0.0009 rad/symbol), and its user tunes by hand until it
//!   syncs ("Fine-tune the frequency ... until the synchronization is
//!   established", AMSAT-DL wiki). NB tunes by itself: the beacon is where
//!   rxCorr says, give or take what is left of the LNB's drift and of the
//!   ground station's own error. When no frame has decoded for a while,
//!   this measures the residual from the Mth power of the soft symbols -
//!   the 7th of the outer ring for 8APSK (the 1+7 constellation's carrier
//!   has a 7-fold ambiguity, so the 7th power strips the modulation;
//!   EA4GPZ's Costas loop for the beacon multiplies the angle by 7 for the
//!   same reason), the 4th for QPSK, the square for BPSK - and retunes a
//!   mixer ahead of the tracker. Its range is +-Rs/2M: +-171 Hz for the
//!   beacon, +-276 Hz for QPSK at 2205 Bd, +-300 Hz for BPSK at 1200 Bd.
//!
//! Decode quality is the modulation error ratio of the soft symbols
//! against the decided points (an Es/N0 estimate, meaningful once the
//! carrier is locked).

use super::demod::{AudioFront, SymOut, SymTrack, Watchdog};
use super::frame::{Deframer, Frame, Look};
use super::liquid::{firdes_kaiser, Nco, Scheme, C32};
use super::resample::Resampler;
use super::speed::{Speed, BEACON};

/// The beacon's mode (speed mode 9): 2400 symbols a second, four samples a
/// symbol into the tracker.
pub const SYMBOL_RATE: f32 = 2400.0;
pub const TRACK_RATE: f32 = 9600.0;
/// What the beacon's coarse frequency search can tell apart: the 7th power
/// folds every 2400/7 = 342.9 Hz onto itself (a carrier that far off turns
/// each symbol by one point of the outer ring - a constellation that looks
/// perfect and decodes to nothing). Its correction is kept within half of
/// this either side of where NB tuned, never let to walk onto an alias.
/// Other speeds: `afc_span`.
pub const AFC_SPAN: f32 = SYMBOL_RATE / 7.0;

/// The power that strips a constellation's modulation: its rotational
/// symmetry (8APSK's outer ring has seven points).
fn afc_power(scheme: Scheme) -> u32 {
    match scheme {
        Scheme::Bpsk => 2,
        Scheme::Qpsk => 4,
        Scheme::Apsk8 => 7,
    }
}

/// The coarse search's unambiguous span at a speed, Hz.
pub fn afc_span(speed: &Speed) -> f32 {
    speed.symbol_rate() / afc_power(speed.scheme()) as f32
}

/// SSB audio's front end (ours): the real audio mixed down from its
/// centre, then a low-pass that keeps the signal and the coarse search's
/// span and drops the mix's image (at minus twice the centre) and any
/// neighbour in the audio passband, before the resampler. HSmodem's own
/// audio path keeps both and lets the matched filter sort them out; with
/// the image only 120 Hz from the signal's edge at 2400 Bd, and other
/// stations' audio in the AGC's sum, a filter first is cheap and kinder.
struct SsbFront {
    nco: Nco,
    h: Vec<f32>,
    hist: Vec<C32>,
    pos: usize,
}

impl SsbFront {
    fn new(rate: f32, centre: f32, speed: &Speed) -> SsbFront {
        let mut nco = Nco::new();
        nco.set_frequency(2.0 * std::f32::consts::PI * centre / rate);
        // Pass to the RRC's edge plus the AFC's reach, transition 400 Hz.
        let edge = 0.6 * speed.symbol_rate() + afc_span(speed) / 2.0 + 200.0;
        let n = ((60.0 - 8.0) / (14.36 * 400.0 / rate)).ceil() as usize | 1;
        let mut h = firdes_kaiser(n, edge / rate, 60.0, 0.0);
        let g: f32 = h.iter().sum();
        h.iter_mut().for_each(|v| *v /= g);
        SsbFront {
            nco,
            hist: vec![C32::ZERO; 2 * n],
            h,
            pos: 0,
        }
    }

    fn push(&mut self, f: f32) -> C32 {
        self.nco.step();
        let c = self.nco.mix_down(C32::new(f, 0.0));
        let n = self.h.len();
        // A doubled ring buffer: the last n samples are always contiguous.
        self.hist[self.pos] = c;
        self.hist[self.pos + n] = c;
        self.pos = (self.pos + 1) % n;
        let w = &self.hist[self.pos..self.pos + n];
        let mut acc = C32::ZERO;
        for (x, &k) in w.iter().zip(&self.h) {
            acc = acc.add(x.scale(k));
        }
        acc
    }
}

/// Counters and quality, for the operator and the tests.
#[derive(Debug, Clone, Default)]
pub struct Stats {
    pub symbols: u64,
    pub frames_ok: u64,
    /// Frames that should have been there and did not decode: counted from
    /// the gap between good frames (688 symbols apart on a continuous
    /// stream like the beacon's), when the gap is under 30 frames.
    pub frames_lost: u64,
    /// Header hits the RS decoder refused. Most are not frames at all: the
    /// 8-symbol header (2 errors allowed) turns up inside frames about
    /// once per frame (HSmodem's receiver sees the same), so this is not a
    /// count of lost frames.
    pub fec_failed: u64,
    pub crc_failed: u64,
    pub resets: u64,
    pub corrected: u64,
    /// Symbol index of the last good frame.
    pub last_frame_symbol: Option<u64>,
    pub in_sync: bool,
    /// Modulation error ratio of recent symbols, dB.
    pub mer_db: f32,
    /// Carrier frequency the tracker's NCO holds, Hz (plus the coarse mixer).
    pub freq_hz: f32,
    pub agc_gain: f32,
    pub tau: f32,
}

/// One decoded frame and where it was found.
#[derive(Debug, Clone)]
pub struct Decoded {
    pub frame: Frame,
    /// Symbol index (since the receiver started) of the frame's last symbol.
    pub symbol: u64,
}

/// Options for the IQ receiver.
#[derive(Debug, Clone, Copy)]
pub struct Options {
    /// Coarse frequency acquisition (ours).
    pub afc: bool,
    /// HSmodem's watchdog reset.
    pub watchdog: bool,
    /// Header symbol errors allowed.
    pub max_header_errors: usize,
}

impl Default for Options {
    fn default() -> Self {
        Options {
            afc: true,
            watchdog: true,
            max_header_errors: super::frame::MAX_HEADER_ERRORS,
        }
    }
}

/// HSmodem's receiver as NB uses it.
pub struct Receiver {
    speed: Speed,
    scheme: Scheme,
    resampler: Option<Resampler>,
    audio: Option<AudioFront>,
    ssb: Option<SsbFront>,
    mixer: Nco,
    track: SymTrack,
    deframer: Deframer,
    watchdog: Watchdog,
    opts: Options,
    stats: Stats,
    mer_sig: f32,
    mer_err: f32,
    // coarse acquisition: Mth-power differential accumulator
    afc_acc: C32,
    afc_n: u32,
    afc_prev: C32,
    afc_hz: f32,
    tmp: Vec<C32>,
    ssb_tmp: Vec<C32>,
    /// Stage values of every symbol, when asked for (the comparison).
    pub record: Option<Vec<(SymOut, i8)>>,
}

impl Receiver {
    /// A receiver for the beacon's mode on complex baseband at `rate` S/s,
    /// the signal centred at 0 Hz.
    pub fn iq(rate: f32, opts: Options) -> Receiver {
        Receiver::iq_at(rate, BEACON, opts)
    }

    /// The same at any speed.
    pub fn iq_at(rate: f32, speed: Speed, opts: Options) -> Receiver {
        Receiver::build(speed, Receiver::resampler(rate, &speed), None, None, opts)
    }

    fn resampler(rate: f32, speed: &Speed) -> Option<Resampler> {
        let track = speed.track_rate();
        if (rate - track).abs() < 1e-3 {
            None
        } else {
            Some(Resampler::new(rate, track))
        }
    }

    /// A receiver for HSmodem's own audio path at the beacon's mode: real
    /// samples at `rate` (48000), the signal centred at `centre` Hz (1500),
    /// exactly as liquid_if.cpp demodulates. No AFC (HSmodem has none).
    pub fn audio(rate: f32, centre: f32, opts: Options) -> Receiver {
        Receiver::audio_at(rate, centre, BEACON, opts)
    }

    /// HSmodem's own audio path at any speed: `rate` must be a whole
    /// multiple of the speed's tracker rate (its own sound-card rate is).
    pub fn audio_at(rate: f32, centre: f32, speed: Speed, opts: Options) -> Receiver {
        let factor = (rate / speed.track_rate()).round() as usize;
        Receiver::build(
            speed,
            None,
            Some(AudioFront::new(rate, factor, centre)),
            None,
            Options { afc: false, ..opts },
        )
    }

    /// A receiver for an SSB receiver's audio (NB's 12 kHz decoder feed):
    /// real samples at any `rate`, the signal centred at `centre` Hz (1500,
    /// as HSmodem puts it), with the resampler and the coarse search.
    pub fn ssb(rate: f32, centre: f32, speed: Speed, opts: Options) -> Receiver {
        Receiver::build(
            speed,
            Receiver::resampler(rate, &speed),
            None,
            Some(SsbFront::new(rate, centre, &speed)),
            opts,
        )
    }

    pub fn speed(&self) -> Speed {
        self.speed
    }

    fn build(
        speed: Speed,
        resampler: Option<Resampler>,
        audio: Option<AudioFront>,
        ssb: Option<SsbFront>,
        opts: Options,
    ) -> Receiver {
        let scheme = speed.scheme();
        let mut deframer = Deframer::new(scheme);
        deframer.set_max_header_errors(opts.max_header_errors);
        Receiver {
            speed,
            scheme,
            resampler,
            audio,
            ssb,
            mixer: Nco::new(),
            track: SymTrack::hsmodem(scheme),
            deframer,
            watchdog: Watchdog::new(speed.symbol_rate(), speed.bitrate as f32),
            opts,
            stats: Stats::default(),
            mer_sig: 0.0,
            mer_err: 0.0,
            afc_acc: C32::ZERO,
            afc_n: 0,
            afc_prev: C32::ZERO,
            afc_hz: 0.0,
            tmp: Vec::new(),
            ssb_tmp: Vec::new(),
            record: None,
        }
    }

    /// Start acquisition again, from the frequency tuned: for when the
    /// caller has moved the channel (NB: a new receive correction) and
    /// whatever the loops had learnt is wrong by that much. Counters stay.
    pub fn reset(&mut self) {
        self.track.reset();
        self.deframer.reset();
        self.afc_hz = 0.0;
        self.afc_acc = C32::ZERO;
        self.afc_n = 0;
        self.afc_prev = C32::ZERO;
        self.mixer.reset();
        self.stats.resets += 1;
    }

    pub fn stats(&self) -> Stats {
        let mut s = self.stats.clone();
        s.in_sync = self.watchdog.in_sync;
        s
    }

    /// Feed SSB audio (`ssb` receivers).
    pub fn feed_ssb(&mut self, a: &[f32], out: &mut Vec<Decoded>) {
        let mut c = std::mem::take(&mut self.ssb_tmp);
        c.clear();
        let front = self.ssb.as_mut().expect("an SSB receiver");
        c.extend(a.iter().map(|&f| front.push(f)));
        self.feed_iq(&c, out);
        self.ssb_tmp = c;
    }

    /// Feed complex baseband (IQ receivers).
    pub fn feed_iq(&mut self, x: &[C32], out: &mut Vec<Decoded>) {
        let mut tmp = std::mem::take(&mut self.tmp);
        tmp.clear();
        match &mut self.resampler {
            Some(r) => r.process(x, &mut tmp),
            None => tmp.extend_from_slice(x),
        }
        for &v in &tmp {
            let v = if self.afc_hz != 0.0 {
                self.mixer.step();
                self.mixer.mix_down(v)
            } else {
                v
            };
            self.track_one(v, out);
        }
        self.tmp = tmp;
    }

    /// Feed sound-card samples (audio receivers).
    pub fn feed_audio(&mut self, a: &[f32], out: &mut Vec<Decoded>) {
        for &f in a {
            let y = self.audio.as_mut().expect("an audio receiver").push(f);
            if let Some(y) = y {
                self.track_one(y, out);
            }
        }
    }

    fn track_one(&mut self, v: C32, out: &mut Vec<Decoded>) {
        let Some(s) = self.track.execute(v) else { return };
        let n = self.stats.symbols;
        self.stats.symbols += 1;
        let look = self.deframer.push(super::frame::gray(self.scheme, s.sym));
        let mut flag = 0i8;
        let mut frame = false;
        match look {
            Look::Frame(f) => {
                flag = 1;
                frame = true;
                self.stats.frames_ok += 1;
                self.stats.corrected += f.corrected as u64;
                if let Some(last) = self.stats.last_frame_symbol {
                    let per = self.speed.frame_symbols() as u64;
                    let gap = ((n - last) as f64 / per as f64).round() as u64;
                    if (2..30).contains(&gap) {
                        self.stats.frames_lost += gap - 1;
                    }
                }
                self.stats.last_frame_symbol = Some(n);
                out.push(Decoded { frame: f, symbol: n });
            }
            Look::FecFailed => {
                flag = -1;
                self.stats.fec_failed += 1;
            }
            Look::CrcFailed => {
                flag = -2;
                self.stats.crc_failed += 1;
            }
            Look::Nothing => {}
        }
        if let Some(rec) = &mut self.record {
            rec.push((s, flag));
        }
        // Quality: exponential average over ~500 symbols.
        let a = 0.002f32;
        let e = s.d_hat.sub(s.x_hat).norm_sqr();
        let p = s.x_hat.norm_sqr().max(1e-9);
        self.mer_sig = (1.0 - a) * self.mer_sig + a * p;
        self.mer_err = (1.0 - a) * self.mer_err + a * e;
        self.stats.mer_db = 10.0 * (self.mer_sig / self.mer_err.max(1e-12)).log10();
        self.stats.freq_hz = s.nco_freq * self.speed.track_rate() / 2.0 / std::f32::consts::PI / 2.0 + self.afc_hz;
        self.stats.agc_gain = s.agc_gain;
        self.stats.tau = s.tau;
        if self.opts.afc {
            self.afc(&s, frame);
        }
        if self.opts.watchdog && self.watchdog.on_symbol(n, frame) {
            self.track.reset();
            self.stats.resets += 1;
        }
    }

    /// Coarse acquisition: average the symbol-to-symbol rotation of the Mth
    /// power of the soft symbols (8APSK: the outer ring's) over half a
    /// second; while no frame has decoded for a second, a rotation the PLL
    /// is not removing is moved to the mixer and the tracker restarted.
    fn afc(&mut self, s: &SymOut, frame: bool) {
        if frame {
            self.afc_acc = C32::ZERO;
            self.afc_n = 0;
            return;
        }
        let d = s.d_hat;
        let m = afc_power(self.scheme);
        let rs = self.speed.symbol_rate();
        // 8APSK's centre point has no phase; a PSK symbol always has one.
        if self.scheme != Scheme::Apsk8 || d.abs() > 0.6 {
            let mut p = d;
            for _ in 1..m {
                p = p.mul(d);
            }
            let r = p.abs().max(1e-9);
            let p = p.scale(1.0 / r);
            if self.afc_prev != C32::ZERO {
                self.afc_acc = self.afc_acc.add(p.mul(self.afc_prev.conj()));
            }
            self.afc_prev = p;
        }
        self.afc_n += 1;
        if (self.afc_n as f32) < rs / 2.0 {
            return;
        }
        let w = self.afc_acc.arg() / m as f32; // rad per symbol
        let hz = w * rs / (2.0 * std::f32::consts::PI);
        self.afc_acc = C32::ZERO;
        self.afc_n = 0;
        self.afc_prev = C32::ZERO;
        let since = self
            .stats
            .last_frame_symbol
            .map(|f| self.stats.symbols - f)
            .unwrap_or(u64::MAX);
        if since as f32 > rs && hz.abs() > 2.0 {
            let span = afc_span(&self.speed);
            let half = span / 2.0;
            self.afc_hz = (self.afc_hz + hz + half).rem_euclid(span) - half;
            self.mixer
                .set_frequency(2.0 * std::f32::consts::PI * self.afc_hz / self.speed.track_rate());
            self.track.reset();
        }
    }
}
