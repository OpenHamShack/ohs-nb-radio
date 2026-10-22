// ohsdigi - Python binding for HSmodem.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! `ohscore.ohsdigi.HsReceiver` and friends (docs/digimodes-rust.md, "HSmodem").
//!
//! Samples cross as bytes: complex64 (interleaved float32, little-endian)
//! for IQ, float32 for audio - what numpy's tobytes() gives and
//! frombuffer() reads. Frames come back as dicts with the 219-byte payload
//! as bytes; what the payload means (files, DX cluster, spectra) is read
//! in Python. A receive call runs with the GIL released: NB feeds the
//! beacon channel from a worker thread while the radio and the UI run.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

use super::frame::{self, Packer, PAYLOADLEN, UDPBLOCKLEN};
use super::liquid::{Scheme, C32};
use super::modulator::{ssb_audio, Audio, Baseband};
use super::receiver::{afc_span, Decoded, Options, Receiver};
use super::speed::{self, Speed, SPEEDS};

fn speed_of(mode: u8) -> PyResult<Speed> {
    speed::by_mode(mode).ok_or_else(|| PyValueError::new_err(format!("HSmodem has no speed mode {mode} (0-9)")))
}

fn float_bytes<'py>(py: Python<'py>, a: &[f32]) -> Bound<'py, PyBytes> {
    let mut raw = Vec::with_capacity(a.len() * 4);
    for v in a {
        raw.extend_from_slice(&v.to_le_bytes());
    }
    PyBytes::new(py, &raw)
}

fn complex_from(b: &[u8]) -> PyResult<Vec<C32>> {
    if b.len() % 8 != 0 {
        return Err(PyValueError::new_err("IQ must be complex64 bytes (8 bytes a sample)"));
    }
    Ok(b.chunks_exact(8)
        .map(|c| {
            C32::new(
                f32::from_le_bytes([c[0], c[1], c[2], c[3]]),
                f32::from_le_bytes([c[4], c[5], c[6], c[7]]),
            )
        })
        .collect())
}

fn real_from(b: &[u8]) -> PyResult<Vec<f32>> {
    if b.len() % 4 != 0 {
        return Err(PyValueError::new_err("audio must be float32 bytes"));
    }
    Ok(b.chunks_exact(4)
        .map(|c| f32::from_le_bytes([c[0], c[1], c[2], c[3]]))
        .collect())
}

fn complex_bytes<'py>(py: Python<'py>, x: &[C32]) -> Bound<'py, PyBytes> {
    let mut raw = Vec::with_capacity(x.len() * 8);
    for s in x {
        raw.extend_from_slice(&s.re.to_le_bytes());
        raw.extend_from_slice(&s.im.to_le_bytes());
    }
    PyBytes::new(py, &raw)
}

fn payload_of(b: &[u8]) -> PyResult<[u8; PAYLOADLEN]> {
    if b.len() > PAYLOADLEN {
        return Err(PyValueError::new_err(format!(
            "a payload is at most {PAYLOADLEN} bytes"
        )));
    }
    let mut p = [0u8; PAYLOADLEN];
    p[..b.len()].copy_from_slice(b);
    Ok(p)
}

fn frame_dict<'py>(py: Python<'py>, d: &Decoded) -> PyResult<Bound<'py, PyDict>> {
    let o = PyDict::new(py);
    o.set_item("type", d.frame.ftype)?;
    o.set_item("status", d.frame.status)?;
    o.set_item("counter", d.frame.counter)?;
    o.set_item("payload", PyBytes::new(py, &d.frame.payload))?;
    o.set_item("symbol", d.symbol)?;
    o.set_item("corrected", d.frame.corrected)?;
    o.set_item("rotation", d.frame.rotation)?;
    Ok(o)
}

/// HSmodem's receiver, at any of its speed modes.
#[pyclass(name = "HsReceiver", module = "ohsdigi")]
pub struct PyHsReceiver {
    inner: Receiver,
    input: Input,
}

#[derive(Clone, Copy, PartialEq)]
enum Input {
    Iq,
    Audio,
    Ssb,
}

