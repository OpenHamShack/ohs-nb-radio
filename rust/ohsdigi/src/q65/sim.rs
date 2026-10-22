// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! Deterministic Q65 test periods: transmissions from [`super::waveform`]
//! at a given SNR in white noise, scaled as `crate::decode::sim` scales
//! FT8's (signal sqrt(2 x 2500/6000) x 10^(SNR/20) against unit noise, so
//! the SNR is in WSJT-X's 2500 Hz reference bandwidth; then x100 and
//! rounded to int16 units).

use super::{encode, start_delay, tone_spacing, waveform};
use crate::decode::sim::Rng;

#[derive(Clone, Debug)]
pub struct SimSignal {
    pub message: String,
    /// Frequency of the sync tone, Hz.
    pub freq: f64,
    pub snr_db: f64,
    /// Seconds from the nominal start (start_delay into the period).
    pub dt: f64,
}

/// One period holding `signals`, noise from `seed`.
pub fn make_period(period: u32, submode: usize, signals: &[SimSignal], seed: u64) -> Vec<f32> {
    let n = period as usize * 12000;
    let mut wave = vec![0f64; n];
    for s in signals {
        let e = encode(&s.message).expect("a message Q65 can send");
        let w = waveform(&e.tones, s.freq, 12000.0, period, submode);
        let amp = (2.0f64 * 2500.0 / 6000.0).sqrt() * 10f64.powf(0.05 * s.snr_db);
        let start = ((start_delay(period) + s.dt) * 12000.0).round() as i64;
        for (k, v) in w.iter().enumerate() {
            let j = start + k as i64;
            if j >= 0 && (j as usize) < n {
                wave[j as usize] += amp * *v as f64;
            }
        }
    }
    let mut rng = Rng::new(seed);
    for v in wave.iter_mut() {
        *v += rng.gauss();
    }
    wave.iter().map(|v| (100.0 * v).round().clamp(-32767.0, 32767.0) as f32).collect()
}

const CALLS: &[&str] = &["K1ABC", "W9XYZ", "G4XYZ", "GM4BRI", "DL1ABC", "VK3ACF", "JA1XYZ", "PA3ABC", "F5ABC", "OH2XYZ"];
const GRIDS: &[&str] = &["FN42", "EN37", "IO91", "IO75", "JO62", "QF22", "PM95", "JO22", "JN18", "KP20"];

/// A random standard exchange message (CQ, grid, report, R-report, RR73, 73).
pub fn random_message(rng: &mut Rng) -> String {
    let pick = |rng: &mut Rng, v: &[&str]| v[(rng.next_u64() % v.len() as u64) as usize].to_string();
    let a = pick(rng, CALLS);
    let mut b = pick(rng, CALLS);
    while b == a {
        b = pick(rng, CALLS);
    }
    match rng.next_u64() % 6 {
        0 => format!("CQ {a} {}", pick(rng, GRIDS)),
        1 => format!("{a} {b} {}", pick(rng, GRIDS)),
        2 => format!("{a} {b} {:+03}", (rng.next_u64() % 40) as i32 - 30),
        3 => format!("{a} {b} R{:+03}", (rng.next_u64() % 40) as i32 - 30),
        4 => format!("{a} {b} RR73"),
        _ => format!("{a} {b} 73"),
    }
}

/// A crowded random period, as tests/q65_golden.rs and `q65dev batch`
/// make them: up to four signals between 400 and 2600 Hz, no two
/// overlapping, SNR -30..0 dB, DT -0.5..+1.5 s, and half the time one
/// more within 5 Hz of 1500 Hz (the receive frequency) at -30..-5 dB;
/// then the noise seed. Draws from `rng` in a fixed order.
pub fn crowded(period: u32, submode: usize, rng: &mut Rng) -> (Vec<SimSignal>, u64) {
    let width = 65.0 * tone_spacing(period, submode) + 20.0;
    // Few enough that random placement can never paint itself into a
    // corner: each signal placed rules out at most 2 x width of the span.
    let span = (2600.0 - width - 400.0).max(1.0);
    let room = ((span / (2.0 * width)).ceil() as usize).clamp(1, 4);
    let nsig = 1 + (rng.next_u64() % room as u64) as usize;
    let mut sigs: Vec<SimSignal> = Vec::new();
    while sigs.len() < nsig {
        let f = rng.range(400.0, (2600.0 - width).max(401.0));
        if sigs.iter().any(|s| (s.freq - f).abs() < width) {
            continue;
        }
        sigs.push(SimSignal { message: random_message(rng), freq: f, snr_db: rng.range(-30.0, 0.0), dt: rng.range(-0.5, 1.5) });
    }
    if rng.next_u64() % 2 == 0 && !sigs.iter().any(|s| (s.freq - 1500.0).abs() < width) {
        sigs.push(SimSignal {
            message: random_message(rng),
            freq: 1500.0 + rng.range(-5.0, 5.0),
            snr_db: rng.range(-30.0, -5.0),
            dt: rng.range(-0.3, 0.8),
        });
    }
    (sigs, rng.next_u64())
}
