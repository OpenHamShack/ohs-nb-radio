//! Numerical helpers the WSJT-X decoders lean on, ported so that their
//! quirks come along: Numerical Recipes' `indexx` (an unstable quicksort, so
//! which of two equal sync scores comes first is whatever indexx says, and
//! the candidate order with it), `shell`/`pctile`, and `polyfit`/`determ`.
//!
//! From WSJT-X 2.7.0 (GPL-3): lib/indexx.f90, shell.f90, pctile.f90,
//! polyfit.f90, determ.f90, nuttal_window.f90, four2a.f90 (FFTW wrapper,
//! here rustfft). Copyright (C) 2001-2024 Joe Taylor K1JT and the WSJT-X
//! development team; indexx/polyfit after Numerical Recipes and Bevington.

use rustfft::num_complex::Complex32;
use rustfft::{Fft, FftDirection, FftPlanner};
use std::collections::HashMap;
use std::sync::{Arc, Mutex, OnceLock};

pub type C32 = Complex32;

/// FFT plans, shared by every thread. four2a keeps a table of FFTW plans
/// for the same reason: the decoder asks for the same few lengths
/// thousands of times a slot.
type Plans = (FftPlanner<f32>, HashMap<(usize, bool), Arc<dyn Fft<f32>>>);
type PulseTables = HashMap<(u32, usize), Arc<Vec<f32>>>;

pub fn fft_plan(n: usize, forward: bool) -> Arc<dyn Fft<f32>> {
    static PLANS: OnceLock<Mutex<Plans>> = OnceLock::new();
    let m = PLANS.get_or_init(|| Mutex::new((FftPlanner::new(), HashMap::new())));
    let mut g = m.lock().unwrap();
    if let Some(p) = g.1.get(&(n, forward)) {
        return p.clone();
    }
    let dir = if forward {
        FftDirection::Forward
    } else {
        FftDirection::Inverse
    };
    let p = g.0.plan_fft(n, dir);
    g.1.insert((n, forward), p.clone());
    p
}

/// Run `f` on a thread pool of its own, `threads` wide (0 = one fewer than
/// the machine's cores, at least 1), and take the pool down when `f`
/// returns.
///
/// Not rayon's global pool: that one is as wide as the machine and its
/// workers live for the rest of the process. Inside NB that meant a decode
/// could take every core from the receive path and the UI for its
/// duration, and leave 16 idle threads behind. A pool per decode costs a
/// few tens of microseconds to start, against tens of milliseconds of
/// decoding, and nothing of ours is running between slots. (It was first
/// written while chasing a segfault in the Python suite that turned out
/// to be the UI's: Python's garbage collector freeing a closed window
/// inside QApplication.setStyleSheet - docs/digimodes-rust.md, "Threads".)
pub fn with_pool<R: Send>(threads: usize, f: impl FnOnce() -> R + Send) -> R {
    let n = if threads == 0 {
        std::thread::available_parallelism()
            .map(|n| n.get())
            .unwrap_or(2)
            .saturating_sub(1)
            .max(1)
    } else {
        threads
    };
    match rayon::ThreadPoolBuilder::new()
        .num_threads(n)
        .thread_name(|i| format!("ohsdigi-decode-{i}"))
        .build()
    {
        Ok(pool) => pool.install(f),
        // No threads to be had: decode on this one (rayon's par_iter then
        // runs on the global pool; better slow than nothing).
        Err(_) => f(),
    }
}

/// four2a(...,isign=-1,iform=1): in-place forward complex FFT, unscaled.
pub fn fft_fwd(buf: &mut [C32]) {
    fft_plan(buf.len(), true).process(buf);
}

/// four2a(...,isign=+1,iform=1): in-place inverse complex FFT, unscaled.
pub fn fft_inv(buf: &mut [C32]) {
    fft_plan(buf.len(), false).process(buf);
}

/// four2a(x,nfft,1,-1,0): real-to-complex forward FFT of `x` (zero padded
/// to `nfft`), returning bins 0..=nfft/2 like FFTW's r2c.
pub fn rfft(x: &[f32], nfft: usize) -> Vec<C32> {
    let mut buf: Vec<C32> = Vec::with_capacity(nfft);
    buf.extend(x.iter().take(nfft).map(|&v| C32::new(v, 0.0)));
    buf.resize(nfft, C32::new(0.0, 0.0));
    fft_fwd(&mut buf);
    buf.truncate(nfft / 2 + 1);
    buf
}

