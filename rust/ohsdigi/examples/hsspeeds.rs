//! Development tool: HSmodem's sensitivity at every speed, station to
//! station as OpenHamShack NB runs it - modulator::ssb_audio at 12 kHz, white
//! noise, Receiver::ssb - so the user guide's margins come from a run, not
//! a guess. Not part of the library.
//!
//!   cargo run --release --example hsspeeds [offset_hz]
//!
//! For each speed and Es/N0 it prints the frames decoded of those sent and
//! the receiver's MER; then, per speed, the lowest Es/N0 at which every
//! frame after the first two decoded (the "cliff"), also as SNR in 2.5 kHz
//! (Es/N0 + 10 log10(Rs / 2500)), the way an SSB operator reads a signal.

use ohsdigi::hsmodem::frame::{Packer, PAYLOADLEN};
use ohsdigi::hsmodem::modulator::ssb_audio;
use ohsdigi::hsmodem::receiver::{Options, Receiver};
use ohsdigi::hsmodem::speed::{Speed, SPEEDS};

const RATE: f32 = 12000.0;

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

fn run(sp: &Speed, n: usize, esn0: f32, hz: f32, seed: u64) -> (usize, f32, f32) {
    let mut p = Packer::default();
    let mut bytes = Vec::new();
    for i in 0..n {
        let mut pl = [0u8; PAYLOADLEN];
        for (j, b) in pl.iter_mut().enumerate() {
            *b = (i * 31 + j * 7 + seed as usize) as u8;
        }
        bytes.extend_from_slice(&p.pack(&pl, 5, 1, false));
    }
    let a = ssb_audio(sp, &bytes, RATE, 1500.0 + hz, 0.85, 400, 400);
    let lead = (400.0 * RATE / sp.symbol_rate()) as usize;
    let body = &a[lead..a.len() - lead];
    let pw: f32 = body.iter().map(|v| v * v).sum::<f32>() / body.len() as f32;
    let sigma = (pw * RATE / (2.0 * sp.symbol_rate() * 10f32.powf(esn0 / 10.0))).sqrt();
    let mut g = Lcg(seed);
    let a: Vec<f32> = a.iter().map(|v| v + sigma * g.gauss()).collect();
    let mut rx = Receiver::ssb(RATE, 1500.0, *sp, Options::default());
    let mut out = Vec::new();
    let mut mer = Vec::new();
    for c in a.chunks(1200) {
        rx.feed_ssb(c, &mut out);
        if rx.stats().in_sync {
            mer.push(rx.stats().mer_db);
        }
    }
    let m = if mer.is_empty() {
        0.0
    } else {
        mer.iter().sum::<f32>() / mer.len() as f32
    };
    (out.len(), m, rx.stats().freq_hz)
}

fn main() {
    let hz: f32 = std::env::args().nth(1).map(|s| s.parse().unwrap()).unwrap_or(0.0);
    println!("offset {hz} Hz; frames decoded/sent, mean MER while in sync");
    let mut cliffs = Vec::new();
    for sp in SPEEDS {
        let n = (20.0 * sp.bitrate as f32 / 8.0 / 258.0).ceil() as usize + 2;
        let start = match sp.bits {
            1 => 0.0,
            2 => 3.0,
            _ => 8.0,
        };
        let mut cliff = None;
        let mut line = format!("mode {} {:>4} bit/s:", sp.mode, sp.bitrate);
        for step in 0..14 {
            let e = start + step as f32;
            let (got, mer, _) = run(&sp, n, e, hz, 100 + step);
            line += &format!(" {e:>2}dB {got:>3}/{n} ({mer:.1})");
            if got + 2 >= n && cliff.is_none() {
                cliff = Some(e);
            }
        }
        println!("{line}");
        cliffs.push((sp, cliff));
    }
    println!();
    println!("speed  bit/s   scheme  baud    cliff Es/N0   = SNR in 2.5 kHz");
    for (sp, c) in cliffs {
        let s = match sp.bits {
            1 => "BPSK",
            2 => "QPSK",
            _ => "8APSK",
        };
        match c {
            Some(e) => println!(
                "{:>5}  {:>5}   {s:<6}  {:>6.1}  {e:>5.0} dB      {:>6.1} dB",
                sp.mode,
                sp.bitrate,
                sp.symbol_rate(),
                e + 10.0 * (sp.symbol_rate() / 2500.0).log10()
            ),
            None => println!("{:>5}  {:>5}   {s:<6}  never", sp.mode, sp.bitrate),
        }
    }
}