#[pymethods]
impl PyHsReceiver {
    /// HsReceiver(rate, audio=False, centre=1500.0, afc=True, watchdog=True,
    ///            max_header_errors=2, speed=9, ssb=False)
    ///
    /// IQ (the default): complex baseband at `rate`, the signal at 0 Hz.
    /// audio=True: HSmodem's sound-card path, real samples at `rate` (a
    /// whole multiple of the speed's tracker rate: its own 48000 or 44100),
    /// the signal at `centre` Hz; no AFC.
    /// ssb=True: an SSB receiver's audio (NB's decoder feed), real samples
    /// at any `rate`, the signal at `centre` Hz, with the AFC.
    /// `speed`: HSmodem's speed mode, 0-9 (9 is the beacon's).
    #[new]
    #[pyo3(signature = (rate, audio = false, centre = 1500.0, afc = true, watchdog = true, max_header_errors = 2,
                        speed = 9, ssb = false))]
    #[allow(clippy::too_many_arguments)]
    fn new(
        rate: f32,
        audio: bool,
        centre: f32,
        afc: bool,
        watchdog: bool,
        max_header_errors: usize,
        speed: u8,
        ssb: bool,
    ) -> PyResult<Self> {
        if rate.is_nan() || rate <= 0.0 {
            return Err(PyValueError::new_err("rate must be positive"));
        }
        if audio && ssb {
            return Err(PyValueError::new_err(
                "audio and ssb are two different inputs: choose one",
            ));
        }
        let sp = speed_of(speed)?;
        let opts = Options {
            afc,
            watchdog,
            max_header_errors,
        };
        let (inner, input) = if audio {
            if (rate / sp.track_rate()).fract().abs() > 1e-6 {
                return Err(PyValueError::new_err(format!(
                    "an audio receiver at speed {speed} needs a rate that is a multiple of {} ({})",
                    sp.track_rate(),
                    sp.audio_rate
                )));
            }
            (Receiver::audio_at(rate, centre, sp, opts), Input::Audio)
        } else if ssb {
            (Receiver::ssb(rate, centre, sp, opts), Input::Ssb)
        } else {
            (Receiver::iq_at(rate, sp, opts), Input::Iq)
        };
        Ok(PyHsReceiver { inner, input })
    }

    /// Feed samples (bytes: complex64 for IQ, float32 for audio and SSB);
    /// returns the frames that decoded, oldest first.
    fn feed<'py>(&mut self, py: Python<'py>, data: &[u8]) -> PyResult<Vec<Bound<'py, PyDict>>> {
        let mut out = Vec::new();
        let rx = &mut self.inner;
        match self.input {
            Input::Audio => {
                let a = real_from(data)?;
                py.detach(|| rx.feed_audio(&a, &mut out));
            }
            Input::Ssb => {
                let a = real_from(data)?;
                py.detach(|| rx.feed_ssb(&a, &mut out));
            }
            Input::Iq => {
                let x = complex_from(data)?;
                py.detach(|| rx.feed_iq(&x, &mut out));
            }
        }
        out.iter().map(|d| frame_dict(py, d)).collect()
    }

    /// The speed mode this receiver is at.
    #[getter]
    fn speed(&self) -> u8 {
        self.inner.speed().mode
    }

    /// Counters and decode quality.
    fn stats<'py>(&self, py: Python<'py>) -> PyResult<Bound<'py, PyDict>> {
        let s = self.inner.stats();
        let o = PyDict::new(py);
        o.set_item("symbols", s.symbols)?;
        o.set_item("frames_ok", s.frames_ok)?;
        o.set_item("frames_lost", s.frames_lost)?;
        o.set_item("fec_failed", s.fec_failed)?;
        o.set_item("crc_failed", s.crc_failed)?;
        o.set_item("resets", s.resets)?;
        o.set_item("corrected", s.corrected)?;
        o.set_item("last_frame_symbol", s.last_frame_symbol)?;
        o.set_item("in_sync", s.in_sync)?;
        o.set_item("mer_db", s.mer_db)?;
        o.set_item("freq_hz", s.freq_hz)?;
        o.set_item("agc_gain", s.agc_gain)?;
        o.set_item("tau", s.tau)?;
        Ok(o)
    }

    /// Start acquiring again from the tuned frequency (counters kept): call
    /// after moving the signal in the channel by more than the loops follow.
    fn reset(&mut self) {
        self.inner.reset();
    }

    /// Start (True) or stop keeping every symbol's stage values.
    fn record(&mut self, on: bool) {
        self.inner.record = if on { Some(Vec::new()) } else { None };
    }

    /// The stage values kept since record(True), and clear them: per
    /// symbol 8 float32 - soft symbol re, im, hard symbol, tau, carrier NCO
    /// frequency and phase, AGC gain, header outcome (1 frame, 0 nothing,
    /// -1 FEC failed, -2 CRC failed) - the layout harness/hsmodem's hsh writes.
    fn take_record<'py>(&mut self, py: Python<'py>) -> Bound<'py, PyBytes> {
        let mut raw = Vec::new();
        if let Some(r) = &mut self.inner.record {
            for (s, flag) in r.drain(..) {
                for v in [
                    s.d_hat.re,
                    s.d_hat.im,
                    s.sym as f32,
                    s.tau,
                    s.nco_freq,
                    s.nco_phase,
                    s.agc_gain,
                    flag as f32,
                ] {
                    raw.extend_from_slice(&v.to_le_bytes());
                }
            }
        }
        PyBytes::new(py, &raw)
    }
}

