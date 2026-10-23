"""Receivers and stations for the listening tests (test_ham_wfm.py,
test_ham_listen.py): the band simulator posing as an SDRplay RSPdx, with
broadcast and utility stations on the air where the amateur simulator has
none, and a sound card that keeps what it is given."""
import math
import tempfile

import numpy as np

from ohscore.audio import NullAudio
from ohscore.devices.sdrsource import SdrplayDevice
from ohsradio.devices.sim import HamSim
from ohsradio.radio import Radio

RSPDX_RANGE = (1e3, 2e9)       # SDRplay's figure for the RSPdx: 1 kHz to 2 GHz
HEARD = float(Radio.OUT_RATE)  # what the sound card is given: 48 kHz since 23/10/2026


class Station:
    """One transmitter on the air at `hz`: a `tone` Hz test tone in `mode`
    (am: 50 % modulation; fm: 2.5 kHz deviation peak; wfm: 50 kHz peak,
    pre-emphasised as a broadcaster does), `level_db` dBFS carrier."""

    DEVIATION = {"fm": 1250.0, "wfm": 50_000.0}

    def __init__(self, hz, mode, tone=1000.0, level_db=-30.0):
        self.hz, self.mode, self.tone = float(hz), mode, float(tone)
        self.amp = 10 ** (level_db / 20)

    def iq(self, t, rx_if):
        """Complex baseband at the simulated receiver's centre `rx_if` over
        absolute times `t` (seconds)."""
        carrier = 2 * np.pi * (self.hz - rx_if) * t
        w = 2 * np.pi * self.tone * t
        if self.mode == "am":
            return (self.amp * (1 + 0.5 * np.sin(w)) * np.exp(1j * carrier)).astype(np.complex64)
        dev = self.DEVIATION[self.mode]
        if self.mode == "wfm":
            # A 50 us pre-emphasised tone is the tone, louder and leading:
            # 1 + j w tau at its frequency.
            g = 1 + 1j * 2 * np.pi * self.tone * 50e-6
            dev, phase = dev * abs(g), math.atan2(g.imag, g.real)
        else:
            phase = 0.0
        # The phase of a sin(w t + phase) deviation is its integral.
        return (self.amp * np.exp(1j * (carrier - dev / self.tone * np.cos(w + phase)))).astype(np.complex64)


class ListeningSim(HamSim):
    """The band simulator shaped like an RSPdx: 1 kHz-2 GHz, its one rate
    (2.4 MS/s, sdrsource.SdrplayDevice.RATES), receive only with the
    receiver's own refusal - plus `stations` on the air."""

    kind = "sdrplay"
    can_tx = False
    tx_refusal = SdrplayDevice.tx_refusal
    rx_range = RSPDX_RANGE

    def __init__(self, cfg, fs=2_400_000.0, stations=(), receive_only=True):
        super().__init__(cfg, fs)
        self.stations = list(stations)
        self.k = 0
        if not receive_only:
            # The transmitting simulator over the same range, for the guard.
            self.kind, self.can_tx, self.tx_refusal = "sim", True, ""

    def _generate(self, m):
        y = super()._generate(m)
        if self.stations:
            t = (self.k + np.arange(len(y))) / self.fs
            for st in self.stations:
                y = y + st.iq(t, self.rx_if)
        self.k += len(y)
        return y.astype(np.complex64)


class TapAudio(NullAudio):
    """A sound card that keeps what the radio plays."""

    def __init__(self):
        super().__init__(realtime=False)
        self.chunks = []

    def play(self, audio):
        super().play(audio)
        self.chunks.append(np.array(audio, np.float32))

    def take(self):
        a = np.concatenate(self.chunks) if self.chunks else np.zeros(0, np.float32)
        self.chunks = []
        return a


def make_listener(stations=(), receive_only=True, fs=2_400_000.0, **over):
    """A Radio on the RSPdx-shaped simulator (no simulated amateur stations:
    only `stations`), a Full licence, and a sound card that keeps the audio."""
    tmp = tempfile.TemporaryDirectory()
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "simSignals": False, "callsign": "GM4BRI", "licenceClass": "full"}
    cfg.update(over)
    audio = TapAudio()
    dev = ListeningSim(dict(cfg), fs, stations, receive_only)
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio, device=dev)
    r._tmp = tmp
    return r, audio, dev


def tone_snr(a, hz, rate=HEARD):
    """(frequency of the strongest bin 100 Hz-5 kHz, SNR dB of `hz` against
    the rest of that band)."""
    w = np.hanning(len(a))
    A = np.abs(np.fft.rfft(a * w)) ** 2
    f = np.fft.rfftfreq(len(a), 1 / rate)
    band = (f > 100) & (f < 5000)
    peak = float(f[band][int(np.argmax(A[band]))])
    near = band & (np.abs(f - hz) < 30)
    return peak, 10 * math.log10(A[near].sum() / (A[band & ~near].sum() + 1e-30))


def peak_hz(a, rate=HEARD):
    """The strongest frequency in `a`, to a fraction of a bin (a parabola
    through the peak bin and its neighbours on the log spectrum)."""
    A = np.log(np.abs(np.fft.rfft(a * np.hanning(len(a)))) + 1e-30)
    i = int(np.argmax(A[1:-1])) + 1
    d = 0.5 * (A[i - 1] - A[i + 1]) / (A[i - 1] - 2 * A[i] + A[i + 1])
    return (i + d) * rate / len(a)
