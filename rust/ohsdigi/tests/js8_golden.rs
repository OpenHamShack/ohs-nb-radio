//! JS8 against JS8Call 2.2.0 itself, both directions.
//!
//! - Encoding: the channel symbols for 300 random frames, both Costas
//!   sets and every header, are those JS8Call's own genjs8 produced
//!   (harness/js8/js8gen, built from JS8Call's Fortran unchanged:
//!   testdata/js8/genjs8.txt).
//! - Our audio, their decoder, our decoder: 200 crowded slots made with
//!   ohsdigi's waveform (40 per speed) were decoded by JS8Call's `js8` at
//!   depth 3 (testdata/js8/js8-batch.txt). ohsdigi must produce the same
//!   lines - frame, header, SNR, DT and frequency, in the same order. The
//!   test regenerates the slots from their seeds (sim::crowded) and checks
//!   the first ten of each speed, which keeps it to a few seconds; all 200
//!   were compared when the file was recorded (574 decodes, identical).
//! - Their audio, our decoder: one of JS8Call's own regression recordings
//!   (media/tests/A_2_9.wav, nine stations), decoded as `js8 -d 2` does.
//! - The message layer: 910 texts turned into frames (every command,
//!   heartbeats and CQs, compound and group calls, data at every speed,
//!   five callsigns, a selected call, forced identification and data) and
//!   2 952 random frames read back, against JS8Call's varicode.cpp,
//!   jsc.cpp and decodedtext.cpp compiled unchanged (harness/js8,
//!   testdata/js8/varicode.tsv.gz). Identical, except that on lower-case
//!   text JS8Call never returns and ohsdigi says it cannot send it.

use ohsdigi::decode::sim::Rng;
use ohsdigi::js8::decode::{decode_slot, Js8Params};
use ohsdigi::js8::sim::{crowded, make_slot};
use ohsdigi::js8::varicode::{build_frames, unpack_frame};
use ohsdigi::js8::{tones, Submode};
use std::io::Read;
use std::path::PathBuf;

fn testdata(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("testdata/js8").join(name)
}

fn read_wav(path: &PathBuf) -> Vec<f32> {
    let b = std::fs::read(path).unwrap();
    b[44..].chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]]) as f32).collect()
}

/// A decode as `js8` prints it: snr, dt (one decimal), frequency (rounded), frame, header.
fn line(snr: i32, dt: f32, freq: f32, frame: &str, i3: u8) -> String {
    format!("{snr} {dt:.1} {} {frame} {i3}", freq.round() as i32)
}

#[test]
fn tones_match_genjs8() {
    let text = std::fs::read_to_string(testdata("genjs8.txt")).unwrap();
    let mut n = 0;
    for l in text.lines() {
        let f: Vec<&str> = l.split_whitespace().collect();
        let (frame, i3, icos, want) = (f[0], f[1].parse::<u8>().unwrap(), f[2], f[3]);
        let sub = if icos == "1" { Submode::Normal } else { Submode::Fast };
        let got: String = tones(frame, i3, sub).unwrap().iter().map(|t| (b'0' + t) as char).collect();
        assert_eq!(got, want, "{frame} {i3} icos {icos}");
        n += 1;
    }
    assert_eq!(n, 300);
}

#[test]
fn decodes_what_js8_decodes_from_our_audio() {
    let text = std::fs::read_to_string(testdata("js8-batch.txt")).unwrap();
    let per_speed = 10;
    for sub in Submode::ALL {
        let mut rng = Rng::new(100 + sub.letter() as u64);
        for n in 0..per_speed {
            let name = format!("{}_{n:03}.wav", sub.letter());
            let want: Vec<String> = text
                .lines()
                .filter(|l| l.starts_with(&name))
                .map(|l| l.split_once(' ').unwrap().1.to_string())
                .collect();
            let (sigs, seed) = crowded(sub, &mut rng);
            let audio = make_slot(sub, &sigs, seed, true);
            let got: Vec<String> = decode_slot(&audio, sub, &Js8Params { ndepth: 3, ..Default::default() })
                .iter()
                .map(|d| line(d.snr, d.dt, d.freq, &d.frame, d.i3bit))
                .collect();
            assert_eq!(got, want, "{name}");
        }
    }
}

#[test]
fn decodes_js8calls_own_recording() {
    let audio = read_wav(&testdata("js8call-A_2_9.wav"));
    let got: Vec<String> = decode_slot(&audio, Submode::Normal, &Js8Params { ndepth: 2, ..Default::default() })
        .iter()
        .map(|d| line(d.snr, d.dt, d.freq, &d.frame, d.i3bit))
        .collect();
    // `js8 -8 -b A -d 2 A_2_9.wav`, JS8Call 2.2.0.
    let want = [
        "5 0.1 501 VkDSPUuGBfqa 3",
        "13 0.1 651 SIUT1UuGBfqb 3",
        "4 0.2 806 VkNoM-uGBfqK 3",
        "-22 0.1 896 SKgyQ-uGBfqU 3",
        "-16 1.6 950 Uw2nt-uGBfqS 3",
        "0 0.3 1324 SQu8IUuGBfqL 3",
        "-4 -0.1 1762 VlPJy-uGBfqI 3",
        "-5 0.2 1997 SJff7UuGBfqY 3",
        "-3 0.3 592 QB+p3UuGBfqK 3",
    ];
    assert_eq!(got, want);
}

fn unescape(s: &str) -> String {
    let mut out = String::new();
    let mut it = s.chars();
    while let Some(c) = it.next() {
        if c == '\\' {
            match it.next() {
                Some('n') => out.push('\n'),
                Some('t') => out.push('\t'),
                Some(o) => out.push(o),
                None => {}
            }
        } else {
            out.push(c);
        }
    }
    out
}

#[test]
fn message_layer_matches_js8call() {
    let mut text = String::new();
    flate2::read::GzDecoder::new(std::fs::File::open(testdata("varicode.tsv.gz")).unwrap())
        .read_to_string(&mut text)
        .unwrap();
    let subs = [(0, Submode::Normal), (1, Submode::Fast), (2, Submode::Turbo), (4, Submode::Slow), (8, Submode::Ultra)];
    let (mut nu, mut nb) = (0, 0);
    for l in text.lines().filter(|l| !l.starts_with('#')) {
        let f: Vec<&str> = l.split('\t').collect();
        if f[0] == "U" {
            let u = unpack_frame(f[1], f[2].parse().unwrap());
            assert_eq!(u.text, unescape(f[4]), "{l}");
            assert_eq!(u.kind as u8, f[5].parse::<u8>().unwrap(), "{l}");
            nu += 1;
        } else {
            let sub = subs.iter().find(|s| s.0 == f[1].parse::<i32>().unwrap()).unwrap().1;
            let sel = if f[4] == "-" { "" } else { f[4] };
            let got = build_frames(f[2], f[3], sel, &unescape(f[7]), f[5] == "1", f[6] == "1", sub);
            if f[8] == "HANG" {
                assert!(got.is_err(), "{l}");
            } else {
                let got: Vec<String> = got.unwrap().iter().map(|(fr, b)| format!("{fr}:{b}")).collect();
                assert_eq!(got.join(","), f[8], "{l}");
            }
            nb += 1;
        }
    }
    assert_eq!((nu, nb), (2952, 923));
}