/// HSmodem's Pack() with its frame-counter rules.
#[pyclass(name = "HsPacker", module = "ohsdigi")]
pub struct PyHsPacker {
    inner: Packer,
}

#[pymethods]
impl PyHsPacker {
    #[new]
    fn new() -> Self {
        PyHsPacker {
            inner: Packer::default(),
        }
    }

    /// pack(payload, ftype, status, repeat=False) -> 258 bytes
    #[pyo3(signature = (payload, ftype, status, repeat = false))]
    fn pack<'py>(
        &mut self,
        py: Python<'py>,
        payload: &[u8],
        ftype: u8,
        status: u8,
        repeat: bool,
    ) -> PyResult<Bound<'py, PyBytes>> {
        let p = payload_of(payload)?;
        Ok(PyBytes::new(py, &self.inner.pack(&p, ftype, status, repeat)))
    }

    #[getter]
    fn counter(&self) -> u16 {
        self.inner.counter
    }
}

/// hs_pack(payload, ftype, status, counter) -> 258 bytes: one frame with
/// the counter given.
#[pyfunction]
fn hs_pack<'py>(py: Python<'py>, payload: &[u8], ftype: u8, status: u8, counter: u16) -> PyResult<Bound<'py, PyBytes>> {
    let p = payload_of(payload)?;
    Ok(PyBytes::new(
        py,
        &frame::pack(&p, ftype & 0x0f, status & 3, counter & 0x3ff),
    ))
}

fn check_frames(frames: &[u8]) -> PyResult<()> {
    if frames.len() % UDPBLOCKLEN != 0 {
        return Err(PyValueError::new_err(format!(
            "frames must be a multiple of {UDPBLOCKLEN} bytes"
        )));
    }
    Ok(())
}

/// hs_baseband(frames, k=5, flush=0, speed=9) -> complex64 bytes: the
/// speed's constellation (8APSK for 9), RRC 0.2, k samples a symbol (5 is
/// 12 kHz at 2400 Bd), then `flush` symbols of filter tail.
#[pyfunction]
#[pyo3(signature = (frames, k = 5, flush = 0, speed = 9))]
fn hs_baseband<'py>(
    py: Python<'py>,
    frames: &[u8],
    k: usize,
    flush: usize,
    speed: u8,
) -> PyResult<Bound<'py, PyBytes>> {
    check_frames(frames)?;
    if !(2..=64).contains(&k) {
        return Err(PyValueError::new_err("k must be 2..64"));
    }
    let scheme: Scheme = speed_of(speed)?.scheme();
    let f = frames.to_vec();
    let x = py.detach(move || {
        let mut b = Baseband::new(scheme, k);
        let mut out = Vec::new();
        b.frames(&f, &mut out);
        b.flush(flush, &mut out);
        out
    });
    Ok(complex_bytes(py, &x))
}