/// Numerical Recipes `indexx`, as lib/indexx.f90 has it. Returns 0-based
/// indices of `arr` in ascending order. Not stable: equal keys come out in
/// whatever order this particular quicksort leaves them, and sync8's
/// candidate list inherits that order, so it is ported rather than
/// replaced by a library sort.
pub fn indexx(arr: &[f32]) -> Vec<usize> {
    const MM: usize = 7;
    let n = arr.len();
    // 1-based working copy, as in the Fortran.
    let mut indx: Vec<usize> = (0..=n).collect();
    if n == 0 {
        return vec![];
    }
    let a_ = |i: usize| arr[i - 1];
    let mut istack: Vec<usize> = vec![0; 64];
    let mut jstack: usize = 0;
    let mut l: usize = 1;
    let mut ir: usize = n;
    loop {
        if ir - l < MM {
            for j in (l + 1)..=ir {
                let indxt = indx[j];
                let a = a_(indxt);
                let mut i = j as isize - 1;
                while i >= 1 {
                    if a_(indx[i as usize]) <= a {
                        break;
                    }
                    indx[i as usize + 1] = indx[i as usize];
                    i -= 1;
                }
                if i < 1 {
                    i = 0;
                }
                indx[i as usize + 1] = indxt;
            }
            if jstack == 0 {
                break;
            }
            ir = istack[jstack];
            l = istack[jstack - 1];
            jstack -= 2;
        } else {
            let k = (l + ir) / 2;
            indx.swap(k, l + 1);
            if a_(indx[l + 1]) > a_(indx[ir]) {
                indx.swap(l + 1, ir);
            }
            if a_(indx[l]) > a_(indx[ir]) {
                indx.swap(l, ir);
            }
            if a_(indx[l + 1]) > a_(indx[l]) {
                indx.swap(l + 1, l);
            }
            let mut i = l + 1;
            let mut j = ir;
            let indxt = indx[l];
            let a = a_(indxt);
            loop {
                i += 1;
                while a_(indx[i]) < a {
                    i += 1;
                }
                j -= 1;
                while a_(indx[j]) > a {
                    j -= 1;
                }
                if j < i {
                    break;
                }
                indx.swap(i, j);
            }
            indx[l] = indx[j];
            indx[j] = indxt;
            jstack += 2;
            if jstack + 1 >= istack.len() {
                istack.resize(istack.len() * 2, 0);
            }
            if ir - i + 1 >= j - l {
                istack[jstack] = ir;
                istack[jstack - 1] = i;
                ir = j - 1;
            } else {
                istack[jstack] = j - 1;
                istack[jstack - 1] = l;
                l = i;
            }
        }
    }
    indx[1..].iter().map(|&v| v - 1).collect()
}

/// lib/shell.f90: Shell sort, ascending, in place.
pub fn shell(a: &mut [f32]) {
    let n = a.len();
    if n == 0 {
        return;
    }
    // 1-based indexing as in the Fortran.
    let mut inc: usize = 1;
    loop {
        inc = 3 * inc + 1;
        if inc > n {
            break;
        }
    }
    loop {
        inc /= 3;
        for i in (inc + 1)..=n {
            let v = a[i - 1];
            let mut j = i;
            while a[j - inc - 1] > v {
                a[j - 1] = a[j - inc - 1];
                j -= inc;
                if j <= inc {
                    break;
                }
            }
            a[j - 1] = v;
        }
        if inc <= 1 {
            break;
        }
    }
}

/// lib/pctile.f90: the npct'th percentile of x.
pub fn pctile(x: &[f32], npct: i32) -> f32 {
    let npts = x.len();
    if !(0..=100).contains(&npct) {
        return 1.0;
    }
    let mut tmp = x.to_vec();
    shell(&mut tmp);
    let mut j = (npts as f32 * 0.01 * npct as f32).round() as isize;
    if j < 1 {
        j = 1;
    }
    if j > npts as isize {
        j = npts as isize;
    }
    tmp[j as usize - 1]
}

