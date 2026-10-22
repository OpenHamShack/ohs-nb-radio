//! ohsdigi against jt9 without jt9: each case is a generated slot (decode::sim,
//! fixed seed) and the payloads /usr/bin/jt9 (WSJT-X 2.7.0, Debian) decoded
//! from it, as `jt9 -8|-5 -p 15|7 -d <depth>` - NB's invocation plus the
//! depth. Written by `harness/compare.py <work> golden`; regenerate rather
//! than edit. ohsdigi must decode exactly the same set.

use ohsdigi::decode::sim::bits77_to_hex;
use ohsdigi::decode::sim::{make_slot, payload_pool, random_signals, Mode};
use ohsdigi::decode::{ft4, ft8};
use ohsdigi::msg77::CallHashes;

#[allow(clippy::type_complexity)]
const CASES: &[(&str, i32, u64, usize, f64, f64, f64, f64, f64, &[&str])] = &[
    (
        "ft8",
        1,
        41,
        15,
        -21.0,
        -17.0,
        0.6,
        0.1,
        60.0,
        &[
            "000000225b86dc9129c8",
            "00000023e86ef08f8388",
            "000000247844f61ba1c8",
            "000000267e500192c488",
            "00000026cb1b8b930748",
            "0000002738e1a4084648",
            "000046f59225ff131108",
            "01de7cb96000d9199200",
            "09bde3506149dc1fa508",
            "0a1d7110e6f4e30f84c8",
            "63edcee2a4ae07f50000",
            "6d5c40631a5fef1f9d48",
        ],
    ),
    (
        "ft8",
        1,
        42,
        15,
        -20.0,
        -10.0,
        0.6,
        0.1,
        60.0,
        &[
            "000000225b86dc9129c8",
            "00000023444a119137c8",
            "000000247844f61ba1c8",
            "00000026cb1b8b930748",
            "0000002738e1a4084648",
            "000046f59225ff131108",
            "00615f904def1a8a1988",
            "01531689ea735b5cac00",
            "091056936a5fe38f6908",
            "095d39959a6b631f9d48",
            "09bde3506149dc1fa508",
            "0a1d7110e6f4e30f84c8",
            "0c293b804def1a9fa488",
            "0c293b804def1a9faa08",
            "6d5c40631a5fef1f9d48",
        ],
    ),
    (
        "ft8",
        1,
        43,
        20,
        -18.0,
        5.0,
        0.8,
        0.1,
        50.0,
        &[
            "000000204882b48f84c8",
            "000000204def1a8a1988",
            "000000225b86dc9129c8",
            "00000023e86ef08f8388",
            "000000247844f61ba1c8",
            "000000267e500192c488",
            "00000026cb1b8b930748",
            "0000002738e1a4084648",
            "000046f59225ff131108",
            "01531689ea735b5cac00",
            "01de7cb96000d9199200",
            "095d39959a6b631f9d48",
            "09bde3506149dc1fa508",
            "0a1d7110e6f4e30f84c8",
            "0c293b804def1a9faa08",
            "6d4bfc704882b49faac8",
            "6d5c40631a5fef1f9d48",
            "bc162ec5026cda0b0a48",
            "e2012187e9c37b1e7148",
        ],
    ),
    (
        "ft8",
        1,
        44,
        25,
        -15.0,
        10.0,
        0.5,
        0.0,
        40.0,
        &[
            "000000204882b48f84c8",
            "000000204def1a8a1988",
            "000000225b86dc9129c8",
            "00000023444a119137c8",
            "000000247844f61ba1c8",
            "00000025bce4ff113588",
            "000000267e500192c488",
            "00000026cb1b8b930748",
            "0000002738e1a4084648",
            "000046f59225ff131108",
            "00615f904def1a8a1988",
            "01531689ea735b5cac00",
            "01de7cb96000d9199200",
            "095d39959a6b631f9d48",
            "09bde3506149dc085648",
            "09bde3506149dc3faa88",
            "0a1d7110e6f4e30f84c8",
            "0c293b804def1a9fa488",
            "0c293b804def1a9faa08",
            "6889423047157e911b88",
            "6d4bfc704882b49faac8",
            "6d5c40631a5fef1f9d48",
            "bc162ec5026cda0b0a48",
            "e2012187e9c37b1e7148",
            "fd386f6710090c3fad48",
        ],
    ),
    (
        "ft8",
        2,
        45,
        15,
        -21.0,
        -10.0,
        0.6,
        0.1,
        60.0,
        &[
            "000000204def1a8a1988",
            "000000247844f61ba1c8",
            "01de7cb96000d9199200",
            "08e2afd3444a11bfa9c8",
            "091056936a5fe38f6908",
            "095d39959a6b631f9d48",
            "09bde3506149dc085648",
            "0c293b804def1a9fa488",
            "0c293b804def1a9faa08",
            "6889423047157e911b88",
            "6d4bfc704882b49faac8",
            "6d5c40631a5fef1f9d48",
            "bc162ec5026cda0b0a48",
            "fd386f6710090c3fad48",
        ],
    ),
    (
        "ft8",
        3,
        46,
        15,
        -22.0,
        -16.0,
        0.6,
        0.1,
        60.0,
        &[
            "000000225b86dc9129c8",
            "00000025bce4ff113588",
            "000000267e500192c488",
            "00000026cb1b8b930748",
            "091056936a5fe38f6908",
            "09bde3506149dc1fa508",
            "0c293b804def1a9faa08",
            "63edcee2a4ae07f50000",
            "e2012187e9c37b1e7148",
            "fd386f6710090c3fad48",
        ],
    ),
    (
        "ft8",
        3,
        47,
        25,
        -20.0,
        5.0,
        0.8,
        0.1,
        40.0,
        &[
            "000000204882b48f84c8",
            "000000204def1a8a1988",
            "00000023444a119137c8",
            "00000023e86ef08f8388",
            "000000247844f61ba1c8",
            "00000025bce4ff113588",
            "000000267e500192c488",
            "0000002738e1a4084648",
            "000046f59225ff131108",
            "00615f904def1a8a1988",
            "01531689ea735b5cac00",
            "01de7cb96000d9199200",
            "08e2afd3444a11bfa9c8",
            "091056936a5fe38f6908",
            "095d39959a6b631f9d48",
            "09bde3506149dc1fa508",
            "09bde3506149dc3faa88",
            "0a1d7110e6f4e30f84c8",
            "0c293b804def1a9faa08",
            "63edcee2a4ae07f50000",
            "6d4bfc704882b49faac8",
            "6d5c40631a5fef1f9d48",
            "bc162ec5026cda0b0a48",
            "e2012187e9c37b1e7148",
            "fd386f6710090c3fad48",
        ],
    ),
    (
        "ft4",
        1,
        48,
        10,
        -17.0,
        -10.0,
        0.3,
        0.0,
        100.0,
        &[
            "00000023444a119137c8",
            "000000247844f61ba1c8",
            "00000025bce4ff113588",
            "09bde3506149dc085648",
            "09bde3506149dc1fa508",
            "09bde3506149dc3faa88",
            "0a1d7110e6f4e30f84c8",
            "0c293b804def1a9fa488",
            "0c293b804def1a9faa08",
        ],
    ),
    (
        "ft4",
        1,
        49,
        12,
        -15.0,
        5.0,
        0.3,
        0.0,
        90.0,
        &[
            "000000204882b48f84c8",
            "000000225b86dc9129c8",
            "000000247844f61ba1c8",
            "00000025bce4ff113588",
            "00000026cb1b8b930748",
            "00615f904def1a8a1988",
            "01531689ea735b5cac00",
            "01de7cb96000d9199200",
            "08e2afd3444a11bfa9c8",
            "09bde3506149dc085648",
            "6889423047157e911b88",
            "bc162ec5026cda0b0a48",
        ],
    ),
    (
        "ft4",
        3,
        50,
        10,
        -17.0,
        -5.0,
        0.3,
        0.0,
        100.0,
        &[
            "00000023e86ef08f8388",
            "00000025bce4ff113588",
            "000000267e500192c488",
            "01de7cb96000d9199200",
            "091056936a5fe38f6908",
            "0a1d7110e6f4e30f84c8",
            "0c293b804def1a9fa488",
            "0c293b804def1a9faa08",
            "bc162ec5026cda0b0a48",
            "e2012187e9c37b1e7148",
        ],
    ),
];

