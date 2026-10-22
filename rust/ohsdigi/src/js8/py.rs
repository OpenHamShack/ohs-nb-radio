// ohsdigi - OpenHamShack's digital-mode encoders and decoders.
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! Python binding for JS8 (registered by python.rs on the same
//! `ohscore.ohsdigi` module): decode a period, read a frame, turn text into
//! frames, and a frame into audio. docs/OHSDIGI-PYTHON.md, "JS8".
//!
//! Audio goes in as decode() takes it (pyapi::audio_from: int16, float32
//! or float64 buffers, or int16 bytes) and comes out as float32 bytes, as
//! encode_audio() gives it. The GIL is released for the decode.

use super::decode::{decode_slot, Js8Params};
use super::varicode::{build_frames, unpack_frame, Unpacked};
use super::{tones, waveform, Submode};
use crate::pyapi::audio_from;
use crate::python::f32_bytes;
use pyo3::exceptions::PyValueError;
use pyo3::prelude::*;
use pyo3::types::{PyBytes, PyDict};

fn submode_of(name: &str) -> PyResult<Submode> {
    Submode::from_name(name).ok_or_else(|| {
        PyValueError::new_err(format!("unknown JS8 speed {name:?} (normal, fast, turbo, slow, ultra or A, B, C, E, I)"))
    })
}

fn put_unpacked(o: &Bound<'_, PyDict>, u: &Unpacked) -> PyResult<()> {
    o.set_item("text", &u.text)?;
    o.set_item("kind", u.kind.name())?;
    o.set_item("from", u.from.as_deref())?;
    o.set_item("to", u.to.as_deref())?;
    o.set_item("grid", u.grid.as_deref())?;
    o.set_item("first", u.first)?;
    o.set_item("last", u.last)?;
    Ok(())
}

/// js8_decode(audio, submode="normal", *, depth=3, freq_min=200.0,
///            freq_max=4000.0, freq_qso=1500.0, threads=0) -> list[dict]
///
/// Decode one period of 12 kHz mono audio from its start (15 s for
/// Normal, 10 Fast, 6 Turbo, 30 Slow, 4 Ultra; a signal sent on time
/// starts JS8_SUBMODES[...]["start"] in and decodes with dt near 0).
/// Each decode: frame (12 characters), i3bit, snr, dt, freq (tone 0, Hz),
/// submode, then the frame read as JS8Call shows it - text, kind
/// (heartbeat, compound, compound_directed, directed, data, unknown),
/// from, to, grid, first, last - and sync, hard_errors, qual.
///
/// depth is JS8Call's: 1 BP only, 2 subtraction, 3 (its default, and
/// this one's) OSD as well, 4 one pass more.
#[pyfunction]
#[pyo3(signature = (audio, submode="normal", *, depth=3, freq_min=200.0, freq_max=4000.0, freq_qso=1500.0, threads=0))]
#[allow(clippy::too_many_arguments)]
fn js8_decode<'py>(
    py: Python<'py>,
    audio: &Bound<'py, PyAny>,
    submode: &str,
    depth: i32,
    freq_min: f64,
    freq_max: f64,
    freq_qso: f64,
    threads: usize,
) -> PyResult<Vec<Bound<'py, PyDict>>> {
    let sub = submode_of(submode)?;
    if !(freq_min < freq_max) {
        return Err(PyValueError::new_err("freq_min must be below freq_max"));
    }
    let x = audio_from(audio)?;
    let p = Js8Params {
        nfa: freq_min.round() as i32,
        nfb: freq_max.round() as i32,
        nfqso: freq_qso.round() as i32,
        ndepth: depth.clamp(1, 4),
        threads,
        ..Default::default()
    };
    let decodes = py.detach(|| decode_slot(&x, sub, &p));
    decodes
        .iter()
        .map(|d| {
            let o = PyDict::new(py);
            o.set_item("frame", &d.frame)?;
            o.set_item("i3bit", d.i3bit)?;
            o.set_item("snr", d.snr)?;
            o.set_item("dt", d.dt)?;
            o.set_item("freq", d.freq)?;
            o.set_item("submode", sub.name())?;
            put_unpacked(&o, &unpack_frame(&d.frame, d.i3bit))?;
            o.set_item("sync", d.sync)?;
            o.set_item("hard_errors", d.nharderrors)?;
            o.set_item("qual", d.qual)?;
            Ok(o)
        })
        .collect()
}

