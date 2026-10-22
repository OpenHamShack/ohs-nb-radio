//! Development tool for the HSmodem port: the same commands and file
//! formats as the verification harness (harness/hsmodem/hsh.cpp), run on
//! ohsdigi's code, so harness/hsmodem/compare.py can hold the two side by
//! side. Not part of the library.
//!
//!   hsdev tx    <spec> <frames.out> <audio.f32>     Packer + Audio (marker if HSH_MARKER=1)
//!   hsdev points <spec> <frames.out> <syms.c64>     Packer + modem points (the beacon build)
//!   hsdev rx    <audio48k.f32> <stages.out> <frames.out>
//!   hsdev rxiq  <iq.c64, 9600 S/s> <stages.out> <frames.out>
//!   hsdev rs    <codewords.in> <results.out>
//!   hsdev time  <iq.c64> <rate>                    receive cost (resampler + AFC on)
//!   hsdev ssbtx <spec> <speed> <frames.out> <audio.f32> <rate> [lead]
//!                 what NB transmits (12 kHz SSB audio), resampled to `rate`
//!                 (the speed's sound-card rate, for hsh rx); `lead` symbols of
//!                 silence first (0, as NB sends: see compare.py speeds)
//!   hsdev ssbrx <audio.f32> <rate> <speed> <frames.out>
//!                 what NB receives with: the audio resampled to 12 kHz, then
//!                 Receiver::ssb with its AFC (frames only, no stages)

use ohsdigi::hsmodem::frame::{Packer, PAYLOADLEN};
use ohsdigi::hsmodem::liquid::{Scheme, C32};
use ohsdigi::hsmodem::modulator::{points, ssb_audio, Audio};
use ohsdigi::hsmodem::receiver::{Options, Receiver};
use ohsdigi::hsmodem::resample::Resampler;
use ohsdigi::hsmodem::rs;
use ohsdigi::hsmodem::speed;
use std::io::Write;
use std::time::Instant;

fn pack_spec(spec: &str) -> Vec<u8> {
    let s = std::fs::read(spec).expect("spec");
    let mut p = Packer::default();
    let mut frames = Vec::new();
    for r in s.chunks_exact(222) {
        let mut pl = [0u8; PAYLOADLEN];
        pl.copy_from_slice(&r[3..]);
        frames.extend_from_slice(&p.pack(&pl, r[0], r[1], r[2] != 0));
    }
    frames
}

fn f32s(b: &[u8]) -> Vec<f32> {
    b.chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect()
}

fn c32s(b: &[u8]) -> Vec<C32> {
    let f = f32s(b);
    f.chunks_exact(2).map(|c| C32::new(c[0], c[1])).collect()
}

fn write_f32(path: &str, v: impl IntoIterator<Item = f32>) {
    let mut raw = Vec::new();
    for x in v {
        raw.extend_from_slice(&x.to_le_bytes());
    }
    std::fs::write(path, raw).expect("write");
}

/// Real audio from one rate to another (the complex resampler, imaginary 0).
fn resample_real(a: &[f32], from: f32, to: f32) -> Vec<f32> {
    let x: Vec<C32> = a.iter().map(|&v| C32::new(v, 0.0)).collect();
    let mut y = Vec::new();
    Resampler::new(from, to).process(&x, &mut y);
    y.into_iter().map(|c| c.re).collect()
}

fn run_rx(rx: &mut Receiver, stages: &str, frames: &str, audio: Option<Vec<f32>>, iq: Option<Vec<C32>>) {
    rx.record = Some(Vec::new());
    let mut out = Vec::new();
    if let Some(a) = audio {
        rx.feed_audio(&a, &mut out);
    }
    if let Some(x) = iq {
        rx.feed_iq(&x, &mut out);
    }
    let rec = rx.record.take().unwrap();
    write_f32(
        stages,
        rec.iter().flat_map(|(s, f)| {
            [
                s.d_hat.re,
                s.d_hat.im,
                s.sym as f32,
                s.tau,
                s.nco_freq,
                s.nco_phase,
                s.agc_gain,
                *f as f32,
            ]
        }),
    );
    write_frames(frames, &out);
}

