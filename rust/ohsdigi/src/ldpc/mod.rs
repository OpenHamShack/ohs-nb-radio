// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! LDPC codes. The (174,91) code carries FT8 and FT4 (and FST4's 77-bit
//! messages). JS8's older (174,87) code lives with JS8, in
//! `crate::js8::ldpc`: its decoders are WSJT-X 1.9's, which differ from
//! 2.7.0's in more than their tables, so sharing one decoder between the
//! two codes would have meant reproducing neither exactly.

pub mod ldpc174_91;
