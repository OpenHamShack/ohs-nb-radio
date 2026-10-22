// ohsdigi - the pieces of liquid-dsp that HSmodem's modem is built from.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later
//
// Ported from liquid-dsp (https://github.com/jgaeddert/liquid-dsp),
// Copyright (c) 2007-2020 Joseph Gaeddert, MIT licence (notice in
// rust/ohsdigi/LICENSE-THIRD-PARTY). The reference is the "1.3.2" that
// HSmodem ships prebuilt (hsmodem/SharedLibs/*/libliquid.so) - DJ0ABR's fork
// of liquid-dsp (github.com/dj0abr/liquid-dsp), whose algorithms here are the
// 1.3.2 release's with error codes added. Files followed:
// src/nco/src/nco.c, src/agc/src/agc.c, src/filter/src/{symsync,firpfb,
// firinterp,firdecim,firdes,rrcos,iirfiltsos}.c, src/equalization/src/
// eqlms.c, src/modem/src/{modem_apsk,modem_apsk_const,modem_common}.c,
// src/math/src/{math.bessel,math.gamma,math,windows}.c, src/buffer/src/
// {window,wdelay}.c.

//! The liquid-dsp objects HSmodem's receiver and transmitter use, ported
//! one for one, in single precision as liquid computes them. They are
//! kept as liquid has them - including its quirks (the NCO's fixed-point
//! phase and its coarse negative steps, the decimator that drops the last
//! tap of its own prototype, the 1+7 APSK map) - because the point is to
//! behave as HSmodem does, and HSmodem is these objects
//! (docs/hsmodem-research.md, "Verification"). Nothing else in ohsdigi
//! depends on them; they are not a general DSP library.

use std::f32::consts::PI;

/// A complex sample, liquid's `float complex`.
#[derive(Debug, Clone, Copy, PartialEq, Default)]
pub struct C32 {
    pub re: f32,
    pub im: f32,
}

// add/sub/mul as methods rather than operator traits: the DSP below reads
// as liquid's C, one named operation at a time.
#[allow(clippy::should_implement_trait)]
impl C32 {
    pub const ZERO: C32 = C32 { re: 0.0, im: 0.0 };
    #[inline]
    pub fn new(re: f32, im: f32) -> C32 {
        C32 { re, im }
    }
    #[inline]
    pub fn mul(self, o: C32) -> C32 {
        C32::new(self.re * o.re - self.im * o.im, self.re * o.im + self.im * o.re)
    }
    #[inline]
    pub fn conj(self) -> C32 {
        C32::new(self.re, -self.im)
    }
    #[inline]
    pub fn scale(self, k: f32) -> C32 {
        C32::new(self.re * k, self.im * k)
    }
    #[inline]
    pub fn add(self, o: C32) -> C32 {
        C32::new(self.re + o.re, self.im + o.im)
    }
    #[inline]
    pub fn sub(self, o: C32) -> C32 {
        C32::new(self.re - o.re, self.im - o.im)
    }
    #[inline]
    pub fn norm_sqr(self) -> f32 {
        self.re * self.re + self.im * self.im
    }
    #[inline]
    pub fn abs(self) -> f32 {
        self.re.hypot(self.im)
    }
    #[inline]
    pub fn arg(self) -> f32 {
        self.im.atan2(self.re)
    }
    #[inline]
    pub fn expj(phi: f32) -> C32 {
        C32::new(phi.cos(), phi.sin())
    }
}

// ------------------------------------------------------------------ math

/// liquid_lngammaf: log Gamma by recursion up to 10, then Stirling.
fn lngammaf(z: f32) -> f32 {
    if z < 10.0 {
        lngammaf(z + 1.0) - z.ln()
    } else {
        let mut g = (0.5 * ((2.0 * std::f64::consts::PI as f32).ln() as f64 - (z as f64).ln())) as f32;
        g += z * ((z + (1.0 / (12.0 * z - 0.1 / z))).ln() - 1.0);
        g
    }
}

/// liquid_besseli0f: 32 terms of the series, through lngamma.
fn besseli0f(z: f32) -> f32 {
    if z == 0.0 {
        return 1.0;
    }
    let mut y = 0.0f32;
    for k in 0..32u32 {
        let t = k as f32 * (0.5 * z).ln() - lngammaf(k as f32 + 1.0);
        y += (2.0 * t).exp();
    }
    y
}

