// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! The app-facing API: `decode`, `encode_audio` and `version`, the three
//! calls every OpenHamShack app (Icom, Digital Modes, NB/Radio) is meant to
//! use, documented in docs/OHSDIGI-PYTHON.md.
//!
//! The rest of the module mirrors WSJT-X's tools and internals (ft8code's
//! encode, jt9's ft8_decode/ft4_decode with every knob, pack77) and is
//! shaped by being held bit-exact against them, so its names and arguments
//! follow WSJT-X rather than what an app wants to say. These three are
//! the opposite: a small surface in the apps' own terms (a mode name, a
//! buffer of audio, a frequency in Hz), promised not to change shape
//! within a major version, and built only out of the parts below, so
//! there is still one decoder.
//!
//! They live here rather than in a Python wrapper package so that the
//! wheel (tools/build-wheels.sh) and the bare module the NB/HAM bundles
//! copy in (tools/build-ohsdigi.sh) are the same file with the same API.

use pyo3::buffer::PyBuffer;
use pyo3::exceptions::{PyTypeError, PyValueError};
use pyo3::prelude::*;
use pyo3::types::{PyByteArray, PyBytes, PyDict};

use crate::decode::ap::{ft4_ap, ft8_ap};
use crate::decode::{ft4, ft8};
use crate::msg77::CallHashes;
use crate::python::{f32_bytes, BadMessage, PyCallHashes};
use crate::{EncodeError, Mode};

/// int16 full scale: a float sample of 1.0 becomes what an int16 sample of
/// 32767 is, so the decoder sees the same numbers whichever the caller has.
/// (Its thresholds are relative - SNR is measured against the slot's own
/// noise - so the scale matters only for being the same, not for working.)
const FULL_SCALE: f32 = 32767.0;

/// The caller's audio as the decoder takes it: f32 at int16 scale.
///
/// Anything with the buffer protocol: numpy arrays, array.array, memoryview
/// - int16 ('h') as it is, float32 ('f') and float64 ('d') as full scale
/// ±1.0. bytes and bytearray (and a byte-format buffer) are int16
/// little-endian, which is what the WAV NB hands jt9 contains and what
/// ft8_decode/ft4_decode have always taken. A list is refused rather than
/// guessed at: whether [0.5, ...] means half scale or half an LSB is
/// exactly the mistake that decodes nothing and says nothing.
pub(crate) fn audio_from(obj: &Bound<'_, PyAny>) -> PyResult<Vec<f32>> {
    let py = obj.py();
    let le16 = |raw: &[u8]| -> PyResult<Vec<f32>> {
        if raw.len() % 2 != 0 {
            return Err(PyValueError::new_err("byte audio must be int16 little-endian (an even length)"));
        }
        Ok(raw.chunks_exact(2).map(|b| i16::from_le_bytes([b[0], b[1]]) as f32).collect())
    };
    if let Ok(b) = obj.cast::<PyBytes>() {
        return le16(b.as_bytes());
    }
    if let Ok(b) = obj.cast::<PyByteArray>() {
        return le16(&b.to_vec());
    }
    let one_d = |ndim: usize| -> PyResult<()> {
        if ndim == 1 {
            Ok(())
        } else {
            Err(PyValueError::new_err(format!("audio must be one-dimensional (mono), not {ndim}-D")))
        }
    };
    if let Ok(b) = PyBuffer::<i16>::get(obj) {
        one_d(b.dimensions())?;
        return Ok(b.to_vec(py)?.into_iter().map(|s| s as f32).collect());
    }
    if let Ok(b) = PyBuffer::<f32>::get(obj) {
        one_d(b.dimensions())?;
        return Ok(b.to_vec(py)?.into_iter().map(|s| s * FULL_SCALE).collect());
    }
    if let Ok(b) = PyBuffer::<f64>::get(obj) {
        one_d(b.dimensions())?;
        return Ok(b.to_vec(py)?.into_iter().map(|s| (s as f32) * FULL_SCALE).collect());
    }
    if let Ok(b) = PyBuffer::<u8>::get(obj) {
        one_d(b.dimensions())?;
        return le16(&b.to_vec(py)?);
    }
    Err(PyTypeError::new_err(
        "audio must be int16, float32 or float64 samples (numpy array, array.array, memoryview) \
         or int16 little-endian bytes",
    ))
}

fn mode_of(name: &str) -> PyResult<Mode> {
    Mode::from_name(name).ok_or_else(|| PyValueError::new_err(format!("unknown mode {name:?} (ft8 or ft4)")))
}

/// decode(mode, audio, *, time=None, depth=1, freq_min=200.0,
///        freq_max=4000.0, freq_qso=1500.0, mycall="", dxcall="",
///        hashes=None, threads=0) -> list[dict]
///
/// Decode one slot of 12 kHz mono audio: FT8's 15 s or FT4's 7.5 s,
/// starting at the slot boundary (a signal sent on time starts 0.5 s in
/// and decodes with dt near 0). Shorter audio is padded with silence,
/// longer is cut. Each decode is a dict with time (`time` as given, for
/// the caller to stamp the slot with), snr (dB in 2500 Hz, int), dt (s),
/// freq (Hz of tone 0), message, mode, and bits, ap, hard_errors, qual as
/// ft8_decode gives them. `hashes` (a CallHashes kept across slots) shows
/// hashed calls heard in full earlier by name.
///
/// depth is WSJT-X's 1-3 (fast, normal, deep). 1 by default: it is what
/// NB runs, and the only one a Pi 400 decodes inside the ~2 s after a slot
/// ends (docs/digimodes-rust.md, "Speed"); a desktop app can afford 3.
#[pyfunction]
#[pyo3(signature = (mode, audio, *, time=None, depth=1, freq_min=200.0, freq_max=4000.0, freq_qso=1500.0,
                    mycall="", dxcall="", hashes=None, threads=0))]
