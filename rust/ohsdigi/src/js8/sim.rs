// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! Deterministic JS8 test slots: transmissions from [`super::waveform`]
//! at a given SNR in white noise, scaled as `crate::decode::sim` scales
//! FT8's (signal sqrt(2 x 2500/6000) x 10^(SNR/20) against unit noise, so
//! the SNR is in WSJT-X's and JS8Call's 2500 Hz reference bandwidth; then
//! x100 and rounded to int16 units, which is what a decoder is fed).

use super::{tones, waveform, Submode};
use crate::decode::sim::Rng;

#[derive(Clone, Debug)]
pub struct SimSignal {
    pub frame: String,
    pub i3bit: u8,
    /// Frequency of tone 0, Hz.
    pub freq: f64,
    /// Seconds from the speed's nominal start (ASTART into the period).
    pub dt: f64,
    pub snr_db: f64,
}

/// Samples in one period of `sub`.
pub fn slot_samples(sub: Submode) -> usize {
    (sub.params().period * 12000.0) as usize
}

/// One period of audio holding `signals`, with noise from `seed` when
/// `noise` is set.
pub fn make_slot(sub: Submode, signals: &[SimSignal], seed: u64, noise: bool) -> Vec<f32> {
    let n = slot_samples(sub);
    let mut wave = vec![0f64; n];
    let bandwidth_ratio = 2500.0 / 6000.0;
    for s in signals {
        let sig = (2.0f64 * bandwidth_ratio).sqrt() * 10f64.powf(0.05 * s.snr_db);
        let t = tones(&s.frame, s.i3bit, sub).expect("a valid frame");
        let w = waveform(&t, s.freq, 12000.0, sub);
        let start = ((s.dt + sub.params().astart as f64) * 12000.0).round() as i64;
        for (k, v) in w.iter().enumerate() {
            let j = start + k as i64;
            if j >= 0 && (j as usize) < n {
                wave[j as usize] += sig * *v as f64;
            }
        }
    }
    if noise {
        let mut rng = Rng::new(seed);
        for v in wave.iter_mut() {
            *v += rng.gauss();
        }
    }
    wave.iter().map(|v| (100.0 * v).round().clamp(-32767.0, 32767.0) as f32).collect()
}

/// A random frame of the 64 characters a frame can carry.
pub fn random_frame(rng: &mut Rng) -> String {
    (0..12).map(|_| super::ALPHABET[(rng.next_u64() % 64) as usize] as char).collect()
}

/// A crowded random slot, as tests/js8_golden.rs and `js8dev batch` make
/// them: 1-6 random frames with random headers, SNR -24..+5 dB, spread
/// over 300-2700 Hz no closer than eight tones plus 10 Hz (60 Hz at
/// least), DT -0.5..+1.5 s; then the noise seed. Draws from `rng` in a
/// fixed order, so the same seed gives the same slot everywhere.
pub fn crowded(sub: Submode, rng: &mut Rng) -> (Vec<SimSignal>, u64) {
    let width = 8.0 * sub.tone_spacing() + 10.0;
    let nsig = 1 + (rng.next_u64() % 6) as usize;
    let mut sigs: Vec<SimSignal> = Vec::new();
    while sigs.len() < nsig {
        let freq = rng.range(300.0, 2700.0 - width);
        if sigs.iter().any(|s| (s.freq - freq).abs() < width.max(60.0)) {
            continue;
        }
        sigs.push(SimSignal {
            frame: random_frame(rng),
            i3bit: (rng.next_u64() % 8) as u8,
            freq,
            dt: rng.range(-0.5, 1.5),
            snr_db: rng.range(-24.0, 5.0),
        });
    }
    let seed = rng.next_u64();
    (sigs, seed)
}
