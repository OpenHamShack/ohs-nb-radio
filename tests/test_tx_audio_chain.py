"""The voice transmit chain end to end, measured the way the station at the
other end hears it: a tone played into the sound card's microphone ring at
the card's rate, read by PortAudio.read_mic in the engine's 75 ms blocks,
modulated (AM, and USB for comparison), placed by the filter bank, written
through the Pluto's own write() - interpolated x2 as on the Tezuka nano -
into a fake IIO buffer, and demodulated by a plain envelope / product
detector written here, independent of the receive code.

Why it exists: Ray (05/10/2026, HAM on a Pluto, 70 cm AM) was heard as a
strong signal with terrible audio. The RF half of the chain measured clean
(better than -100 dB); read_mic dropped one 12 kHz sample per block, which
put ~10 % distortion on every voice mode. Nothing transmits: the IIO
buffer is a fake and no radio is opened."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

import numpy as np

from ohscore import audio as au
from ohscore.devices import pluto
from ohscore.dsp.bank import Geometry, Source, Synthesis
from ohscore.dsp.mod import AmMod, SsbMod
from ohscore.dsp.multirate import Interpolator
from ohscore.dsp.resample import Resampler

AR = 12_000
BLOCK = 900                     # the engine's 75 ms TX block at 12 kHz


def mic_blocks(card_rate: int, seconds: float, f: float = 1000.0, amp: float = 0.3) -> np.ndarray:
    """What the TX thread gets from read_mic while the card delivers a tone
    in 20 ms callbacks, paced as a real card would be."""
    pa = au.PortAudio()                         # __init__ never opens a stream
    pa.rate = card_rate
    pa.mic_ring = au.Ring(card_rate)
    pa.down = Resampler(AR, card_rate)
    chunk = int(0.02 * card_rate)
    t = np.arange(int(card_rate * (seconds + 0.5))) / card_rate
    card = (amp * np.sin(2 * np.pi * f * t)).astype(np.float32)
    pos, out = 0, []
    for b in range(int(seconds / 0.075)):
        while pos < int((b + 1) * 0.075 * card_rate) + chunk:
            pa._on_mic(card[pos:pos + chunk])
            pos += chunk
        out.append(pa.read_mic(BLOCK))
    return np.concatenate(out)


class FakeTxBuf:
    def __init__(self):
        self.pushed, self.cur = [], b""

    def write(self, b):
        self.cur = bytes(b)

    def push(self):
        self.pushed.append(np.frombuffer(self.cur, np.int16).copy())


def transmit(audio: np.ndarray, mod, fs: float = 1_200_000.0, m: int = 2):
    """audio -> modulator -> Source/Synthesis (signal a quarter of fs above
    the LO, as radio.py places it) -> PlutoDevice.write -> int16 as the DAC
    would get it. Returns hardware-rate IQ (full scale 1), its rate, and how
    many int16 values sat at the clip."""
    geo = Geometry(fs)
    d = geo.decimation_for(AR)
    src, syn = Source(geo, d, freq=0.25 * fs), Synthesis(geo)
    dev = pluto.PlutoDevice(fs=fs)
    dev.m, dev.interp = m, (Interpolator(m) if m > 1 else None)
    dev.txbuf, dev.tx_pending, dev.tx_on = FakeTxBuf(), np.zeros(0, np.complex64), True
    n = 5 * (geo.L // d)
    for i in range(0, len(audio) - n + 1, n):
        dev.write(syn.render(5, [(src, mod(audio[i:i + n]))]))
    s = np.concatenate(dev.txbuf.pushed).astype(np.float64)
    return (s[0::2] + 1j * s[1::2]) / 32767, fs * m, int(np.sum(np.abs(s) >= 32767))


def receive(z: np.ndarray, hw: float, off: float) -> np.ndarray:
    """An ideal receiver: shift the signal to 0 Hz, brick-wall it to +-5 kHz
    in one FFT and keep every hw/12k-th sample."""
    bb = z * np.exp(-2j * np.pi * off / hw * np.arange(len(z)))
    Z = np.fft.fft(bb)
    Z[np.abs(np.fft.fftfreq(len(z), 1 / hw)) > 5_000] = 0
    return np.fft.ifft(Z)[::int(round(hw / AR))]


def thd_n_db(x: np.ndarray, f0: float) -> float:
    """Everything 200 Hz-5 kHz that is not the tone, relative to the tone."""
    x = x - x.mean()
    X = np.abs(np.fft.rfft(x * np.blackman(len(x)))) ** 2
    f = np.fft.rfftfreq(len(x), 1 / AR)
    fund = np.abs(f - f0) < 15
    band = (f > 200) & (f < 5_000)
    return float(10 * np.log10(X[band & ~fund].sum() / X[fund].sum()))


class MicPath(unittest.TestCase):
    def test_read_mic_neither_drops_nor_invents_samples(self):
        # Before the fix: -20.5 dB at 48 kHz, -17.9 dB at 44.1 kHz.
        for rate in (48_000, 44_100):
            with self.subTest(card=rate):
                a = mic_blocks(rate, 2.5)
                self.assertLess(thd_n_db(a[2_400:2_400 + 16_384], 1000.0), -80.0)


class VoiceTransmit(unittest.TestCase):
    """Through the whole chain to the DAC and back, at the nano's x2."""

    def setUp(self):
        self.audio = mic_blocks(48_000, 2.0)

    def test_am_tone_is_clean_and_never_overmodulated(self):
        am = AmMod()
        am.configure(2700.0, 0.0, voice=True)
        z, hw, clipped = transmit(self.audio, am)
        env = np.abs(receive(z, hw, 300_000.0))[3_000:3_000 + 16_384]
        carrier = np.median(env)
        self.assertEqual(clipped, 0)
        self.assertLess(thd_n_db(env, 1000.0), -60.0)
        # Index held at 90 %: neither peak passes it, so the carrier never pinches off.
        self.assertLess((env.max() - carrier) / carrier, 0.91)
        self.assertLess((carrier - env.min()) / carrier, 0.91)
        self.assertGreater((env.max() - carrier) / carrier, 0.7)

    def test_am_keeps_hum_and_dc_off_the_carrier(self):
        # A laptop mic's DC offset and mains hum under a 1 kHz tone. Before
        # AM had a low edge: the carrier moved 10 % and the hum was -10 dB
        # of the transmitted audio.
        t = np.arange(len(self.audio)) / AR
        x = (self.audio * 0.3 + 0.05 + 0.0316 * np.sin(2 * np.pi * 50 * t)).astype(np.float32)
        am = AmMod()
        am.configure(2700.0, 0.0, voice=True, lo=300.0)
        z, hw, _ = transmit(x, am)
        env = np.abs(receive(z, hw, 300_000.0))[3_000:3_000 + 16_384]
        self.assertAlmostEqual(float(np.median(env)), AmMod.PEAK / (1 + AmMod.INDEX), delta=0.005)
        a = env - env.mean()
        p = np.abs(np.fft.rfft(a)) ** 2
        f = np.fft.rfftfreq(len(a), 1 / AR)
        self.assertLess(10 * np.log10(p[(f > 20) & (f < 200)].sum() / p[f > 20].sum()), -40.0)

    def test_usb_tone_is_clean(self):
        ssb = SsbMod()
        ssb.configure(300.0, 2700.0, 0.0, 6.0, True, "usb")
        z, hw, clipped = transmit(self.audio, ssb)
        y = receive(z, hw, 300_000.0).real[3_000:3_000 + 16_384]
        self.assertEqual(clipped, 0)
        self.assertLess(thd_n_db(y, 1000.0), -60.0)


