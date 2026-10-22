"""The end of an over (ohscore/engine.py, "Two ways an over ends").

A normal end - the message all sent, PTT released - lets the device send
what it already holds before it is stopped, so the last CW element and the
last RTTY or PSK character reach the air; an emergency unkey - Escape, the
watchdog, a guard refusal - stops at once and drops the queue. Until the
engine drained, tx_stop emptied the queue on every over, and the "K" of
"GM4BRI K" came back as a "D".

On NB's simulator (its 150 ms fifo plus a block), OpenHamShack HAM's band
simulator with its PTT sequencer, and the Hermes-Lite 2 emulator over UDP.
Nothing here touches real hardware."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import shutil
import tempfile
import threading
import time
import unittest

import numpy as np

import ham_helpers
from helpers import make_radio, run_sim, wait_rx_lock
from ohscore.audio import NullAudio
from ohscore.devices.hl2sim import HL2Sim
from ohsradio.radio import Radio as HamRadio
from ohsradio.sequencer import Sequencer

CW_DIAL = 10_489_550_000.0      # NB's CW segment
DATA_DIAL = 10_489_575_000.0    # NB's narrow digimode segment


def watch(radio, log):
    """Record each tx_finish and tx_stop on the radio's device: when, how
    much it still held, and whether the engine still called it keyed."""
    dev = radio.dev
    finish, stop = dev.tx_finish, dev.tx_stop

    def tx_finish():
        log.append(("finish", time.monotonic(), dev.tx_queued(), radio.st["keyed"]))
        finish()

    def tx_stop():
        log.append(("stop", time.monotonic(), dev.tx_queued(), radio.st["keyed"]))
        stop()
    dev.tx_finish, dev.tx_stop = tx_finish, tx_stop


def events(log, kind):
    return [e for e in log if e[0] == kind]


def wait(cond, timeout=10.0, beat=None):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if beat is not None:
            beat.heartbeat()
        if cond():
            return True
        time.sleep(0.005)
    return cond()


class EchoKeepsTheLastCharacter(unittest.TestCase):
    """Our own over, round NB's simulated transponder and decoded: the
    last element or character is the one that was being cut off. Measured
    before the drain: CW "GM4BRI K" came back "GM4BRI D" (the K's last dah
    gone), RTTY with no idle tail lost its "K" altogether."""

    def echo(self, mode, text, dial, **msg):
        tmp = tempfile.mkdtemp()
        try:
            r = make_radio(tmp, simSeed=11, simRxErrorHz=1800.0, simUlErrorHz=0.0, txGain=-30.0, simRefGainDb=-20.0,
                           mode=mode, vfo=dial)
            ev = r.subscribe("events", 2000)
            r.start()
            try:
                if not r.state()["modes"][mode]["encode"]:
                    self.skipTest(f"{mode} not available: " + r.state()["modes"][mode]["missing"])
                self.assertTrue(wait_rx_lock(r))
                got = run_sim(r, 2.0, [ev])["events"]
                r.send(mode, text=text, **msg)
                got += run_sim(r, 40.0, [ev], until=lambda: not r.state()["keyed"])["events"]
                got += run_sim(r, 3.0, [ev])["events"]
            finally:
                r.stop()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        return "".join(e.get("text", "") for e in got if e.get("mode") == mode)

    def test_cw_last_element(self):
        # ohscore/modes/cw.py ends on the last element itself, no tail.
        heard = self.echo("cw", "TEST DE GM4BRI K", CW_DIAL)
        self.assertIn("GM4BRI K", heard)

    def test_rtty_last_character_with_no_idle_tail(self):
        # postamble 0: the encoder's two-bit minimum, the hardest case. The
        # default idle tail (0.1 s) is for the far decoder, not for this.
        heard = self.echo("rtty", "CQ DE GM4BRI PSE K", DATA_DIAL, postamble=0.0)
        self.assertIn("PSE K", heard)

    def test_psk31_last_character_with_no_idle_tail(self):
        heard = self.echo("psk31", "CQ DE GM4BRI PSE K", DATA_DIAL, postamble=0.0)
        self.assertIn("PSE K", heard)


class NbOverEnds(unittest.TestCase):
    """When RF stops, on NB's simulator."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.r = make_radio(self.tmp, mode="cw", vfo=CW_DIAL, cwWpm=20.0)
        self.r.start()
        self.addCleanup(self.r.stop)
        self.log = []
        watch(self.r, self.log)
        self.toasts = self.r.subscribe("toast", 64)

    def keyed(self):
        return self.r.state()["keyed"]

    def send_long(self):
        self.r.send("cw", text="PARIS " * 10)
        run_sim(self.r, 1.0)
        self.assertTrue(self.keyed())

    def test_a_normal_end_keeps_rf_on_until_the_queue_is_empty(self):
        self.r.send("cw", text="TEST K")
        run_sim(self.r, 20.0, until=lambda: not self.keyed() and events(self.log, "stop"))
        (_, t_fin, q_fin, keyed_fin), = events(self.log, "finish")
        (_, t_stop, q_stop, _), = events(self.log, "stop")
        self.assertGreater(q_fin, 0.1)       # the simulator held over 100 ms when the message ran out ...
        self.assertTrue(keyed_fin)           # ... still keyed while it went out ...
        self.assertEqual(q_stop, 0.0)        # ... and none of it was left to drop
        self.assertLess(t_stop - t_fin, self.r.DRAIN_MAX)
        self.assertEqual(self.r.dev.underruns, 0)     # the queue running dry was the end, not a fault

    def test_ptt_released_drains_too(self):
        self.r.ptt(True)
        run_sim(self.r, 0.5)
        self.r.ptt(False)
        self.assertTrue(self.keyed())        # RF is still on: the end is going out
        run_sim(self.r, 5.0, until=lambda: events(self.log, "stop"))
        (_, _, q_fin, _), = events(self.log, "finish")
        (_, _, q_stop, _), = events(self.log, "stop")
        self.assertGreater(q_fin, 0.1)
        self.assertEqual(q_stop, 0.0)

    def test_a_device_that_never_empties_is_stopped_at_the_bound(self):
        dev = self.r.dev
        finish = dev.tx_finish

        def stuck():
            finish()
            dev.tx_queued = lambda: 0.3      # it stops taking samples, and says so
        dev.tx_finish = stuck
        self.r.send("cw", text="E")
        with self.assertLogs(self.r.log, "WARNING") as logged:
            self.assertTrue(wait(lambda: events(self.log, "stop"), 5.0, self.r))
        t_fin = events(self.log, "finish")[0][1]
        t_stop = events(self.log, "stop")[0][1]
        self.assertAlmostEqual(t_stop - t_fin, 0.3 + self.r.DRAIN_SLACK, delta=0.1)
        self.assertIn("stopping it anyway", logged.output[0])

    def assert_dropped(self, t_from):
        """Stopped promptly with the queue still full: no drain."""
        self.assertTrue(wait(lambda: events(self.log, "stop"), 2.0))
        (_, t_stop, q_stop, _), = events(self.log, "stop")
        self.assertEqual(events(self.log, "finish"), [])
        self.assertGreater(q_stop, 0.05)
        self.assertLess(t_stop - t_from, 0.2)

    def test_halt_stops_at_once_and_drops_the_queue(self):
        self.send_long()
        t = time.monotonic()
        self.r.halt()
        self.assertFalse(self.keyed())
        self.assert_dropped(t)

    def test_halt_during_a_drain_ends_it_at_once(self):
        dev = self.r.dev
        finish = dev.tx_finish

        def stuck():
            finish()
            dev.tx_queued = lambda: 0.5
            threading.Timer(0.05, self.r.halt).start()      # Escape, 50 ms into the drain
        dev.tx_finish = stuck
        self.r.send("cw", text="E")
        self.assertTrue(wait(lambda: events(self.log, "stop"), 5.0, self.r))
        t_fin = events(self.log, "finish")[0][1]
        t_stop = events(self.log, "stop")[0][1]
        self.assertLess(t_stop - t_fin, 0.2)                # not the 0.75 s bound

    def test_the_watchdog_stops_at_once_and_drops_the_queue(self):
        self.r.set(authorise=True, watchdogSec=0.5)
        self.send_long()
        t = time.monotonic()
        self.r.heartbeat()
        # No heartbeat from here: the UI has hung.
        self.assertTrue(wait(lambda: events(self.log, "stop"), 3.0))
        (_, t_stop, q_stop, _), = events(self.log, "stop")
        self.assertEqual(events(self.log, "finish"), [])
        self.assertGreater(q_stop, 0.05)
        self.assertLess(t_stop - t, 0.5 + 0.3)
        self.assertTrue(any("watchdog" in x["text"] for x in self.toasts.drain()))

    def test_a_guard_refusal_stops_at_once_and_drops_the_queue(self):
        self.r.ptt(True)                                     # a CW carrier
        run_sim(self.r, 1.0)
        t = time.monotonic()
        self.r.set(vfo=10_489_750_000.0)                     # onto the middle beacon
        self.assertFalse(self.keyed())
        self.assert_dropped(t)
        self.assertTrue(any("beacon" in x["text"] for x in self.toasts.drain()))


