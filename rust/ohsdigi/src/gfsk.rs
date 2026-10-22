// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from WSJT-X 2.7.0, lib/ft8/gen_ft8wave.f90, lib/ft4/gen_ft4wave.f90
// and lib/gfsk_pulse.f90, copyright (C) 2001-2023 Joe Taylor K1JT, Steve
// Franke K9AN and the WSJT Development Group, GPL-3.0-or-later.

//! Continuous-phase GFSK audio from channel symbols, as WSJT-X makes it.
//!
//! Each symbol's frequency step is smoothed by a Gaussian pulse three
//! symbols long (BT = 2 for FT8, 1 for FT4) and the smoothed frequency is
//! integrated to phase; the first and last symbols are shaped in amplitude
//! so a transmission starts and stops without a click. This replaced a
//! numpy convolution in ohscore/modes/ft8.py whose filter width was chosen
//! until jt9 decoded it, not taken from WSJT-X. A decoder that subtracts
//! each signal it finds (WSJT-X's does, and phase 2's will) needs exactly
//! this waveform anyway, so it lives with the encoder.
//!
//! The arithmetic is single precision, step for step as WSJT-X's Fortran
//! does it, on purpose. Done in double precision the result was "better"
//! and measurably not WSJT-X's: the per-sample phase increments rounded to
//! f32 put a slow phase drift into WSJT-X's waveform, up to 75/32767 of
//! full scale by the end of an FT8 transmission. In f32 it matches
//! WSJT-X's own ft8sim output to within its table lookup's rounding (a
//! few parts in 10^4; tests/test_ohsdigi.py checks), which makes this a
//! port that can be verified rather than an approximation of one.

/// erf in double precision (to about 1e-15): a Taylor series near zero
/// and Lentz's continued fraction for erfc further out. Rust's standard
/// library has none; rounded to f32 it gives what single-precision erff
/// gives, which is what gfsk_pulse calls in WSJT-X.
fn erf(x: f64) -> f64 {
    let z = x.abs();
    let r = if z < 3.0 {
        let mut sum = 0.0f64;
        let mut term = z; // z^(2n+1) (-1)^n / n!
        let mut n = 0.0;
        while term.abs() > 1e-17 * sum.abs().max(1e-300) || n < 3.0 {
            sum += term / (2.0 * n + 1.0);
            n += 1.0;
            term *= -z * z / n;
            if n > 200.0 {
                break;
            }
        }
        sum * 2.0 / std::f64::consts::PI.sqrt()
    } else if z < 10.0 {
        // erfc(z) = exp(-z^2)/sqrt(pi) * 1/(z + (1/2)/(z + 1/(z + (3/2)/(z + ...))))
        let tiny = 1e-300;
        let mut f = z;
        let mut c = z;
        let mut d = 0.0;
        for k in 1..200 {
            let a = k as f64 / 2.0;
            d = z + a * d;
            d = if d.abs() < tiny { tiny } else { d };
            c = z + a / c;
            c = if c.abs() < tiny { tiny } else { c };
            d = 1.0 / d;
            let delta = c * d;
            f *= delta;
            if (delta - 1.0).abs() < 1e-16 {
                break;
            }
        }
        1.0 - (-z * z).exp() / std::f64::consts::PI.sqrt() / f
    } else {
        1.0
    };
    if x < 0.0 {
        -r
    } else {
        r
    }
}

fn erff(x: f32) -> f32 {
    erf(x as f64) as f32
}

/// gfsk_pulse: the frequency pulse of one symbol, `t` in symbols from its
/// centre, in WSJT-X's single precision.
pub fn gfsk_pulse(b: f32, t: f32) -> f32 {
    let pi = 4.0f32 * 1.0f32.atan();
    let c = pi * (2.0f32 / 2.0f32.ln()).sqrt();
    0.5f32 * (erff(c * b * (t + 0.5)) - erff(c * b * (t - 0.5)))
}

/// The smoothed per-sample phase increments, carrier included: (nsym + 2)
/// symbols, each symbol's pulse starting one symbol before it.
fn dphi(tones: &[u8], nsps: usize, bt: f32, f0: f32, fs: f32, extend_ends: bool) -> Vec<f32> {
    let nsym = tones.len();
    let twopi = 8.0f32 * 1.0f32.atan();
    let dt = 1.0f32 / fs;
    let pulse: Vec<f32> = (1..=3 * nsps)
        .map(|i| gfsk_pulse(bt, (i as f32 - 1.5 * nsps as f32) / nsps as f32))
        .collect();
    let dphi_peak = twopi * 1.0f32 / nsps as f32;
    let mut d = vec![0.0f32; (nsym + 2) * nsps];
    for (j, &tone) in tones.iter().enumerate() {
        let ib = j * nsps;
        for (x, p) in d[ib..ib + 3 * nsps].iter_mut().zip(pulse.iter()) {
            *x += dphi_peak * p * tone as f32;
        }
    }
    if extend_ends {
        // Dummy symbols before the first and after the last, of the same
        // tones, so their pulses do not fall back towards tone 0.
        let (first, last) = (tones[0] as f32, tones[nsym - 1] as f32);
        for i in 0..2 * nsps {
            d[i] += dphi_peak * first * pulse[nsps + i];
            d[nsym * nsps + i] += dphi_peak * last * pulse[i];
        }
    }
    let carrier = twopi * f0 * dt;
    for x in d.iter_mut() {
        *x += carrier;
    }
    d
}

