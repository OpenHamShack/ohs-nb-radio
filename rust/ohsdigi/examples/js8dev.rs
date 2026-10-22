//! Development tool for the JS8 decoder: decodes WAVs in `js8`'s own
//! line format, writes test WAVs, and runs noise sweeps. Not part of the
//! library; tests/js8_golden.rs holds the results it was used to check.
//!
//!   js8dev decode <A|B|C|E|I> <depth> <wav>...
//!       one line per decode: snr dt freq letter frame i3bit
//!   js8dev gen <A|B|C|E|I> <out.wav> <seed> <snr> <freq> <dt> <frame> <i3bit> [more frame:i3bit:freq ...]
//!   js8dev sweep <A|B|C|E|I> <depth> <outdir> <snr_lo> <snr_hi> <step> <trials>
//!       writes <outdir>/s<snr>_<n>.wav (one random frame each, 1500 Hz)
//!       and prints ohsdigi's decode rate per SNR; <outdir>/truth.txt
//!       lists each file's frame for comparison with `js8`
//!   js8dev batch <A|B|C|E|I> <outdir> <nfiles> <seed>
//!       crowded slots: 1-6 random frames each, SNR -24..+5 dB, 300-2700
//!       Hz at least 60 Hz apart, DT -0.5..+1.5 s; <outdir>/truth.txt
//!   js8dev time <A|B|C|E|I> <depth> <wav>...
//!   js8dev varicode < lines
//!       harness/js8/varicodeh's protocol, answered by src/js8/varicode.rs

use ohsdigi::decode::sim::Rng;
use ohsdigi::js8::decode::{decode_slot, Js8Params};
use ohsdigi::js8::sim::{crowded, make_slot, random_frame, SimSignal};
use ohsdigi::js8::Submode;
use std::io::Write;
use std::time::Instant;

