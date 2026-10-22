//! Q65 against WSJT-X 2.7.0 itself, both directions.
//!
//! - Encoding: the 85 channel symbols for 89 messages (standard, CQ with
//!   modifiers, reports, nonstandard and hashed calls, contest, telemetry,
//!   free text) are q65code's (testdata/q65/q65code.txt).
//! - Our audio, their decoder, our decoder: crowded periods made with
//!   ohsdigi's waveform at every period and submode were decoded by
//!   WSJT-X's `jt9 -3` (testdata/q65/jt9-batch.txt). ohsdigi must print the
//!   same lines - text, SNR, DT, frequency and the "q" flag - in the same
//!   order. The test regenerates the periods from their seeds
//!   (sim::crowded) and checks the first few of each set.
//! - Their audio, our decoder: a recording WSJT-X's q65sim made (three
//!   stations in Q65-15A with 2 Hz Doppler spread) decodes as jt9 decodes
//!   it, with and without the operator's calls.

use ohsdigi::decode::sim::Rng;
use ohsdigi::msg77::CallHashes;
use ohsdigi::q65::decode::{decode_period, jt9_hashes, Q65Params};
use ohsdigi::q65::sim::{crowded, make_period};
use ohsdigi::q65::{encode, submode_index};
use std::path::PathBuf;

fn testdata(name: &str) -> PathBuf {
    PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("testdata/q65").join(name)
}

fn read_wav(path: &PathBuf) -> Vec<f32> {
    let b = std::fs::read(path).unwrap();
    b[44..].chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]]) as f32).collect()
}

/// A decode as jt9 prints it: snr, dt (one decimal), frequency, text, q flag.
fn line(d: &ohsdigi::q65::decode::Q65Decode) -> String {
    format!("{} {:.1} {} {} q{}", d.snr, d.dt, d.freq.round() as i32, d.text, d.idec)
}

#[test]
fn tones_match_q65code() {
    let text = std::fs::read_to_string(testdata("q65code.txt")).unwrap();
    let mut n = 0;
    for l in text.lines().filter(|l| !l.starts_with('#')) {
        let (msg, want) = l.split_once('|').unwrap();
        let got: Vec<String> = encode(msg).unwrap().tones.iter().map(|t| t.to_string()).collect();
        assert_eq!(got.join(" "), want, "{msg}");
        n += 1;
    }
    assert_eq!(n, 89);
}

#[test]
fn decodes_what_jt9_decodes_from_our_audio() {
    let text = std::fs::read_to_string(testdata("jt9-batch.txt")).unwrap();
    // set: period submode depth seed files-checked
    let mut sets = 0;
    for l in text.lines().filter(|l| l.starts_with("set ")) {
        let f: Vec<&str> = l.split_whitespace().collect();
        let (period, sub, depth, seed, nfiles): (u32, &str, i32, u64, usize) =
            (f[1].parse().unwrap(), f[2], f[3].parse().unwrap(), f[4].parse().unwrap(), f[5].parse().unwrap());
        let s = submode_index(sub).unwrap();
        let mut rng = Rng::new(seed);
        let mut p = Q65Params::jt9(period, s);
        p.ndepth = depth;
        let tag = format!("{period}{sub}d{depth}");
        for n in 0..nfiles {
            let name = format!("q{period}{sub}_{n:03}.wav");
            let want: Vec<String> = text
                .lines()
                .filter_map(|l| l.strip_prefix(&format!("{tag} {name} ")))
                .map(|s| s.to_string())
                .collect();
            let (sigs, nseed) = crowded(period, s, &mut rng);
            let audio = make_period(period, s, &sigs, nseed);
            let mut h = jt9_hashes(&p.mycall, &p.hiscall);
            let got: Vec<String> = decode_period(&audio, &p, &mut h).iter().map(line).collect();
            assert_eq!(got, want, "{tag} {name}");
        }
        sets += 1;
    }
    assert_eq!(sets, 8);
}

#[test]
fn decodes_q65sims_recording() {
    let audio = read_wav(&testdata("q65sim-15A.wav"));
    // jt9 -3 -p 15 -b A [-d 3 -c GM4BRI -x G4XYZ] 000000_000000.wav
    let want = ["-17 0.0 1500 G4XYZ GM4BBB IO75 q0", "-17 0.0 1000 G4XYZ GM4BAA IO75 q0", "-18 0.0 2000 G4XYZ GM4BCC IO75 q0"];
    let mut p = Q65Params::jt9(15, 0);
    let mut h = CallHashes::new();
    let got: Vec<String> = decode_period(&audio, &p, &mut h).iter().map(line).collect();
    assert_eq!(got, want);
    p.ndepth = 3;
    p.mycall = "GM4BRI".into();
    p.hiscall = "G4XYZ".into();
    let mut h = jt9_hashes(&p.mycall, &p.hiscall);
    let got: Vec<String> = decode_period(&audio, &p, &mut h).iter().map(line).collect();
    assert_eq!(got, want);
}