#[allow(clippy::too_many_arguments)]
fn decode<'py>(
    py: Python<'py>,
    mode: &str,
    audio: &Bound<'py, PyAny>,
    time: Option<Bound<'py, PyAny>>,
    depth: i32,
    freq_min: f64,
    freq_max: f64,
    freq_qso: f64,
    mycall: &str,
    dxcall: &str,
    hashes: Option<PyRefMut<'_, PyCallHashes>>,
    threads: usize,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let m = mode_of(mode)?;
    if !(freq_min < freq_max) {
        return Err(PyValueError::new_err("freq_min must be below freq_max"));
    }
    let x = audio_from(audio)?;
    let mut local = CallHashes::new();
    let mut guard = hashes;
    let h: &mut CallHashes = match guard.as_mut() {
        Some(g) => &mut g.inner,
        None => &mut local,
    };
    // (text, bits, snr, dt, freq, ap, hard errors, qual), whichever mode.
    type Row = (String, [u8; 77], i32, f32, f32, i32, i32, f32);
    let depth = depth.clamp(1, 3);
    let rows: Vec<Row> = match m {
        Mode::Ft8 => {
            let p = ft8::Ft8Params {
                nfa: freq_min.round() as i32,
                nfb: freq_max.round() as i32,
                nfqso: freq_qso.round() as i32,
                ndepth: depth,
                lapon: true,
                ap: ft8_ap(mycall, dxcall),
                threads,
                ..Default::default()
            };
            let r = py.detach(|| ft8::decode_slot(&x, &p, h));
            r.decodes
                .into_iter()
                .map(|d| (d.text, d.payload, d.snr, d.dt, d.freq, d.iaptype, d.nharderrors, d.qual))
                .collect()
        }
        Mode::Ft4 => {
            let p = ft4::Ft4Params {
                nfa: freq_min as f32,
                nfb: freq_max as f32,
                nfqso: freq_qso.round() as i32,
                ndepth: depth,
                ap: ft4_ap(mycall, dxcall),
                threads,
                ..Default::default()
            };
            let (d, _) = py.detach(|| ft4::decode_slot(&x, &p, h));
            d.into_iter()
                .map(|d| (d.text, d.payload, d.snr, d.dt, d.freq, d.iaptype, d.nharderrors, d.qual))
                .collect()
        }
    };
    let time = time.unwrap_or_else(|| py.None().into_bound(py));
    rows.into_iter()
        .map(|(text, bits, snr, dt, freq, ap, hard, qual)| {
            let o = PyDict::new(py);
            o.set_item("time", &time)?;
            o.set_item("snr", snr)?;
            o.set_item("dt", dt)?;
            o.set_item("freq", freq)?;
            o.set_item("message", text)?;
            o.set_item("mode", m.name())?;
            o.set_item("bits", bits.iter().map(|&b| (b'0' + b) as char).collect::<String>())?;
            o.set_item("ap", ap)?;
            o.set_item("hard_errors", hard)?;
            o.set_item("qual", qual)?;
            Ok(o)
        })
        .collect()
}

/// encode_audio(mode, message, freq=1500.0, sample_rate=12000.0) -> bytes
///
/// The transmission for `message` as float32 little-endian samples, full
/// scale ±1.0, tone 0 at `freq` Hz - encode(mode, message).waveform() in
/// one call. Raises BadMessage for a message WSJT-X would not send.
#[pyfunction]
#[pyo3(signature = (mode, message, freq=1500.0, sample_rate=12_000.0))]
fn encode_audio<'py>(
    py: Python<'py>,
    mode: &str,
    message: &str,
    freq: f64,
    sample_rate: f64,
) -> PyResult<Bound<'py, PyBytes>> {
    let m = mode_of(mode)?;
    if !(sample_rate > 0.0 && freq > 0.0 && freq < sample_rate / 2.0) {
        return Err(PyValueError::new_err("freq must lie between 0 and half the sample rate"));
    }
    let e = match crate::encode(m, message) {
        Ok(e) => e,
        Err(e @ (EncodeError::BadMessage { .. } | EncodeError::Unencodable { .. } | EncodeError::Undefined { .. })) => {
            return Err(BadMessage::new_err(e.to_string()))
        }
    };
    let w = py.detach(move || m.waveform(&e.tones, freq, sample_rate));
    Ok(f32_bytes(py, &w))
}

/// version() -> str: ohsdigi's version, the same as the ohs-ohsdigi wheel's.
#[pyfunction]
fn version() -> &'static str {
    env!("CARGO_PKG_VERSION")
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(decode, m)?)?;
    m.add_function(wrap_pyfunction!(encode_audio, m)?)?;
    m.add_function(wrap_pyfunction!(version, m)?)?;
    m.add("MODES", ("ft8", "ft4"))?;
    Ok(())
}