fn read_wav(path: &str) -> Vec<f32> {
    let b = std::fs::read(path).expect("read wav");
    // Find the data chunk rather than assume a 44-byte header.
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

fn sub(s: &str) -> Submode {
    Submode::from_name(s).expect("submode A B C E or I")
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    match a.get(1).map(|s| s.as_str()) {
        Some("decode") => {
            let sm = sub(&a[2]);
            let p = Js8Params { ndepth: a[3].parse().unwrap(), ..Default::default() };
            for f in &a[4..] {
                if a.len() > 5 {
                    println!("== {f}");
                }
                for d in decode_slot(&read_wav(f), sm, &p) {
                    println!("{:4} {:4.1} {:4} {} {} {}", d.snr, d.dt, d.freq.round(), sm.letter(), d.frame, d.i3bit);
                }
            }
        }
        Some("gen") => {
            let sm = sub(&a[2]);
            let seed: u64 = a[4].parse().unwrap();
            let snr: f64 = a[5].parse().unwrap();
            let mut sigs = vec![SimSignal {
                freq: a[6].parse().unwrap(),
                dt: a[7].parse().unwrap(),
                frame: a[8].clone(),
                i3bit: a[9].parse().unwrap(),
                snr_db: snr,
            }];
            for more in &a[10..] {
                let v: Vec<&str> = more.split(':').collect();
                sigs.push(SimSignal {
                    frame: v[0].to_string(),
                    i3bit: v[1].parse().unwrap(),
                    freq: v[2].parse().unwrap(),
                    dt: 0.0,
                    snr_db: snr,
                });
            }
            write_wav(&a[3], &make_slot(sm, &sigs, seed, true));
        }
        Some("sweep") => {
            let sm = sub(&a[2]);
            let depth: i32 = a[3].parse().unwrap();
            let outdir = &a[4];
            let (lo, hi, step): (f64, f64, f64) = (a[5].parse().unwrap(), a[6].parse().unwrap(), a[7].parse().unwrap());
            let trials: usize = a[8].parse().unwrap();
            std::fs::create_dir_all(outdir).unwrap();
            let mut truth = std::fs::File::create(format!("{outdir}/truth.txt")).unwrap();
            let p = Js8Params { ndepth: depth, ..Default::default() };
            let mut rng = Rng::new(0x15_8u64 + (sm as u64));
            let mut snr = lo;
            while snr <= hi + 1e-9 {
                let mut ok = 0;
                for n in 0..trials {
                    let frame = random_frame(&mut rng);
                    let i3 = (rng.next_u64() % 8) as u8;
                    let dt = rng.range(-0.2, 0.2);
                    let freq = rng.range(1400.0, 1600.0);
                    let seed = rng.next_u64();
                    let s = SimSignal { frame: frame.clone(), i3bit: i3, freq, dt, snr_db: snr };
                    let audio = make_slot(sm, &[s], seed, true);
                    let name = format!("s{snr:+05.1}_{n:03}.wav");
                    write_wav(&format!("{outdir}/{name}"), &audio);
                    writeln!(truth, "{name} {frame} {i3}").unwrap();
                    if decode_slot(&audio, sm, &p).iter().any(|d| d.frame == frame && d.i3bit == i3) {
                        ok += 1;
                    }
                }
                println!("{snr:+.1} {ok}/{trials}");
                snr += step;
            }
        }
        Some("batch") => {
            let sm = sub(&a[2]);
            let outdir = &a[3];
            let nfiles: usize = a[4].parse().unwrap();
            let mut rng = Rng::new(a[5].parse().unwrap());
            std::fs::create_dir_all(outdir).unwrap();
            let mut truth = std::fs::File::create(format!("{outdir}/truth.txt")).unwrap();
            for n in 0..nfiles {
                let (sigs, seed) = crowded(sm, &mut rng);
                let name = format!("{}_{n:03}.wav", sm.letter());
                write_wav(&format!("{outdir}/{name}"), &make_slot(sm, &sigs, seed, true));
                for s in &sigs {
                    writeln!(truth, "{name} {} {} {:.1} {:.2} {:.1}", s.frame, s.i3bit, s.freq, s.dt, s.snr_db).unwrap();
                }
            }
        }
        Some("varicode") => {
            use ohsdigi::js8::varicode::{build_frames, unpack_frame};
            use std::io::BufRead;
            let subs = [(0, Submode::Normal), (1, Submode::Fast), (2, Submode::Turbo), (4, Submode::Slow), (8, Submode::Ultra)];
            for l in std::io::stdin().lock().lines() {
                let l = l.unwrap();
                let w: Vec<&str> = l.splitn(8, ' ').collect();
                match w[0] {
                    "U" => {
                        let u = unpack_frame(w[1], w[2].parse().unwrap());
                        println!("|{}| {}", u.text, u.kind as u8);
                    }
                    "B" => {
                        let sm = subs.iter().find(|s| s.0 == w[1].parse::<i32>().unwrap()).unwrap().1;
                        let sel = if w[4] == "-" { "" } else { w[4] };
                        let text = w.get(7).copied().unwrap_or("");
                        match build_frames(w[2], w[3], sel, text, w[5] == "1", w[6] == "1", sm) {
                            Ok(f) => {
                                for (fr, b) in f {
                                    println!("{fr} {b}");
                                }
                            }
                            Err(e) => println!("error {e}"),
                        }
                        println!(".");
                    }
                    _ => {}
                }
            }
        }
        Some("time") => {
            let sm = sub(&a[2]);
            let p = Js8Params { ndepth: a[3].parse().unwrap(), ..Default::default() };
            for f in &a[4..] {
                let x = read_wav(f);
                let t = Instant::now();
                let n = decode_slot(&x, sm, &p).len();
                println!("{f}: {n} decodes in {:.3} s", t.elapsed().as_secs_f64());
            }
        }
        _ => eprintln!("see the comment at the top of examples/js8dev.rs"),
    }
}
