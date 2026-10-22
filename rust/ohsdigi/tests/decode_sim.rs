//! End-to-end decoder tests on generated slots (decode::sim): no jt9, no
//! stored audio. The payloads are real WSJT-X messages (sim::PAYLOAD_POOL).

use ohsdigi::decode::ft4;
use ohsdigi::decode::ft8::{self, Ft8Params};
use ohsdigi::decode::sim::{make_slot, payload_pool, random_signals, Mode, SimSignal};
use ohsdigi::msg77::CallHashes;

fn pool() -> Vec<[u8; 77]> {
    payload_pool()
}

#[test]
fn ft8_one_strong_signal() {
    let m = pool()[0];
    let s = SimSignal {
        payload: m,
        freq: 1234.0,
        dt: 0.1,
        snr_db: -10.0,
        drift_hz_s: 0.0,
    };
    let x = make_slot(Mode::Ft8, &[s], 1, true);
    let r = ft8::decode_slot(
        &x,
        &Ft8Params {
            threads: 2,
            ..Default::default()
        },
        &mut CallHashes::new(),
    );
    assert_eq!(r.decodes.len(), 1, "{:?}", r.decodes);
    let d = &r.decodes[0];
    assert_eq!(d.payload, m);
    assert_eq!(d.text, "CQ K1ABC FN42");
    assert!((d.freq - 1234.0).abs() < 1.0, "freq {}", d.freq);
    assert!((d.dt - 0.1).abs() < 0.03, "dt {}", d.dt);
    assert!((d.snr + 10).abs() <= 2, "snr {}", d.snr);
}

#[test]
fn ft8_crowded_slot() {
    let sigs = random_signals(Mode::Ft8, &pool(), 15, -16.0, 0.0, 0.5, 0.0, 60.0, 7);
    let x = make_slot(Mode::Ft8, &sigs, 7, true);
    let r = ft8::decode_slot(
        &x,
        &Ft8Params {
            threads: 2,
            ..Default::default()
        },
        &mut CallHashes::new(),
    );
    eprintln!("{} signals, {} decodes", sigs.len(), r.decodes.len());
}

/// A decode runs on a pool of its own and leaves no threads behind (see
/// util::with_pool): in NB the decoder shares the process with the
/// receive path and the UI.
#[cfg(target_os = "linux")]
#[test]
fn decode_leaves_no_threads_behind() {
    fn tasks() -> usize {
        std::fs::read_dir("/proc/self/task").unwrap().count()
    }
    let sigs = random_signals(Mode::Ft8, &pool(), 10, -16.0, 0.0, 0.5, 0.0, 60.0, 3);
    let x = make_slot(Mode::Ft8, &sigs, 3, true);
    // Other tests may be running on the harness's own threads: compare
    // with the count just before, and wait (rayon ends its workers
    // asynchronously) for it to come back down.
    let before = tasks();
    let p = Ft8Params { threads: 4, ..Default::default() };
    let r = ft8::decode_slot(&x, &p, &mut CallHashes::new());
    assert!(!r.decodes.is_empty());
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while tasks() > before && std::time::Instant::now() < deadline {
        std::thread::sleep(std::time::Duration::from_millis(20));
    }
    assert!(tasks() <= before, "{} threads before, {} after", before, tasks());
}

#[test]
fn ft4_one_strong_signal() {
    let m = pool()[0];
    let s = SimSignal {
        payload: m,
        freq: 1234.0,
        dt: 0.1,
        snr_db: -8.0,
        drift_hz_s: 0.0,
    };
    let x = make_slot(Mode::Ft4, &[s], 1, true);
    let (d, _) = ft4::decode_slot(
        &x,
        &ft4::Ft4Params {
            threads: 2,
            ..Default::default()
        },
        &mut CallHashes::new(),
    );
    assert_eq!(d.len(), 1, "{:?}", d);
    assert_eq!(d[0].payload, m);
    assert_eq!(d[0].text, "CQ K1ABC FN42");
    assert!((d[0].freq - 1234.0).abs() < 2.0, "freq {}", d[0].freq);
    assert!((d[0].dt - 0.1).abs() < 0.03, "dt {}", d[0].dt);
}