def rapp(z: np.ndarray, p: float = 2.0) -> np.ndarray:
    """A transmitter that saturates softly at DAC full scale (the Rapp model,
    the usual one for a solid-state output stage): what the AD936x and any
    amplifier after it do to an envelope near the top. A model - the
    Pluto's own curve is unmeasured."""
    m = np.abs(z)
    return z / (1 + m ** (2 * p)) ** (1 / (2 * p))


def hot_speech(seconds: float = 3.0) -> np.ndarray:
    """Speech-like audio with a voice's crest factor (~12 dB), peaking at
    full scale on the card: a hot microphone."""
    from ohscore.devices import simsignals as sg
    v = sg.voice(np.random.default_rng(5), seconds).real
    return (v / np.abs(v).max()).astype(np.float32)


class AmOnTheAir(unittest.TestCase):
    """Brian heard Ray's 70 cm AM as terrible while FM, USB and LSB from the
    same stock Pluto were fine (06/10/2026). AM is the one mode whose audio
    is its envelope, and it drove that envelope to 0.95 of full scale,
    where a transmitter's top end compresses; at 1.2 MS/s, no interpolator,
    as Ray's radio ran."""

    def am(self, mic_gain_db=20.0):
        m = AmMod()
        m.configure(2700.0, mic_gain_db, voice=True, lo=300.0)
        return m

    def test_hot_speech_leaves_the_top_of_the_dac_alone(self):
        z, hw, clipped = transmit(hot_speech(), self.am(), m=1)
        self.assertEqual(clipped, 0)
        self.assertLess(float(np.abs(z).max()), 0.55)        # was 0.947
        env = np.abs(receive(z, hw, 300_000.0))[6_000:-6_000]
        carrier = np.median(env)
        # Never pinched off, however hot the microphone.
        self.assertGreater(env.min() / carrier, 0.05)
        self.assertLess(env.max() / carrier, 1.95)

    def test_am_survives_a_transmitter_that_compresses_at_full_scale(self):
        tone = (0.3 * np.sin(2 * np.pi * 1000 * np.arange(2 * AR) / AR)).astype(np.float32)
        z, hw, _ = transmit(tone, self.am(0.0), m=1)
        env = np.abs(receive(rapp(z), hw, 300_000.0))[6_000:6_000 + 16_384]
        self.assertLess(thd_n_db(env, 1000.0), -40.0)        # was -23 dB

    def test_usb_was_never_hurt_by_it(self):
        # Why only AM sounded bad: the same compression leaves USB alone.
        tone = (0.3 * np.sin(2 * np.pi * 1000 * np.arange(2 * AR) / AR)).astype(np.float32)
        ssb = SsbMod()
        ssb.configure(300.0, 2700.0, 0.0, 6.0, True, "usb")
        z, hw, _ = transmit(tone, ssb, m=1)
        y = receive(rapp(z), hw, 300_000.0).real[6_000:6_000 + 16_384]
        self.assertLess(thd_n_db(y, 1000.0), -60.0)


if __name__ == "__main__":
    unittest.main()