/// liquid's sincf, with its small-argument product form.
fn sincf(x: f32) -> f32 {
    if x.abs() < 0.01 {
        return (PI * x / 2.0).cos() * (PI * x / 4.0).cos() * (PI * x / 8.0).cos();
    }
    (PI * x).sin() / (PI * x)
}

/// kaiser(): note r = 2t/N, not 2t/(N-1) - liquid's definition.
fn kaiser(n: usize, len: usize, beta: f32, mu: f32) -> f32 {
    let t = n as f32 - (len - 1) as f32 / 2.0 + mu;
    let r = 2.0 * t / len as f32;
    besseli0f(beta * (1.0 - r * r).sqrt()) / besseli0f(beta)
}

fn kaiser_beta_as(as_db: f32) -> f32 {
    let a = as_db.abs();
    if a > 50.0 {
        0.1102 * (a - 8.7)
    } else if a > 21.0 {
        (0.5842 * ((a - 21.0).powf(0.4)) as f64 + (0.07886 * (a - 21.0)) as f64) as f32
    } else {
        0.0
    }
}

/// liquid_firdes_kaiser.
pub fn firdes_kaiser(n: usize, fc: f32, as_db: f32, mu: f32) -> Vec<f32> {
    let beta = kaiser_beta_as(as_db);
    (0..n)
        .map(|i| {
            let t = i as f32 - (n - 1) as f32 / 2.0 + mu;
            sincf(2.0 * fc * t) * kaiser(i, n, beta, mu)
        })
        .collect()
}

/// liquid_firdes_rrcos: square-root raised cosine, 2km+1 taps, peak
/// 1 - beta + 4 beta/pi (not normalised).
pub fn firdes_rrcos(k: usize, m: usize, beta: f32, dt: f32) -> Vec<f32> {
    let pi = std::f64::consts::PI as f32;
    let len = 2 * k * m + 1;
    let (kf, mf) = (k as f32, m as f32);
    (0..len)
        .map(|n| {
            let z = (n as f32 + dt) / kf - mf;
            let t1 = ((1.0 + beta) * pi * z).cos();
            let t2 = ((1.0 - beta) * pi * z).sin();
            if z.abs() < 1e-5 {
                1.0 - beta + 4.0 * beta / pi
            } else {
                let t3 = 1.0 / (4.0 * beta * z);
                let mut g = 1.0 - 16.0 * beta * beta * z * z;
                g *= g;
                if g < 1e-5 {
                    let g1 = 1.0 + 2.0 / pi;
                    let g2 = (0.25 * pi / beta).sin();
                    let g3 = 1.0 - 2.0 / pi;
                    let g4 = (0.25 * pi / beta).cos();
                    beta / 2.0f32.sqrt() * (g1 * g2 + g3 * g4)
                } else {
                    let t4 = 4.0 * beta / (pi * 1.0f32.sqrt() * (1.0 - (16.0 * beta * beta * z * z)));
                    t4 * (t1 + (t2 * t3))
                }
            }
        })
        .collect()
}

// ------------------------------------------------------------------ buffers

/// liquid's window: the last `len` samples, oldest first.
#[derive(Clone)]
pub struct Window<T: Copy + Default> {
    buf: Vec<T>,
    len: usize,
}

impl<T: Copy + Default> Window<T> {
    pub fn new(len: usize) -> Self {
        Window {
            buf: vec![T::default(); len],
            len,
        }
    }
    #[inline]
    pub fn push(&mut self, x: T) {
        // A shift is cheapest at these lengths (9 to 80) and keeps read()
        // a plain slice.
        self.buf.copy_within(1.., 0);
        self.buf[self.len - 1] = x;
    }
    #[inline]
    pub fn read(&self) -> &[T] {
        &self.buf
    }
    pub fn reset(&mut self) {
        self.buf.iter_mut().for_each(|v| *v = T::default());
    }
}

/// liquid's wdelay: the value pushed `delay` pushes ago.
#[derive(Clone)]
struct WDelay {
    v: Vec<f32>,
    idx: usize,
}

