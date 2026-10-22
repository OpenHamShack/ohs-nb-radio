//! Deterministic FT8/FT4 test slots, so the decoder's tests need neither
//! jt9 nor stored audio: a seed and a list of signals define a slot.
//!
//! Levels and noise follow WSJT-X's own simulators (lib/ft8/ft8sim.f90,
//! lib/ft4/ft4sim.f90, GPL-3, K1JT et al.): signal amplitude
//! sqrt(2 * 2500/6000) * 10^(SNR/20) against unit-variance Gaussian noise,
//! so SNR is in WSJT-X's 2500 Hz reference bandwidth, then x100 and rounded
//! to 16-bit sample units. The waveform is the Gaussian-filtered FSK of
//! gen_ft8wave / gen_ft4wave (BT 2.0 / 1.0), evaluated in double
//! precision, with an optional linear frequency drift that WSJT-X's
//! simulators do not offer.

use super::util::gfsk_pulse;
use crate::ft4::tones as ft4_tones;
use crate::ft8::tones as ft8_tones;

/// Real messages for test slots, packed by WSJT-X 2.7.0's ft8code
/// ("Source-encoded message", 77 bits as hex, MSB first). Standard
/// exchanges, CQ variants, a free-text and a non-standard-call message.
pub const PAYLOAD_POOL: &[(&str, &str)] = &[
    ("CQ K1ABC FN42", "000000204def1a8a1988"),
    ("CQ G4XYZ IO91", "000000204882b48f84c8"),
    ("CQ DL1ABC JO31", "00000023444a119137c8"),
    ("G4XYZ EA4QRP IN80", "091056936a5fe38f6908"),
    ("EA4QRP G4XYZ -08", "6d4bfc704882b49faac8"),
    ("CQ DX OH8ZZ KP24", "000046f59225ff131108"),
    ("DL1ABC F5KLM JN18", "6889423047157e911b88"),
    ("F5KLM DL1ABC R-12", "08e2afd3444a11bfa9c8"),
    ("CQ PA3QOS JO22", "00000025bce4ff113588"),
    ("I0XYZ ON4BB RR73", "095d39959a6b631f9d48"),
    ("CQ SV1QO KM18", "000000267e500192c488"),
    ("K1ABC W9XYZ EN37", "09bde3506149dc085648"),
    ("W9XYZ K1ABC -11", "0c293b804def1a9faa08"),
    ("K1ABC W9XYZ R-09", "09bde3506149dc3faa88"),
    ("W9XYZ K1ABC RRR", "0c293b804def1a9fa488"),
    ("K1ABC W9XYZ 73", "09bde3506149dc1fa508"),
    ("CQ JA1XYZ PM95", "000000247844f61ba1c8"),
    ("VK2ABC ZL1XYZ RF73", "e2012187e9c37b1e7148"),
    ("ZL1XYZ VK2ABC R+02", "fd386f6710090c3fad48"),
    ("CQ WB4ABC EM73", "0000002738e1a4084648"),
    ("N0CALL G0ABC IO82", "01de7cb96000d9199200"),
    ("G0ABC N0CALL -20", "01531689ea735b5cac00"),
    ("CQ GM4BRI IO86", "00000023e86ef08f8388"),
    ("M0XYZ 2E0ABC IO91", "0a1d7110e6f4e30f84c8"),
    ("TNX BOB 73 GL", "63edcee2a4ae07f50000"),
    ("CQ TEST K1ABC FN42", "00615f904def1a8a1988"),
    ("PY2ABC LU1XYZ GF05", "bc162ec5026cda0b0a48"),
    ("CQ 9A1ABC JN75", "000000225b86dc9129c8"),
    ("EA8ABC CT1XYZ RR73", "6d5c40631a5fef1f9d48"),
    ("CQ UA3ABC KO85", "00000026cb1b8b930748"),
];

pub fn payload_pool() -> Vec<[u8; 77]> {
    PAYLOAD_POOL.iter().map(|(_, h)| hex_to_bits77(h).unwrap()).collect()
}

/// 77 bits as 20 hex digits, MSB first (the last digit's low 3 bits are 0):
/// a compact, greppable form for test data and the harness.
pub fn bits77_to_hex(b: &[u8; 77]) -> String {
    let mut bytes = [0u8; 10];
    for (i, &bit) in b.iter().enumerate() {
        if bit != 0 {
            bytes[i / 8] |= 0x80 >> (i % 8);
        }
    }
    bytes.iter().map(|x| format!("{:02x}", x)).collect()
}

