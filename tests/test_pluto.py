"""The Pluto device's sample-rate set-up and its software rate change, on a
fake AD9361 IIO context (no radio, nothing transmitted).

The fake behaves like the driver where it matters: below 2.083 MS/s the
rate is refused unless the x4 FIR is loaded and enabled, and a firmware
that refuses FIR loads answers EINVAL to filter_fir_config - as a Nano
PlutoSDR on Tezuka tezuka-v0.3.21 does."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import errno
import unittest
from unittest import mock

import numpy as np

from ohscore.devices import pluto
from ohscore.devices.base import DeviceError
from tests.test_multirate import level_db, tone, worst_spur_db


class Attr:
    def __init__(self, owner, name, value=""):
        self.owner, self.name, self._v = owner, name, value

    @property
    def value(self):
        return self._v

    @value.setter
    def value(self, v):
        self.owner.radio.check(self.name, str(v))
        self._v = str(v)


class Node:
    """A device or channel: attrs by name, channels by (name, output)."""

    def __init__(self, radio, names=()):
        self.radio = radio
        self.attrs = {n: Attr(self, n) for n in names}
        self.chans = {}
        self.enabled = False

    def find_channel(self, name, output=False):
        return self.chans.get((name, output))

    def set_kernel_buffers_count(self, n):
        pass


class FakeRadio:
    def __init__(self, fir_ok=True, no_fir_rate_ok=True):
        self.fir_ok, self.no_fir_rate_ok = fir_ok, no_fir_rate_ok
        self.fir_loaded = self.fir_en = False
        self.phy = Node(self, ["filter_fir_config", "in_out_voltage_filter_fir_en", "xo_correction"])
        self.phy._device = None
        self.rx_ch = Node(self, ["sampling_frequency", "rf_bandwidth", "gain_control_mode", "hardwaregain"])
        self.tx_ch = Node(self, ["hardwaregain", "rf_bandwidth"])
        self.rate = None

    def check(self, name, v):
        if name == "filter_fir_config":
            if not self.fir_ok:
                raise OSError(errno.EINVAL, "Invalid argument")
            self.fir_loaded = True
        elif name == "in_out_voltage_filter_fir_en":
            if v == "1" and not self.fir_loaded:
                raise OSError(errno.EINVAL, "Invalid argument")
            self.fir_en = v == "1"
        elif name == "sampling_frequency":
            r = int(v)
            if r < pluto.NO_FIR_MIN and not self.fir_en:
                raise OSError(errno.EINVAL, "Invalid argument")
            if r >= pluto.NO_FIR_MIN and not self.no_fir_rate_ok:
                raise OSError(errno.EINVAL, "Invalid argument")
            self.rate = r


def device_on(radio, fs=1_200_000.0):
    d = pluto.PlutoDevice(fs=fs)
    d.phy, d.rx_ch, d.tx_ch = radio.phy, radio.rx_ch, radio.tx_ch
    return d


class FakeLib:
    """libad9361 that fails as it did on the Tezuka nano."""

    def __init__(self, ret):
        def ad9361_set_bb_rate(phy, rate):
            return ret
        self.ad9361_set_bb_rate = ad9361_set_bb_rate


def with_lib(ret):
    return [mock.patch.object(pluto.ctypes.util, "find_library", return_value="libad9361.so.0"),
            mock.patch.object(pluto.ctypes, "CDLL", return_value=FakeLib(ret))]


def without_lib():
    return [mock.patch.object(pluto.ctypes.util, "find_library", return_value=None)]


def patched(patches, fn):
    for p in patches:
        p.start()
    try:
        return fn()
    finally:
        for p in patches:
            p.stop()


class SetRate(unittest.TestCase):
    def test_firmware_that_loads_the_fir_is_unchanged(self):
        r = FakeRadio(fir_ok=True)
        d = device_on(r)
        patched(without_lib(), d._set_rate)
        self.assertEqual((r.rate, d.m, d.dec), (1_200_000, 1, None))
        self.assertEqual(d.notes, [])

    def test_refused_fir_falls_back_to_a_multiple_without_it(self):
        for fs, m in [(1_200_000.0, 2), (600_000.0, 4)]:
            with self.subTest(fs=fs):
                r = FakeRadio(fir_ok=False)
                d = device_on(r, fs)
                patched(with_lib(-22), d._set_rate)
                self.assertEqual(r.rate, 2_400_000)
                self.assertEqual(d.m, m)
                self.assertEqual(d.fs, fs)              # what the engine sees does not change
                self.assertEqual(len(d.notes), 1)
                self.assertIn("returned -22", d.notes[0])
                self.assertIn("2.4 MS/s", d.notes[0])

    def test_libad9361_is_only_suggested_when_it_is_missing(self):
        # Everything refused, even the no-FIR rate: the sentence says why
        # and names the package only if it really is absent.
        r = FakeRadio(fir_ok=False, no_fir_rate_ok=False)
        with self.assertRaises(DeviceError) as cm:
            patched(with_lib(-22), device_on(r)._set_rate)
        self.assertNotIn("install libad9361", str(cm.exception))
        self.assertIn("returned -22", str(cm.exception))
        r = FakeRadio(fir_ok=False, no_fir_rate_ok=False)
        with self.assertRaises(DeviceError) as cm:
            patched(without_lib(), device_on(r)._set_rate)
        self.assertIn("install libad9361-0", str(cm.exception))


class ReceiverGain(unittest.TestCase):
    def test_gain_is_written_to_the_open_radio_mode_first(self):
        r = FakeRadio()
        d = device_on(r)
        written = []
        r.check = lambda name, v: written.append((name, v))
        d.set_rx_gain("manual", 55.0)
        self.assertEqual(written, [("gain_control_mode", "manual"), ("hardwaregain", "55.0")])
        written.clear()
        d.set_rx_gain("fast_attack", 55.0)
        # Under AGC the gain figure is the AGC's to choose; writing it would
        # only be refused or overridden.
        self.assertEqual(written, [("gain_control_mode", "fast_attack")])

    def test_a_refused_gain_is_a_device_error_with_the_reason(self):
        r = FakeRadio()
        d = device_on(r)

        def refuse(name, v):
            if name == "hardwaregain":
                raise OSError(errno.EINVAL, "Invalid argument")
        r.check = refuse
        with self.assertRaisesRegex(DeviceError, "hardwaregain"):
            d.set_rx_gain("manual", 80.0)


class FakeRxBuf:
    def __init__(self, iq_hw, n):
        self.iq, self.n, self.pos, self.raw = iq_hw, n, 0, b""

    def refill(self):
        blk = self.iq[self.pos:self.pos + self.n]
        self.pos += self.n
        s = np.empty(2 * len(blk), np.int16)
        s[0::2], s[1::2] = np.round(blk.real * 2048), np.round(blk.imag * 2048)
        self.raw = s.tobytes()

    def read(self):
        return self.raw


class FakeTxBuf:
    def __init__(self, dev, n, cyclic):
        self.n, self.pushed, self.cur = n, [], b""
        FakeTxBuf.last = self

    def write(self, b):
        assert len(b) == 4 * self.n, "a TX buffer write must fill the buffer exactly"
        self.cur = bytes(b)

    def push(self):
        s = np.frombuffer(self.cur, np.int16).astype(np.float32)
        self.pushed.append((s[0::2] + 1j * s[1::2]) / 32767)


class Clock:
    def __init__(self):
        self.t = 100.0

    def __call__(self):
        return self.t


class RingTxBuf(FakeTxBuf):
    """The kernel's ring of four TX buffers, drained by the DAC at the
    hardware rate on a fake clock: push() blocks (moves the clock on) until
    a buffer is free, as the real one does."""
    clock: Clock = None
    rate = 0.0

    def __init__(self, dev, n, cyclic):
        super().__init__(dev, n, cyclic)
        self.ends: list[float] = []

    def push(self):
        c = self.clock
        self.ends = [e for e in self.ends if e > c.t]
        if len(self.ends) == 4:
            c.t = self.ends.pop(0)
        start = max(c.t, self.ends[-1]) if self.ends else c.t
        self.ends.append(start + self.n / self.rate)
        super().push()


class SamplePaths(unittest.TestCase):
    def fallback_device(self, fs=1_200_000.0):
        r = FakeRadio(fir_ok=False)
        d = device_on(r, fs)
        patched(without_lib(), d._set_rate)
        self.assertEqual(d.m, 2)
        return d

    def test_receive_is_decimated_to_the_engine_rate(self):
        d = self.fallback_device()
        hw = d.fs * d.m
        # ~+300 kHz at 0.25 FS wanted; ~+700 kHz would alias to ~-500 kHz.
        # (Frequencies off any round grid: the fake's int16 rounding of two
        # tones on a 100 kHz grid makes distortion lines exactly there.)
        n = int(hw * 0.3)
        x = tone(301_234.0, hw, n, 0.25) + tone(701_111.0, hw, n, 0.25)
        d.rxbuf = FakeRxBuf(x, d.block * d.m)
        y = np.concatenate([d.read(d.block) for _ in range(3)])[2000:]
        self.assertEqual(len(y), 3 * d.block - 2000)
        self.assertAlmostEqual(level_db(y, 301_234.0, d.fs), 20 * np.log10(0.25), delta=0.05)
        self.assertLess(level_db(y, 701_111.0 - d.fs, d.fs), 20 * np.log10(0.25) - 80)

    def test_transmit_is_interpolated_with_the_image_suppressed(self):
        # Nothing here reaches a radio: the TX buffer is a fake that keeps
        # what would have been pushed.
        d = self.fallback_device()
        d.txdev = Node(d.phy.radio)
        for i in (0, 1):
            d.txdev.chans[(f"voltage{i}", True)] = Node(d.phy.radio)
        d.tx_lo_ch = Node(d.phy.radio, ["powerdown"])
        d.iio = mock.Mock(Buffer=FakeTxBuf)
        d.tx_start()
        buf = FakeTxBuf.last
        self.assertEqual(buf.n, d.m * d.tx_block)
        x = tone(400_000.0, d.fs, 4 * d.tx_block, 0.9)
        for i in range(0, len(x), 10_007):           # the engine's blocks are not the device's
            d.write(x[i:i + 10_007])
        self.assertEqual(len(buf.pushed), 4)
        y = np.concatenate(buf.pushed)
        self.assertEqual(len(y), d.m * len(x))
        seg = y[5_000:5_000 + 2 ** 17]
        self.assertGreater(worst_spur_db(seg, d.fs * d.m, 400_000.0), 50.0)
        self.assertAlmostEqual(level_db(seg, 400_000.0, d.fs * d.m), 20 * np.log10(0.9), delta=0.05)
        # latency: four 75 ms buffers whatever the hardware rate, plus a few us of filter
        self.assertAlmostEqual(d.tx_latency(), 4 * d.tx_block / d.fs, delta=1e-4)
        d.tx_stop()
        self.assertEqual(len(buf.pushed), 5)
        self.assertEqual(np.abs(buf.pushed[-1]).max(), 0.0)

    def tx_device(self, buffer):
        d = self.fallback_device()
        d.txdev = Node(d.phy.radio)
        for i in (0, 1):
            d.txdev.chans[(f"voltage{i}", True)] = Node(d.phy.radio)
        d.tx_lo_ch = Node(d.phy.radio, ["powerdown"])
        d.iio = mock.Mock(Buffer=buffer)
        return d

    def test_tx_queued_follows_the_kernel_ring_and_finish_sends_the_last_part_block(self):
        # Nothing reaches a radio: the ring is a fake on a fake clock.
        clock = Clock()
        d = self.tx_device(RingTxBuf)
        RingTxBuf.clock, RingTxBuf.rate = clock, d.fs * d.m
        blk = d.tx_block / d.fs                                  # 75 ms
        with mock.patch.object(pluto.time, "monotonic", clock):
            d.tx_start()
            buf = RingTxBuf.last
            t0 = clock.t
            x = tone(100_000.0, d.fs, 6 * d.tx_block + d.tx_block // 3, 0.5)
            d.write(x)
            # Six pushed into a ring of four: the fifth and sixth waited one
            # buffer each, so 4 buffers are in flight from t0 + 2 blocks, and
            # a third of a block waits here for the rest of its buffer.
            self.assertAlmostEqual(clock.t - t0, 2 * blk, places=9)
            self.assertAlmostEqual(d.tx_queued(), 4 * blk + blk / 3, places=6)
            # tx_stop now would drop all of it; a normal end pushes the third
            # padded with silence, and counts only to its last real sample.
            d.tx_finish()
            self.assertEqual(len(buf.pushed), 7)
            last = buf.pushed[-1]
            k = d.m * (d.tx_block // 3)
            self.assertGreater(np.abs(last[k // 2:k - 100]).min(), 0.4)
            self.assertLess(np.abs(last[k + 100:]).max(), 1e-3)
            self.assertAlmostEqual(d.tx_queued(), 4 * blk - 2 * blk / 3, places=6)
            # It goes as the DAC clocks it out, and nothing is left when the
            # last real sample has.
            clock.t += 2 * blk
            self.assertAlmostEqual(d.tx_queued(), 2 * blk - 2 * blk / 3, places=6)
            clock.t += 2 * blk - 2 * blk / 3 + 1e-9
            self.assertEqual(d.tx_queued(), 0.0)
            d.tx_stop()
            self.assertEqual(d.tx_queued(), 0.0)


if __name__ == "__main__":
    unittest.main()
