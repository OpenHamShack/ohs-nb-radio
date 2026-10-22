// ohsdigi - OpenHamShack's digital-mode encoders (and, later, decoders).
// Copyright (C) 2026 Brian Henderson
// SPDX-License-Identifier: GPL-3.0-or-later

//! Bit-exact against WSJT-X 2.7.0: every message in the corpus that
//! tools/digi-corpus.py recorded from ft8code and ft4code must encode here
//! to the same type, the same "as received" text, the same 77 bits and the
//! same channel symbols - and a message WSJT-X refuses, or stops on, must
//! be refused here too.
//!
//! The exception is the handful of messages for which WSJT-X has no single
//! answer, because its packer reads a variable it never set (see
//! msg77::PackError::Undefined and msg77::Packed::undefined): for those,
//! ft8code and ft4code disagree with each other, and the bits are whatever
//! was left in memory. ohsdigi refuses the ones whose result is garbage, and
//! for the one where ft8code is consistent (an unset RTTY serial number,
//! which it treats as 0) gives ft8code's answer for both modes; such
//! messages are counted and reported, not compared for FT4.
//!
//! OHSDIGI_EXTRA_CORPUS names further corpus files (comma-separated, plain
//! or .gz) to hold to the same standard: a large fuzz run made with
//! `tools/digi-corpus.py --count 100000 --out /tmp/fuzz.tsv`.

use ohsdigi::{encode, EncodeError, Mode};
use std::io::Read;
use std::path::{Path, PathBuf};

fn load(path: &Path) -> String {
    let raw = std::fs::read(path).unwrap_or_else(|e| panic!("{}: {e}", path.display()));
    let bytes = if path.extension().is_some_and(|e| e == "gz") {
        let mut out = Vec::new();
        flate2::read::GzDecoder::new(&raw[..]).read_to_end(&mut out).unwrap();
        out
    } else {
        raw
    };
    // The corpus is written as Latin-1; every message in it is ASCII.
    bytes.iter().map(|&b| b as char).collect()
}

fn digits(v: &[u8]) -> String {
    v.iter().map(|d| (b'0' + d) as char).collect()
}

fn type_str(i3: i32, n3: i32) -> String {
    if i3 >= 1 {
        format!("{i3}.")
    } else {
        format!("{i3}.{n3}")
    }
}

enum Verdict {
    Same,
    /// WSJT-X's answer is undefined for this message (see above); why.
    Undefined(&'static str),
    Differs(String),
}

/// One mode's comparison with WSJT-X.
fn check(mode: Mode, msg: &str, status: &str, typ: &str, sent: &str, bits: &str, tones: &str) -> Verdict {
    match encode(mode, msg) {
        Err(EncodeError::Undefined { why, .. }) => Verdict::Undefined(why),
        Ok(e) if e.undefined_in_wsjtx.is_some() && mode == Mode::Ft4 => {
            Verdict::Undefined(e.undefined_in_wsjtx.unwrap())
        }
        got => match compare(mode, msg, status, typ, sent, bits, tones, got) {
            None => Verdict::Same,
            Some(d) => Verdict::Differs(d),
        },
    }
}

/// Every difference between WSJT-X's answer for one mode and ours.
#[allow(clippy::too_many_arguments)]
fn compare(
    mode: Mode,
    msg: &str,
    status: &str,
    typ: &str,
    sent: &str,
    bits: &str,
    tones: &str,
    got: Result<ohsdigi::Encoded, EncodeError>,
) -> Option<String> {
    let tag = mode.name();
    match (status, got) {
        ("ok", Ok(e)) => {
            let mut diffs = Vec::new();
            if type_str(e.i3, e.n3) != typ {
                diffs.push(format!("type {} != {typ}", type_str(e.i3, e.n3)));
            }
            if e.sent != sent {
                diffs.push(format!("sent {:?} != {sent:?}", e.sent));
            }
            if digits(&e.bits) != bits {
                diffs.push(format!("bits {} != {bits}", digits(&e.bits)));
            }
            if digits(&e.tones) != tones {
                diffs.push(format!("tones {} != {tones}", digits(&e.tones)));
            }
            if diffs.is_empty() {
                None
            } else {
                Some(format!("{tag} {msg:?}: {}", diffs.join("; ")))
            }
        }
        ("bad", Err(EncodeError::BadMessage { i3, n3, .. })) => {
            if type_str(i3, n3) == typ {
                None
            } else {
                Some(format!("{tag} {msg:?}: bad, type {} != {typ}", type_str(i3, n3)))
            }
        }
        ("crash", Err(EncodeError::Unencodable { .. })) => None,
        (s, got) => Some(format!("{tag} {msg:?}: WSJT-X {s} {typ} {sent:?}, ohsdigi {got:?}")),
    }
}

fn run(path: &Path) -> (usize, std::collections::BTreeMap<&'static str, usize>, Vec<String>) {
    let text = load(path);
    let mut n = 0;
    let mut undefined = std::collections::BTreeMap::new();
    let mut fails = Vec::new();
    // Line 1 says where the corpus came from, line 2 names the fields; a
    // message may itself start with '#', so nothing else is a comment.
    let mut lines = text.split('\n');
    assert!(
        lines.next().is_some_and(|l| l.starts_with('#')),
        "{}: no provenance line",
        path.display()
    );
    assert!(
        lines.next().is_some_and(|l| l.starts_with("message\t")),
        "{}: no field names",
        path.display()
    );
    for line in lines {
        if line.is_empty() {
            continue;
        }
        let f: Vec<&str> = line.split('\t').collect();
        assert_eq!(f.len(), 11, "malformed corpus line {line:?}");
        n += 1;
        for v in [
            check(Mode::Ft8, f[0], f[1], f[2], f[3], f[4], f[5]),
            check(Mode::Ft4, f[0], f[6], f[7], f[8], f[9], f[10]),
        ] {
            match v {
                Verdict::Same => {}
                Verdict::Undefined(why) => *undefined.entry(why).or_insert(0) += 1,
                Verdict::Differs(d) => fails.push(d),
            }
        }
    }
    (n, undefined, fails)
}

fn report(path: &Path, min: usize) {
    let (n, why, fails) = run(path);
    let undefined: usize = why.values().sum();
    assert!(n >= min, "{}: only {n} messages", path.display());
    if !fails.is_empty() {
        let shown: Vec<&String> = fails.iter().take(40).collect();
        panic!(
            "{} of {n} messages differ from WSJT-X 2.7.0 ({}):\n{}",
            fails.len(),
            path.display(),
            shown.iter().map(|s| s.as_str()).collect::<Vec<_>>().join("\n")
        );
    }
    // Undefined in WSJT-X must stay the exception, even in a corpus that
    // goes looking for it.
    assert!(
        undefined * 20 < n * 2,
        "{undefined} of {} encodings undefined in WSJT-X: {why:?}",
        n * 2
    );
    eprintln!(
        "{}: {n} messages x FT8 and FT4: {} identical to WSJT-X 2.7.0, {undefined} undefined in WSJT-X {why:?}",
        path.display(),
        n * 2 - undefined
    );
}

#[test]
fn identical_to_wsjtx_2_7_0() {
    let p = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("testdata/wsjtx-2.7.0-ft8-ft4.tsv.gz");
    report(&p, 5000);
}

#[test]
fn extra_corpora() {
    if let Ok(list) = std::env::var("OHSDIGI_EXTRA_CORPUS") {
        for p in list.split(',').filter(|s| !s.is_empty()) {
            report(Path::new(p), 1);
        }
    }
}