impl WDelay {
    fn new(delay: usize) -> Self {
        WDelay {
            v: vec![0.0; delay + 1],
            idx: 0,
        }
    }
    fn push(&mut self, x: f32) {
        self.v[self.idx] = x;
        self.idx = (self.idx + 1) % self.v.len();
    }
    fn read(&self) -> f32 {
        self.v[self.idx]
    }
    fn reset(&mut self) {
        self.v.iter_mut().for_each(|v| *v = 0.0);
        self.idx = 0;
    }
}

// ------------------------------------------------------------------ NCO

/// nco_crcf: 32-bit fixed-point phase, a 1024-entry sine table, and the
/// first-order PLL liquid gives it.
#[derive(Clone)]
pub struct Nco {
    sintab: Vec<f32>,
    pub theta: u32,
    pub d_theta: u32,
    alpha: f32,
    beta: f32,
}

/// nco_constrain: radians to fixed point, through liquid's float
/// arithmetic (a negative step lands on 1 - |x| in single precision, so it
/// is ~256 times coarser than a positive one; HSmodem lives with that).
fn nco_constrain(theta: f32) -> u32 {
    let p = (theta as f64 * 0.159154943091895) as f32;
    let mut fpart = p - (p as i64) as f32;
    if fpart < 0.0 {
        fpart = (fpart as f64 + 1.0) as f32;
    }
    // (uint32_t)(fpart * 0xffffffff): the constant becomes 4294967296.0f.
    let v = fpart * 4_294_967_296.0f32;
    if v >= 4_294_967_295.0 {
        u32::MAX
    } else {
        v as u32
    }
}

impl Nco {
    pub fn new() -> Nco {
        let sintab = (0..1024).map(|i| (2.0 * PI * i as f32 / 1024.0).sin()).collect();
        let mut n = Nco {
            sintab,
            theta: 0,
            d_theta: 0,
            alpha: 0.0,
            beta: 0.0,
        };
        n.pll_set_bandwidth(0.1);
        n
    }
    pub fn reset(&mut self) {
        self.theta = 0;
        self.d_theta = 0;
    }
    pub fn set_frequency(&mut self, dtheta: f32) {
        self.d_theta = nco_constrain(dtheta);
    }
    pub fn set_phase(&mut self, phi: f32) {
        self.theta = nco_constrain(phi);
    }
    #[inline]
    pub fn adjust_frequency(&mut self, df: f32) {
        self.d_theta = self.d_theta.wrapping_add(nco_constrain(df));
    }
    #[inline]
    pub fn adjust_phase(&mut self, dphi: f32) {
        self.theta = self.theta.wrapping_add(nco_constrain(dphi));
    }
    #[inline]
    pub fn step(&mut self) {
        self.theta = self.theta.wrapping_add(self.d_theta);
    }
    pub fn get_phase(&self) -> f32 {
        2.0 * PI * self.theta as f32 / 4_294_967_296.0
    }
    pub fn get_frequency(&self) -> f32 {
        let d = 2.0 * PI * self.d_theta as f32 / 4_294_967_296.0;
        if d > PI {
            d - 2.0 * PI
        } else {
            d
        }
    }
    #[inline]
    fn index(&self) -> usize {
        ((self.theta.wrapping_add(1 << 21) >> 22) & 0x3ff) as usize
    }
    #[inline]
    pub fn sin(&self) -> f32 {
        self.sintab[self.index()]
    }
    #[inline]
    pub fn cos(&self) -> f32 {
        self.sintab[(self.index() + 256) & 0x3ff]
    }
    #[inline]
    pub fn cexp(&self) -> C32 {
        let i = self.index();
        C32::new(self.sintab[(i + 256) & 0x3ff], self.sintab[i])
    }
    #[inline]
    pub fn mix_up(&self, x: C32) -> C32 {
        x.mul(self.cexp())
    }
    #[inline]
    pub fn mix_down(&self, x: C32) -> C32 {
        x.mul(self.cexp().conj())
    }
    pub fn pll_set_bandwidth(&mut self, bw: f32) {
        self.alpha = bw;
        self.beta = bw.sqrt();
    }
    #[inline]
    pub fn pll_step(&mut self, dphi: f32) {
        self.adjust_frequency(dphi * self.alpha);
        self.adjust_phase(dphi * self.beta);
    }
}

impl Default for Nco {
    fn default() -> Self {
        Nco::new()
    }
}

