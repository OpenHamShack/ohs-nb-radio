//! HSmodem at every speed, station to station: what OpenHamShack NB sends
//! (modulator::ssb_audio, 12 kHz SSB audio) received by what it listens
//! with (Receiver::ssb), through white noise and a mistuning. The beacon's
//! own corpus tests (tests/hsmodem.rs) hold the receiver against HSmodem's
//! code at mode 9; harness/hsmodem/compare.py `speeds` does the same
//! against HSmodem's transmitter and receiver at every mode.

use ohsdigi::hsmodem::frame::{Packer, PAYLOADLEN};
use ohsdigi::hsmodem::modulator::ssb_audio;
use ohsdigi::hsmodem::receiver::{afc_span, Decoded, Options, Receiver};
use ohsdigi::hsmodem::speed::{Speed, SPEEDS};
use rustfft::num_complex::Complex32;
use rustfft::FftPlanner;

const RATE: f32 = 12000.0;

fn own_frames(n: usize, seed: usize) -> (Vec<u8>, Vec<[u8; PAYLOADLEN]>) {
    let mut p = Packer::default();
    let mut bytes = Vec::new();
    let mut pls = Vec::new();
    for i in 0..n {
        let mut pl = [0u8; PAYLOADLEN];
        for (j, b) in pl.iter_mut().enumerate() {
            *b = (i * 31 + j * 7 + seed * 13) as u8;
        }
        bytes.extend_from_slice(&p.pack(&pl, 5, if i == 0 { 0 } else { 1 }, false));
        pls.push(pl);
    }
    (bytes, pls)
}

struct Lcg(u64);
impl Lcg {
    fn gauss(&mut self) -> f32 {
        let mut u = || {
            self.0 = self
                .0
                .wrapping_mul(6364136223846793005)
                .wrapping_add(1442695040888963407);
            ((self.0 >> 11) as f64 + 0.5) / (1u64 << 53) as f64
        };
        let (a, b) = (u(), u());
        ((-2.0 * a.ln()).sqrt() * (2.0 * std::f64::consts::PI * b).cos()) as f32
    }
}

/// NB's transmit audio for `frames`, `hz` off tune (the whole audio moved,
/// as a receiver's mistuning moves it: a single-sideband shift by an
/// analytic mix), with white noise for Es/N0 `esn0` dB.
fn link(speed: &Speed, frames: &[u8], hz: f32, esn0: f32, seed: u64) -> Vec<f32> {
    let a = ssb_audio(speed, frames, RATE, 1500.0 + hz, 0.85, 400, 400);
    // Es/N0 = P / Rs / N0 with N0 = 2 sigma^2 / fs for real noise.
    let lead = (400.0 * RATE / speed.symbol_rate()) as usize;
    let body = &a[lead..a.len() - lead];
    let p: f32 = body.iter().map(|v| v * v).sum::<f32>() / body.len() as f32;
    let sigma = (p * RATE / (2.0 * speed.symbol_rate() * 10f32.powf(esn0 / 10.0))).sqrt();
    let mut g = Lcg(seed);
    a.iter().map(|v| v + sigma * g.gauss()).collect()
}

fn receive(speed: Speed, a: &[f32]) -> (Vec<Decoded>, Receiver) {
    let mut rx = Receiver::ssb(RATE, 1500.0, speed, Options::default());
    let mut out = Vec::new();
    for c in a.chunks(900) {
        rx.feed_ssb(c, &mut out);
    }
    (out, rx)
}

/// The Es/N0 every speed is held to decode everything at: a few dB above
/// where it starts losing frames (`hsspeeds` prints the cliff per speed).
fn comfortable(speed: &Speed) -> f32 {
    match speed.bits {
        1 => 10.0,
        2 => 13.0,
        _ => 19.0,
    }
}

#[test]
fn every_speed_carries_frames_station_to_station() {
    for sp in SPEEDS {
        // Enough frames for ~4 s at any speed, after a second of preamble
        // (the loops settle on the first frames, as HSmodem's own repeated
        // first frame lets them).
        let n = (4.0 * sp.bitrate as f32 / 8.0 / 258.0).ceil() as usize + 3;
        let (bytes, pls) = own_frames(n, sp.mode as usize);
        let a = link(&sp, &bytes, 0.0, comfortable(&sp), 10 + sp.mode as u64);
        let (out, rx) = receive(sp, &a);
        let got: Vec<_> = out.iter().map(|d| d.frame.payload).collect();
        assert!(
            got.iter().all(|p| pls.contains(p)),
            "speed {}: a frame that was not sent",
            sp.mode
        );
        assert!(
            got.len() + 2 >= n,
            "speed {} ({} bit/s): {} of {} frames, {:?}",
            sp.mode,
            sp.bitrate,
            got.len(),
            n,
            rx.stats()
        );
        assert_eq!(rx.stats().frames_lost, 0, "speed {}", sp.mode);
    }
}

