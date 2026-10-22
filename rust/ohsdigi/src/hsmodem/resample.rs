// ohsdigi - an arbitrary-ratio resampler for HSmodem's IQ and SSB paths.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! Ours, not HSmodem's: HSmodem only ever runs at its sound card's rate.
//! The receiver uses it to bring NB's channel (12 kHz) to the tracker's
//! four samples a symbol, and the transmitter to bring HSmodem's own
//! sound-card pulse shaping (44.1 or 48 kHz) to NB's 12 kHz audio.

use super::liquid::C32;

/// Arbitrary-ratio resampler: a Kaiser-windowed sinc, 64 phases,
/// interpolated linearly between phases. Ours (HSmodem never resamples
/// IQ); flat to beyond the beacon's +-1.44 kHz.
pub struct Resampler {
    step: f64,
    t: f64,
    hist: Vec<C32>,
    taps: usize,
    phases: usize,
    h: Vec<f32>,
}

impl Resampler {
    pub fn new(in_rate: f32, out_rate: f32) -> Resampler {
        let taps = 24usize;
        let phases = 64usize;
        let cutoff = 0.42 * out_rate.min(in_rate) / in_rate; // cycles per input sample
        let len = taps * phases + 1;
        let beta = 7.0f64;
        let i0 = |x: f64| {
            let mut s = 1.0;
            let mut t = 1.0;
            for k in 1..30 {
                t *= (x / 2.0) / k as f64;
                s += t * t;
            }
            s
        };
        let mut h = vec![0.0f32; len];
        let mid = (len - 1) as f64 / 2.0;
        for (i, v) in h.iter_mut().enumerate() {
            let t = (i as f64 - mid) / phases as f64; // in input samples
            let x = 2.0 * cutoff as f64 * t;
            let sinc = if x.abs() < 1e-12 {
                1.0
            } else {
                (std::f64::consts::PI * x).sin() / (std::f64::consts::PI * x)
            };
            let r = (i as f64 - mid) / mid;
            let w = i0(beta * (1.0 - r * r).max(0.0).sqrt()) / i0(beta);
            *v = (2.0 * cutoff as f64 * sinc * w) as f32;
        }
        Resampler {
            step: in_rate as f64 / out_rate as f64,
            t: 0.0,
            hist: vec![C32::ZERO; taps],
            taps,
            phases,
            h,
        }
    }

    /// Feed input samples; outputs appended.
    pub fn process(&mut self, x: &[C32], out: &mut Vec<C32>) {
        for &s in x {
            self.hist.copy_within(1.., 0);
            let n = self.hist.len();
            self.hist[n - 1] = s;
            // Outputs whose time falls within the newest input interval.
            while self.t < 1.0 {
                // Output at fractional time t before the newest sample:
                // filter centre sits taps/2 samples back.
                let mu = self.t; // 0..1
                let mut acc = C32::ZERO;
                for k in 0..self.taps {
                    // distance from the output instant to hist[k], in input samples
                    let d = (self.taps - 1 - k) as f64 + mu - (self.taps as f64 / 2.0);
                    let pos = (d + self.taps as f64 / 2.0) * self.phases as f64;
                    if pos < 0.0 || pos >= (self.h.len() - 1) as f64 {
                        continue;
                    }
                    let i = pos.floor() as usize;
                    let fr = (pos - i as f64) as f32;
                    let c = self.h[i] * (1.0 - fr) + self.h[i + 1] * fr;
                    acc = acc.add(self.hist[k].scale(c));
                }
                out.push(acc);
                self.t += self.step;
            }
            self.t -= 1.0;
        }
    }
}
