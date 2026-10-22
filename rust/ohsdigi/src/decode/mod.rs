//! FT8 and FT4 decoders: a port of WSJT-X 2.7.0's, stage by stage.
//!
//! WSJT-X (https://wsjt.sourceforge.io) is Copyright (C) 2001-2024 Joe
//! Taylor K1JT, Steve Franke K9AN, Bill Somerville G4WJS, Nico Palermo
//! IV3NWV and the WSJT-X development team, GPL-3. Each file names the
//! routines it ports.
//!
//! Layout:
//! - `ft8`: sync8 -> downsample/sync8d -> ft8b metrics -> LDPC ->
//!   subtractft8, and ft8_decode's pass structure;
//! - `ft4`: the same for FT4 (getcandidates4, sync4d, bit metrics);
//! - `ldpc`: BP + OSD (decode174_91, osd174_91), shared by both;
//! - `ldpc_tables`: the parity-check tables, generated from WSJT-X's DATA
//!   statements (the generator is crate::ldpc::ldpc174_91's);
//! - `ap`: a-priori bits from MyCall/DxCall (ft8apset);
//! - `util`: indexx, pctile, polyfit and friends, ported for their quirks;
//! - `sim`: a deterministic test-signal generator (no jt9 needed);
//! - `py`: the Python binding (feature "python").
//!
//! Not ported: contest AP variants (ncontest != 0: NA/EU VHF, Field Day,
//! RTTY RU, WW Digi, Fox/Hound, ARRL Digi) and ft8_a7 (the "a7" decodes
//! of last cycle's messages, which need decoder state across slots; jt9
//! run once per WAV file, as NB runs it, never reaches them either).

// The ports index arrays as the Fortran does (1-based maths, parallel
// arrays, stride loops); iterator rewrites would obscure the line-by-line
// correspondence the harness checks, so clippy's loop-style lint is off here.
#![allow(clippy::needless_range_loop)]

pub mod ap;
pub mod ft4;
pub mod ft8;
pub mod ldpc;
pub mod ldpc_tables;
pub mod sim;
pub mod util;

#[cfg(feature = "python")]
pub mod py;
