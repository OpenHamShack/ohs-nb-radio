// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! Python binding for Q65 (registered by python.rs on the same
//! `ohscore.ohsdigi` module): decode a period, encode a message, make its
//! audio. docs/OHSDIGI-PYTHON.md, "Q65". Audio as decode() and
//! encode_audio() take and give it; the GIL is released for the decode.

use super::decode::{decode_period, jt9_hashes, Q65Params};
use super::{encode, nsps, start_delay, submode_index, tone_spacing, waveform, NSYM, PERIODS};
use crate::pyapi::audio_from;
use crate::python::{f32_bytes, BadMessage, PyCallHashes};
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

fn mode_of(period: u32, submode: &str) -> PyResult<usize> {
    if nsps(period).is_none() {
        return Err(PyValueError::new_err(format!("Q65 has no {period} s period (15, 30, 60, 120 or 300)")));
    }
    submode_index(submode).ok_or_else(|| PyValueError::new_err(format!("unknown Q65 submode {submode:?} (A to E)")))
}

/// q65_decode(audio, period=60, submode="A", *, depth=1, freq_qso=1500.0,
///            tol=10.0, freq_min=200.0, freq_max=4000.0, mycall="",
///            dxcall="", dxgrid="", qso_progress=0, emedelay=None,
///            single=False, hashes=None, threads=0) -> list[dict]
///
/// Decode one period of 12 kHz mono audio from its start, as `jt9 -3`
/// decodes a WAV: first at freq_qso +/- tol (with dxcall known, a list
/// decode of the likely replies first), then the rest of the band unless
/// `single`. Each decode: text, snr, dt (from the nominal start: 0.5 s
/// into a 15/30 s period, 1 s into a longer one), freq (Hz of the sync
/// tone), ap (0 none, 1 CQ, 2 MyCall, 3 list: jt9's "q" digit), averaged
/// (always 1), bits (77 '0'/'1'), period, submode.
///
/// `emedelay` defaults to jt9's: 2.5 s at 60 s periods, else 0. `hashes`
/// keeps hashed calls across periods; without it the table is jt9's
/// (MyCall, DxCall and the list's calls).
#[pyfunction]
#[pyo3(signature = (audio, period=60, submode="A", *, depth=1, freq_qso=1500.0, tol=10.0, freq_min=200.0,
                    freq_max=4000.0, mycall="", dxcall="", dxgrid="", qso_progress=0, emedelay=None,
                    single=false, hashes=None, threads=0))]
#[allow(clippy::too_many_arguments)]
fn q65_decode<'py>(
    py: Python<'py>,
    audio: &Bound<'py, PyAny>,
    period: u32,
    submode: &str,
    depth: i32,
    freq_qso: f64,
    tol: f64,
    freq_min: f64,
    freq_max: f64,
    mycall: &str,
    dxcall: &str,
    dxgrid: &str,
    qso_progress: usize,
    emedelay: Option<f32>,
    single: bool,
    hashes: Option<PyRefMut<'_, PyCallHashes>>,
    threads: usize,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let sub = mode_of(period, submode)?;
    if !(freq_min < freq_max) {
        return Err(PyValueError::new_err("freq_min must be below freq_max"));
    }
    let x = audio_from(audio)?;
    let mut p = Q65Params::jt9(period, sub);
    p.ndepth = depth.clamp(1, 3);
    p.nfqso = freq_qso.round() as i32;
    p.ntol = tol.round() as i32;
    p.nfa = freq_min.round() as i32;
    p.nfb = freq_max.round() as i32;
    p.mycall = mycall.trim().to_ascii_uppercase();
    p.hiscall = dxcall.trim().to_ascii_uppercase();
    p.hisgrid = dxgrid.trim().to_ascii_uppercase();
    p.nqso_progress = qso_progress.min(5);
    if let Some(d) = emedelay {
        p.emedelay = d;
    }
    p.single_decode = single;
    p.threads = threads;
    let mut local = jt9_hashes(&p.mycall, &p.hiscall);
    let mut guard = hashes;
    let h = match guard.as_mut() {
        Some(g) => &mut g.inner,
        None => &mut local,
    };
    let decodes = py.detach(|| decode_period(&x, &p, h));
    let letter = ["A", "B", "C", "D", "E"][sub];
    decodes
        .iter()
        .map(|d| {
            let o = PyDict::new(py);
            o.set_item("text", &d.text)?;
            o.set_item("snr", d.snr)?;
            o.set_item("dt", d.dt)?;
            o.set_item("freq", d.freq)?;
            o.set_item("ap", d.idec)?;
            o.set_item("averaged", d.nused)?;
            o.set_item("bits", &d.bits)?;
            o.set_item("period", period)?;
            o.set_item("submode", letter)?;
            Ok(o)
        })
        .collect()
}

/// q65_encode(message) -> (sent, tones): the message as it will be
/// received and its 85 tones (0 = sync, data symbol v is tone v + 1), as
/// WSJT-X's genq65. Raises BadMessage for what WSJT-X would not send.
#[pyfunction]
fn q65_encode<'py>(py: Python<'py>, message: &str) -> PyResult<(String, Bound<'py, PyBytes>)> {
    let e = encode(message).map_err(|e| BadMessage::new_err(e.to_string()))?;
    Ok((e.sent, PyBytes::new(py, &e.tones)))
}

/// q65_encode_audio(message, period=60, submode="A", freq=1500.0,
///                  sample_rate=12000.0) -> bytes
///
/// The transmission as float32 little-endian, full scale, sync tone at
/// `freq`: what WSJT-X's modulator plays, to start Q65_PERIODS[period]
/// ["start"] after the period boundary.
#[pyfunction]
#[pyo3(signature = (message, period=60, submode="A", freq=1500.0, sample_rate=12_000.0))]
fn q65_encode_audio<'py>(
    py: Python<'py>,
    message: &str,
    period: u32,
    submode: &str,
    freq: f64,
    sample_rate: f64,
) -> PyResult<Bound<'py, PyBytes>> {
    let sub = mode_of(period, submode)?;
    if !(sample_rate > 0.0 && freq > 0.0 && freq + 65.0 * tone_spacing(period, sub) < sample_rate / 2.0) {
        return Err(PyValueError::new_err("freq must leave the signal below half the sample rate"));
    }
    let e = encode(message).map_err(|e| BadMessage::new_err(e.to_string()))?;
    let w = py.detach(move || waveform(&e.tones, freq, sample_rate, period, sub));
    Ok(f32_bytes(py, &w))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(q65_decode, m)?)?;
    m.add_function(wrap_pyfunction!(q65_encode, m)?)?;
    m.add_function(wrap_pyfunction!(q65_encode_audio, m)?)?;
    let periods = PyDict::new(m.py());
    for p in PERIODS {
        let d = PyDict::new(m.py());
        let n = nsps(p).unwrap();
        d.set_item("nsps", n)?;
        d.set_item("start", start_delay(p))?;
        d.set_item("symbols", NSYM)?;
        d.set_item("duration", NSYM as f64 * n as f64 / 12000.0)?;
        d.set_item("baud", 12000.0 / n as f64)?;
        periods.set_item(p, d)?;
    }
    m.add("Q65_PERIODS", periods)?;
    m.add("Q65_SUBMODES", ("A", "B", "C", "D", "E"))?;
    Ok(())
}