/// lib/determ.f90 (Bevington): determinant by elimination; modifies `a`.
fn determ(a: &mut [[f64; 10]; 10], norder: usize) -> f64 {
    let mut det = 1.0f64;
    for k in 0..norder {
        if a[k][k] == 0.0 {
            let mut found = None;
            for j in k..norder {
                if a[k][j] != 0.0 {
                    found = Some(j);
                    break;
                }
            }
            let Some(j) = found else { return 0.0 };
            for i in k..norder {
                a[i].swap(j, k);
            }
            det = -det;
        }
        det *= a[k][k];
        if k + 1 < norder {
            for i in (k + 1)..norder {
                for j in (k + 1)..norder {
                    a[i][j] -= a[i][k] * a[k][j] / a[k][k];
                }
            }
        }
    }
    det
}

/// lib/polyfit.f90 with mode=0 (unweighted): least-squares polynomial of
/// `nterms` coefficients by Cramer's rule, as WSJT-X does it.
pub fn polyfit(x: &[f64], y: &[f64], nterms: usize) -> [f64; 5] {
    let nmax = 2 * nterms - 1;
    let mut sumx = [0f64; 10];
    let mut sumy = [0f64; 10];
    for (&xi, &yi) in x.iter().zip(y.iter()) {
        let mut xterm = 1.0;
        for n in 0..nmax {
            sumx[n] += xterm;
            xterm *= xi;
        }
        let mut yterm = yi;
        for n in 0..nterms {
            sumy[n] += yterm;
            yterm *= xi;
        }
    }
    let mut array = [[0f64; 10]; 10];
    for j in 0..nterms {
        array[j][..nterms].copy_from_slice(&sumx[j..j + nterms]);
    }
    let delta = determ(&mut array, nterms);
    let mut a = [0f64; 5];
    if delta == 0.0 {
        return a;
    }
    for l in 0..nterms {
        for j in 0..nterms {
            array[j][..nterms].copy_from_slice(&sumx[j..j + nterms]);
            array[j][l] = sumy[j];
        }
        a[l] = determ(&mut array, nterms) / delta;
    }
    a
}

/// lib/nuttal_window.f90.
pub fn nuttall_window(n: usize) -> Vec<f32> {
    let pi = 4.0f32 * 1f32.atan();
    let (a0, a1, a2, a3) = (0.3635819f32, -0.4891775f32, 0.1365995f32, -0.0106411f32);
    (0..n)
        .map(|i| {
            let i = i as f32;
            let nf = n as f32;
            a0 + a1 * (2.0 * pi * i / nf).cos() + a2 * (4.0 * pi * i / nf).cos() + a3 * (6.0 * pi * i / nf).cos()
        })
        .collect()
}

/// Fortran's nint for reals: round half away from zero.
#[inline]
pub fn nint(x: f32) -> i32 {
    x.round() as i32
}

/// Fortran's maxloc on a slice: the first index of the largest value.
#[inline]
pub fn maxloc(v: &[f32]) -> usize {
    let mut best = 0;
    for i in 1..v.len() {
        if v[i] > v[best] {
            best = i;
        }
    }
    best
}

/// lib/ft8/ft8b.f90 `normalizebmet`.
pub fn normalizebmet(b: &mut [f32]) {
    let n = b.len() as f32;
    let av: f32 = b.iter().sum::<f32>() / n;
    let av2: f32 = b.iter().map(|x| x * x).sum::<f32>() / n;
    let var = av2 - av * av;
    let sig = if var > 0.0 { var.sqrt() } else { av2.sqrt() };
    for x in b.iter_mut() {
        *x /= sig;
    }
}

/// gfsk_pulse over the 3 symbols gen_ft8wave/gen_ft4wave sample it on,
/// `pulse(i) = gfsk_pulse(bt, (i - 1.5 nsps)/nsps)` for i = 1..3 nsps. Made
/// once per (bt, nsps), as the Fortran does (its `fchk` cache): 5760 erf
/// evaluations per FT8 subtraction were a third of the subtraction time.
pub fn gfsk_pulse_table(bt: f32, nsps: usize) -> Arc<Vec<f32>> {
    static T: OnceLock<Mutex<PulseTables>> = OnceLock::new();
    let m = T.get_or_init(|| Mutex::new(HashMap::new()));
    let mut g = m.lock().unwrap();
    g.entry((bt.to_bits(), nsps))
        .or_insert_with(|| {
            Arc::new(
                (1..=3 * nsps)
                    .map(|i| gfsk_pulse(bt, (i as f32 - 1.5 * nsps as f32) / nsps as f32))
                    .collect(),
            )
        })
        .clone()
}

