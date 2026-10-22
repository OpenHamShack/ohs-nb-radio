"""The receive device read ahead of the DSP (ohscore/rxprefetch.py): a DSP
thread the window has starved falls behind and catches up without the radio
losing a sample; a queue that overflows drops the oldest and says how much;
samples that never arrived from the radio are told apart from samples the
program dropped. The device here is a counter delivered as a Pluto's DMA
delivers (tools/rx_storm.py's model, at a low rate so the tests are quick):
at its rate, into four blocks of buffering, lost beyond that."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import threading
import time
import unittest

import numpy as np

from ohscore.rxprefetch import Prefetch

FS = 40_000.0
N = 3000                 # 75 ms blocks, as the engine reads at any rate


class DmaCounter:
    """Sample k has the value k, so a gap or a repeat is visible in the
    data. `stall(s)`: the link stops delivering for s seconds; what the
    four buffers cannot hold meanwhile is lost (`lost`)."""

    def __init__(self, buffers=4):
        self.cap = buffers * N
        self.t0 = None
        self.next = 0               # value of the next sample the radio will deliver
        self.lost = 0
        self.stall_s = 0.0
        self.fail_after = None
        self.reads = 0

    def stall(self, s):
        self.stall_s = s

    def read(self, n):
        if self.fail_after is not None and self.reads >= self.fail_after:
            raise OSError("Pluto receive failed: [Errno 32] Broken pipe")
        self.reads += 1
        if self.stall_s:
            s, self.stall_s = self.stall_s, 0.0
            time.sleep(s)
        now = time.monotonic()
        if self.t0 is None:
            self.t0 = now - n / FS
        produced = int((now - self.t0) * FS)
        if produced - self.next > self.cap:
            self.lost += produced - self.next - self.cap
            self.next = produced - self.cap
        due = self.t0 + (self.next + n) / FS
        if due > time.monotonic():
            time.sleep(due - time.monotonic())
        x = np.arange(self.next, self.next + n, dtype=np.float64).astype(np.complex64)
        self.next += n
        return x


def take(pf, seconds, stall_at=None, stall_s=0.0):
    """Read like the engine for `seconds`, stopping dead for `stall_s` once
    `stall_at` seconds in (a DSP thread with no share of the GIL); the
    blocks and the gap before each."""
    out = []
    t_end = time.monotonic() + seconds
    t_stall = time.monotonic() + stall_at if stall_at is not None else None
    while time.monotonic() < t_end:
        x = pf.read()
        if x is None:
            continue
        out.append((x, pf.gap))
        if t_stall is not None and time.monotonic() >= t_stall:
            t_stall = None
            time.sleep(stall_s)
    return out


class ReadAhead(unittest.TestCase):
    def setUp(self):
        self.pfs = []

    def tearDown(self):
        for pf in self.pfs:
            pf.stop()
            pf.thread.join(2)

    def prefetch(self, dev, **kw):
        kw.setdefault("window_s", 0.6)
        kw.setdefault("tolerance_s", 0.1)
        pf = Prefetch(dev, N, FS, **kw).start()
        self.pfs.append(pf)
        return pf

    def test_a_starved_dsp_thread_loses_nothing(self):
        # A second of no processing - a theme toggle's worth on ohs-dev -
        # against 300 ms of radio buffering. Read directly it lost 0.45 s.
        dev = DmaCounter()
        pf = self.prefetch(dev)
        got = take(pf, 2.5, stall_at=0.3, stall_s=1.0)
        self.assertEqual(dev.lost, 0)
        self.assertEqual(pf.lost, 0)
        values = np.concatenate([x for x, _ in got]).real
        np.testing.assert_array_equal(values, np.arange(len(values)))   # every sample, in order
        self.assertTrue(all(g == 0 for _, g in got))
        self.assertGreaterEqual(pf.max_behind, 10)                        # it did fall behind, and caught up

    def test_reading_directly_the_same_stall_loses_samples(self):
        # The model is a fair one: without the queue the stall is a loss.
        dev = DmaCounter()
        t_end = time.monotonic() + 2.0
        stalled = False
        while time.monotonic() < t_end:
            dev.read(N)
            if not stalled and time.monotonic() > t_end - 1.7:
                stalled = True
                time.sleep(1.0)
        self.assertGreater(dev.lost / FS, 0.5)

    def test_an_overflowing_queue_drops_the_oldest_and_says_how_much(self):
        dev = DmaCounter()
        pf = self.prefetch(dev, depth_s=0.5)
        got = take(pf, 2.5, stall_at=0.3, stall_s=1.2)
        self.assertEqual(dev.lost, 0)                   # the radio was drained throughout
        self.assertGreater(pf.queue_lost, 0)
        self.assertEqual(pf.stream_lost, 0)
        gaps = [(i, g) for i, (_, g) in enumerate(got) if g]
        self.assertEqual(len(gaps), 1)
        i, g = gaps[0]
        self.assertEqual(g, pf.queue_lost)
        # The block after the gap starts exactly that many samples on: the
        # oldest went, the newest were kept.
        prev, this = got[i - 1][0], got[i][0]
        self.assertEqual(int(this[0].real), int(prev[-1].real) + 1 + g)

    def test_samples_that_never_arrived_are_counted_as_the_streams(self):
        # The link stalls for 0.8 s: 0.5 s of it the radio could not hold.
        dev = DmaCounter()
        pf = self.prefetch(dev)
        t0 = time.monotonic()
        got = []
        stalled = False
        while time.monotonic() - t0 < 2.5:
            x = pf.read()
            if x is not None:
                got.append((x, pf.gap))
            if not stalled and len(got) == 6:
                stalled = True
                dev.stall(0.8)
        self.assertAlmostEqual(dev.lost / FS, 0.5, delta=0.05)
        self.assertEqual(pf.queue_lost, 0)
        self.assertAlmostEqual(pf.stream_lost / FS, dev.lost / FS, delta=0.06)
        self.assertEqual(sum(g for _, g in got), pf.stream_lost)

    def test_jitter_that_catches_up_is_not_a_loss(self):
        # Late deliveries the radio's buffers cover (a busy network that
        # then catches up) arrive in full: nothing is reported lost.
        dev = DmaCounter()
        pf = self.prefetch(dev)
        stalls = iter([0.15, 0.2, 0.1, 0.25])
        t0 = time.monotonic()
        next_stall = 0.3
        while time.monotonic() - t0 < 2.5:
            pf.read()
            if time.monotonic() - t0 > next_stall:
                s = next(stalls, None)
                if s is not None:
                    dev.stall(s)
                next_stall += 0.5
        self.assertEqual(dev.lost, 0)
        self.assertEqual(pf.lost, 0)

    def test_a_device_error_reaches_the_reader_after_the_blocks_before_it(self):
        dev = DmaCounter()
        dev.fail_after = 5
        pf = self.prefetch(dev)
        blocks = 0
        with self.assertRaises(OSError):
            for _ in range(100):
                if pf.read() is not None:
                    blocks += 1
        self.assertEqual(blocks, 5)
        pf.thread.join(2)
        self.assertFalse(pf.thread.is_alive())

    def test_each_block_is_stamped_by_the_radios_clock_not_its_arrival(self):
        # Blocks taken late from the queue keep their own times, one block
        # apart, so a recording sees no gap that is not there.
        dev = DmaCounter()
        pf = self.prefetch(dev)
        got = []
        t_end = time.monotonic() + 1.5
        stalled = False
        while time.monotonic() < t_end:
            x = pf.read()
            if x is not None:
                got.append(pf.utc)
            if not stalled and len(got) == 3:
                stalled = True
                time.sleep(0.8)
        steps = np.diff(got)
        np.testing.assert_allclose(steps, N / FS, atol=0.002)
        self.assertAlmostEqual(got[0], time.time() - 1.5, delta=0.3)


if __name__ == "__main__":
    unittest.main()
