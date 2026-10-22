"""What a simulated device needs whatever it simulates.

QO-100 NB's sim is the QO-100 transponder (ohsnb/devices/sim.py); OpenHamShack
HAM's will be a terrestrial band. Both are a population of stations that
come and go, a noise floor drawn from a bank of pre-shaped spectra, and our
own transmission looped back after a delay - so those live here, and an
app's simulator supplies only what makes it that simulator: where stations
are, the shape of the noise, and where and how loud our signal returns.

Moved out of ohsnb/devices/sim.py unchanged (docs/ham/DESIGN-HAM.md section
2.5 step 5), so the RNG is drawn in the same order and a given simSeed
still produces the same band.
"""
from __future__ import annotations

import bisect
import threading
import time

import numpy as np

from .base import Device, DeviceError
from ..dsp.bank import Source
from . import simsignals as sg


class Presence:
    """When a station is on the air: on for a while, off for a while,
    repeating over `cycle_s` - precomputed once at open() (not re-rolled
    per block, which would need an RNG draw on the RX thread's hot path) so
    checking it at render time is a cheap bisect, not randomness. `gain()`
    also ramps the first/last `fade_s` of each on-window linearly, so a
    station's arrival or departure is a fade, not a click in the waterfall.
    """

    def __init__(self, rng: np.random.Generator, on_range: tuple[float, float],
                 off_range: tuple[float, float], cycle_s: float = 7200.0, fade_s: float = 1.5):
        self.cycle, self.fade = cycle_s, fade_s
        self.windows: list[tuple[float, float]] = []
        # The first window's start is allowed to be negative - i.e. already
        # under way when the sim opens, for roughly on/(on+off) of stations -
        # so tuning in finds an evening already in progress, not everyone
        # keying up together at t=0 (which a start of rng.uniform(0, ...)
        # would do, and did: the first couple of minutes came out near-empty).
        t = rng.uniform(-on_range[1], off_range[1])
        while t < cycle_s:
            end = min(cycle_s, t + rng.uniform(*on_range))
            self.windows.append((t, end))
            t = end + rng.uniform(*off_range)
        self.starts = [w[0] for w in self.windows]

    def gain(self, t: float) -> float:
        """0 off, 1 fully on, ramped in between - at absolute time `t`."""
        tt = t % self.cycle
        i = bisect.bisect_right(self.starts, tt) - 1
        if i < 0:
            return 0.0
        a, b = self.windows[i]
        if tt >= b:
            return 0.0
        return min(1.0, (tt - a) / self.fade, (b - tt) / self.fade)


class Station:
    def __init__(self, name: str, dl: float, template: np.ndarray, level_db: float, phase: float = 0.0,
                 presence: Presence | None = None):
        self.name, self.dl = name, dl
        self.tpl = template
        self.amp = 10 ** (level_db / 20)
        self.pos = int(phase * len(template)) % max(len(template), 1)
        self.presence = presence
        self.src: Source | None = None

    def take(self, n: int, gain: float = 1.0) -> np.ndarray:
        L = len(self.tpl)
        idx = (self.pos + np.arange(n)) % L
        self.pos = (self.pos + n) % L
        x = self.tpl[idx] * self.amp
        return x if gain == 1.0 else x * np.float32(gain)


