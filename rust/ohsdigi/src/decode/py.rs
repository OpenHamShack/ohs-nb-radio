//! Python binding for the decoders (registered by python.rs on the same
//! `ohscore.ohsdigi` module as the encoder).
//!
//! Audio goes in as `bytes` of little-endian int16 - exactly the samples NB
//! writes into the WAV it hands jt9, so both decoders see the same numbers.
//! Decodes come back as dicts: the message text (unpack77, as received),
//! the 77 bits as a '0'/'1' string (the encoder's convention), and jt9's
//! numbers (SNR, DT, frequency) plus the AP type and quality.
//!
//! A receiver passes its own `CallHashes` (the encoder's class) so hashed
//! calls heard in full in earlier slots are shown by name; without one,
//! each call starts from empty tables, as jt9 run once per WAV does.
//!
//! The GIL is released for the whole decode: NB calls this from its decode
//! worker thread and the UI must keep running meanwhile.

use super::ap::{ft4_ap, ft8_ap};
use super::{ft4, ft8};
use crate::msg77::CallHashes;
use crate::python::PyCallHashes;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::PyDict;

fn samples(audio: &[u8]) -> PyResult<Vec<f32>> {
    if audio.len() % 2 != 0 {
        return Err(PyValueError::new_err("audio must be int16 little-endian bytes"));
    }
    Ok(audio
        .chunks_exact(2)
        .map(|b| i16::from_le_bytes([b[0], b[1]]) as f32)
        .collect())
}

fn bits_str(b: &[u8; 77]) -> String {
    b.iter().map(|&x| (b'0' + x) as char).collect()
}

#[allow(clippy::too_many_arguments)]
fn decode_dict<'py>(
    py: Python<'py>,
    text: &str,
    payload: &[u8; 77],
    snr: i32,
    dt: f32,
    freq: f32,
    ap: i32,
    hard: i32,
    qual: f32,
) -> PyResult<Bound<'py, PyDict>> {
    let o = PyDict::new(py);
    o.set_item("text", text)?;
    o.set_item("bits", bits_str(payload))?;
    o.set_item("snr", snr)?;
    o.set_item("dt", dt)?;
    o.set_item("freq", freq)?;
    o.set_item("ap", ap)?;
    o.set_item("hard_errors", hard)?;
    o.set_item("qual", qual)?;
    Ok(o)
}

/// ft8_decode(audio, depth=1, nfa=200, nfb=4000, nfqso=1500, ap=True,
///            mycall="", dxcall="", qso_progress=0, hashes=None,
///            jt9_file_mode=True, threads=0) -> list[dict]
///
/// `threads`: the decode's own pool, 0 = cores - 1 (util::with_pool); the
/// pool is gone when the call returns.
///
/// jt9 run with no -c/-x has mycall "K1ABC", dxcall "W9XYZ" (JT9_MYCALL /
/// JT9_DXCALL); NB gives it the operator's calls, and the shadow decode
/// passes the same ones here.
#[pyfunction]
#[pyo3(signature = (audio, depth=1, nfa=200, nfb=4000, nfqso=1500, ap=true, mycall="", dxcall="",
                    qso_progress=0, hashes=None, jt9_file_mode=true, threads=0))]
#[allow(clippy::too_many_arguments)]
fn ft8_decode<'py>(
    py: Python<'py>,
    audio: &[u8],
    depth: i32,
    nfa: i32,
    nfb: i32,
    nfqso: i32,
    ap: bool,
    mycall: &str,
    dxcall: &str,
    qso_progress: usize,
    hashes: Option<PyRefMut<'_, PyCallHashes>>,
    jt9_file_mode: bool,
    threads: usize,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let x = samples(audio)?;
    let p = ft8::Ft8Params {
        nfa,
        nfb,
        nfqso,
        ndepth: depth.clamp(1, 3),
        lapon: ap,
        ap: ft8_ap(mycall, dxcall),
        nqso_progress: qso_progress.min(5),
        jt9_file_mode,
        threads,
        ..Default::default()
    };
    let mut local = CallHashes::new();
    let mut guard = hashes;
    let h: &mut CallHashes = match guard.as_mut() {
        Some(g) => &mut g.inner,
        None => &mut local,
    };
    let res = py.detach(|| ft8::decode_slot(&x, &p, h));
    res.decodes
        .iter()
        .map(|d| {
            decode_dict(
                py,
                &d.text,
                &d.payload,
                d.snr,
                d.dt,
                d.freq,
                d.iaptype,
                d.nharderrors,
                d.qual,
            )
        })
        .collect()
}

/// ft4_decode(audio, depth=1, nfa=200, nfb=4000, nfqso=1500, mycall="",
///            dxcall="", qso_progress=0, hashes=None, threads=0)
///            -> list[dict]
#[pyfunction]
#[pyo3(signature = (audio, depth=1, nfa=200.0, nfb=4000.0, nfqso=1500, mycall="", dxcall="",
                    qso_progress=0, hashes=None, threads=0))]
#[allow(clippy::too_many_arguments)]
fn ft4_decode<'py>(
    py: Python<'py>,
    audio: &[u8],
    depth: i32,
    nfa: f32,
    nfb: f32,
    nfqso: i32,
    mycall: &str,
    dxcall: &str,
    qso_progress: usize,
    hashes: Option<PyRefMut<'_, PyCallHashes>>,
    threads: usize,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let x = samples(audio)?;
    let p = ft4::Ft4Params {
        nfa,
        nfb,
        nfqso,
        ndepth: depth.clamp(1, 3),
        ap: ft4_ap(mycall, dxcall),
        nqso_progress: qso_progress.min(5),
        threads,
        ..Default::default()
    };
    let mut local = CallHashes::new();
    let mut guard = hashes;
    let h: &mut CallHashes = match guard.as_mut() {
        Some(g) => &mut g.inner,
        None => &mut local,
    };
    let (decodes, _) = py.detach(|| ft4::decode_slot(&x, &p, h));
    decodes
        .iter()
        .map(|d| {
            decode_dict(
                py,
                &d.text,
                &d.payload,
                d.snr,
                d.dt,
                d.freq,
                d.iaptype,
                d.nharderrors,
                d.qual,
            )
        })
        .collect()
}

/// Register the decoder's functions on the extension module.
pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(ft8_decode, m)?)?;
    m.add_function(wrap_pyfunction!(ft4_decode, m)?)?;
    // jt9 run from the command line (as NB runs it) has these calls.
    m.add("JT9_MYCALL", ft8::JT9_MYCALL)?;
    m.add("JT9_DXCALL", ft8::JT9_DXCALL)?;
    Ok(())
}