/// gfsk_pulse.f90 (lib/ft2): the frequency pulse of a Gaussian-filtered
/// FSK symbol with bandwidth-time product `b`, at time `t` in symbols.
pub fn gfsk_pulse(b: f32, t: f32) -> f32 {
    let pi = 4.0f32 * 1f32.atan();
    let c = pi * (2.0f32 / 2f32.ln()).sqrt();
    0.5 * (erf(c * b * (t + 0.5)) - erf(c * b * (t - 0.5)))
}

/// erf, to f32 precision (Rust's std has none). W. J. Cody's rational
/// approximations as used by most libms, evaluated in f64.
pub fn erf(x: f32) -> f32 {
    erf64(x as f64) as f32
}

fn erf64(x: f64) -> f64 {
    // Abramowitz & Stegun 7.1.26 is only good to 1.5e-7; use the series /
    // continued fraction split instead, accurate to ~1e-15 in f64.
    let ax = x.abs();
    let r = if ax < 2.5 {
        // Maclaurin series.
        let mut sum = ax;
        let mut term = ax;
        let x2 = ax * ax;
        let mut n = 0.0;
        loop {
            n += 1.0;
            term *= -x2 / n;
            let add = term / (2.0 * n + 1.0);
            sum += add;
            if add.abs() <= 1e-17 * sum.abs() || n > 200.0 {
                break;
            }
        }
        sum * 2.0 / std::f64::consts::PI.sqrt()
    } else {
        // erfc by Lentz's continued fraction.
        let x2 = ax * ax;
        let tiny = 1e-300;
        let mut f = ax;
        if f == 0.0 {
            f = tiny;
        }
        let mut c = f;
        let mut d = 0.0;
        for i in 1..200 {
            let an = i as f64 / 2.0;
            d = ax + an * d;
            if d == 0.0 {
                d = tiny;
            }
            c = ax + an / c;
            if c == 0.0 {
                c = tiny;
            }
            d = 1.0 / d;
            let delta = c * d;
            f *= delta;
            if (delta - 1.0).abs() < 1e-16 {
                break;
            }
        }
        let erfc = (-x2).exp() / (f * std::f64::consts::PI.sqrt());
        1.0 - erfc
    };
    if x < 0.0 {
        -r
    } else {
        r
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn indexx_sorts() {
        let v: Vec<f32> = (0..200).map(|i| ((i * 7919) % 211) as f32 * 0.5).collect();
        let ix = indexx(&v);
        for w in ix.windows(2) {
            assert!(v[w[0]] <= v[w[1]]);
        }
        let mut seen = ix.clone();
        seen.sort();
        assert_eq!(seen, (0..200).collect::<Vec<_>>());
    }

    #[test]
    fn shell_sorts() {
        let mut v: Vec<f32> = (0..97).map(|i| ((i * 31) % 97) as f32).collect();
        shell(&mut v);
        for w in v.windows(2) {
            assert!(w[0] <= w[1]);
        }
    }

    #[test]
    fn erf_values() {
        assert!((erf(0.5) - 0.520_499_9).abs() < 1e-6);
        assert!((erf(1.0) - 0.842_700_8).abs() < 1e-6);
        assert!((erf(3.0) - 0.999_977_9).abs() < 1e-6);
        assert!((erf(-2.0) + 0.995_322_3).abs() < 1e-6);
    }

    #[test]
    fn polyfit_exact_quadratic() {
        let x: Vec<f64> = (0..20).map(|i| i as f64 - 10.0).collect();
        let y: Vec<f64> = x.iter().map(|t| 3.0 + 0.5 * t - 0.25 * t * t).collect();
        let a = polyfit(&x, &y, 5);
        assert!((a[0] - 3.0).abs() < 1e-6 && (a[1] - 0.5).abs() < 1e-6 && (a[2] + 0.25).abs() < 1e-6);
    }
}
