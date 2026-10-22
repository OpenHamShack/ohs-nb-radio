//! Development tool for Q65: tones, test WAVs and decodes in jt9's format.
//! Not part of the library; tests/q65_golden.rs holds what it checked.
//!
//!   q65dev tones < messages            one line per message: message|tones (85 digits pairs)
//!   q65dev gen <period> <A-E> <out.wav> <seed> <snr> <freq> <dt> <message> [more msg@freq@snr ...]
//!   q65dev decode <period> <A-E> <depth> [mycall hiscall] <wav>...
//!       one line per decode: snr dt freq text qN
//!   q65dev batch <period> <A-E> <outdir> <nfiles> <seed>
//!   q65dev sweep <period> <A-E> <depth> <outdir> <snr_lo> <snr_hi> <step> <trials>

use ohsdigi::decode::sim::Rng;
use ohsdigi::msg77::CallHashes;
use ohsdigi::q65::decode::{decode_period, Q65Params};
use ohsdigi::q65::sim::{crowded, make_period as sim_period, random_message, SimSignal};
use ohsdigi::q65::{encode, submode_index};

fn make_period(period: u32, sub: usize, sigs: &[(String, f64, f64, f64)], seed: u64) -> Vec<f32> {
    let s: Vec<SimSignal> =
        sigs.iter().map(|(m, f, snr, dt)| SimSignal { message: m.clone(), freq: *f, snr_db: *snr, dt: *dt }).collect();
    sim_period(period, sub, &s, seed)
}
use std::io::{BufRead, Write};

fn read_wav(path: &str) -> Vec<f32> {
    let b = std::fs::read(path).expect("read wav");
    let mut p = 12;
    while p + 8 <= b.len() {
        let id = &b[p..p + 4];
        let len = u32::from_le_bytes([b[p + 4], b[p + 5], b[p + 6], b[p + 7]]) as usize;
        if id == b"data" {
            let end = (p + 8 + len).min(b.len());
            return b[p + 8..end].chunks_exact(2).map(|c| i16::from_le_bytes([c[0], c[1]]) as f32).collect();
        }
        p += 8 + len + (len & 1);
    }
    panic!("{path}: no data chunk");
}

