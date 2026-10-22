// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! The Python module, imported as ohscore.ohsdigi (docs/digimodes-rust.md,
//! "Python API").
//!
//! Plain values cross the boundary: strings, ints, and bytes for symbol
//! and sample arrays (one byte per tone; little-endian float32 for audio,
//! which numpy.frombuffer reads without a copy). No numpy at the Rust end:
//! the numpy crate would tie each build to a numpy ABI, and the arrays here
//! are small enough that one copy costs nothing.
//!
//! Anything that takes real time runs with the GIL released (Python::detach),
//! so the radio's other threads keep running while it works; phase 2's
//! decoder, which takes tens of milliseconds a slot, depends on that.

use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyBytes;

use crate::msg77::{self, CallHashes};
use crate::{EncodeError, Mode};

pyo3::create_exception!(
    ohsdigi,
    BadMessage,
    PyValueError,
    "A message WSJT-X 2.7.0 would not send: it reports \"*** bad message ***\", stops with an error, \
     or would send whatever was in memory. str() says which."
);

fn mode_of(name: &str) -> PyResult<Mode> {
    Mode::from_name(name).ok_or_else(|| PyValueError::new_err(format!("unknown mode {name:?} (ft8 or ft4)")))
}

fn bits_from_str(bits: &str) -> PyResult<msg77::Bits77> {
    let b = bits.as_bytes();
    if b.len() != 77 || !b.iter().all(|&c| c == b'0' || c == b'1') {
        return Err(PyValueError::new_err("bits must be 77 characters of '0' and '1'"));
    }
    let mut out = [0u8; 77];
    for (o, &c) in out.iter_mut().zip(b) {
        *o = c - b'0';
    }
    Ok(out)
}

fn bits_to_str(bits: &msg77::Bits77) -> String {
    bits.iter().map(|&b| if b == 1 { '1' } else { '0' }).collect()
}

pub(crate) fn f32_bytes<'py>(py: Python<'py>, samples: &[f32]) -> Bound<'py, PyBytes> {
    let mut raw = Vec::with_capacity(samples.len() * 4);
    for s in samples {
        raw.extend_from_slice(&s.to_le_bytes());
    }
    PyBytes::new(py, &raw)
}

/// A message encoded for sending.
#[pyclass(name = "Encoded", module = "ohsdigi", frozen)]
struct PyEncoded {
    inner: crate::Encoded,
}

#[pymethods]
impl PyEncoded {
    /// "ft8" or "ft4".
    #[getter]
    fn mode(&self) -> &'static str {
        self.inner.mode.name()
    }

    /// The message as read: first 37 characters, upper case, single blanks.
    #[getter]
    fn message(&self) -> &str {
        &self.inner.message
    }

    /// The message as it will be received ("<...>" for a hashed call the
    /// message does not spell out).
    #[getter]
    fn sent(&self) -> &str {
        &self.inner.sent
    }

    #[getter]
    fn i3(&self) -> i32 {
        self.inner.i3
    }

    #[getter]
    fn n3(&self) -> i32 {
        self.inner.n3
    }

    /// WSJT-X's name for the message type ("Standard msg", "Free text"...).
    #[getter]
    fn type_name(&self) -> &'static str {
        msg77::type_name(self.inner.i3, self.inner.n3)
    }

    /// The 77 payload bits as a string of '0' and '1'.
    #[getter]
    fn bits(&self) -> String {
        bits_to_str(&self.inner.bits)
    }

    /// Channel symbols, one byte each: 79 tones 0..7 (FT8), 103 tones 0..3 (FT4).
    #[getter]
    fn tones<'py>(&self, py: Python<'py>) -> Bound<'py, PyBytes> {
        PyBytes::new(py, &self.inner.tones)
    }

    /// Why WSJT-X's own result is not defined for this message, if it is
    /// not (this is then what its FT8 encoder gives in practice); else None.
    #[getter]
    fn undefined_in_wsjtx(&self) -> Option<&'static str> {
        self.inner.undefined_in_wsjtx
    }

    /// The transmission's audio, float32 little-endian, tone 0 at `f0` Hz,
    /// as WSJT-X generates it (Gaussian-smoothed, ramped): 151 680 samples
    /// for FT8, 60 480 for FT4 (the 103 symbols and the two ramp symbols)
    /// at 12 kHz.
    #[pyo3(signature = (f0 = 1500.0, fs = 12_000.0))]
    fn waveform<'py>(&self, py: Python<'py>, f0: f64, fs: f64) -> Bound<'py, PyBytes> {
        let (mode, tones) = (self.inner.mode, self.inner.tones.clone());
        let w = py.detach(move || mode.waveform(&tones, f0, fs));
        f32_bytes(py, &w)
    }

    fn __repr__(&self) -> String {
        format!(
            "<ohsdigi.Encoded {} {:?} i3.n3={}.{}>",
            self.inner.mode.name(),
            self.inner.sent,
            self.inner.i3,
            self.inner.n3
        )
    }
}

