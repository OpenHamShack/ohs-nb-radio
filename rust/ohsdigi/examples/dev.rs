//! Development tool for the decoder: writes test WAVs, dumps each stage in
//! the verification harness's line format (harness/ft8h.f90), decodes, and
//! times. harness/compare.py drives it; it is not part of the library.
//!
//!   dev gen ft8|ft4 <out.wav> <seed> <nsig> <snr_lo> <snr_hi> <dt_spread> <drift> <min_sep>
//!           [<fmin> <fmax> [calls]]   band, and only messages with K1ABC/W9XYZ
//!   dev stages <wav> <ndepth> <out>        FT8 stages 1-4, per candidate
//!   dev ldpc <harness_dump> <out>          LDPC on the harness's own LLRs
//!   dev subtract <wav> <list> <out.f32>    subtractft8, as `ft8h subtract`
//!   dev decode ft8|ft4 <wav> <ndepth> [serial] [nofile] [q=<QSO progress>]
//!   dev ft4 <wav> <ndepth> <out>           FT4 stage trace
//!   dev time ft8|ft4 <ndepth> <wav>...     decode time per slot

use ohsdigi::decode::ft4;
use ohsdigi::decode::ft8::{self, Ft8Params};
use ohsdigi::decode::ldpc::decode174_91;
use ohsdigi::decode::sim::bits77_to_hex;
use ohsdigi::decode::sim::{make_slot, payload_pool, random_signals, Mode};
use ohsdigi::msg77::{unpack77, CallHashes};
use std::fmt::Write as _;
use std::io::Write;
use std::time::Instant;

