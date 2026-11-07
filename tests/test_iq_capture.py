"""tools/iq-capture: the scheduled HF IQ capture for Naughtcade's contest
recordings (Brian, 07/11/2026).

decimate.py runs on synthetic ci16 SigMF recordings with tones at known
offsets: what is in the segment comes out at the right frequency and
level, what is outside it is suppressed, and nothing about the output
depends on where the blocks fall.

ohs-iq-capture (the box-side bash script) runs end to end against the fake
controller on a local socket (tests/fake_controller.py), never the box,
with decimate.py run here by python3 in place of Radio's image under
podman: it must skip the weather-satellite passes in its window, wait for
a held receiver and give up cleanly, roll over parts and cut each down,
and put the receiver back exactly - after success, after an error and
after SIGTERM.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import datetime as dt
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

import numpy as np

from fake_controller import TOKEN, FakeRadio, token_file

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "tools" / "iq-capture"
DECIMATE = TOOL / "decimate.py"
SCRIPT = TOOL / "ohs-iq-capture"

FS = 1_200_000
SSB = (3_600_000, 3_775_000)
CW = (3_510_000, 3_570_000)


def tones(fs, centre, freqs_amps, n, start=0, noise=0.0):
    """Complex samples n of them from sample `start` on: a tone of each
    (absolute Hz, amplitude) as heard by a receiver centred on `centre`."""
    t = (np.arange(n) + start) / fs
    x = np.zeros(n, np.complex128)
    for f, a in freqs_amps:
        x += a * np.exp(2j * np.pi * (f - centre) * t)
    if noise:
        rng = np.random.default_rng(3)
        x += rng.normal(0, noise, n) + 1j * rng.normal(0, noise, n)
    return x


def ci16(x) -> bytes:
    out = np.empty(2 * len(x), "<i2")
    out[0::2], out[1::2] = np.rint(x.real), np.rint(x.imag)
    return out.tobytes()


def write_recording(folder: Path, rid: str, data: bytes, captures, fs=FS) -> tuple[Path, Path]:
    (folder / f"{rid}.sigmf-data").write_bytes(data)
    meta = folder / f"{rid}.sigmf-meta"
    meta.write_text(json.dumps({"global": {"core:datatype": "ci16_le", "core:sample_rate": fs},
                                "captures": captures}))
    return meta, folder / f"{rid}.sigmf-data"


def read_ci16(path: Path) -> np.ndarray:
    raw = np.fromfile(path, "<i2").astype(np.float64)
    return raw[0::2] + 1j * raw[1::2]


def level(z, fs, f):
    """The amplitude of a tone at baseband frequency f in z (Hann-windowed
    DFT at exactly f, so the bin grid does not matter)."""
    w = np.hanning(len(z))
    k = np.arange(len(z))
    return abs(np.sum(z * w * np.exp(-2j * np.pi * f * k / fs))) / w.sum()


def alias(f, fs_out):
    return (f + fs_out / 2) % fs_out - fs_out / 2


class Decimate(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.out = self.tmp / "out"

    def cut(self, meta, data, seg, *extra, part=1):
        res = subprocess.run([sys.executable, str(DECIMATE), "--meta", str(meta), "--data", str(data),
                              "--lo", str(seg[0]), "--hi", str(seg[1]), "--out-dir", str(self.out),
                              "--name", "test", "--part", str(part), "--antenna", "Antenna C, Loop Antenna",
                              *extra], capture_output=True, text=True, timeout=300)
        self.assertEqual(res.returncode, 0, res.stderr)
        base = self.out / f"test-p{part:02d}"
        meta_out = json.loads(base.with_suffix(".sigmf-meta").read_text())
        small = json.loads((self.out / f"test-p{part:02d}.json").read_text())
        return read_ci16(base.with_suffix(".sigmf-data")), meta_out, small

    def test_in_segment_tones_land_right_and_the_rest_are_suppressed(self):
        # The receiver's centre is 100 kHz off the segment's (Radio's LO
        # offset): the cut-down must mix from the recording's own centre.
        rx = 3_787_500
        inside = [(3_605_000, 1000.0), (3_690_000, 3000.0), (3_770_000, 2000.0)]
        # ten times the loudest in-segment tone, the sum still inside ci16
        outside = [(3_500_000, 6000.0), (3_900_000, 6000.0), (4_200_000, 6000.0), (3_395_000, 6000.0)]
        n = FS // 2
        meta, data = write_recording(self.tmp, "rec", ci16(tones(FS, rx, inside + outside, n)),
                                     [{"core:sample_start": 0, "core:frequency": rx,
                                       "core:datetime": "2026-11-11T19:55:01.000000Z"}])
        z, m, small = self.cut(meta, data, SSB, "--scale", "1")
        centre = sum(SSB) / 2
        # 1.15 x 175 kHz is 201.25 kHz, so 5 (240 kS/s), not 6 (200 kS/s).
        self.assertEqual(m["global"]["openhamshack:decimation"], 5)
        fs_out = FS / 5
        self.assertEqual(m["global"]["core:sample_rate"], fs_out)
        self.assertEqual(len(z), n // 5)
        z = z[400:-400]                       # clear of the filter's edges at the ends
        for f, a in inside:
            got = level(z, fs_out, f - centre)
            self.assertAlmostEqual(20 * np.log10(got / a), 0.0, delta=0.05, msg=f"{f} Hz")
            # and it is there, not beside it: the strongest bin within 1 kHz
            spec = np.abs(np.fft.fft(z * np.hanning(len(z))))
            freqs = np.fft.fftfreq(len(z), 1 / fs_out)
            near = np.abs(freqs - (f - centre)) < 1000
            self.assertLess(abs(freqs[near][np.argmax(spec[near])] - (f - centre)), fs_out / len(z) + 1)
        for f, a in outside:
            got = level(z, fs_out, alias(f - centre, fs_out))
            self.assertLess(20 * np.log10(max(got, 1e-9) / a), -50, f"{f} Hz is not suppressed")
        # the metadata Naughtcade asked for
        self.assertEqual(small["centreHz"], centre)
        self.assertEqual(small["sampleRate"], fs_out)
        self.assertEqual(small["startUtc"], "2026-11-11T19:55:01.000000Z")
        self.assertEqual((small["receiver"], small["antenna"]), ("RSPdx", "Antenna C, Loop Antenna"))
        self.assertIn("ci16_le", small["format"])
        self.assertEqual(m["captures"][0]["core:frequency"], centre)
        self.assertEqual(m["captures"][0]["openhamshack:source_frequency"], rx)
        self.assertEqual(m["global"]["openhamshack:segment"], {"lowHz": SSB[0], "highHz": SSB[1]})
        self.assertEqual(oct(os.stat(self.out / "test-p01.sigmf-data").st_mode & 0o777), "0o600")
        self.assertFalse(list(self.out.glob("*.partial")))

    def test_cw_segment_decimates_by_17(self):
        rx = 3_540_000 - 40_000
        n = FS // 4
        meta, data = write_recording(self.tmp, "cw", ci16(tones(FS, rx, [(3_525_000, 500.0), (3_600_000, 8000.0)], n)),
                                     [{"core:sample_start": 0, "core:frequency": rx}])
        z, m, _ = self.cut(meta, data, CW, "--scale", "1")
        self.assertEqual(m["global"]["openhamshack:decimation"], 17)
        fs_out = FS / 17
        z = z[200:-200]
        self.assertAlmostEqual(level(z, fs_out, 3_525_000 - 3_540_000), 500.0, delta=500 * 0.006)
        self.assertLess(level(z, fs_out, alias(3_600_000 - 3_540_000, fs_out)), 8000 * 10 ** (-50 / 20))

    def test_the_output_does_not_depend_on_where_blocks_fall(self):
        # Phase continuity: blocks of 5 * 1009 input samples put hundreds of
        # block boundaries in the file; the result must be the one-block
        # result, and a single tone's phase must advance evenly throughout.
        rx = 3_700_000
        n = 300_000
        meta, data = write_recording(self.tmp, "ph", ci16(tones(FS, rx, [(3_652_345, 5000.0)], n)),
                                     [{"core:sample_start": 0, "core:frequency": rx}])
        small_blocks, _, _ = self.cut(meta, data, SSB, "--scale", "4", "--block", str(5 * 1009), part=1)
        one_block, _, _ = self.cut(meta, data, SSB, "--scale", "4", "--block", str(n * 2), part=2)
        self.assertEqual(len(small_blocks), len(one_block))
        self.assertLessEqual(np.max(np.abs(small_blocks - one_block)), 1.0)    # at most a rounding apart
        z = small_blocks[300:-300]
        step = np.angle(z[1:] * np.conj(z[:-1]))
        want = 2 * np.pi * (3_652_345 - sum(SSB) / 2) / (FS / 5)
        self.assertLess(np.max(np.abs(step - want)), 1e-3)

    def test_each_capture_is_mixed_from_its_own_centre(self):
        # Radio starts a new capture at a retune or a gap; the tone, fixed
        # on the air, must stay put in the output across the change.
        n1, n2 = 120_000, 120_000
        f1, f2 = 3_700_000, 3_650_000
        tone = [(3_620_000, 3000.0)]
        x = np.concatenate((tones(FS, f1, tone, n1), tones(FS, f2, tone, n2, start=n1)))
        meta, data = write_recording(self.tmp, "re", ci16(x), [
            {"core:sample_start": 0, "core:frequency": f1, "core:datetime": "2026-11-11T19:55:00.000000Z"},
            {"core:sample_start": n1, "core:frequency": f2}])
        z, m, _ = self.cut(meta, data, SSB, "--scale", "1")
        fs_out = FS / 5
        want = 3_620_000 - sum(SSB) / 2
        first, second = z[300:n1 // 5 - 300], z[n1 // 5 + 300:-300]
        for half in (first, second):
            self.assertAlmostEqual(level(half, fs_out, want), 3000.0, delta=30)
        self.assertEqual([c["core:sample_start"] for c in m["captures"]], [0, n1 // 5])

    def test_without_a_scale_the_peak_is_near_full_scale_and_never_clips(self):
        rx = 3_700_000
        meta, data = write_recording(self.tmp, "lv", ci16(tones(FS, rx, [(3_650_000, 20.0)], 120_000, noise=3.0)),
                                     [{"core:sample_start": 0, "core:frequency": rx}])
        z, m, small = self.cut(meta, data, SSB)
        peak = max(np.max(np.abs(z.real)), np.max(np.abs(z.imag)))
        self.assertGreater(peak, 31000)
        self.assertLessEqual(peak, 32767)
        self.assertEqual(m["global"]["openhamshack:clipped"], 0)
        self.assertGreater(small["gain"], 100)            # a quiet segment is lifted, and says by how much

    def test_a_segment_outside_the_recording_is_refused(self):
        meta, data = write_recording(self.tmp, "far", ci16(tones(FS, 7_100_000, [], 1000)),
                                     [{"core:sample_start": 0, "core:frequency": 7_100_000}])
        res = subprocess.run([sys.executable, str(DECIMATE), "--meta", str(meta), "--data", str(data),
                              "--lo", str(SSB[0]), "--hi", str(SSB[1]), "--out-dir", str(self.out),
                              "--name", "x"], capture_output=True, text=True)
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("not inside the recording", res.stderr)


PODMAN = r"""#!/bin/bash
echo "podman $*" >> "$FAKE_LOG"
if [ "$1" = inspect ]; then echo localhost/dock360-shack-radio:9.9; exit 0; fi
shift                                  # run
maps=()
while [ $# -gt 0 ]; do
    case $1 in
        --rm) ;;
        -v) maps+=("$2"); shift ;;
        --*) shift ;;
        *) break ;;
    esac
    shift