/// Integrate `dphi[start..start+n]` to a sine, as WSJT-X's real-valued path
/// (icmplx = 0, the one its transmitter uses) does.
fn integrate(dphi: &[f32], start: usize, n: usize) -> Vec<f32> {
    let twopi = 8.0f32 * 1.0f32.atan();
    let mut phi = 0.0f32;
    let mut out = Vec::with_capacity(n);
    for &d in &dphi[start..start + n] {
        out.push(phi.sin());
        phi = (phi + d) % twopi;
    }
    out
}

/// The raised-cosine ramp up over the first `nramp` samples and down over
/// the `nramp` from `end_from`.
fn ramp(wave: &mut [f32], nramp: usize, end_from: usize) {
    let twopi = 8.0f32 * 1.0f32.atan();
    for i in 0..nramp {
        let g = (twopi * i as f32 / (2.0f32 * nramp as f32)).cos();
        wave[i] *= (1.0f32 - g) / 2.0f32;
        wave[end_from + i] *= (1.0f32 + g) / 2.0f32;
    }
}

fn nsps_at(nsps12k: usize, fs: f64) -> usize {
    (nsps12k as f64 * fs / 12_000.0).round() as usize
}

/// gen_ft8wave: 79 symbols' audio, 151 680 samples at 12 kHz, tone 0 at
/// `f0` Hz. The end symbols are extended into the pulse's tails by dummy
/// symbols of the same tone, then ramped over an eighth of a symbol.
pub fn ft8_waveform(tones: &[u8], f0: f64, fs: f64) -> Vec<f32> {
    if tones.is_empty() {
        return Vec::new();
    }
    let nsps = nsps_at(crate::ft8::NSPS, fs);
    let d = dphi(tones, nsps, crate::ft8::BT as f32, f0 as f32, fs as f32, true);
    let nwave = tones.len() * nsps;
    let mut wave = integrate(&d, nsps, nwave);
    let nramp = (nsps as f32 / 8.0).round() as usize;
    ramp(&mut wave, nramp, nwave - nramp);
    wave
}

/// gen_ft4wave: 103 symbols plus the ramp-up and ramp-down symbols, 60 480
/// samples at 12 kHz, tone 0 at `f0` Hz. Unlike FT8 the ramps are whole
/// symbols, and nothing extends the end symbols' tones.
pub fn ft4_waveform(tones: &[u8], f0: f64, fs: f64) -> Vec<f32> {
    if tones.is_empty() {
        return Vec::new();
    }
    let nsps = nsps_at(crate::ft4::NSPS, fs);
    let d = dphi(tones, nsps, crate::ft4::BT as f32, f0 as f32, fs as f32, false);
    let nwave = (tones.len() + 2) * nsps;
    let mut wave = integrate(&d, 0, nwave);
    ramp(&mut wave, nsps, (tones.len() + 1) * nsps);
    wave
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn erf_values() {
        for (x, want) in [
            (0.0, 0.0),
            (0.5, 0.520_499_877_813_046_5),
            (1.0, 0.842_700_792_949_714_9),
            (-1.0, -0.842_700_792_949_714_9),
            (2.5, 0.999_593_047_982_555),
            (3.5, 0.999_999_256_901_627_7),
        ] {
            assert!((erf(x) - want).abs() < 1e-14, "erf({x}) = {}", erf(x));
        }
    }

    #[test]
    fn pulse_sums_to_one_symbol() {
        // The pulse spreads one symbol's frequency step: its integral is 1.
        let n = 3000;
        let s: f64 = (0..n)
            .map(|i| gfsk_pulse(2.0, -1.5 + 3.0 * (i as f32 + 0.5) / n as f32) as f64 * 3.0 / n as f64)
            .sum();
        assert!((s - 1.0).abs() < 1e-4, "{s}");
    }

    #[test]
    fn lengths() {
        assert_eq!(ft8_waveform(&[0u8; 79], 1500.0, 12_000.0).len(), 79 * 1920);
        assert_eq!(ft4_waveform(&[0u8; 103], 1500.0, 12_000.0).len(), 105 * 576);
    }

    #[test]
    fn steady_tone_is_at_its_frequency() {
        // Every symbol tone 3: a sine at f0 + 3 x 6.25 Hz once the ramp is
        // over - count its zero crossings over one second.
        let w = ft8_waveform(&[3u8; 79], 1000.0, 12_000.0);
        let crossings = w[5000..17_000]
            .windows(2)
            .filter(|p| (p[0] <= 0.0) != (p[1] <= 0.0))
            .count();
        assert!(((crossings as f64 / 2.0) - 1018.75).abs() <= 1.0, "{crossings}");
        assert!(w.iter().all(|s| s.abs() <= 1.0));
    }
}