/// hs_audio(frames, speed=9, marker=False) -> float32 bytes: HSmodem's
/// sound-card signal for the frames, at the speed's own sound-card rate
/// and interpolation (48000 Hz and 20 for 9).
#[pyfunction]
#[pyo3(signature = (frames, speed = 9, marker = false))]
fn hs_audio<'py>(py: Python<'py>, frames: &[u8], speed: u8, marker: bool) -> PyResult<Bound<'py, PyBytes>> {
    check_frames(frames)?;
    let sp = speed_of(speed)?;
    let f = frames.to_vec();
    let a = py.detach(move || {
        let mut m = Audio::new(sp.scheme(), sp.audio_rate, sp.tx_k, marker);
        let mut out = Vec::new();
        m.frames(&f, &mut out);
        out
    });
    Ok(float_bytes(py, &a))
}

/// hs_ssb_audio(frames, speed, rate=12000, centre=1500, peak=0.85, lead=0,
/// tail=0) -> float32 bytes: what OpenHamShack NB transmits - the frames as SSB
/// audio at `rate`, centred at `centre`, its envelope peaking at `peak`,
/// with `lead` and `tail` symbols of silence (modulator.rs ssb_audio).
#[pyfunction]
#[pyo3(signature = (frames, speed, rate = 12000.0, centre = 1500.0, peak = 0.85, lead = 0, tail = 0))]
#[allow(clippy::too_many_arguments)]
fn hs_ssb_audio<'py>(
    py: Python<'py>,
    frames: &[u8],
    speed: u8,
    rate: f32,
    centre: f32,
    peak: f32,
    lead: usize,
    tail: usize,
) -> PyResult<Bound<'py, PyBytes>> {
    check_frames(frames)?;
    let sp = speed_of(speed)?;
    if rate.is_nan() || rate <= 2.0 * (centre + sp.symbol_rate()) {
        return Err(PyValueError::new_err(
            "the rate is too low for the signal at that centre",
        ));
    }
    let f = frames.to_vec();
    let a = py.detach(move || ssb_audio(&sp, &f, rate, centre, peak, lead, tail));
    Ok(float_bytes(py, &a))
}

/// hs_speeds() -> [dict]: HSmodem's speed modes (hsmodem.cpp sr[]): mode,
/// bitrate, bits, baud, audio_rate, tx_k, rx_k, scheme, afc_span (Hz,
/// the coarse frequency search's unambiguous span), idle_repetitions (the
/// first frame's repeats when the transmitter starts).
#[pyfunction]
fn hs_speeds<'py>(py: Python<'py>) -> PyResult<Vec<Bound<'py, PyDict>>> {
    SPEEDS
        .iter()
        .map(|s| {
            let o = PyDict::new(py);
            o.set_item("mode", s.mode)?;
            o.set_item("bitrate", s.bitrate)?;
            o.set_item("bits", s.bits)?;
            o.set_item("baud", s.symbol_rate())?;
            o.set_item("audio_rate", s.audio_rate)?;
            o.set_item("tx_k", s.tx_k)?;
            o.set_item("rx_k", s.rx_k)?;
            o.set_item(
                "scheme",
                match s.scheme() {
                    Scheme::Bpsk => "BPSK",
                    Scheme::Qpsk => "QPSK",
                    Scheme::Apsk8 => "8APSK",
                },
            )?;
            o.set_item("afc_span", afc_span(s))?;
            o.set_item("idle_repetitions", s.idle_repetitions())?;
            Ok(o)
        })
        .collect()
}

/// hs_crc16(data) -> int: HSmodem's CRC (frames, and a file's ID).
#[pyfunction]
fn hs_crc16(data: &[u8]) -> u16 {
    frame::crc16(data)
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_class::<PyHsReceiver>()?;
    m.add_class::<PyHsPacker>()?;
    m.add_function(wrap_pyfunction!(hs_pack, m)?)?;
    m.add_function(wrap_pyfunction!(hs_baseband, m)?)?;
    m.add_function(wrap_pyfunction!(hs_audio, m)?)?;
    m.add_function(wrap_pyfunction!(hs_ssb_audio, m)?)?;
    m.add_function(wrap_pyfunction!(hs_speeds, m)?)?;
    m.add_function(wrap_pyfunction!(hs_crc16, m)?)?;
    m.add("HS_PAYLOAD", PAYLOADLEN)?;
    m.add("HS_FRAME", UDPBLOCKLEN)?;
    m.add("HS_SOURCE", super::HSMODEM_SOURCE)?;
    Ok(())
}
