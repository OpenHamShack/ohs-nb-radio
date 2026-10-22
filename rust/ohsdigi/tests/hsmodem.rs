//! HSmodem against HSmodem's own output, from the compact corpus in
//! testdata/hsmodem (written by harness/hsmodem/compare.py corpus, which
//! runs AMSAT-DL's HSmodem source and its bundled liquid-dsp; see
//! docs/hsmodem-research.md "Verification"), and the receiver's behaviour
//! where HSmodem has no answer (resampled IQ, frequency offsets beyond its
//! loop, noise that breaks every frame).

use flate2::read::GzDecoder;
use ohsdigi::hsmodem::frame::{Packer, PAYLOADLEN};
use ohsdigi::hsmodem::liquid::{Scheme, C32};
use ohsdigi::hsmodem::modulator::Baseband;
use ohsdigi::hsmodem::receiver::{Decoded, Options, Receiver};
use std::io::Read;

const DATA: &str = concat!(env!("CARGO_MANIFEST_DIR"), "/testdata/hsmodem/");

fn gunzip(name: &str) -> Vec<u8> {
    let mut out = Vec::new();
    GzDecoder::new(std::fs::File::open(format!("{DATA}{name}")).unwrap()).read_to_end(&mut out).unwrap();
    out
}

fn corpus_iq() -> Vec<C32> {
    let scale: f32 = std::fs::read_to_string(format!("{DATA}beacon-iq-9600.scale")).unwrap().trim().parse().unwrap();
    let raw = gunzip("beacon-iq-9600.s16.gz");
    let s: Vec<f32> = raw.chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]]) as f32 / scale).collect();
    s.chunks_exact(2).map(|c| C32::new(c[0], c[1])).collect()
}

fn hex(b: &[u8]) -> String {
    b.iter().map(|x| format!("{x:02x}")).collect()
}

#[test]
fn pack_is_byte_for_byte_hsmodems() {
    let spec = std::fs::read(format!("{DATA}pack.spec")).unwrap();
    let want = std::fs::read(format!("{DATA}pack.frames")).unwrap();
    let mut p = Packer::default();
    let mut got = Vec::new();
    for r in spec.chunks_exact(222) {
        let mut pl = [0u8; PAYLOADLEN];
        pl.copy_from_slice(&r[3..]);
        got.extend_from_slice(&p.pack(&pl, r[0], r[1], r[2] != 0));
    }
    assert_eq!(got.len(), want.len());
    assert!(got == want, "frames differ from HSmodem's Pack()");
}

#[test]
fn receives_what_hsmodem_received() {
    let iq = corpus_iq();
    let mut rx = Receiver::iq(9600.0, Options { afc: false, watchdog: true, max_header_errors: 2 });
    rx.record = Some(Vec::new());
    let mut out: Vec<Decoded> = Vec::new();
    rx.feed_iq(&iq, &mut out);
    // Frames: the same ones, found at the same symbol, as HSmodem's receiver.
    let want: Vec<String> = std::fs::read_to_string(format!("{DATA}beacon-iq-9600.hsmodem-frames.txt"))
        .unwrap()
        .lines()
        .map(|l| {
            let (sym, h) = l.split_once(' ').unwrap();
            format!("{sym} {} {}", &h[..2], &h[20..])
        })
        .collect();
    let got: Vec<String> =
        out.iter().map(|d| format!("{} {:02x} {}", d.symbol, d.frame.ftype, hex(&d.frame.payload))).collect();
    assert_eq!(got, want);
    // Hard symbols: HSmodem's, one for one (the soft values differ in the
    // last bits; at this SNR no decision sits on a boundary).
    let hs = gunzip("beacon-iq-9600.hsmodem-symbols.gz");
    let rec = rx.record.take().unwrap();
    assert_eq!(rec.len(), hs.len());
    let agree = rec.iter().zip(&hs).filter(|((s, _), &h)| s.sym == h).count();
    assert!(agree as f64 >= 0.999 * hs.len() as f64, "{agree} of {}", hs.len());
}

/// A beacon-like stream of our own: n frames of known payloads.
fn own_frames(n: usize) -> (Vec<u8>, Vec<[u8; PAYLOADLEN]>) {
    let mut p = Packer::default();
    let mut bytes = Vec::new();
    let mut pls = Vec::new();
    for i in 0..n {
        let mut pl = [0u8; PAYLOADLEN];
        for (j, b) in pl.iter_mut().enumerate() {
            *b = (i * 31 + j * 7) as u8;
        }
        bytes.extend_from_slice(&p.pack(&pl, 8, 3, true));
        pls.push(pl);
    }
    (bytes, pls)
}