/// encode(mode, message) -> Encoded
///
/// Encode as WSJT-X 2.7.0's ft8code / ft4code do given `message` as their
/// argument. Raises BadMessage for a message WSJT-X would not send.
#[pyfunction]
fn encode(mode: &str, message: &str) -> PyResult<PyEncoded> {
    let m = mode_of(mode)?;
    match crate::encode(m, message) {
        Ok(e) => Ok(PyEncoded { inner: e }),
        Err(e @ (EncodeError::BadMessage { .. } | EncodeError::Unencodable { .. } | EncodeError::Undefined { .. })) => {
            Err(BadMessage::new_err(e.to_string()))
        }
    }
}

/// tones(mode, bits) -> bytes: channel symbols for a 77-bit payload
/// ('0'/'1' string), as get_ft8_tones_from_77bits / get_ft4_tones_from_77bits.
#[pyfunction]
fn tones<'py>(py: Python<'py>, mode: &str, bits: &str) -> PyResult<Bound<'py, PyBytes>> {
    let m = mode_of(mode)?;
    let b = bits_from_str(bits)?;
    Ok(PyBytes::new(py, &m.tones(&b)))
}

/// waveform(mode, tones, f0=1500.0, fs=12000.0) -> bytes (float32 LE).
#[pyfunction]
#[pyo3(signature = (mode, tones, f0 = 1500.0, fs = 12_000.0))]
fn waveform<'py>(py: Python<'py>, mode: &str, tones: &[u8], f0: f64, fs: f64) -> PyResult<Bound<'py, PyBytes>> {
    let m = mode_of(mode)?;
    let limit = match m {
        Mode::Ft8 => 7,
        Mode::Ft4 => 3,
    };
    if let Some(&t) = tones.iter().find(|&&t| t > limit) {
        return Err(PyValueError::new_err(format!("tone {t} out of range for {}", m.name())));
    }
    let tones = tones.to_vec();
    let w = py.detach(move || m.waveform(&tones, f0, fs));
    Ok(f32_bytes(py, &w))
}

/// Callsign hash tables, kept across messages: a decoder holds one for a
/// session so a hashed call heard in full earlier is shown by name.
#[pyclass(name = "CallHashes", module = "ohsdigi")]
pub(crate) struct PyCallHashes {
    // The decoder's binding (decode/py.rs) unpacks into the same tables.
    pub(crate) inner: CallHashes,
}

#[pymethods]
impl PyCallHashes {
    #[new]
    fn new() -> Self {
        PyCallHashes {
            inner: CallHashes::new(),
        }
    }

    /// The operator's own call (shown for a received hash that matches it).
    fn set_mycall(&mut self, call: &str) {
        self.inner.set_mycall(call);
    }

    /// The call of the station being worked.
    fn set_dxcall(&mut self, call: &str) {
        self.inner.set_dxcall(call);
    }