class FakeLine:
    def __init__(self, log):
        self.log = log

    def set(self, on):
        self.log.append(("line", time.monotonic(), on, None))

    def close(self):
        pass


class HamSequencerWaitsForTheDrain(unittest.TestCase):
    """OpenHamShack HAM's PTT line drops seqDelayMs after the true end of RF:
    after the device's queue has gone out, not after the last block was
    written."""

    def setUp(self):
        self.r = ham_helpers.make_radio()
        self.addCleanup(ham_helpers.close, self.r)
        self.r.set(authorise=True, licenceClass="full")
        self.r.set(vfo=14_060_000.0, mode="cw")
        self.r.start()
        self.log = []
        self.r.seq = Sequencer(FakeLine(self.log), delay_ms=20)
        watch(self.r, self.log)

    def test_line_drops_after_the_queue_has_gone(self):
        self.r.send("cw", text="TEST K")
        self.assertTrue(wait(lambda: any(e[0] == "line" and e[2] is False for e in self.log), 30.0, self.r))
        kinds = [e[0] for e in self.log]
        self.assertEqual(kinds, ["line", "finish", "stop", "line"])
        _, t_fin, q_fin, keyed_fin = self.log[1]
        _, t_stop, q_stop, _ = self.log[2]
        t_off = self.log[3][1]
        self.assertGreater(q_fin, 0.1)
        self.assertTrue(keyed_fin)
        self.assertEqual(q_stop, 0.0)
        self.assertEqual(self.r.state()["seqState"], "rx")
        self.assertGreaterEqual(t_off - t_stop, 0.019)

    def test_halt_drops_the_line_without_draining(self):
        self.r.send("cw", text="PARIS " * 10)
        ham_helpers.pump(self.r, 2.0, until=lambda: self.r.dev.tx_queued() > 0.1)
        self.r.halt()
        self.assertTrue(wait(lambda: any(e[0] == "line" and e[2] is False for e in self.log), 2.0))
        self.assertEqual([e[0] for e in self.log], ["line", "stop", "line"])
        self.assertGreater(self.log[1][2], 0.05)                 # what the device held was dropped