struct Lcg(u64);
impl Lcg {
    fn gauss(&mut self) -> f32 {
        // Box-Muller from a 64-bit LCG: enough for test noise.
        let mut u = || {
            self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
            ((self.0 >> 11) as f64 + 0.5) / (1u64 << 53) as f64
        };
        let (a, b) = (u(), u());
        ((-2.0 * a.ln()).sqrt() * (2.0 * std::f64::consts::PI * b).cos()) as f32
    }
}

/// 12 kHz complex baseband (NB's channel rate), shifted by `hz`, at Es/N0
/// `snr_db`.
fn channel(frames: &[u8], hz: f32, snr_db: f32, seed: u64) -> Vec<C32> {
    let mut b = Baseband::new(Scheme::Apsk8, 5);
    let mut x = Vec::new();
    b.flush(200, &mut x);
    b.frames(frames, &mut x);
    b.flush(200, &mut x);
    let p: f32 = x.iter().map(|c| c.norm_sqr()).sum::<f32>() / x.len() as f32;
    // Es/N0 in the symbol rate: noise power in 12 kHz is N0 * 12000.
    let n0 = p * 5.0 / 10f32.powf(snr_db / 10.0); // Es = P * 5 samples
    let sigma = (n0 / 2.0).sqrt();
    let mut g = Lcg(seed);
    x.iter()
        .enumerate()
        .map(|(i, c)| {
            let ph = 2.0 * std::f32::consts::PI * hz * i as f32 / 12000.0;
            c.mul(C32::expj(ph)).add(C32::new(sigma * g.gauss(), sigma * g.gauss()))
        })
        .collect()
}

fn decode(x: &[C32], afc: bool) -> (Vec<Decoded>, Receiver) {
    let mut rx = Receiver::iq(12000.0, Options { afc, ..Options::default() });
    let mut out = Vec::new();
    for c in x.chunks(900) {
        rx.feed_iq(c, &mut out);
    }
    (out, rx)
}

#[test]
fn resampled_iq_decodes_every_frame() {
    let (bytes, pls) = own_frames(30);
    let (out, rx) = decode(&channel(&bytes, 0.0, 25.0, 1), true);
    let got: Vec<_> = out.iter().map(|d| d.frame.payload).collect();
    // The first frame or two go by while the loops settle.
    assert!(got.len() >= 28, "{} frames", got.len());
    assert!(got.iter().all(|p| pls.contains(p)));
    // None lost between the first and the last.
    assert_eq!(rx.stats().frames_lost, 0);
}

#[test]
fn coarse_acquisition_finds_a_carrier_hsmodems_loop_cannot() {
    // 60 Hz off: far outside the carrier loop's pull-in, inside the
    // 7th-power estimator's +-171 Hz.
    let (bytes, _) = own_frames(60);
    let x = channel(&bytes, 60.0, 25.0, 2);
    let (without, _) = decode(&x, false);
    let (with, rx) = decode(&x, true);
    assert!(without.is_empty(), "HSmodem's loop alone decoded {}", without.len());
    assert!(with.len() >= 40, "{} frames with AFC, stats {:?}", with.len(), rx.stats());
    assert!((rx.stats().freq_hz - 60.0).abs() < 3.0, "{:?}", rx.stats());
}

#[test]
fn coarse_acquisition_never_walks_onto_an_alias() {
    // Started 1.8 kHz off (NB before beacon lock: the beacon is not even in
    // the channel's passband), then the signal moves to where it belongs -
    // as rxCorr arriving does. The estimator, folded every 342.9 Hz, must
    // come back to 0, not to -342.9 where the constellation looks perfect
    // and nothing decodes.
    let (bytes, _) = own_frames(140);
    let far = channel(&bytes[..258 * 40], 1800.0, 25.0, 4);
    let near = channel(&bytes[258 * 40..], 4.0, 25.0, 5);
    let mut rx = Receiver::iq(12000.0, Options::default());
    let mut out = Vec::new();
    for c in far.chunks(900) {
        rx.feed_iq(c, &mut out);
    }
    for c in near.chunks(900) {
        rx.feed_iq(c, &mut out);
    }
    assert!(out.len() >= 80, "{} frames, {:?}", out.len(), rx.stats());
    assert!(rx.stats().freq_hz.abs() < 10.0, "{:?}", rx.stats());
}

#[test]
fn hopeless_noise_fails_cleanly() {
    let (bytes, _) = own_frames(20);
    let (out, rx) = decode(&channel(&bytes, 0.0, 3.0, 3), true);
    let s = rx.stats();
    assert!(out.is_empty());
    assert_eq!(s.frames_ok, 0);
    assert!(s.symbols > 20 * 600);
    // Header-shaped noise reaches the RS decoder and is refused, never
    // passed on.
    assert!(s.fec_failed + s.crc_failed > 0 || s.symbols > 0);
    assert!(s.mer_db < 8.0, "{s:?}");
}