    /// Remember a callsign under its 10-, 12- and 22-bit hashes.
    fn save(&mut self, call: &str) -> Option<(i64, i64, i64)> {
        self.inner.save(call.as_bytes())
    }

    /// Calls heard most recently, newest first.
    fn recent(&self) -> Vec<String> {
        self.inner.recent()
    }
}

/// pack77(message, hashes=None) -> (bits, i3, n3)
///
/// The 77-bit payload of an already-normalised message (no fmtmsg),
/// remembering its calls in `hashes` if given. Raises BadMessage where a
/// field overflows or WSJT-X has no defined answer.
#[pyfunction]
#[pyo3(signature = (message, hashes = None))]
fn pack77(message: &str, hashes: Option<PyRefMut<'_, PyCallHashes>>) -> PyResult<(String, i32, i32)> {
    let mut local = CallHashes::new();
    let mut guard = hashes;
    let h = match guard.as_mut() {
        Some(g) => &mut g.inner,
        None => &mut local,
    };
    let p = msg77::pack77(message.as_bytes(), h).map_err(|e| BadMessage::new_err(format!("{message:?}: {e:?}")))?;
    let bits = p
        .bits()
        .ok_or_else(|| BadMessage::new_err(format!("{message:?}: a field does not fit")))?;
    Ok((bits_to_str(&bits), p.i3, p.n3))
}

/// unpack77(bits, received=True, hashes=None) -> (text, ok)
///
/// The message 77 bits carry, as WSJT-X shows it; ok is False for bits
/// WSJT-X would not display. `received` is True for a decoded message.
#[pyfunction]
#[pyo3(signature = (bits, received = true, hashes = None))]
fn unpack77(bits: &str, received: bool, hashes: Option<PyRefMut<'_, PyCallHashes>>) -> PyResult<(String, bool)> {
    let b = bits_from_str(bits)?;
    let mut local = CallHashes::new();
    let mut guard = hashes;
    let h = match guard.as_mut() {
        Some(g) => &mut g.inner,
        None => &mut local,
    };
    let u = msg77::unpack77(&b, received, h);
    Ok((u.text_lossy(), u.ok))
}

/// FT8/FT4 and Q65 (from WSJT-X 2.7.0), JS8 (from JS8Call 2.2.0) and HSmodem
/// encode and decode for OpenHamShack.
/// Apps use decode(), encode_audio() and version() (docs/OHSDIGI-PYTHON.md).
#[pymodule]
fn ohsdigi(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("WSJTX_VERSION", crate::WSJTX_VERSION)?;
    m.add("BadMessage", m.py().get_type::<BadMessage>())?;
    m.add_class::<PyEncoded>()?;
    m.add_class::<PyCallHashes>()?;
    m.add_function(wrap_pyfunction!(encode, m)?)?;
    m.add_function(wrap_pyfunction!(tones, m)?)?;
    m.add_function(wrap_pyfunction!(waveform, m)?)?;
    m.add_function(wrap_pyfunction!(pack77, m)?)?;
    m.add_function(wrap_pyfunction!(unpack77, m)?)?;
    crate::decode::py::register(m)?;
    crate::hsmodem::py::register(m)?;
    crate::js8::py::register(m)?;
    crate::q65::py::register(m)?;
    crate::pyapi::register(m)?;
    // In the wheel this module is ohsdigi/ohsdigi.abi3.so under a package
    // whose __init__ (maturin's) does `from .ohsdigi import *`; without
    // __all__ that skips __version__, and `ohsdigi.__version__` - which
    // ohscore checks - would exist in the bare module and not in the wheel.
    let mut names: Vec<String> = vec!["__version__".into()];
    for k in m.dict().keys() {
        let k: String = k.extract()?;
        if !k.starts_with('_') {
            names.push(k);
        }
    }
    m.add("__all__", names)?;
    Ok(())
}