// ------------------------------------------------------------------ AGC

/// agc_crcf: a single-pole energy estimate driving a log-domain gain.
#[derive(Clone)]
pub struct Agc {
    pub g: f32,
    y2_prime: f32,
    alpha: f32,
}

impl Agc {
    pub fn new() -> Agc {
        let mut a = Agc {
            g: 1.0,
            y2_prime: 1.0,
            alpha: 0.0,
        };
        a.set_bandwidth(1e-2);
        a
    }
    pub fn set_bandwidth(&mut self, bt: f32) {
        self.alpha = bt;
    }
    pub fn reset(&mut self) {
        self.g = 1.0;
        self.y2_prime = 1.0;
    }
    #[inline]
    pub fn execute(&mut self, x: C32) -> C32 {
        let y = x.scale(self.g);
        let y2 = y.norm_sqr();
        self.y2_prime = ((1.0 - self.alpha as f64) * self.y2_prime as f64 + (self.alpha * y2) as f64) as f32;
        if self.y2_prime > 1e-6 {
            self.g *= (-0.5 * self.alpha * self.y2_prime.ln()).exp();
        }
        if self.g > 1e6 {
            self.g = 1e6;
        }
        y
    }
}

impl Default for Agc {
    fn default() -> Self {
        Agc::new()
    }
}

// ------------------------------------------------------------------ filters

/// firpfb_crcf: a bank of sub-filters over one window (real taps).
#[derive(Clone)]
pub struct FirPfb {
    subs: Vec<Vec<f32>>, // each reversed, as liquid loads them
    w: Window<C32>,
}

impl FirPfb {
    pub fn new(num: usize, h: &[f32]) -> FirPfb {
        let sub_len = h.len() / num;
        let subs = (0..num)
            .map(|i| {
                let mut s = vec![0.0f32; sub_len];
                for n in 0..sub_len {
                    s[sub_len - n - 1] = h[i + n * num];
                }
                s
            })
            .collect();
        FirPfb {
            subs,
            w: Window::new(sub_len),
        }
    }
    #[inline]
    pub fn push(&mut self, x: C32) {
        self.w.push(x);
    }
    #[inline]
    pub fn execute(&self, i: usize) -> C32 {
        dot(&self.subs[i], self.w.read())
    }
    pub fn reset(&mut self) {
        self.w.reset();
    }
}

#[inline]
fn dot(h: &[f32], x: &[C32]) -> C32 {
    let (mut re, mut im) = (0.0f32, 0.0f32);
    for (a, b) in h.iter().zip(x) {
        re += a * b.re;
        im += a * b.im;
    }
    C32::new(re, im)
}

/// firinterp_crcf: one input, M outputs.
#[derive(Clone)]
pub struct FirInterp {
    m: usize,
    pfb: FirPfb,
}

impl FirInterp {
    pub fn new(m: usize, h: &[f32]) -> FirInterp {
        let mut sub = 0;
        while m * sub < h.len() {
            sub += 1;
        }
        let mut hp = vec![0.0f32; m * sub];
        hp[..h.len()].copy_from_slice(h);
        FirInterp {
            m,
            pfb: FirPfb::new(m, &hp),
        }
    }
    pub fn execute(&mut self, x: C32, y: &mut [C32]) {
        self.pfb.push(x);
        for (i, o) in y.iter_mut().enumerate().take(self.m) {
            *o = self.pfb.execute(i);
        }
    }
}

/// firdecim_crcf as HSmodem creates it: firdecim_crcf_create_kaiser(M, m,
/// As), which designs 2Mm+1 taps and hands liquid only the first 2Mm, then
/// scaled by 1/M (liquid_if.cpp).
#[derive(Clone)]
pub struct FirDecim {
    m: usize,
    h: Vec<f32>, // reversed
    w: Window<C32>,
    scale: f32,
}