fn write_wav(path: &str, x: &[f32]) {
    let n = x.len() as u32;
    let mut b: Vec<u8> = Vec::with_capacity(44 + 2 * x.len());
    b.extend_from_slice(b"RIFF");
    b.extend_from_slice(&(36 + 2 * n).to_le_bytes());
    b.extend_from_slice(b"WAVEfmt ");
    b.extend_from_slice(&16u32.to_le_bytes());
    b.extend_from_slice(&1u16.to_le_bytes());
    b.extend_from_slice(&1u16.to_le_bytes());
    b.extend_from_slice(&12000u32.to_le_bytes());
    b.extend_from_slice(&24000u32.to_le_bytes());
    b.extend_from_slice(&2u16.to_le_bytes());
    b.extend_from_slice(&16u16.to_le_bytes());
    b.extend_from_slice(b"data");
    b.extend_from_slice(&(2 * n).to_le_bytes());
    for v in x {
        b.extend_from_slice(&(*v as i16).to_le_bytes());
    }
    std::fs::write(path, b).expect("write wav");
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    match a.get(1).map(|s| s.as_str()) {
        Some("tones") => {
            for l in std::io::stdin().lock().lines() {
                let m = l.unwrap();
                match encode(&m) {
                    Ok(e) => {
                        let t: Vec<String> = e.tones.iter().map(|x| x.to_string()).collect();
                        println!("{m}|{}", t.join(" "));
                    }
                    Err(err) => println!("{m}|error {err}"),
                }
            }
        }
        Some("gen") => {
            let period: u32 = a[2].parse().unwrap();
            let sub = submode_index(&a[3]).unwrap();
            let snr: f64 = a[6].parse().unwrap();
            let mut sigs = vec![(a[9].clone(), a[7].parse().unwrap(), snr, a[8].parse().unwrap())];
            for more in &a[10..] {
                let v: Vec<&str> = more.split('@').collect();
                sigs.push((v[0].to_string(), v[1].parse().unwrap(), v[2].parse().unwrap(), 0.0));
            }
            write_wav(&a[4], &make_period(period, sub, &sigs, a[5].parse().unwrap()));
        }
        Some("decode") => {
            let period: u32 = a[2].parse().unwrap();
            let sub = submode_index(&a[3]).unwrap();
            let mut p = Q65Params::jt9(period, sub);
            p.ndepth = a[4].parse().unwrap();
            let mut files = &a[5..];
            if files.len() >= 2 && !files[0].ends_with(".wav") {
                p.mycall = files[0].clone();
                p.hiscall = files[1].clone();
                files = &files[2..];
            }
            for f in files {
                let mut h = CallHashes::new();
                for d in decode_period(&read_wav(f), &p, &mut h) {
                    println!("{f} {} {:.1} {} {} q{}", d.snr, d.dt, d.freq.round(), d.text, d.idec);
                }
            }
        }
        Some("batch") => {
            let period: u32 = a[2].parse().unwrap();
            let sub = submode_index(&a[3]).unwrap();
            let outdir = &a[4];
            let nfiles: usize = a[5].parse().unwrap();
            let mut rng = Rng::new(a[6].parse().unwrap());
            std::fs::create_dir_all(outdir).unwrap();
            let mut truth = std::fs::File::create(format!("{outdir}/truth.txt")).unwrap();
            for n in 0..nfiles {
                let (sigs, seed) = crowded(period, sub, &mut rng);
                let name = format!("q{period}{}_{n:03}.wav", a[3]);
                write_wav(&format!("{outdir}/{name}"), &sim_period(period, sub, &sigs, seed));
                for s in &sigs {
                    writeln!(truth, "{name}|{}|{:.1}|{:.1}|{:.2}", s.message, s.freq, s.snr_db, s.dt).unwrap();
                }
            }
        }
        Some("sweep") => {
            let period: u32 = a[2].parse().unwrap();
            let sub = submode_index(&a[3]).unwrap();
            let depth: i32 = a[4].parse().unwrap();
            let outdir = &a[5];
            let (lo, hi, step): (f64, f64, f64) = (a[6].parse().unwrap(), a[7].parse().unwrap(), a[8].parse().unwrap());
            let trials: usize = a[9].parse().unwrap();
            std::fs::create_dir_all(outdir).unwrap();
            let mut truth = std::fs::File::create(format!("{outdir}/truth.txt")).unwrap();
            let mut p = Q65Params::jt9(period, sub);
            p.ndepth = depth;
            let mut rng = Rng::new(0x65 + period as u64 * 10 + sub as u64);
            let mut snr = lo;
            while snr <= hi + 1e-9 {
                let mut ok = 0;
                for n in 0..trials {
                    let msg = random_message(&mut rng);
                    let f = 1500.0 + rng.range(-4.0, 4.0);
                    let dt = rng.range(-0.2, 0.3);
                    let audio = make_period(period, sub, &[(msg.clone(), f, snr, dt)], rng.next_u64());
                    let name = format!("s{snr:+05.1}_{n:03}.wav");
                    write_wav(&format!("{outdir}/{name}"), &audio);
                    let want = encode(&msg).unwrap().sent;
                    writeln!(truth, "{name}|{want}").unwrap();
                    let mut h = CallHashes::new();
                    if decode_period(&audio, &p, &mut h).iter().any(|d| d.text == want) {
                        ok += 1;
                    }
                }
                println!("{snr:+.1} {ok}/{trials}");
                snr += step;
            }
        }
        _ => eprintln!("see the comment at the top of examples/q65dev.rs"),
    }
}