done
shift                                  # the image
args=()
for a in "$@"; do
    for m in "${maps[@]}"; do
        IFS=: read -r host inside _ <<<"$m"
        a=${a/#$inside\//$host/}
        [ "$a" = "$inside" ] && a=$host
    done
    args+=("$a")
done
exec nice "${args[@]}"
"""


def utc_in(seconds: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")


class Capture(unittest.TestCase):
    """End times are whole seconds a few seconds ahead: with less, a slow
    start can begin after the end and (rightly) do nothing."""
    NAME = "rsgb-test"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.recdir = self.tmp / "recordings"
        self.recdir.mkdir()
        self.fake = FakeRadio(self.recdir).start()
        self.addCleanup(self.fake.stop)
        self.fake.st["soapyAntennaLabels"] = '{"Antenna C": "Loop Antenna"}'
        # What a recording holds: a tone at 3650 kHz heard on whatever
        # centre the fake's device has (the dial plus 100 kHz).
        self.fake.iq = lambda rate, centre: ci16(tones(rate, centre, [(3_650_000, 2000.0)], int(rate) // 20, noise=5))
        self.out_root = self.tmp / "ohs-iq"
        self.logdir = self.tmp / "log"
        self.env = {**os.environ, "OHS_API_ROOT": self.fake.root, "OHS_TOKEN_FILE": str(token_file(self.tmp)),
                    "OHS_IQ_RECDIR": str(self.recdir), "OHS_IQ_OUT_ROOT": str(self.out_root),
                    "OHS_IQ_LOG_DIR": str(self.logdir), "OHS_IQ_TOOL_DIR": str(TOOL), "OHS_IQ_RUNNER": "local",
                    "OHS_IQ_RETRY_S": "0.3", "OHS_IQ_POLL_S": "1", "OHS_IQ_SETTLE_S": "0",
                    "TMPDIR": str(self.tmp)}
        self.original = dict(self.fake.st)

    @property
    def out(self) -> Path:
        return self.out_root / self.NAME

    def log(self) -> str:
        return (self.logdir / f"{self.NAME}.log").read_text()

    def run_it(self, end_in: float, *, seg=SSB, timeout=60, **env):
        res = subprocess.run(["bash", str(SCRIPT), self.NAME, str(seg[0]), str(seg[1]), utc_in(end_in)],
                             env={**self.env, **env}, capture_output=True, text=True, timeout=timeout)
        self.assertNotIn(TOKEN, res.stdout + res.stderr, "the token was printed")
        if (self.logdir / f"{self.NAME}.log").exists():
            self.assertNotIn(TOKEN, self.log(), "the token was logged")
        return res

    def status(self) -> dict:
        return json.loads((self.out / "capture.json").read_text())

    def sets(self) -> list[dict]:
        return [b["changes"] for m, p, b in self.fake.calls if p == "set"]

    def assertRestored(self):
        self.assertEqual(self.fake.st, self.original)

    def test_records_rolls_over_cuts_each_part_down_and_puts_everything_back(self):
        self.fake.iq_max_s = 1.5                 # Radio's iqMaxSeconds, shrunk
        res = self.run_it(5)
        self.assertEqual(res.returncode, 0, res.stderr)
        # Taken as asked: Antenna C, USB, the dial on the centre - and the
        # rate left alone, so the radio is never stopped or restarted (the
        # RSP runs at 2.4 MS/s whatever sampleRate says).
        self.assertIn({"soapyAntenna": "Antenna C", "mode": "usb", "vfo": 3687500}, self.sets())
        self.assertFalse(any("sampleRate" in c for c in self.sets()), self.sets())
        self.assertEqual([x for x in self.fake.paths("POST") if x in ("start", "stop")], [])
        self.assertRestored()
        st = self.status()
        self.assertEqual((st["status"], st["restored"]), ("done", True))
        parts = st["parts"]
        self.assertGreaterEqual(len(parts), 2, self.log())
        self.assertTrue(all(p["ok"] for p in parts))
        self.assertIn("ended by Radio (the time limit)", self.log())
        # Each part cut down, raw part deleted from Radio's recordings.
        self.assertEqual(list(self.recdir.iterdir()), [])
        for p in parts:
            base = self.out / f"{self.NAME}-p{p['part']:02d}"
            for suffix in (".sigmf-data", ".sigmf-meta", ".json"):
                f = Path(str(base) + suffix)
                self.assertTrue(f.exists(), f)
                self.assertEqual(f.stat().st_mode & 0o777, 0o600, f)
        self.assertEqual(self.out.stat().st_mode & 0o777, 0o700)
        small = json.loads((self.out / f"{self.NAME}-p01.json").read_text())
        self.assertEqual(small["antenna"], "Antenna C, Loop Antenna")
        self.assertEqual((small["centreHz"], small["sampleRate"]), (3687500, 2_400_000 / 11))
        # Mixed from the recording's centre (the dial plus 100 kHz), not the dial.
        z = read_ci16(self.out / f"{self.NAME}-p01.sigmf-data")[200:-200]
        self.assertAlmostEqual(level(z, 2_400_000 / 11, 3_650_000 - 3_687_500) / small["gain"], 2000, delta=20)

    def test_on_the_box_the_cut_down_runs_in_radios_image_under_podman(self):
        # Stand-ins for runuser and podman on PATH: podman records how it
        # was asked and runs the command as the container would, with the
        # mounts mapped back to their host folders.
        try:
            uid = int(subprocess.run(["id", "-u", "dock360"], capture_output=True, text=True, check=True).stdout)
        except (subprocess.CalledProcessError, ValueError):
            self.skipTest("no dock360 account on this host")
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "runuser").write_text('#!/bin/sh\necho "runuser $*" >> "$FAKE_LOG"\nshift 3\nexec "$@"\n')
        (bin_ / "podman").write_text(PODMAN)
        for f in bin_.iterdir():
            f.chmod(0o755)
        calls = self.tmp / "podman.log"
        res = self.run_it(4, OHS_IQ_RUNNER="podman", PATH=f"{bin_}:{os.environ['PATH']}", FAKE_LOG=str(calls))
        self.assertEqual(res.returncode, 0, res.stderr + self.log())
        log = calls.read_text()
        self.assertIn(f"runuser -u dock360 -- env XDG_RUNTIME_DIR=/run/user/{uid} ", log)
        self.assertIn("podman inspect --format {{.ImageName}} dock360-shack-radio", log)
        run = next(ln for ln in log.splitlines() if ln.startswith("podman run"))
        for want in ("--rm", "--network none", "--user 0:0", "--entrypoint nice", "--memory 1g", "--cpus 1",
                     f"-v {self.recdir}:/rec:ro", f"-v {self.out}:/out", f"-v {TOOL}:/tool:ro",
                     "localhost/dock360-shack-radio:9.9 -n 19 python3 /tool/decimate.py --meta /rec/"):
            self.assertIn(want, run)
        self.assertTrue((self.out / f"{self.NAME}-p01.sigmf-data").exists())
        self.assertEqual(list(self.recdir.iterdir()), [])

    def test_overlapping_weather_satellite_passes_are_skipped_first(self):
        def p(pid, aos, los, plan="record"):
            return {"id": pid, "aos": utc_in(aos), "los": utc_in(los), "plan": plan}
        self.fake.passes = [p("in-window", 1, 600), p("in-the-sky-now", -300, 300, "recording"),
                            p("too-low", 1, 600, "skip-low"), p("after-the-end", 3600, 4200),
                            p("before-now", -900, -300, "done")]
        res = self.run_it(4)
        self.assertEqual(res.returncode, 0, res.stderr)
        deleted = [x for x in self.fake.paths("DELETE") if x.startswith("wxsat/")]
        self.assertEqual(sorted(deleted), ["wxsat/passes/in-the-sky-now/record", "wxsat/passes/in-window/record"])
        # before the receiver was touched
        first_set = next(i for i, c in enumerate(self.fake.calls) if c[1] == "set")
        last_skip = max(i for i, c in enumerate(self.fake.calls) if c[1].startswith("wxsat/passes/"))
        self.assertLess(last_skip, first_set)

    def test_a_held_receiver_is_waited_for(self):
        self.fake._hold("dab", 222064000, "ds_dab1")
        self.fake.release_at = time.monotonic() + 1.0          # the DAB station ends a second later
        self.original = {**self.fake.st, **self.fake.prior}     # the operator's, not DAB's
        res = self.run_it(4)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("try 1 of 20: the receiver is held", self.log())
        self.assertIn("recordings/start", self.fake.paths("POST"))
        self.assertRestored()

    def test_parts_end_on_their_own_timer_before_radios_limit(self):
        # At 2.4 MS/s Radio's 35-minute part is about 20 GB; ours end after
        # PART_S so at most two raw parts sit in the 30 GB recordings.
        self.fake.iq_max_s = None
        res = self.run_it(5, OHS_IQ_PART_S="1")
        self.assertEqual(res.returncode, 0, res.stderr + self.log())
        self.assertIn("stopped at its 1 s", self.log())
        self.assertGreaterEqual(len(self.status()["parts"]), 2, self.log())
        self.assertRestored()

    def test_a_refused_tune_is_waited_for_like_a_held_receiver(self):
        self.fake.st["sampleRate"] = 1200000
        self.original = dict(self.fake.st)
        self.fake.fail["POST set"] = (409, "receiver_busy")
        threading.Timer(0.8, self.fake.fail.clear).start()
        res = self.run_it(4)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("tuning was refused: receiver_busy", self.log())
        self.assertIn("recordings/start", self.fake.paths("POST"))
        self.assertRestored()

    def test_giving_up_changes_nothing(self):
        self.fake._hold("adsb", 1090000000, "adsb")
        before = dict(self.fake.st)
        res = self.run_it(30, OHS_IQ_HELD_TRIES="3", OHS_IQ_RETRY_S="0.1")
        self.assertEqual(res.returncode, 3, res.stderr)
        self.assertIn("try 3 of 3", self.log())
        self.assertIn("gave up waiting for the receiver", self.log())
        self.assertNotIn("set", self.fake.paths("POST"))
        self.assertEqual(self.fake.st, before)
        self.assertEqual(self.status()["status"], "gave-up")

    def test_an_error_still_puts_everything_back(self):
        # Recording refused all evening (the disk full): nothing recorded,
        # the receiver back as it was, and a failed run.
        self.fake.fail["recordings/start"] = (507, "low_disk")
        res = self.run_it(3)
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("could not start part 1: 507 low_disk", self.log())
        self.assertRestored()
        self.assertEqual((self.status()["status"], self.status()["restored"]), ("failed", True))

    def test_a_refused_start_is_tried_again(self):
        # A radio stopped before the capture is started for it, and a
        # refusal (the RSP still being released, or 07/11/2026's server bug
        # that left the radio stopped) is tried again, each logged. It is
        # stopped again afterwards, as it was.
        self.fake.running = False
        self.fake.iq_max_s = 1.5
        self.fake.fail_times["POST start"] = [501, "unsupported", 2]
        res = self.run_it(8)
        self.assertEqual(res.returncode, 0, res.stderr + self.log())
        self.assertEqual(self.log().count("start: refused (501 unsupported"), 2)
        self.assertIn("recordings/start", self.fake.paths("POST"))
        self.assertRestored()
        self.assertFalse(self.fake.running)

    def test_a_radio_left_stopped_is_started_and_if_it_cannot_be_said_loudly(self):
        # The radio was running; something stops it mid-capture and it will
        # not start again. Restore's last step tries, and the log and status
        # say plainly that it is stopped rather than leaving it quietly so.
        def stop_it():
            self.fake.running = False
            self.fake.fail["POST start"] = (503, "busy")
        threading.Timer(1.0, stop_it).start()
        res = self.run_it(3)
        self.assertIn("START THE RADIO: it is stopped", self.log())
        self.assertFalse(self.status()["restored"])

    def test_a_failed_cut_down_keeps_the_raw_part(self):
        broken = self.tmp / "broken-tool"
        broken.mkdir()
        (broken / "decimate.py").write_text("import sys\nsys.exit('no numpy here')\n")
        res = self.run_it(4, OHS_IQ_TOOL_DIR=str(broken))
        self.assertEqual(res.returncode, 1, res.stderr)
        self.assertIn("cut-down FAILED", self.log())
        self.assertEqual(len(list(self.recdir.glob("*.sigmf-data"))), 1)     # kept for doing by hand
        self.assertNotIn("recordings/delete", self.fake.paths("POST"))
        self.assertRestored()

    def test_sigterm_mid_part_stops_keeps_and_puts_everything_back(self):
        p = subprocess.Popen(["bash", str(SCRIPT), self.NAME, str(SSB[0]), str(SSB[1]), utc_in(60)],
                             env=self.env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        deadline = time.monotonic() + 30
        while "recordings/start" not in self.fake.paths("POST") and time.monotonic() < deadline:
            time.sleep(0.1)
        self.assertIn("recordings/start", self.fake.paths("POST"))
        p.send_signal(signal.SIGTERM)                 # what systemd's stop does
        out, err = p.communicate(timeout=30)
        self.assertEqual(p.returncode, 130, err)
        self.assertRestored()
        self.assertIsNone(self.fake.recording)
        self.assertEqual(len(list(self.recdir.glob("*.sigmf-data"))), 1, "the part is kept, whole")
        self.assertEqual(self.status()["status"], "interrupted")
        self.assertIn("left in Radio's recordings", self.log())

    def test_started_after_the_end_does_nothing(self):
        res = self.run_it(-60)
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("started after the end time", self.log())
        self.assertEqual(self.fake.calls, [])

    def test_bad_arguments_change_nothing(self):
        for args in (["x y", "3600000", "3775000", utc_in(60)], [self.NAME, "3775000", "3600000", utc_in(60)],
                     [self.NAME, "3600000", "3775000", "tomorrow-ish"], [self.NAME, "3600000"]):
            res = subprocess.run(["bash", str(SCRIPT), *args], env=self.env, capture_output=True, text=True)
            self.assertEqual(res.returncode, 2, args)
        self.assertEqual(self.fake.calls, [])


class Fetch(unittest.TestCase):
    """fetch.sh with stand-ins for ssh (runs the command here), sudo and
    systemctl, and the box's folders moved to scratch ones."""

    NAME = "rsgb-test"

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.home = self.tmp / "home"
        (self.home / ".config" / "openhamshack").mkdir(parents=True)
        (self.home / ".config" / "openhamshack" / "box-update.conf").write_text("BOX_HOST=fakebox\n")
        self.box = self.tmp / "box"
        self.src = self.box / "ohs-iq" / self.NAME
        self.src.mkdir(parents=True)
        (self.box / "log").mkdir()
        (self.box / "log" / f"{self.NAME}.log").write_text("the box's log\n")
        self.files = {f"{self.NAME}-p01.sigmf-data": os.urandom(300_000), f"{self.NAME}-p01.sigmf-meta": b"{}",
                      f"{self.NAME}-p01.json": b"{}", "capture.json": b'{"status": "done", "parts": [{}]}'}
        for n, b in self.files.items():
            (self.src / n).write_bytes(b)
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        self.active = self.tmp / "active"           # present: the capture is still running
        (bin_ / "ssh").write_text('#!/bin/bash\nwhile [[ $1 == -* ]]; do [ "$1" = -o ] && shift; shift; done\n'
                                  'shift\nexec bash -c "$*"\n')
        (bin_ / "sudo").write_text('#!/bin/sh\nexec "$@"\n')
        (bin_ / "systemctl").write_text(f'#!/bin/sh\nif [ -e {self.active} ]; then echo active; else echo inactive; exit 3; fi\n')
        for f in bin_.iterdir():
            f.chmod(0o755)
        self.env = {**os.environ, "HOME": str(self.home), "PATH": f"{bin_}:{os.environ['PATH']}",
                    "OHS_IQ_BOX_ROOT": str(self.box / "ohs-iq"), "OHS_IQ_BOX_LOG_DIR": str(self.box / "log"),
                    "OHS_IQ_FETCH_WAIT_S": "0.2", "OHS_IQ_FETCH_TRIES": "3"}
        self.dest = self.home / "naughtcade-private" / "iq" / self.NAME

    def fetch(self, **env):
        return subprocess.run(["bash", str(TOOL / "fetch.sh"), self.NAME], env={**self.env, **env},
                              capture_output=True, text=True, timeout=60)

    def test_copies_checks_and_then_removes_the_box_copy(self):
        res = self.fetch()
        self.assertEqual(res.returncode, 0, res.stdout + res.stderr)
        for n, b in self.files.items():
            self.assertEqual((self.dest / n).read_bytes(), b)
            self.assertEqual((self.dest / n).stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.dest / "capture.log").read_text(), "the box's log\n")
        for d in (self.dest, self.dest.parent, self.dest.parent.parent):
            self.assertEqual(d.stat().st_mode & 0o777, 0o700, d)
        self.assertFalse(self.src.exists())
        self.assertIn("copied 4 file(s)", res.stdout)

    def test_a_capture_still_running_is_waited_for_then_left_alone(self):
        self.active.touch()
        res = self.fetch()
        self.assertEqual(res.returncode, 1)
        self.assertIn("not finished yet (active", res.stdout)
        self.assertTrue((self.src / "capture.json").exists())

    def test_a_short_copy_keeps_the_box_copy(self):
        # cat that loses the end of the data file, as a dropped connection would
        real_cat = shutil.which("cat")
        cat = self.tmp / "bin" / "cat"
        cat.write_text(f'#!/bin/bash\nif [[ "$1" == *sigmf-data ]]; then head -c 1000 "$1"; else exec {real_cat} "$@"; fi\n')
        cat.chmod(0o755)
        res = self.fetch()
        self.assertEqual(res.returncode, 1)
        self.assertIn("copied wrong", res.stdout)
        self.assertTrue(self.src.exists())
        self.assertEqual(len(list(self.src.iterdir())), 4)


if __name__ == "__main__":
    unittest.main()