impl FirDecim {
    pub fn kaiser(m: usize, delay: usize, as_db: f32) -> FirDecim {
        let full = firdes_kaiser(2 * m * delay + 1, 0.5 / m as f32, as_db, 0.0);
        let n = 2 * m * delay;
        let h: Vec<f32> = (0..n).map(|i| full[n - i - 1]).collect();
        FirDecim {
            m,
            h,
            w: Window::new(n),
            scale: 1.0,
        }
    }
    pub fn set_scale(&mut self, s: f32) {
        self.scale = s;
    }
    /// M inputs, one output (computed after the first of them, as liquid does).
    pub fn execute(&mut self, x: &[C32]) -> C32 {
        let mut y = C32::ZERO;
        for (i, &v) in x.iter().enumerate().take(self.m) {
            self.w.push(v);
            if i == 0 {
                y = dot(&self.h, self.w.read()).scale(self.scale);
            }
        }
        y
    }
}

/// iirfiltsos_rrrf, direct form II.
#[derive(Clone)]
struct IirSos {
    b: [f32; 3],
    a: [f32; 3],
    v: [f32; 3],
}

impl IirSos {
    fn new(b: [f32; 3], a: [f32; 3]) -> IirSos {
        let mut s = IirSos {
            b: [0.0; 3],
            a: [0.0; 3],
            v: [0.0; 3],
        };
        s.set(b, a);
        s
    }
    fn set(&mut self, b: [f32; 3], a: [f32; 3]) {
        let a0 = a[0];
        self.b = [b[0] / a0, b[1] / a0, b[2] / a0];
        self.a = [a[0] / a0, a[1] / a0, a[2] / a0];
    }
    fn reset(&mut self) {
        self.v = [0.0; 3];
    }
    fn execute(&mut self, x: f32) -> f32 {
        self.v[2] = self.v[1];
        self.v[1] = self.v[0];
        self.v[0] = x - self.a[1] * self.v[1] - self.a[2] * self.v[2];
        self.b[0] * self.v[0] + self.b[1] * self.v[1] + self.b[2] * self.v[2]
    }
}

// ------------------------------------------------------------------ symsync

/// symsync_crcf: polyphase matched filter and derivative filter, timing
/// error q = Re(conj(mf) dmf), a second-order loop on the filterbank index.
#[derive(Clone)]
pub struct SymSync {
    k: usize,
    k_out: usize,
    decim_counter: usize,
    rate: f32,
    del: f32,
    pub tau: f32,
    pub tau_decim: f32,
    bf: f32,
    b: i32,
    q: f32,
    pub q_hat: f32,
    rate_adjustment: f32,
    npfb: usize,
    mf: FirPfb,
    dmf: FirPfb,
    pll: IirSos,
}

impl SymSync {
    pub fn new(k: usize, npfb: usize, h: &[f32]) -> SymSync {
        let n = h.len();
        let mut dh = vec![0.0f32; n];
        let mut hdh_max = 0.0f32;
        for i in 0..n {
            dh[i] = if i == 0 {
                h[i + 1] - h[n - 1]
            } else if i == n - 1 {
                h[0] - h[i - 1]
            } else {
                h[i + 1] - h[i - 1]
            };
            if (h[i] * dh[i]).abs() > hdh_max || i == 0 {
                hdh_max = (h[i] * dh[i]).abs();
            }
        }
        for v in dh.iter_mut() {
            *v *= 0.06 / hdh_max;
        }
        let mut s = SymSync {
            k,
            k_out: 1,
            decim_counter: 0,
            rate: k as f32,
            del: k as f32,
            tau: 0.0,
            tau_decim: 0.0,
            bf: 0.0,
            b: 0,
            q: 0.0,
            q_hat: 0.0,
            rate_adjustment: 0.0,
            npfb,
            mf: FirPfb::new(npfb, h),
            dmf: FirPfb::new(npfb, &dh),
            pll: IirSos::new([0.0; 3], [1.0, 0.0, 0.0]),
        };
        s.reset();
        s.set_lf_bw(0.01);
        s
    }

    /// symsync_crcf_create_rnyquist(type RRC, k, m, beta, M).
    pub fn rrc(k: usize, m: usize, beta: f32, npfb: usize) -> SymSync {
        let h = firdes_rrcos(k * npfb, m, beta, 0.0);
        SymSync::new(k, npfb, &h)
    }

    pub fn reset(&mut self) {
        self.mf.reset();
        self.rate = self.k as f32 / self.k_out as f32;
        self.del = self.rate;
        self.b = 0;
        self.bf = 0.0;
        self.tau = 0.0;
        self.tau_decim = 0.0;
        self.q = 0.0;
        self.q_hat = 0.0;
        self.decim_counter = 0;
        self.pll.reset();
    }