/// js8_unpack(frame, i3bit) -> dict: a frame read as JS8Call shows it
/// (text, kind, from, to, grid, first, last).
#[pyfunction]
fn js8_unpack<'py>(py: Python<'py>, frame: &str, i3bit: u8) -> PyResult<Bound<'py, PyDict>> {
    let o = PyDict::new(py);
    put_unpacked(&o, &unpack_frame(frame, i3bit))?;
    Ok(o)
}

/// js8_frames(text, mycall, mygrid="", *, selected_call="",
///            submode="normal", force_identify=False, force_data=False)
///            -> list[tuple[str, int]]
///
/// The frames JS8Call would send for `text` (its buildMessageFrames), each
/// with its i3bit; one frame per period, in order. Text is taken as given:
/// JS8Call sends upper case, and lower case cannot be sent. Raises
/// ValueError for text no frame can carry.
#[pyfunction]
#[pyo3(signature = (text, mycall, mygrid="", *, selected_call="", submode="normal", force_identify=false, force_data=false))]
fn js8_frames(
    text: &str,
    mycall: &str,
    mygrid: &str,
    selected_call: &str,
    submode: &str,
    force_identify: bool,
    force_data: bool,
) -> PyResult<Vec<(String, u8)>> {
    let sub = submode_of(submode)?;
    build_frames(mycall, mygrid, selected_call, text, force_identify, force_data, sub).map_err(PyValueError::new_err)
}

/// js8_tones(frame, i3bit, submode="normal") -> bytes: the 79 tones.
#[pyfunction]
#[pyo3(signature = (frame, i3bit, submode="normal"))]
fn js8_tones<'py>(py: Python<'py>, frame: &str, i3bit: u8, submode: &str) -> PyResult<Bound<'py, PyBytes>> {
    let t = tones(frame, i3bit, submode_of(submode)?).map_err(|e| PyValueError::new_err(e.to_string()))?;
    Ok(PyBytes::new(py, &t))
}

/// js8_encode_audio(frame, i3bit, submode="normal", freq=1500.0,
///                  sample_rate=12000.0) -> bytes
///
/// One frame's transmission as float32 little-endian samples, full scale,
/// tone 0 at `freq`: what JS8Call's modulator plays, to be started
/// JS8_SUBMODES[submode]["start"] seconds into its period.
#[pyfunction]
#[pyo3(signature = (frame, i3bit, submode="normal", freq=1500.0, sample_rate=12_000.0))]
fn js8_encode_audio<'py>(
    py: Python<'py>,
    frame: &str,
    i3bit: u8,
    submode: &str,
    freq: f64,
    sample_rate: f64,
) -> PyResult<Bound<'py, PyBytes>> {
    let sub = submode_of(submode)?;
    if !(sample_rate > 0.0 && freq > 0.0 && freq + 8.0 * sub.tone_spacing() < sample_rate / 2.0) {
        return Err(PyValueError::new_err("freq must leave the signal below half the sample rate"));
    }
    let t = tones(frame, i3bit, sub).map_err(|e| PyValueError::new_err(e.to_string()))?;
    let w = py.detach(move || waveform(&t, freq, sample_rate, sub));
    Ok(f32_bytes(py, &w))
}

pub fn register(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(js8_decode, m)?)?;
    m.add_function(wrap_pyfunction!(js8_unpack, m)?)?;
    m.add_function(wrap_pyfunction!(js8_frames, m)?)?;
    m.add_function(wrap_pyfunction!(js8_tones, m)?)?;
    m.add_function(wrap_pyfunction!(js8_encode_audio, m)?)?;
    let subs = PyDict::new(m.py());
    for s in Submode::ALL {
        let d = PyDict::new(m.py());
        let p = s.params();
        d.set_item("letter", s.letter().to_string())?;
        d.set_item("period", p.period)?;
        d.set_item("start", p.astart)?;
        d.set_item("tone_spacing", s.tone_spacing())?;
        d.set_item("symbols", super::NN)?;
        d.set_item("duration", super::NN as f64 * p.nsps as f64 / 12000.0)?;
        subs.set_item(s.name(), d)?;
    }
    m.add("JS8_SUBMODES", subs)?;
    m.add("JS8_FRAME_FIRST", super::FRAME_FIRST)?;
    m.add("JS8_FRAME_LAST", super::FRAME_LAST)?;
    m.add("JS8_FRAME_DATA", super::FRAME_DATA)?;
    Ok(())
}