#[test]
fn every_speed_finds_a_mistuned_station() {
    // Most of the coarse search's half-span off: far outside HSmodem's
    // carrier loop (about +-20 Hz at 2400 Bd, less at slower speeds), where
    // its operator would retune by hand.
    for sp in SPEEDS {
        let off = 0.35 * afc_span(&sp);
        let n = (8.0 * sp.bitrate as f32 / 8.0 / 258.0).ceil() as usize + 3;
        let (bytes, _) = own_frames(n, 1);
        let a = link(&sp, &bytes, off, comfortable(&sp) + 3.0, 20 + sp.mode as u64);
        let (out, rx) = receive(sp, &a);
        assert!(
            out.len() * 2 >= n,
            "speed {}: {} of {} frames {off} Hz off, {:?}",
            sp.mode,
            out.len(),
            n,
            rx.stats()
        );
        // Where it settled: the mixer plus the carrier loop, to a few per
        // cent of the span (the squaring loops of BPSK jitter most).
        assert!(
            (rx.stats().freq_hz - off).abs() < 3.0 + 0.02 * afc_span(&sp),
            "speed {}: {:?}",
            sp.mode,
            rx.stats()
        );
    }
}

#[test]
fn the_audio_stays_where_hsmodem_puts_it() {
    // Centred on 1500 Hz and no wider than the RRC's 1.2 Rs, so an SSB
    // transmitter's 100-2950 Hz passband carries all of it at every speed.
    for sp in SPEEDS {
        let (bytes, _) = own_frames(6, 0);
        let a = ssb_audio(&sp, &bytes, RATE, 1500.0, 0.85, 0, 0);
        let n = a.len();
        let mut buf: Vec<Complex32> = a.iter().map(|&v| Complex32::new(v, 0.0)).collect();
        FftPlanner::new().plan_fft_forward(n).process(&mut buf);
        let band = |lo: f32, hi: f32| -> f64 {
            buf[..n / 2]
                .iter()
                .enumerate()
                .filter(|(i, _)| (lo..hi).contains(&(*i as f32 * RATE / n as f32)))
                .map(|(_, c)| c.norm_sqr() as f64)
                .sum()
        };
        let inside = band(100.0, 2950.0);
        let outside = band(0.0, 100.0) + band(2950.0, 6000.0);
        assert!(
            outside < 1e-3 * inside,
            "speed {}: {:.2e} of the power outside 100-2950 Hz",
            sp.mode,
            outside / inside
        );
        let env = a.iter().fold(0.0f32, |m, v| m.max(v.abs()));
        assert!(env <= 0.85 + 1e-3, "speed {}: peak {env}", sp.mode);
    }
}

#[test]
fn receives_hsmodems_own_transmitter_at_the_default_speed() {
    // testdata/hsmodem/speed4-*: HSmodem's own sound-card audio (its
    // liquid_if.cpp modulator and Pack(), compiled from source with the
    // liquid-dsp it ships: harness/hsmodem/compare.py corpus4) for a short
    // file transfer at speed mode 4 - QPSK, 4410 bit/s, 44.1 kHz, its
    // GUI's "QO-100 Standard". Taken the way NB takes a station: resampled
    // to 12 kHz, then Receiver::ssb with its AFC on.
    use flate2::read::GzDecoder;
    use ohsdigi::hsmodem::liquid::C32;
    use ohsdigi::hsmodem::resample::Resampler;
    use ohsdigi::hsmodem::speed;
    use std::io::Read;
    let data = concat!(env!("CARGO_MANIFEST_DIR"), "/testdata/hsmodem/");
    let mut raw = Vec::new();
    GzDecoder::new(std::fs::File::open(format!("{data}speed4-audio-44100.s16.gz")).unwrap())
        .read_to_end(&mut raw)
        .unwrap();
    let x: Vec<C32> = raw
        .chunks_exact(2)
        .map(|c| C32::new(i16::from_le_bytes([c[0], c[1]]) as f32 / 16000.0, 0.0))
        .collect();
    let mut y = Vec::new();
    Resampler::new(44100.0, RATE).process(&x, &mut y);
    // A little noise, as any receiver adds.
    let mut g = Lcg(9);
    let a: Vec<f32> = y.iter().map(|c| c.re + 1e-3 * g.gauss()).collect();
    let (out, rx) = receive(speed::by_mode(4).unwrap(), &a);
    let want: Vec<String> = std::fs::read_to_string(format!("{data}speed4-payloads.txt"))
        .unwrap()
        .lines()
        .map(String::from)
        .collect();
    let mut got: Vec<String> = out
        .iter()
        .map(|d| d.frame.payload.iter().map(|b| format!("{b:02x}")).collect())
        .collect();
    got.sort();
    got.dedup();
    assert_eq!(got, want, "{:?}", rx.stats());
}