    pub fn set_output_rate(&mut self, k_out: usize) {
        self.k_out = k_out;
        self.rate = self.k as f32 / k_out as f32;
        self.del = self.rate;
    }

    pub fn set_lf_bw(&mut self, bt: f32) {
        let alpha = 1.0 - bt;
        let beta = 0.22 * bt;
        let (a, b) = (0.5f32, 0.495f32);
        self.pll.set([beta, 0.0, 0.0], [1.0 - a * alpha, -b * alpha, 0.0]);
        self.rate_adjustment = (0.5 * bt as f64) as f32;
    }

    /// One input sample; outputs appended to `out` (0 to 2 at k=4, k_out=2).
    pub fn step(&mut self, x: C32, out: &mut Vec<C32>) {
        self.mf.push(x);
        self.dmf.push(x);
        while self.b < self.npfb as i32 {
            let mf = self.mf.execute(self.b as usize);
            out.push(mf.scale(1.0 / self.k as f32));
            if self.decim_counter == self.k_out {
                self.decim_counter = 0;
                let dmf = self.dmf.execute(self.b as usize);
                self.advance_internal_loop(mf, dmf);
                self.tau_decim = self.tau;
            }
            self.decim_counter += 1;
            self.tau += self.del;
            self.bf = self.tau * self.npfb as f32;
            self.b = self.bf.round() as i32;
        }
        self.tau -= 1.0;
        self.bf -= self.npfb as f32;
        self.b -= self.npfb as i32;
    }

    fn advance_internal_loop(&mut self, mf: C32, dmf: C32) {
        self.q = mf.conj().mul(dmf).re;
        self.q = self.q.clamp(-1.0, 1.0);
        self.q_hat = self.pll.execute(self.q);
        self.rate += self.rate_adjustment * self.q_hat;
        self.del = self.rate + self.q_hat;
    }
}

// ------------------------------------------------------------------ eqlms

/// eqlms_cccf, as km_symtrack uses it: decision directed, normalised LMS.
#[derive(Clone)]
pub struct EqLms {
    h0: Vec<C32>,
    w0: Vec<C32>,
    mu: f32,
    count: usize,
    buf_full: bool,
    buffer: Window<C32>,
    x2: WDelay,
    x2_sum: f32,
}

impl EqLms {
    pub fn new(h: Vec<C32>) -> EqLms {
        let n = h.len();
        let mut e = EqLms {
            w0: h.clone(),
            h0: h,
            mu: 0.5,
            count: 0,
            buf_full: false,
            buffer: Window::new(n),
            x2: WDelay::new(n),
            x2_sum: 0.0,
        };
        e.reset();
        e
    }
    /// eqlms_cccf_create_lowpass(n, fc): Kaiser, 40 dB.
    pub fn lowpass(n: usize, fc: f32) -> EqLms {
        EqLms::new(
            firdes_kaiser(n, fc, 40.0, 0.0)
                .into_iter()
                .map(|v| C32::new(v, 0.0))
                .collect(),
        )
    }
    pub fn reset(&mut self) {
        self.w0.copy_from_slice(&self.h0);
        self.buffer.reset();
        self.x2.reset();
        self.count = 0;
        self.buf_full = false;
        self.x2_sum = 0.0;
    }
    pub fn set_bw(&mut self, mu: f32) {
        self.mu = mu;
    }
    #[inline]
    pub fn push(&mut self, x: C32) {
        self.buffer.push(x);
        let x2n = x.mul(x.conj()).re;
        self.x2.push(x2n);
        let x20 = self.x2.read();
        self.x2_sum = self.x2_sum + x2n - x20;
        self.count += 1;
    }
    #[inline]
    pub fn execute(&self) -> C32 {
        let mut y = C32::ZERO;
        for (w, r) in self.w0.iter().zip(self.buffer.read()) {
            y = y.add(w.conj().mul(*r));
        }
        y
    }
    pub fn step(&mut self, d: C32, d_hat: C32) {
        if !self.buf_full {
            if self.count < self.w0.len() {
                return;
            }
            self.buf_full = true;
        }
        let alpha = d.sub(d_hat);
        let r = self.buffer.read();
        for (w, x) in self.w0.iter_mut().zip(r) {
            *w = w.add(alpha.conj().mul(*x).scale(self.mu).scale(1.0 / self.x2_sum));
        }
    }
}