class FT8Activity:
    """FT8 at 10489.540: a new set of transmissions each 15 s slot, from the
    real encoder when ohscore.modes has one, else FT8-shaped stand-ins."""

    MESSAGES = ["CQ G4XYZ IO91", "CQ DL1ABC JO31", "G4XYZ EA4QRP IN80", "EA4QRP G4XYZ -08", "CQ DX OH8ZZ KP24",
                "DL1ABC F5KLM JN18", "F5KLM DL1ABC R-12", "CQ PA3QOS JO22", "I0XYZ ON4BB RR73", "CQ SV1QO KM18"]

    def __init__(self, rng: np.random.Generator, dial: float, level_db: float, t0: float):
        # Its own generator: slots are rendered on a worker thread, and numpy
        # Generators are not thread-safe.
        self.rng, self.dial, self.dl = np.random.default_rng(rng.integers(2**63)), dial, dial
        self.amp = 10 ** (level_db / 20)
        self.slot_len = int(15 * sg.RATE)
        self.t0 = t0
        self.cur_slot = None
        self.buf = np.zeros(self.slot_len, np.complex64)
        self.enc = None
        try:
            from .. import modes_glue
            self.enc = modes_glue.encoder("ft8")
        except Exception:  # noqa: BLE001 - the sim must run without ohscore.modes
            self.enc = None
        self.src: Source | None = None
        self.name = "FT8"
        self.lock = threading.Lock()
        self.ready: dict[int, np.ndarray] = {}

    def _render_slot(self):
        buf = np.zeros(self.slot_len, np.complex64)
        start = int(0.5 * sg.RATE)
        for _ in range(int(self.rng.integers(3, 7))):
            off = float(self.rng.uniform(300, 2700))
            lvl = 10 ** (self.rng.uniform(-14, 0) / 20)
            sig = None
            if self.enc is not None:
                try:
                    a = np.asarray(self.enc.render(text=str(self.rng.choice(self.MESSAGES)), freq=off, df=off),
                                   np.float32)
                    sig = sg.analytic(a) if len(a) else None
                except Exception:  # noqa: BLE001
                    sig = None
            if sig is None:
                sig = sg.ft8_like(self.rng, off)
            n = min(len(sig), self.slot_len - start)
            buf[start:start + n] += sig[:n] * lvl
        return buf

    def _prepare(self, slot: int):
        # Rendering a slot (possibly through a real FT8 encoder) is done one
        # slot ahead on a worker so the receive thread never waits for it.
        def work():
            buf = self._render_slot()
            with self.lock:
                self.ready[slot] = buf

        threading.Thread(target=work, name="sim-ft8", daemon=True).start()

    def take(self, n: int, t: float) -> np.ndarray:
        """n samples starting at absolute time t (seconds since the epoch)."""
        out = np.empty(n, np.complex64)
        i = 0
        while i < n:
            tt = t + i / sg.RATE
            slot = int(tt // 15)
            if slot != self.cur_slot:
                self.cur_slot = slot
                with self.lock:
                    buf = self.ready.pop(slot, None)
                    self.ready = {k: v for k, v in self.ready.items() if k > slot}
                self.buf = buf if buf is not None else self._render_slot()
                self._prepare(slot + 1)
            k = int(round((tt - slot * 15) * sg.RATE)) % self.slot_len
            m = min(n - i, self.slot_len - k)
            out[i:i + m] = self.buf[k:k + m]
            i += m
        return out * self.amp


class SimCore(Device):
    """The receive pacing, noise bank and transmit loopback of a simulated
    full-duplex device. The subclass sets `fs`, `geo` (a Geometry), `rng`,
    `rx_if` and `rtt` (seconds before our signal comes back), calls
    `_init_loop()`, and supplies `_generate(m)` (m frames of receive IQ,
    which calls `_noise_bank` and `_loopback`), `_noise_density`,
    `_loopback_amp` and `_loopback_shift`."""

    can_tx = True
    radiates = False          # its "transmitter" is a FIFO into its own receive stream

    @property
    def rx_prefetch(self) -> bool:
        # In real time it stands in for a radio, and is read as one
        # (Device.rx_prefetch); faster than real time (the tests) it keeps
        # its lock-step with the transmit thread, which reading ahead
        # would break.
        return bool(getattr(self, "realtime", False))

    def _init_loop(self):
        self.cond = threading.Condition()
        self.tx_lo = None
        self.tx_gain = -89.75
        self.tx_active = False
        # Set by tx_finish: the over has ended and the fifo is being let
        # run out. The lock-step read below must not wait for a write that
        # is never coming, and the fifo running dry is not an underrun.
        self.tx_draining = False
        self.fifo: list[np.ndarray] = []
        self.fifo_len = 0
        self.fifo_cap = int(0.15 * self.fs)
        self.delay = np.zeros(int(round(self.rtt * self.fs)), np.complex64)
        self.delay_live = 0
        self.tx_phase = 0.0
        # An inverting converter after the simulated transmitter mirrors
        # what goes out: the app's sim sets this to put one in the loop,
        # so the engine's own mirroring (Engine.tx_invert) is undone on the
        # way back exactly as real hardware would undo it.
        self.loop_invert = False
        self.underruns = 0
        self.tx_written = 0
        self.closed = False
        self.reading = False
        # Stream positions (samples) for tx_latency(): how far the engine has
        # been handed the receive stream, and the end of the frames whose
        # transmit samples _loopback has already taken from the fifo.
        self.returned = 0
        self.popped_to = 0
        cfg = getattr(self, "cfg", None) or {}
        self.set_rx_gain(cfg.get("rxGainMode", "slow_attack"), float(cfg.get("rxGain", 40.0)))

    # The simulated levels are what a receiver's AGC would settle at. Manual
    # gain is taken relative to 40 dB (the setting's default), so turning it
    # moves signals and noise together, as a real front end's gain does
    # until it clips or its noise figure shows - neither of which is
    # simulated. It is here so that the Receiver gain controls visibly do
    # something on the simulator, as they do on a radio.
    RX_GAIN_REF_DB = 40.0

    def set_rx_gain(self, mode: str, db: float) -> None:
        self.rx_scale = 1.0 if mode != "manual" else 10 ** ((float(db) - self.RX_GAIN_REF_DB) / 20)
        self.rx_gain_db = float(db) if mode == "manual" else self.RX_GAIN_REF_DB

    def rx_gain_now(self) -> float | None:
        # Under "AGC" the simulator's levels are those of manual at the reference.
        return getattr(self, "rx_gain_db", self.RX_GAIN_REF_DB)

    def _noise_bank(self, err: float, n: int = 24):
        g = self.geo
        f = np.fft.fftfreq(g.N, 1 / g.fs)
        dens = self._noise_density(f, err)
        sigma = np.sqrt(dens * g.fs * g.N / 2).astype(np.float32)
        r = self.rng.standard_normal((n, 2, g.N), dtype=np.float32)
        self.bank = ((r[:, 0] + 1j * r[:, 1]) * sigma).astype(np.complex64)
        self.bank_err, self.bank_if = err, self.rx_if

    def _noise_density(self, f: np.ndarray, err: float) -> np.ndarray:
        """Noise power density (linear, full scale^2 per Hz) at baseband
        frequencies `f` when everything appears `err` Hz high: the app's
        band shape over the receiver floor."""
        raise NotImplementedError

    def _loopback(self, y: np.ndarray, err: float):
        k = len(y)
        with self.cond:
            self.popped_to = self.n + k
            if self.fifo_len == 0 and self.delay_live <= 0:
                return
            take = np.zeros(k, np.complex64)
            i = 0
            while self.fifo and i < k:
                a = self.fifo[0]
                c = min(len(a), k - i)
                take[i:i + c] = a[:c]
                if c == len(a):
                    self.fifo.pop(0)
                else:
                    self.fifo[0] = a[c:]
                i += c
            self.fifo_len -= i
            if self.tx_active and i < k and not self.tx_draining:
                self.underruns += 1
            gain = self.tx_gain
            lo = self.tx_lo
            self.cond.notify_all()
        if lo is None:
            return
        amp = self._loopback_amp(gain)
        if i:
            self.delay_live = len(self.delay) + k
        joined = np.concatenate([self.delay, take * np.float32(amp)])
        back, self.delay = joined[:k], joined[k:]
        if self.loop_invert:
            back = np.conj(back)
        self.delay_live -= k
        self._uplink_out(back, lo)
        shift = self._loopback_shift(lo, err)
        ph = self.tx_phase + 2 * np.pi * shift / self.fs * np.arange(k)
        y += back * np.exp(1j * ph).astype(np.complex64)
        self.tx_phase = float((self.tx_phase + 2 * np.pi * shift / self.fs * k) % (2 * np.pi))

    def _uplink_out(self, back: np.ndarray, tx_lo: float) -> None:
        """Each block of our own signal on its way back (delayed, at its
        level, before it is shifted into our receive stream), with the TX
        LO it was sent at: for an app's simulator that lets other simulated
        stations hear it (NB: attach_peer). Default: nobody else listens."""

    def _loopback_amp(self, tx_gain: float) -> float:
        """Amplitude our own signal comes back at for TX gain `tx_gain` dB."""
        raise NotImplementedError

    def _loopback_shift(self, tx_lo: float, err: float) -> float:
        """Where, relative to the receiver's centre, a signal sent at TX LO
        `tx_lo` comes back, when everything appears `err` Hz high."""
        raise NotImplementedError

    def read(self, n: int) -> np.ndarray:
        if not self.opened:
            raise DeviceError("The simulator is not open")
        L = self.geo.L
        if not self.reading:
            # Pace from the first read, not from open(): whatever the caller
            # did in between must not be "caught up" as a burst of signal.
            self.t_wall0 = time.monotonic() - self.n / self.fs
            if self.realtime and hasattr(self, "t_epoch"):
                # The simulated UTC (FT8 slots) starts there too. Anchored at
                # the top of open() it lagged the wall clock by however long
                # open() and the engine's start took - NB's sim builds its
                # templates for ~5 s - and every simulated FT8 transmission
                # arrived that late into its slot, outside jt9's DT search,
                # so nothing decoded in real time.
                self.t_epoch = time.time() - self.n / self.fs
        self.reading = True
        while len(self.out) < n:
            m = max(1, min(8, -(-(n - len(self.out)) // L)))
            if not self.realtime and self.tx_active:
                # Lock-step when running faster than real time: wait for the
                # transmit thread so a test sees the same loop a real radio would.
                with self.cond:
                    deadline = time.monotonic() + 5.0
                    while (self.tx_active and not self.tx_draining and self.fifo_len < m * L
                           and not self.closed):
                        left = deadline - time.monotonic()
                        if left <= 0:
                            break
                        self.cond.wait(left)
            self.out = np.concatenate([self.out, self._generate(m)])
        y, self.out = self.out[:n], self.out[n:]
        self.returned = self.n - len(self.out)
        if self.rx_scale != 1.0:
            y = y * np.float32(self.rx_scale)
        if self.realtime:
            due = self.t_wall0 + (self.n - len(self.out)) / self.fs
            lag = due - time.monotonic()
            if lag > 0:
                time.sleep(lag)
        return y

    # -- transmit -----------------------------------------------------------
    def set_tx_freq(self, hz: float) -> None:
        self.tx_lo = float(hz)

    def set_tx_gain(self, db: float) -> None:
        self.tx_gain = max(-89.75, min(0.0, float(db)))

    def tx_start(self) -> None:
        with self.cond:
            self.tx_active = True
            self.tx_draining = False
            self.cond.notify_all()

    def tx_stop(self) -> None:
        with self.cond:
            self.tx_active = False
            self.tx_draining = False
            self.fifo, self.fifo_len = [], 0
            self.cond.notify_all()

    def tx_finish(self) -> None:
        with self.cond:
            self.tx_draining = True
            self.cond.notify_all()

    def tx_queued(self) -> float:
        # The fifo is the whole queue: once _loopback has taken a sample it
        # is "on air" (in the delay line back to our receiver), and tx_stop
        # empties only the fifo. Up to fifo_cap (150 ms) plus the one write
        # that found it just under the cap - the engine's 75 ms block - so
        # about 225 ms at most.
        with self.cond:
            return self.fifo_len / self.fs

    def write(self, iq: np.ndarray) -> None:
        iq = np.asarray(iq, np.complex64)
        with self.cond:
            if not self.tx_active:
                raise DeviceError("Transmit is not started")
            deadline = time.monotonic() + 3.0
            while self.fifo_len > self.fifo_cap and self.tx_active and not self.closed:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise DeviceError("The simulator stopped taking transmit samples")
                self.cond.wait(min(left, 0.2))
            if not self.tx_active:
                return
            self.fifo.append(iq)
            self.fifo_len += len(iq)
            self.tx_written += len(iq)
            self.cond.notify_all()

    def tx_latency(self) -> float:
        # Exact, from stream positions, rather than the fifo alone: the next
        # written sample airs after everything already generated (n, or the
        # end of the frames being generated right now) plus what waits in
        # the fifo, and the engine adds this to the receive samples it has
        # been handed (returned). fifo_len / fs alone left out the samples
        # generated but not yet handed over, which is anything from nothing
        # to a whole read (75 ms) depending on where the receive thread was
        # when the transmit thread asked - a matter of thread scheduling.
        # TxMonitor lines up each 100 ms frame with what we sent to a few ms
        # for speech, so that jitter cost it its fine (speckle) estimate
        # whenever the machine was busy: test_lock's wide acquisition then
        # never became confident and failed, once in a release run and in
        # most tries with the machine loaded. n + fifo_len cannot change
        # under us: _loopback takes from the fifo exactly what n then grows by.
        with self.cond:
            air = max(self.n, self.popped_to) + self.fifo_len
            return max(0, air - self.returned) / self.fs

    def close(self) -> None:
        with self.cond:
            self.closed = True
            self.tx_active = False
            self.cond.notify_all()