pub fn hex_to_bits77(h: &str) -> Option<[u8; 77]> {
    if h.len() != 20 {
        return None;
    }
    let mut out = [0u8; 77];
    for (i, o) in out.iter_mut().enumerate() {
        let byte = u8::from_str_radix(h.get(2 * (i / 8)..2 * (i / 8) + 2)?, 16).ok()?;
        *o = (byte >> (7 - (i % 8))) & 1;
    }
    Some(out)
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Mode {
    Ft8,
    Ft4,
}

impl Mode {
    pub fn slot_samples(self) -> usize {
        match self {
            Mode::Ft8 => 15 * 12000,
            Mode::Ft4 => 21 * 3456,
        }
    }
}

#[derive(Clone, Debug)]
pub struct SimSignal {
    pub payload: [u8; 77],
    pub freq: f64,
    /// Seconds relative to the nominal 0.5 s start (WSJT-X's DT).
    pub dt: f64,
    pub snr_db: f64,
    /// Linear drift, Hz per second, about the start frequency.
    pub drift_hz_s: f64,
}

/// splitmix64: tiny, seedable, the same on every platform.
pub struct Rng(u64);

impl Rng {
    pub fn new(seed: u64) -> Self {
        Rng(seed)
    }
    pub fn next_u64(&mut self) -> u64 {
        self.0 = self.0.wrapping_add(0x9E37_79B9_7F4A_7C15);
        let mut z = self.0;
        z = (z ^ (z >> 30)).wrapping_mul(0xBF58_476D_1CE4_E5B9);
        z = (z ^ (z >> 27)).wrapping_mul(0x94D0_49BB_1331_11EB);
        z ^ (z >> 31)
    }
    /// Uniform in (0, 1).
    pub fn uniform(&mut self) -> f64 {
        ((self.next_u64() >> 11) as f64 + 0.5) / (1u64 << 53) as f64
    }
    pub fn range(&mut self, a: f64, b: f64) -> f64 {
        a + (b - a) * self.uniform()
    }
    pub fn gauss(&mut self) -> f64 {
        let u1 = self.uniform();
        let u2 = self.uniform();
        (-2.0 * u1.ln()).sqrt() * (2.0 * std::f64::consts::PI * u2).cos()
    }
}

/// One real GFSK transmission (unit amplitude), the audio it occupies in
/// the slot starting at sample `start` (may be negative).
fn waveform(mode: Mode, s: &SimSignal) -> (Vec<f64>, i64) {
    let (tones, nsps, bt): (Vec<u8>, usize, f64) = match mode {
        Mode::Ft8 => (ft8_tones(&s.payload).to_vec(), 1920, 2.0),
        Mode::Ft4 => {
            // FT4 adds a ramp symbol at each end (tone 0): 105 in all.
            let mut t = vec![0u8];
            t.extend_from_slice(&ft4_tones(&s.payload));
            t.push(0);
            (t, 576, 1.0)
        }
    };
    let nsym = tones.len();
    let fs = 12000.0f64;
    let twopi = 2.0 * std::f64::consts::PI;
    let pulse: Vec<f64> = (1..=3 * nsps)
        .map(|i| gfsk_pulse(bt as f32, ((i as f64 - 1.5 * nsps as f64) / nsps as f64) as f32) as f64)
        .collect();
    let dphi_peak = twopi / nsps as f64;
    // As gen_ft8wave: (nsym+2) symbols of frequency, first and last
    // extended so the smoothing does not droop at the ends.
    let mut dphi = vec![0f64; (nsym + 2) * nsps];
    for j in 0..nsym {
        for t in 0..3 * nsps {
            dphi[j * nsps + t] += dphi_peak * pulse[t] * tones[j] as f64;
        }
    }
    for t in 0..2 * nsps {
        dphi[t] += dphi_peak * tones[0] as f64 * pulse[nsps + t];
        dphi[nsym * nsps + t] += dphi_peak * tones[nsym - 1] as f64 * pulse[t];
    }
    let n = nsym * nsps;
    let mut out = vec![0f64; n];
    let mut phi = 0f64;
    for k in 0..n {
        out[k] = phi.sin();
        let tsec = k as f64 / fs;
        let f = s.freq + s.drift_hz_s * tsec;
        phi = (phi + dphi[nsps + k] + twopi * f / fs) % twopi;
    }
    let nramp = match mode {
        Mode::Ft8 => nsps / 8,
        Mode::Ft4 => nsps,
    };
    for i in 0..nramp {
        let w = (1.0 - (twopi * i as f64 / (2.0 * nramp as f64)).cos()) / 2.0;
        out[i] *= w;
        out[n - nramp + i] *= 1.0 - w;
    }
    let start = match mode {
        Mode::Ft8 => ((s.dt + 0.5) * fs).round() as i64,
        Mode::Ft4 => ((s.dt + 0.5) * fs).round() as i64 - nsps as i64,
    };
    (out, start)
}

/// A slot of 16-bit-scaled audio (as f32, before rounding and clipping
/// are applied: they are applied here, so the values are integers).
/// `noise` false gives the clean signals at the same scale (for
/// subtraction tests).
pub fn make_slot(mode: Mode, signals: &[SimSignal], seed: u64, noise: bool) -> Vec<f32> {
    let n = mode.slot_samples();
    let mut wave = vec![0f64; n];
    let bandwidth_ratio = 2500.0 / 6000.0;
    for s in signals {
        let sig = (2.0f64 * bandwidth_ratio).sqrt() * 10f64.powf(0.05 * s.snr_db);
        let (w, start) = waveform(mode, s);
        for (k, v) in w.iter().enumerate() {
            let j = start + k as i64;
            if j >= 0 && (j as usize) < n {
                wave[j as usize] += sig * v;
            }
        }
    }
    if noise {
        let mut rng = Rng::new(seed);
        for v in wave.iter_mut() {
            *v += rng.gauss();
        }
    }
    wave.iter()
        .map(|v| (100.0 * v).round().clamp(-32767.0, 32767.0) as f32)
        .collect()
}

/// A crowded random slot: `nsig` signals with payloads drawn from `pool`,
/// SNRs in [snr_lo, snr_hi], spread over 300-2700 Hz with no two closer
/// than `min_sep` Hz, DT in +-dt_spread s, drift up to +-max_drift Hz/s.
#[allow(clippy::too_many_arguments)]
pub fn random_signals(
    mode: Mode,
    pool: &[[u8; 77]],
    nsig: usize,
    snr_lo: f64,
    snr_hi: f64,
    dt_spread: f64,
    max_drift: f64,
    min_sep: f64,
    seed: u64,
) -> Vec<SimSignal> {
    let bw = match mode {
        Mode::Ft8 => 50.0,
        Mode::Ft4 => 83.3,
    };
    random_signals_band(
        pool,
        nsig,
        snr_lo,
        snr_hi,
        dt_spread,
        max_drift,
        min_sep,
        seed,
        300.0,
        2700.0 - bw,
    )
}

/// random_signals with the start frequencies drawn from [fmin, fmax) -
/// e.g. near nfqso, where WSJT-X allows its DxCall a-priori passes.
#[allow(clippy::too_many_arguments)]
pub fn random_signals_band(
    pool: &[[u8; 77]],
    nsig: usize,
    snr_lo: f64,
    snr_hi: f64,
    dt_spread: f64,
    max_drift: f64,
    min_sep: f64,
    seed: u64,
    fmin: f64,
    fmax: f64,
) -> Vec<SimSignal> {
    let mut rng = Rng::new(seed ^ 0xA5A5_5A5A_1234_5678);
    let mut out: Vec<SimSignal> = Vec::new();
    let mut tries = 0;
    while out.len() < nsig && tries < 10000 {
        tries += 1;
        let f = rng.range(fmin, fmax);
        if out.iter().any(|s| (s.freq - f).abs() < min_sep) {
            continue;
        }
        // Distinct messages while the pool lasts, so a test can count
        // decodes by message.
        let mut payload = pool[(rng.next_u64() % pool.len() as u64) as usize];
        if out.len() < pool.len() {
            while out.iter().any(|s| s.payload == payload) {
                payload = pool[(rng.next_u64() % pool.len() as u64) as usize];
            }
        }
        out.push(SimSignal {
            payload,
            freq: f,
            dt: rng.range(-dt_spread, dt_spread),
            snr_db: rng.range(snr_lo, snr_hi),
            drift_hz_s: rng.range(-max_drift, max_drift),
        });
    }
    out
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::msg77::{pack77, CallHashes};

    /// The pool was packed by ft8code; the crate's pack77 must agree (a
    /// cross-check of both, and of the hex helpers).
    #[test]
    fn pool_matches_pack77() {
        for (text, hex) in PAYLOAD_POOL {
            let p = pack77(text.as_bytes(), &mut CallHashes::new()).unwrap();
            assert_eq!(bits77_to_hex(&p.bits().unwrap()), *hex, "{text}");
        }
    }
}