#[test]
fn decodes_what_jt9_decodes() {
    let pool = payload_pool();
    let mut bad = vec![];
    for &(mode, depth, seed, nsig, lo, hi, dts, drift, sep, want) in CASES {
        let m = if mode == "ft8" { Mode::Ft8 } else { Mode::Ft4 };
        let sigs = random_signals(m, &pool, nsig, lo, hi, dts, drift, sep, seed);
        let x = make_slot(m, &sigs, seed, true);
        let mut got: Vec<String> = if m == Mode::Ft8 {
            let p = ft8::Ft8Params {
                ndepth: depth,
                threads: 2,
                ..ft8::Ft8Params::jt9()
            };
            ft8::decode_slot(&x, &p, &mut CallHashes::new())
                .decodes
                .iter()
                .map(|d| bits77_to_hex(&d.payload))
                .collect()
        } else {
            let p = ft4::Ft4Params {
                ndepth: depth,
                threads: 2,
                ..ft4::Ft4Params::jt9()
            };
            ft4::decode_slot(&x, &p, &mut CallHashes::new())
                .0
                .iter()
                .map(|d| bits77_to_hex(&d.payload))
                .collect()
        };
        got.sort();
        let want: Vec<String> = want.iter().map(|s| s.to_string()).collect();
        if got != want {
            bad.push(format!(
                "{} depth {} seed {}: jt9 {:?}, ohsdigi {:?}",
                mode, depth, seed, want, got
            ));
        }
    }
    assert!(bad.is_empty(), "{}", bad.join("\n"));
}