fn write_frames(frames: &str, out: &[ohsdigi::hsmodem::receiver::Decoded]) {
    let mut f = std::fs::File::create(frames).expect("frames");
    for d in out {
        // getPayload()'s 10 management bytes: type, counter MSB, LSB,
        // first/last, lost-frame flag (not kept; 0), speed (0 offline), 0 0 0 0.
        let fr = &d.frame;
        let mut line = format!(
            "{} {:02x}{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}{:02x}",
            d.symbol,
            fr.ftype,
            fr.counter >> 8,
            fr.counter & 0xff,
            fr.status,
            0,
            0,
            0,
            0,
            0,
            0
        );
        for b in fr.payload {
            line.push_str(&format!("{b:02x}"));
        }
        writeln!(f, "{line}").unwrap();
    }
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    let opts = Options {
        afc: false,
        watchdog: true,
        max_header_errors: 2,
    };
    match a.get(1).map(|s| s.as_str()) {
        Some("tx") => {
            let frames = pack_spec(&a[2]);
            std::fs::write(&a[3], &frames).unwrap();
            let marker = std::env::var("HSH_MARKER").map(|v| v == "1").unwrap_or(false);
            let mut m = Audio::new(Scheme::Apsk8, 48000.0, 20, marker);
            let mut out = Vec::new();
            m.frames(&frames, &mut out);
            write_f32(&a[4], out);
        }
        Some("points") => {
            let frames = pack_spec(&a[2]);
            std::fs::write(&a[3], &frames).unwrap();
            write_f32(
                &a[4],
                points(Scheme::Apsk8, &frames)
                    .into_iter()
                    .flat_map(|c| [c.re * 0.9, c.im * 0.9]),
            );
        }
        Some("rx") => {
            let audio = f32s(&std::fs::read(&a[2]).unwrap());
            let mut rx = Receiver::audio(48000.0, 1500.0, opts);
            run_rx(&mut rx, &a[3], &a[4], Some(audio), None);
        }
        Some("rxiq") => {
            let iq = c32s(&std::fs::read(&a[2]).unwrap());
            let mut rx = Receiver::iq(9600.0, opts);
            run_rx(&mut rx, &a[3], &a[4], None, Some(iq));
        }
        Some("rs") => {
            let input = std::fs::read(&a[2]).unwrap();
            let mut out = Vec::new();
            for c in input.chunks_exact(255) {
                let mut cw = [0u8; 255];
                cw.copy_from_slice(c);
                match rs::decode(&cw) {
                    Some((d, _)) => {
                        out.push(1);
                        out.extend_from_slice(&d);
                    }
                    None => {
                        out.push(0);
                        out.extend_from_slice(&[0u8; 223]);
                    }
                }
            }
            std::fs::write(&a[3], out).unwrap();
        }
        Some("time") => {
            let iq = c32s(&std::fs::read(&a[2]).unwrap());
            let rate: f32 = a[3].parse().unwrap();
            let mut rx = Receiver::iq(rate, Options::default());
            let t0 = Instant::now();
            let mut out = Vec::new();
            for c in iq.chunks(900) {
                rx.feed_iq(c, &mut out);
            }
            let dt = t0.elapsed().as_secs_f64();
            let secs = iq.len() as f64 / rate as f64;
            println!(
                "{} s of signal in {:.3} s: {:.2} % of one core; {} frames, stats {:?}",
                secs,
                dt,
                100.0 * dt / secs,
                out.len(),
                rx.stats()
            );
        }
        Some("ssbtx") => {
            let sp = speed::by_mode(a[3].parse().unwrap()).expect("speed 0-9");
            let frames = pack_spec(&a[2]);
            std::fs::write(&a[4], &frames).unwrap();
            let lead: usize = a.get(7).map(|v| v.parse().unwrap()).unwrap_or(0);
            let nb = ssb_audio(&sp, &frames, 12000.0, 1500.0, 0.85, lead, 200);
            write_f32(&a[5], resample_real(&nb, 12000.0, a[6].parse().unwrap()));
        }
        Some("ssbrx") => {
            let rate: f32 = a[3].parse().unwrap();
            let sp = speed::by_mode(a[4].parse().unwrap()).expect("speed 0-9");
            let audio = resample_real(&f32s(&std::fs::read(&a[2]).unwrap()), rate, 12000.0);
            let mut rx = Receiver::ssb(12000.0, 1500.0, sp, Options::default());
            let mut out = Vec::new();
            for c in audio.chunks(900) {
                rx.feed_ssb(c, &mut out);
            }
            write_frames(&a[5], &out);
        }
        _ => {
            eprintln!("usage: hsdev tx|points|rx|rxiq|rs|time|ssbtx|ssbrx ...");
            std::process::exit(2);
        }
    }
}