class Hl2OverEnds(unittest.TestCase):
    """OpenHamShack HAM on the emulated Hermes-Lite 2: the end of an over leaves
    the host at full drive, and MOX stays up while the radio's own buffer
    sends it."""

    def setUp(self):
        self.sim = HL2Sim(tone_hz=None, watchdog_s=1.0).start()
        self.addCleanup(self.sim.stop)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cfg = {"device": "hl2", "hl2Address": self.sim.address, "hl2Rate": 48_000, "audioBackend": "null",
               "vfo": 14_060_000.0, "mode": "cw", "drive": 1.0, "cwWpm": 20.0, "callsign": "GM4BRI"}  # UK: Ofcom
        self.r = HamRadio(cfg, persist=False, data_dir=self.tmp.name, audio=NullAudio(realtime=True))
        self.r.set(authorise=True, licenceClass="full")
        self.addCleanup(self.r.stop)
        self.r.start()
        wait(lambda: self.r.state()["running"], 5.0, self.r)

    def test_last_cw_element_goes_out_at_full_drive(self):
        self.sim.clear_tx()
        self.r.send("cw", text="T")                     # one dah: 180 ms at 20 wpm
        self.assertTrue(wait(lambda: not self.r.state()["keyed"], 10.0, self.r))
        chunks = self.sim.tx_chunks()
        iq = np.concatenate([c for _, _, c in chunks])
        on = np.flatnonzero(np.abs(iq) > 0.05)
        self.assertAlmostEqual((on[-1] - on[0]) / 48_000, 0.180, delta=0.012)       # the whole dah
        real = [(t, step) for t, step, c in chunks if np.abs(c).max() > 0.05]
        self.assertEqual({step for _, step in real}, {15})                          # at full drive throughout
        # keyed falls when the driver sends MOX off; the emulator logs it when
        # that datagram arrives, a moment later on a loaded machine (the 0.1.6
        # release run read the list too soon and found it empty).
        self.assertTrue(wait(lambda: any(not up for _, up in self.sim.mox_events), 2.0, self.r))
        t_off = [t for t, up in self.sim.mox_events if not up][-1]
        self.assertGreaterEqual(t_off - real[-1][0], 0.8 * self.r.dev.tx_latency_ms / 1000)

    def test_halt_drops_mox_at_once(self):
        self.r.send("cw", text="PARIS " * 10)
        self.assertTrue(wait(lambda: self.sim.mox, 5.0, self.r))
        wait(lambda: False, 0.5, self.r)
        t = time.monotonic()
        self.r.halt()
        self.assertTrue(wait(lambda: not self.sim.mox, 1.0))
        t_off = [t for t, up in self.sim.mox_events if not up][-1]
        self.assertLess(t_off - t, 0.1)


if __name__ == "__main__":
    unittest.main()
