"""IQ recording (ohscore/sigmf.py, Engine.start_recording): what a tester
sends must be the receive IQ exactly as the engine had it, in a SigMF pair
any tool can read, with what is needed to analyse it written beside it -
and recording must never cost receive anything, however slow the disk."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import hashlib
import json
import os
import re
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from helpers import make_radio, run_sim
from systems import system
from ohscore import host, sigmf
from ohsnb.devices.sim import SimDevice

FS = 1_200_000.0


def load(path: Path) -> tuple[dict, np.ndarray]:
    data, meta = sigmf.paths(path)
    m = json.loads(meta.read_text())
    raw = np.fromfile(data, "<i2").astype(np.float32) / sigmf.SCALE
    return m, raw[0::2] + 1j * raw[1::2]


def check_core(test: unittest.TestCase, m: dict, data: Path) -> None:
    """SigMF's required core fields and rules, checked here by hand rather
    than by our own validate() alone (no network, no sigmf package)."""
    test.assertEqual(set(m), {"global", "captures", "annotations"})
    g = m["global"]
    test.assertEqual(g["core:datatype"], "ci16_le")
    test.assertRegex(g["core:version"], r"^1\.\d+\.\d+$")
    test.assertGreater(g["core:sample_rate"], 0)
    test.assertIsInstance(m["captures"], list)
    test.assertIsInstance(m["annotations"], list)
    test.assertGreaterEqual(len(m["captures"]), 1)
    starts = [c["core:sample_start"] for c in m["captures"]]
    test.assertEqual(starts, sorted(set(starts)))
    test.assertEqual(starts[0], 0)
    test.assertIn("core:datetime", m["captures"][0])
    test.assertRegex(m["captures"][0]["core:datetime"], r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?Z$")
    a_starts = [a["core:sample_start"] for a in m["annotations"]]
    test.assertEqual(a_starts, sorted(a_starts))
    # Every non-core namespace is declared as an extension.
    declared = {e["name"] for e in g.get("core:extensions", [])}
    for obj in [g, *m["captures"], *m["annotations"]]:
        for k in obj:
            ns = k.split(":", 1)[0]
            test.assertTrue(ns == "core" or ns in declared, k)
    # The data file holds whole ci16 samples, as many as the metadata says,
    # and its hash is the one recorded.
    blob = data.read_bytes()
    test.assertEqual(len(blob) % 4, 0)
    test.assertEqual(len(blob) // 4, g["openhamshack:samples"])
    test.assertEqual(hashlib.sha512(blob).hexdigest(), g["core:sha512"])
    test.assertEqual(sigmf.validate(m), [])


def wait_saved(radio, timeout=10.0):
    """Until every ended recording's writer is done and the supervisor has
    said so (in real time: the supervisor ticks at 10 Hz whatever the
    simulator's speed)."""
    deadline = time.monotonic() + timeout
    while radio.rec_closing and time.monotonic() < deadline:
        radio.heartbeat()
        time.sleep(0.02)


class Stalled(sigmf.Recorder):
    """A writer stuck on a disk that does not answer until `go` is set."""
    go: threading.Event

    def _write_block(self, x):
        self.go.wait(30)
        super()._write_block(x)


class RecorderAlone(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_samples_round_trip_exactly_at_the_plutos_resolution(self):
        # A Pluto's sample is n / 2048; ci16 at full scale 32768 keeps it exactly.
        rng = np.random.default_rng(3)
        x = ((rng.integers(-2048, 2048, 5000) + 1j * rng.integers(-2048, 2048, 5000)) / 2048).astype(np.complex64)
        rec = sigmf.Recorder(self.dir / "a", FS, {}).start()
        self.assertTrue(rec.push(x, (739e6, 10489e6), time.time()))
        rec.close()
        self.assertTrue(rec.wait(10))
        m, y = load(self.dir / "a")
        np.testing.assert_array_equal(y, x)
        check_core(self, m, rec.data_path)
        self.assertEqual(m["global"]["openhamshack:clipped"], 0)

    def test_what_is_written_is_synced_and_dropped_from_the_page_cache(self):
        # In a container the page cache counts against its memory limit, and
        # a 6 MS/s capture lost blocks while the cgroup reclaimed it (sigmf
        # docstring). What the writer has written leaves the cache in whole,
        # contiguous ranges from the start, and the file is still exactly
        # what was pushed.
        dropped = []
        real = getattr(os, "posix_fadvise", None)

        def fadvise(fd, offset, length, advice):
            dropped.append((offset, length, advice))
            if real is not None:
                real(fd, offset, length, advice)

        rng = np.random.default_rng(5)
        x = ((rng.integers(-2048, 2048, 1 << 20) + 1j * rng.integers(-2048, 2048, 1 << 20)) / 2048) \
            .astype(np.complex64)                                   # 4 MB a block as ci16
        with mock.patch.object(sigmf, "DROP_EVERY_BYTES", 8 << 20), \
                mock.patch.object(sigmf.os, "posix_fadvise", fadvise, create=True):
            rec = sigmf.Recorder(self.dir / "p", FS, {}, queue_s=1e9).start()
            for _ in range(10):
                self.assertTrue(rec.push(x, (1090e6, 1090e6), time.time()))
            rec.close()
            self.assertTrue(rec.wait(30))
        self.assertEqual([d[2] for d in dropped], [os.POSIX_FADV_DONTNEED] * len(dropped))
        self.assertEqual([(o, n) for o, n, _ in dropped], [(0, 8 << 20), (8 << 20, 8 << 20), (16 << 20, 8 << 20),
                                                          (24 << 20, 8 << 20), (32 << 20, 8 << 20)])
        m, y = load(self.dir / "p")
        self.assertEqual(len(y), 10 << 20)
        np.testing.assert_array_equal(y[:1 << 20], x)
        np.testing.assert_array_equal(y[-(1 << 20):], x)
        check_core(self, m, rec.data_path)

    def test_over_full_scale_is_clipped_and_counted(self):
        x = np.array([0.5, 1.5, -2.0 + 0.25j], np.complex64)
        rec = sigmf.Recorder(self.dir / "c", FS, {}).start()
        rec.push(x, (1.0, 1.0), time.time())
        rec.close()
        rec.wait(10)
        m, y = load(self.dir / "c")
        self.assertEqual(m["global"]["openhamshack:clipped"], 2)
        self.assertAlmostEqual(float(y[1].real), 32767 / 32768)
        self.assertAlmostEqual(float(y[2].real), -1.0)
        self.assertAlmostEqual(float(y[2].imag), 0.25)

    def test_a_stalled_writer_drops_and_counts_and_never_blocks(self):
        rec = Stalled(self.dir / "s", FS, {}, queue_s=0.5)
        rec.go = threading.Event()
        rec.start()
        block = np.full(int(0.075 * FS), 0.1, np.complex64)
        t0 = time.time()
        worst = 0.0
        for i in range(40):             # 3 s of blocks against a writer that writes nothing
            a = time.perf_counter()
            self.assertTrue(rec.push(block, (1.0, 2.0), t0 + i * 0.075))
            worst = max(worst, time.perf_counter() - a)
        self.assertLess(worst, 0.05, "push waited for the disk")
        self.assertGreater(rec.dropped, 0)
        self.assertEqual(rec.accepted + rec.dropped, 40 * len(block))
        self.assertLessEqual(rec.accepted, rec.cap)
        dropped = rec.dropped
        rec.go.set()
        # Once the disk catches up, later blocks are taken again: after a gap.
        for i in range(40, 44):
            deadline = time.time() + 10
            while rec.queued and time.time() < deadline:
                time.sleep(0.01)
            rec.push(block, (1.0, 2.0), t0 + i * 0.075)
        rec.close()
        self.assertTrue(rec.wait(10))
        m, _ = load(self.dir / "s")
        check_core(self, m, rec.data_path)
        g = m["global"]
        self.assertEqual(g["openhamshack:dropped_samples"], dropped)
        self.assertGreaterEqual(g["openhamshack:dropped_blocks"], 1)
        gaps = [c for c in m["captures"] if "openhamshack:gap_samples" in c]
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["openhamshack:gap_samples"], dropped)
        self.assertIn("core:datetime", gaps[0])
        # The gap's start time is where the samples resume, not where they stopped.
        self.assertAlmostEqual(sigmf.parse_utc(gaps[0]["core:datetime"]),
                               m["captures"][0]["openhamshack:utc"] + (gaps[0]["core:sample_start"] + dropped) / FS,
                               places=3)

    def test_a_full_disk_ends_it_with_a_sentence_and_readable_metadata(self):
        class Full(sigmf.Recorder):
            def _write_block(self, x):
                if self.written:
                    raise OSError(28, "No space left on device")
                super()._write_block(x)

        rec = Full(self.dir / "f", FS, {}).start()
        b = np.full(1000, 0.1, np.complex64)
        self.assertTrue(rec.push(b, (1.0, 1.0), 0.0))
        rec.push(b, (1.0, 1.0), 1000 / FS)
        self.assertTrue(rec.wait(10))
        self.assertFalse(rec.push(b, (1.0, 1.0), 2000 / FS))     # the caller is told it has ended
        self.assertIn("No space left", rec.error)
        m, y = load(self.dir / "f")
        self.assertEqual(len(y), 1000)
        self.assertIn("No space left", m["global"]["openhamshack:stopped"])
        check_core(self, m, rec.data_path)

    def test_the_time_limit_ends_it_on_the_exact_sample(self):
        rec = sigmf.Recorder(self.dir / "l", FS, {}, limit_s=0.2).start()
        block = np.zeros(100_000, np.complex64)
        self.assertTrue(rec.push(block, (1.0, 1.0), 0.0))
        self.assertTrue(rec.push(block, (1.0, 1.0), 0.1))
        self.assertFalse(rec.push(block, (1.0, 1.0), 0.2))       # 40 000 of these, then the end
        self.assertFalse(rec.push(block, (1.0, 1.0), 0.3))
        self.assertTrue(rec.wait(10))
        m, y = load(self.dir / "l")
        self.assertEqual(len(y), 240_000)
        self.assertEqual(m["global"]["openhamshack:stopped"], "time limit")

    def test_a_retune_is_a_new_capture_and_a_status_change_an_annotation(self):
        rec = sigmf.Recorder(self.dir / "r", FS, {}).start()
        b = np.zeros(1000, np.complex64)
        rec.push(b, (100.0, 200.0), 10.0, {"rxLock": "searching"})
        rec.push(b, (100.0, 200.0), 10.0 + 1000 / FS, {"rxLock": "locked"})
        rec.push(b, (150.0, 250.0), 10.0 + 2000 / FS, {"rxLock": "locked"})
        rec.close()
        rec.wait(10)
        m, _ = load(self.dir / "r")
        self.assertEqual([(c["core:sample_start"], c["core:frequency"]) for c in m["captures"]],
                         [(0, 200.0), (2000, 250.0)])
        self.assertNotIn("core:datetime", m["captures"][1])      # a retune is not a gap in time
        self.assertEqual([(a["core:sample_start"], a["core:sample_count"], a["core:label"]) for a in m["annotations"]],
                         [(0, 1000, "rxLock: searching"), (1000, 2000, "rxLock: locked")])

    def test_metadata_is_on_disk_from_the_start(self):
        # A crash mid-recording must still leave a file saying what the samples are.
        rec = sigmf.Recorder(self.dir / "m", FS, {"core:recorder": "test"}).start()
        try:
            m = json.loads(rec.meta_path.read_text())
            self.assertEqual(m["global"]["core:sample_rate"], FS)
            self.assertFalse(m["global"]["openhamshack:complete"])
        finally:
            rec.close()
            rec.wait(10)


class Kept(SimDevice):
    """The simulator, keeping every block it hands the engine."""

    def read(self, n):
        y = super().read(n)
        self.kept.append(y.copy())
        return y

    def open(self):
        self.kept = []
        super().open()


class EngineRecording(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def test_nb_records_exactly_what_the_device_delivered_with_the_facts(self):
        r = make_radio(self.dir, device=Kept, callsign="G4XYZ", mode="usb")
        toasts = r.subscribe("toast", 64)
        r.start()
        try:
            run_sim(r, 1.0)
            path = r.start_recording()
            self.assertTrue(r.state()["recording"])
            with self.assertRaises(ValueError):
                r.start_recording()
            run_sim(r, 2.0)
            self.assertEqual(r.stop_recording(), path)
            self.assertFalse(r.state()["recording"])
            wait_saved(r)
            saved = [t["text"] for t in toasts.drain() if "Recording saved" in t["text"]]
            rx_if, lo = r.rx_if, r.lnb_lo
        finally:
            r.stop()
        self.assertEqual(len(saved), 1)
        self.assertIn(".sigmf-meta", saved[0])
        self.assertTrue(path.name.startswith("openhamshack-nb-"))
        m, y = load(path)
        check_core(self, m, path)
        g = m["global"]
        self.assertGreater(len(y), 1.5 * FS)
        # The file is the device's own blocks, back to back, at ci16 resolution.
        # Every block start the file could begin at, the last one included:
        # on a busy machine the engine may read nothing more between the
        # recording's end and r.stop(), so the file ends on the device's
        # last block - and a search that stopped one block short picked
        # the wrong start and failed the whole comparison.
        dev = np.concatenate(r.dev.kept)
        k = int(np.argmin([np.abs(dev[i:i + 64] - y[:64]).max() for i in range(0, len(dev) - len(y) + 1, 90_000)]))
        start = k * 90_000
        np.testing.assert_allclose(dev[start:start + len(y)], y, atol=1.0 / sigmf.SCALE)
        # Where it was: the LNB's nominal downlink at DC, and the IF the SDR was tuned to.
        self.assertAlmostEqual(m["captures"][0]["core:frequency"], rx_if + lo, places=0)
        self.assertAlmostEqual(m["captures"][0]["openhamshack:device_hz"], rx_if, places=0)
        self.assertEqual(g["core:sample_rate"], FS)
        self.assertEqual(g["core:author"], "G4XYZ")
        self.assertRegex(g["core:recorder"], r"^OpenHamShack QO-100 NB \d+\.\d+\.\d+")
        self.assertTrue(g["openhamshack:os"])
        self.assertEqual(g["openhamshack:converter"]["rxOffset"], 9_750_000_000.0)
        self.assertEqual(g["openhamshack:gain"], {"mode": "slow_attack", "db": 40.0})
        self.assertEqual(g["openhamshack:receive"]["mode"], "usb")
        self.assertIn("rxCorr", g["openhamshack:beacon_lock"])
        self.assertEqual(g["openhamshack:device"]["kind"], "sim")
        self.assertIn("rxCorr", g["openhamshack:track"])
        self.assertEqual(g["openhamshack:dropped_samples"], 0)
        labels = {a["core:label"] for a in m["annotations"]}
        self.assertIn("keyed: False", labels)
        self.assertTrue(any(lab.startswith("rxLock: ") for lab in labels))

    def test_a_stalled_disk_never_stalls_receive(self):
        go = threading.Event()
        real = sigmf.Recorder._write_block

        def stuck(rec, x):
            go.wait(30)
            real(rec, x)

        r = make_radio(self.dir)
        r.start()
        try:
            with mock.patch.object(sigmf.Recorder, "_write_block", stuck):
                path = r.start_recording()
                before = r.rx_samples
                run_sim(r, 5.0, timeout=30)
                self.assertGreater(r.rx_samples - before, 4.5 * FS)     # receive went on
                time.sleep(0.25)                                         # a supervisor tick
                dropped = r.state()["recDropped"]
                self.assertGreater(dropped, 0)
                go.set()
                run_sim(r, 1.0)                 # the disk caught up: blocks are taken again
                r.stop_recording()
                wait_saved(r)
        finally:
            go.set()
            r.stop()
        m, _ = load(path)
        self.assertGreaterEqual(m["global"]["openhamshack:dropped_samples"], dropped)
        self.assertTrue(any("openhamshack:gap_samples" in c for c in m["captures"]))

    def test_a_recording_leaves_the_closing_list_only_once_its_toast_is_out(self):
        # Everything that waits for a recording to be saved waits for
        # rec_closing to empty, then reads the toast. Removed before the
        # toast, a supervisor preempted between the two (a loaded machine)
        # let the waiter find the list empty and nothing said yet.
        r = make_radio(self.dir)
        seen = []
        toast = r.toast

        def watched(text, level="info"):
            if "Recording saved" in text:
                seen.append(len(r.rec_closing))
            toast(text, level)
        r.toast = watched
        r.start()
        try:
            run_sim(r, 0.5)
            r.start_recording()
            run_sim(r, 1.0)
            r.stop_recording()
            wait_saved(r)
        finally:
            r.stop()
        self.assertEqual(seen, [1])
        self.assertEqual(r.rec_closing, [])

    def test_stopping_the_radio_finishes_the_recording(self):
        r = make_radio(self.dir)
        r.start()
        run_sim(r, 0.5)
        path = r.start_recording()
        run_sim(r, 1.0)
        r.stop()
        m, _ = load(path)
        self.assertTrue(m["global"]["openhamshack:complete"])
        self.assertEqual(m["global"]["openhamshack:stopped"], "the radio stopped")
        self.assertFalse(r.state()["recording"])

    def test_not_running_is_a_sentence(self):
        r = make_radio(self.dir)
        with self.assertRaisesRegex(ValueError, "Start the radio"):
            r.start_recording()

    def test_the_time_limit_setting(self):
        r = make_radio(self.dir, recLimitMin=0.02)        # 1.2 s
        r.start()
        try:
            run_sim(r, 0.5)
            path = r.start_recording()
            run_sim(r, 3.0, until=lambda: not r.state()["recording"] and not r.rec_closing)
            self.assertFalse(r.state()["recording"])
        finally:
            r.stop()
        m, y = load(path)
        self.assertEqual(len(y), int(0.02 * 60 * FS))
        self.assertEqual(m["global"]["openhamshack:stopped"], "time limit")

    def test_ham_records_its_band_and_converter(self):
        from ham_helpers import close, make_radio as ham_radio, pump
        r = ham_radio(vfo=144_300_000.0, mode="usb")
        r.start()
        try:
            pump(r, 0.5)
            path = r.start_recording()
            pump(r, 1.0)
            centre = r.centre
            r.stop()                         # finishes the recording
            m, y = load(path)
            check_core(self, m, path)
        finally:
            close(r)
        self.assertTrue(path.name.startswith("openhamshack-radio-"))
        self.assertIn("144.300MHz-USB", path.name)
        g = m["global"]
        self.assertRegex(g["core:recorder"], r"^OpenHamShack Radio ")
        self.assertEqual(g["core:author"], "GM4BRI")
        self.assertEqual(g["openhamshack:band"], "2m")
        self.assertIsNone(g["openhamshack:converter"])
        self.assertEqual(m["captures"][0]["core:frequency"], centre)
        self.assertGreater(len(y), 0)


class Paths(unittest.TestCase):
    def test_names_are_legal_on_windows_wherever_they_are_made(self):
        self.assertEqual(host.safe_filename('a<b>c:d"e/f\\g|h?i*j'), "a-b-c-d-e-f-g-h-i-j")
        self.assertEqual(host.safe_filename("name. "), "name")
        self.assertEqual(host.safe_filename("CON.sigmf-data"), "_CON.sigmf-data")
        self.assertEqual(host.safe_filename("com3"), "_com3")
        with tempfile.TemporaryDirectory() as d:
            base = sigmf.new_base(Path(d), "openhamshack-nb", 1_791_000_000.0, 10_489_750_000.0, "usb")
            for p in sigmf.paths(base):
                self.assertIsNone(re.search(r'[<>:"/\\|?*]', p.name), p.name)
            self.assertEqual(base.name, "openhamshack-nb-20261003-040000Z-10489.750MHz-USB")
            # A second in the same second does not overwrite the first.
            sigmf.paths(base)[0].write_bytes(b"")
            self.assertEqual(sigmf.new_base(Path(d), "openhamshack-nb", 1_791_000_000.0, 10_489_750_000.0, "usb").name,
                             base.name + "-2")

    def test_the_recordings_folder_is_in_the_data_folder_on_both(self):
        from ohsnb import config
        env = {k: v for k, v in os.environ.items() if k not in ("OHS_NB_DATA", "OHSNB_DATA")}
        env["APPDATA"] = "/x/AppData/Roaming"
        with mock.patch.dict(os.environ, env, clear=True):
            with system("windows"):
                self.assertEqual(host.recordings_dir(config.data_dir()),
                                 Path("/x/AppData/Roaming/openhamshack-nb/data/recordings"))
            with system("linux"):
                self.assertEqual(host.recordings_dir(config.data_dir()),
                                 Path.home() / ".local" / "share" / "openhamshack-nb" / "recordings")

    def test_either_file_names_the_recording(self):
        b = Path("/r/x")
        self.assertEqual(sigmf.paths(Path("/r/x.sigmf-meta")), sigmf.paths(b))
        self.assertEqual(sigmf.paths(Path("/r/x.sigmf-data")), (Path("/r/x.sigmf-data"), Path("/r/x.sigmf-meta")))

    def test_free_space_is_found_for_a_folder_not_yet_made(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertGreater(host.free_bytes(Path(d) / "not" / "yet"), 0)

    def test_the_cost_is_said_in_megabytes_a_minute(self):
        self.assertEqual(sigmf.cost_sentence(1_200_000),
                         "At 1.2 MS/s a recording takes about 4.8 MB a second, 288 MB a minute.")


if __name__ == "__main__":
    unittest.main()


class EncodedBlocks(unittest.TestCase):
    """Recorder.push takes blocks already in ci16 (NB's LEILA capture keeps
    its ring that way): the file is the one complex blocks would make."""

    def test_bytes_and_complex_blocks_make_the_same_file(self):
        rng = np.random.default_rng(4)
        blocks = [(0.3 * (rng.standard_normal(9000) + 1j * rng.standard_normal(9000))).astype(np.complex64)
                  for _ in range(3)]
        with tempfile.TemporaryDirectory() as tmp:
            out = []
            for kind in ("complex", "bytes"):
                rec = sigmf.Recorder(Path(tmp) / kind, 1_200_000.0, {}).start()
                for i, x in enumerate(blocks):
                    rec.push(x if kind == "complex" else sigmf.to_ci16(x)[0], (1e6, 2e6), 1000.0 + i * 9000 / 1.2e6)
                rec.close()
                self.assertTrue(rec.wait(5))
                out.append((rec.data_path.read_bytes(), json.loads(rec.meta_path.read_text())["global"]))
            self.assertEqual(out[0][0], out[1][0])
            self.assertEqual(out[0][1]["openhamshack:samples"], out[1][1]["openhamshack:samples"])
            self.assertEqual(out[1][1]["openhamshack:samples"], 27000)