fn read_wav(path: &str) -> Vec<f32> {
    let b = std::fs::read(path).expect("read wav");
    b[44..]
        .chunks_exact(2)
        .map(|c| i16::from_le_bytes([c[0], c[1]]) as f32)
        .collect()
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

fn bits(b: &[u8]) -> String {
    b.iter().map(|&x| char::from(b'0' + x)).collect()
}

fn floats(v: &[f32]) -> String {
    let mut s = String::new();
    for x in v {
        let _ = write!(s, " {:e}", x);
    }
    s
}

/// ft8b's unpack77 test, on fresh tables (one slot, as jt9 per WAV).
fn unpack_ok(m: &[u8; 77]) -> bool {
    unpack77(m, true, &mut CallHashes::new()).ok
}

fn main() {
    let a: Vec<String> = std::env::args().collect();
    match a[1].as_str() {
        "gen" => {
            let mode = if a[2] == "ft4" { Mode::Ft4 } else { Mode::Ft8 };
            let p = |i: usize| a[i].parse::<f64>().unwrap();
            let seed: u64 = a[4].parse().unwrap();
            let sigs = if a.len() > 12 {
                // jt9's dummy calls, for exercising its a-priori passes.
                let pool: Vec<[u8; 77]> = ohsdigi::decode::sim::PAYLOAD_POOL
                    .iter()
                    .filter(|(t, _)| t.contains("K1ABC") && t.contains("W9XYZ"))
                    .map(|(_, h)| ohsdigi::decode::sim::hex_to_bits77(h).unwrap())
                    .collect();
                ohsdigi::decode::sim::random_signals_band(
                    &pool,
                    a[5].parse().unwrap(),
                    p(6),
                    p(7),
                    p(8),
                    p(9),
                    p(10),
                    seed,
                    p(11),
                    p(12),
                )
            } else if a.len() > 11 {
                ohsdigi::decode::sim::random_signals_band(
                    &payload_pool(),
                    a[5].parse().unwrap(),
                    p(6),
                    p(7),
                    p(8),
                    p(9),
                    p(10),
                    seed,
                    p(11),
                    p(12),
                )
            } else {
                random_signals(
                    mode,
                    &payload_pool(),
                    a[5].parse().unwrap(),
                    p(6),
                    p(7),
                    p(8),
                    p(9),
                    p(10),
                    seed,
                )
            };
            let x = make_slot(mode, &sigs, seed, true);
            write_wav(&a[3], &x);
            for s in &sigs {
                println!(
                    "SIG {} {:.2} {:.3} {:.2} {:.3}",
                    bits77_to_hex(&s.payload),
                    s.freq,
                    s.dt,
                    s.snr_db,
                    s.drift_hz_s
                );
            }
        }
        "stages" => {
            let x = read_wav(&a[2]);
            let ndepth: i32 = a[3].parse().unwrap();
            let mut o = std::fs::File::create(&a[4]).unwrap();
            let mut dd = vec![0f32; ft8::NMAX];
            dd[..x.len().min(ft8::NMAX)].copy_from_slice(&x[..x.len().min(ft8::NMAX)]);
            let syncmin = if ndepth <= 2 { 1.6 } else { 1.3 };
            let (cands, sbase) = ft8::sync8(&dd, 200, 4000, syncmin, 1500, 600);
            writeln!(o, "NCAND {}", cands.len()).unwrap();
            for (i, c) in cands.iter().enumerate() {
                writeln!(o, "CAND {} {:e} {:e} {:e}", i + 1, c.freq, c.dt, c.sync).unwrap();
            }
            writeln!(o, "SBASE{}", floats(&sbase[1..])).unwrap();
            let ds = ft8::Downsampler::new(&dd);
            let p = Ft8Params {
                lapon: false,
                ..Default::default()
            };
            for (i, c) in cands.iter().enumerate() {
                let icand = i + 1;
                match ft8::ft8_metrics(&ds, c.freq, c.dt) {
                    None => writeln!(o, "BAIL {}", icand).unwrap(),
                    Some(m) => {
                        writeln!(
                            o,
                            "MET {} {} {} {} {} {:e} {}",
                            icand, m.f1, m.xdt, m.ibest, m.delfbest, m.sync, m.nsync
                        )
                        .unwrap();
                        for (k, name) in ["LLRA", "LLRB", "LLRC", "LLRD"].iter().enumerate() {
                            writeln!(o, "{}{}", name, floats(&m.llr[k])).unwrap();
                        }
                    }
                }
                let ib = (c.freq / 3.125).round() as usize;
                let xbase = 10f32.powf(0.1 * (sbase[ib] - 40.0));
                let r = ft8::ft8b(&ds, &p, ndepth, 50, c.freq, c.dt, xbase, c.sync, Some(&unpack_ok));
                if let Some(d) = r.decoded {
                    writeln!(
                        o,
                        "DEC {} {} {} {} {} {}",
                        icand,
                        d.nharderrors,
                        d.dmin,
                        d.snr,
                        d.freq,
                        bits(&d.payload)
                    )
                    .unwrap();
                }
            }
        }
        "ldpc" => {
            let txt = std::fs::read_to_string(&a[2]).unwrap();
            let mut o = std::fs::File::create(&a[3]).unwrap();
            let mut sets: Vec<[f32; 174]> = vec![];
            for line in txt.lines() {
                let mut it = line.split_whitespace();
                let tag = it.next().unwrap_or("");
                if tag.starts_with("LLR") {
                    let v: Vec<f32> = it.map(|t| t.parse().unwrap()).collect();
                    let mut l = [0f32; 174];
                    l.copy_from_slice(&v);
                    sets.push(l);
                    if sets.len() == 4 {
                        for (iset, l) in sets.iter().enumerate() {
                            for maxosd in [-1, 0, 2] {
                                let r = decode174_91(l, maxosd, 2, &[0; 174]);
                                let m = if r.nharderror >= 0 { r.message91 } else { [0; 91] };
                                writeln!(
                                    o,
                                    "LDPC {} {} {} {} {:.5} {}",
                                    iset + 1,
                                    maxosd,
                                    r.nharderror,
                                    r.ntype,
                                    r.dmin,
                                    bits(&m)
                                )
                                .unwrap();
                            }
                        }
                        sets.clear();
                    }
                }
            }
        }
        "subtract" => {
            let x = read_wav(&a[2]);
            let mut dd = vec![0f32; ft8::NMAX];
            dd[..x.len().min(ft8::NMAX)].copy_from_slice(&x[..x.len().min(ft8::NMAX)]);
            for line in std::fs::read_to_string(&a[3]).unwrap().lines() {
                let v: Vec<f32> = line.split_whitespace().map(|t| t.parse().unwrap()).collect();
                if v.len() < 82 {
                    continue;
                }
                let mut t = [0u8; 79];
                for i in 0..79 {
                    t[i] = v[3 + i] as u8;
                }
                ft8::subtractft8(&mut dd, &t, v[0], v[1], v[2] != 0.0);
            }
            let mut o = std::fs::File::create(&a[4]).unwrap();
            for v in dd {
                o.write_all(&v.to_le_bytes()).unwrap();
            }
        }
        "decode" => {
            let x = read_wav(&a[3]);
            let ndepth: i32 = a[4].parse().unwrap();
            let serial = a.iter().any(|s| s == "serial");
            let nofile = a.iter().any(|s| s == "nofile");
            let q: usize = a
                .iter()
                .find_map(|s| s.strip_prefix("q="))
                .map(|v| v.parse().unwrap())
                .unwrap_or(0);
            if a[2] == "ft4" {
                let p = ft4::Ft4Params {
                    ndepth,
                    threads: if serial { 1 } else { 0 },
                    nqso_progress: q,
                    ..ft4::Ft4Params::jt9()
                };
                let (d, _) = ft4::decode_slot(&x, &p, &mut CallHashes::new());
                for d in d {
                    println!(
                        "{} {} {:.2} {:.1} {} {}",
                        bits77_to_hex(&d.payload),
                        d.snr,
                        d.dt,
                        d.freq,
                        d.iaptype,
                        d.text
                    );
                }
            } else {
                let p = Ft8Params {
                    ndepth,
                    threads: if serial { 1 } else { 0 },
                    jt9_file_mode: !nofile,
                    nqso_progress: q,
                    ..Ft8Params::jt9()
                };
                let r = ft8::decode_slot(&x, &p, &mut CallHashes::new());
                for d in r.decodes {
                    println!(
                        "{} {} {:.2} {:.1} {} {}",
                        bits77_to_hex(&d.payload),
                        d.snr,
                        d.dt,
                        d.freq,
                        d.iaptype,
                        d.text
                    );
                }
            }
        }
        "ft4" => {
            let x = read_wav(&a[2]);
            let ndepth: i32 = a[3].parse().unwrap();
            let p = ft4::Ft4Params {
                ndepth,
                trace: true,
                ..ft4::Ft4Params::jt9()
            };
            let (d, _, tr) = ft4::decode_slot_traced(&x, &p, &mut CallHashes::new());
            let mut o = std::fs::File::create(&a[4]).unwrap();
            for l in tr {
                writeln!(o, "{}", l).unwrap();
            }
            for d in d {
                writeln!(
                    o,
                    "FT4DEC {} {} {} {} {}",
                    d.snr,
                    d.dt,
                    d.freq,
                    d.iaptype,
                    bits(&d.payload)
                )
                .unwrap();
            }
        }
        "time" => {
            let ft4m = a[2] == "ft4";
            let ndepth: i32 = a[3].parse().unwrap();
            let serial = std::env::var("OHSDIGI_SERIAL").is_ok();
            let mut tot = 0f64;
            let mut n = 0;
            for f in &a[4..] {
                let x = read_wav(f);
                let t = Instant::now();
                let nd = if ft4m {
                    let p = ft4::Ft4Params {
                        ndepth,
                        threads: if serial { 1 } else { 0 },
                        ..ft4::Ft4Params::jt9()
                    };
                    ft4::decode_slot(&x, &p, &mut CallHashes::new()).0.len()
                } else {
                    let p = Ft8Params {
                        ndepth,
                        threads: if serial { 1 } else { 0 },
                        ..Ft8Params::jt9()
                    };
                    ft8::decode_slot(&x, &p, &mut CallHashes::new()).decodes.len()
                };
                let e = t.elapsed().as_secs_f64();
                tot += e;
                n += 1;
                println!("{} {:.4} {}", f, e, nd);
            }
            println!("mean {:.4}", tot / n as f64);
        }
        "profile" => {
            // Where one FT8 pass's time goes, single-threaded.
            let x = read_wav(&a[2]);
            let mut dd = vec![0f32; ft8::NMAX];
            dd[..x.len().min(ft8::NMAX)].copy_from_slice(&x[..x.len().min(ft8::NMAX)]);
            let reps = 5;
            let t = Instant::now();
            let mut cands = vec![];
            let mut sbase = vec![];
            for _ in 0..reps {
                (cands, sbase) = ft8::sync8(&dd, 200, 4000, 1.6, 1500, 600);
            }
            println!(
                "sync8          {:.2} ms ({} candidates)",
                t.elapsed().as_secs_f64() * 1e3 / reps as f64,
                cands.len()
            );
            let t = Instant::now();
            let mut ds = ft8::Downsampler::new(&dd);
            for _ in 1..reps {
                ds = ft8::Downsampler::new(&dd);
            }
            println!("downsample FFT {:.2} ms", t.elapsed().as_secs_f64() * 1e3 / reps as f64);
            let p = Ft8Params::jt9();
            let t = Instant::now();
            let mut outs = vec![];
            for c in &cands {
                let ib = (c.freq / 3.125).round() as usize;
                let xbase = 10f32.powf(0.1 * (sbase[ib] - 40.0));
                outs.push(ft8::ft8b(&ds, &p, 1, 50, c.freq, c.dt, xbase, c.sync, Some(&unpack_ok)));
            }
            let e = t.elapsed().as_secs_f64() * 1e3;
            let t = Instant::now();
            let mut nm = 0;
            for c in &cands {
                if ft8::ft8_metrics(&ds, c.freq, c.dt).is_some() {
                    nm += 1;
                }
            }
            let em = t.elapsed().as_secs_f64() * 1e3;
            println!(
                "ft8b x{}       {:.2} ms (metrics alone {:.2} ms; {} past the sync check)",
                cands.len(),
                e,
                em,
                nm
            );
            let subs: Vec<_> = outs.iter().filter_map(|o| o.subtract).collect();
            let t = Instant::now();
            for (it, f1, xdt) in &subs {
                ft8::subtractft8(&mut dd, it, *f1, *xdt, false);
            }
            println!("subtract x{}    {:.2} ms", subs.len(), t.elapsed().as_secs_f64() * 1e3);
        }
        "tones" => {
            let m = ohsdigi::decode::sim::hex_to_bits77(&a[2]).unwrap();
            let t = ohsdigi::ft8::tones(&m);
            println!("{}", t.iter().map(|x| x.to_string()).collect::<Vec<_>>().join(" "));
        }
        "rms" => {
            let x = read_wav(&a[2]);
            let r = (x.iter().map(|v| (*v as f64).powi(2)).sum::<f64>() / x.len() as f64).sqrt();
            println!("{}", r);
        }
        _ => eprintln!("unknown command"),
    }
}