// ------------------------------------------------------------------ modem

/// The constellations HSmodem uses: liquid's BPSK, QPSK and APSK8 (1+7).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Scheme {
    Bpsk,
    Qpsk,
    Apsk8,
}

impl Scheme {
    pub fn bits(self) -> usize {
        match self {
            Scheme::Bpsk => 1,
            Scheme::Qpsk => 2,
            Scheme::Apsk8 => 3,
        }
    }
}

/// APSK8(1,7): modem_apsk_const.c, its literals as liquid writes them.
#[allow(clippy::excessive_precision)]
pub const APSK8_R: [f32; 2] = [0.0, 1.069_044_95];
#[allow(clippy::excessive_precision)]
pub const APSK8_R_SLICER: f32 = 0.534_522_47;
pub const APSK8_MAP: [u8; 8] = [0, 2, 4, 3, 1, 7, 5, 6];

/// modem: modulate / demodulate with the residual liquid keeps for its
/// phase error (Im(r conj(x_hat))).
#[derive(Clone)]
pub struct Modem {
    pub scheme: Scheme,
    map: Vec<C32>,
    pub r: C32,
    pub x_hat: C32,
}

impl Modem {
    pub fn new(scheme: Scheme) -> Modem {
        let map = match scheme {
            Scheme::Apsk8 => (0..8u8)
                .map(|s| {
                    let p = APSK8_MAP[s as usize] as usize;
                    if p == 0 {
                        C32::new(APSK8_R[0], 0.0)
                    } else {
                        // liquid_cexpjf(phi) scaled by the ring's radius
                        let phi = (p - 1) as f32 * 2.0 * PI / 7.0;
                        C32::new(APSK8_R[1] * phi.cos(), APSK8_R[1] * phi.sin())
                    }
                })
                .collect(),
            // modem_psk with M=2: liquid's BPSK is {+1, -1} on the real axis.
            Scheme::Bpsk => vec![C32::new(1.0, 0.0), C32::new(-1.0, 0.0)],
            // liquid QPSK: (+-1 +- j)/sqrt(2), bit 0 makes the real part
            // negative, bit 1 the imaginary (modem_qpsk.c).
            Scheme::Qpsk => (0..4u32)
                .map(|s| {
                    let k = std::f32::consts::FRAC_1_SQRT_2;
                    C32::new(if s & 1 != 0 { -k } else { k }, if s & 2 != 0 { -k } else { k })
                })
                .collect(),
        };
        Modem {
            scheme,
            map,
            r: C32::new(1.0, 0.0),
            x_hat: C32::new(1.0, 0.0),
        }
    }

    pub fn reset(&mut self) {
        self.r = C32::new(1.0, 0.0);
        self.x_hat = self.r;
    }

    #[inline]
    pub fn modulate(&self, sym: u8) -> C32 {
        self.map[sym as usize]
    }

    /// modem_demodulate, remembering r and x_hat as liquid does.
    pub fn demodulate(&mut self, x: C32) -> u8 {
        let s = match self.scheme {
            Scheme::Apsk8 => {
                let r = x.abs();
                let (ring, p, off) = if r < APSK8_R_SLICER {
                    (0, 1u32, 0u32)
                } else {
                    (1, 7u32, 1u32)
                };
                let _ = ring;
                let mut theta = x.arg();
                if theta < 0.0 {
                    theta += 2.0 * PI;
                }
                let dphi = 2.0 * PI / p as f32;
                let i_hat = theta / dphi;
                let s_hat = ((i_hat.round() as u32) % p) + off;
                APSK8_MAP.iter().position(|&m| m as u32 == s_hat).unwrap_or(0) as u8
            }
            Scheme::Bpsk => u8::from(x.re <= 0.0),
            Scheme::Qpsk => u8::from(x.re <= 0.0) | (u8::from(x.im <= 0.0) << 1),
        };
        self.x_hat = self.modulate(s);
        self.r = x;
        s
    }

    #[inline]
    pub fn phase_error(&self) -> f32 {
        self.r.mul(self.x_hat.conj()).im
    }
}
