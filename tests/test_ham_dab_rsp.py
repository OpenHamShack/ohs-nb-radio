"""Decoder sessions through the receiver path a real RSP takes, at its 2.4 MS/s.

test_ham_dab.py plays DAB on the band simulator, which the engine reads as
fast as it likes and feeds into rings that hold two minutes. A real RSPdx
is none of that: ohs-box's (device soapy, driver=sdrplay, opened by
SoapySdrplayDevice through shack_sdr's SdrplaySource) delivers 50 ms
blocks of complex64 at x/32768 in real time, behind the engine's prefetch
queue, and the decoder host keeps two seconds. Here a stand-in shaped
exactly like SdrplaySource (RspStandIn: its constructor, its blocks, its
pace, its DC residue) carries a small air of its own - the DAB
transmitter model's ensemble on 11D, an RTTY and a CW station on 2 m -
through SoapySdrplayDevice, the DC blocker, the engine and the host, with
nothing patched in between.

**What Store Radio 0.1.22-beta.5 did on ohs-box (23/10/2026).** A DAB
session stayed `starting` for ever: no frames, no CPU, and `dropped`
rising by exactly 2.4 MS/s - every sample thrown away, nothing said
anywhere. The process's one shack_sdr worker was at 100 % of a core: a
DAB decoder had gone into shack_sdr 0.2.0's search and never come back
(dab/ofdm.rs: a buffer that starts loud just before a short deep dip, no
phase reference to lock to, and the miss drops nothing, so the same
samples are searched again for ever), and with one worker per host every
session started after it starved. The simulator never makes such a dip;
RspStandIn.DIP does, on a block with no ensemble on it. Whether that is
the very input ohs-box saw is not known (its IQ was not captured); it is
an input that puts this shack_sdr into the state ohs-box was found in.

- **A station plays at 2.4 MS/s** through this path, with nothing dropped.
- **RTTY and CW sessions decode** at 2.4 MS/s through it, nothing dropped.
- **The fading empty block that held the decoder now decodes as noise:**
  `nosignal`, nothing dropped, nothing said; and after it an RTTY session
  decodes and the next DAB station plays. With shack_sdr before ohs-libs
  23b437c this same test stuck the decoder: the session went `error` with
  why `decoder_stuck`, said once in the log and a toast (the starvation
  watch, kept for whatever the next stuck decoder is), and, its host being
  its own, stopping it let the RTTY session and the next station run.
- **The watch itself** (decoders.starvation) on numbers alone.

- **A wide FM session reads RDS** at 2.4 MS/s on a 240 kS/s channel of
  its own (refused on every receiver before 23/10/2026: every unheld
  session started at 12 kHz).

- **PSK and SSTV (Radio's SDR milestone 2)** at 2.4 MS/s: an SSTV session
  paints a picture and saves it, nothing dropped (and a PSK session its two
  stations, skipped while the Rust PSK decoder is switched off,
  ohscore/sdr.py); and as the mode's own decoders, fed the engine's 12 kHz
  audio while the receive audio is 48 kHz, PSK copies its station (psk.py
  as shipped; the Rust one one more) and SSTV a picture.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import logging
import tempfile
import time
import unittest
from unittest import mock

import numpy as np

from ohscore import decoders, sdr
from ohsradio.radio import Radio

from listen_helpers import TapAudio, peak_hz

FS = 2_400_000.0
BLOCK_S = 0.05                      # shack_sdr sdrplay.BLOCK_S: what SdrplaySource hands over at a time
DAB_BLOCK, MP2 = "11D", "C221"
DLS = "Shack MP2 Tone - now: 1 kHz left, 1.5 kHz right"
EMPTY_BLOCK = "12B"                 # what ohs-box was asked for; nothing on it here
HOME = 145_500_000.0
RTTY_HZ = 145_300_000.0             # both inside the span around HOME (+-1.08 MHz at 2.4 MS/s)
CW_HZ = 145_700_000.0
WFM_HZ = 144_800_000.0             # a broadcast-shaped station on the test air, 700 kHz below the dial
PARKED = "PSK library fix parked (ohs-libs fix/psk-tail-and-step)"
PSK_HZ = 145_200_000.0             # two PSK31 stations, 1000 and 1650 Hz above this USB dial
SSTV_HZ = 145_400_000.0            # an SSTV picture's 1900 Hz leader
TEXT = "CQ TEST DE GM4BRI"
# An RSP's own DC residue at the centre of every capture, about -45 dBFS:
# what Radio's DC blocker (dcBlock auto, on for device soapy) takes out
# before anything - the DAB session included - reads the samples.
DC = np.complex64(0.004 + 0.003j)


def wait(radio, cond, timeout=40.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        radio.heartbeat()
        if cond():
            return True
        time.sleep(0.05)
    return False


class Dab:
    """The transmitter model's ensemble on `block`, as simdab makes it."""

    def __init__(self, block, level_db=-30.0):
        from ohsradio.devices import simdab
        self.hz = float(sdr.load().dab.block_centre(block))
        self.loop = simdab.loop(FS) * np.float32(10 ** (level_db / 20))

    def iq(self, k, n, centre):
        if abs(self.hz - centre) > 1.0:
            return None
        return self.loop[(k + np.arange(n)) % len(self.loop)]


class Rtty:
    """shack_sdr's RTTY test signal (45.45 Bd, 170 Hz), its tones centred on
    `hz`, made at 12 kHz once and brought up to the receiver's rate."""

    def __init__(self, hz, text, level_db=-40.0):
        from shack_sdr import _native
        self.hz = hz
        z = np.frombuffer(_native.testsig_rtty(text, rate=12_000.0, centre=0.0, iq=True, lead_s=0.5,
                                               tail_s=0.5), np.complex64)
        self.z = np.tile(z, 20) * np.float32(10 ** (level_db / 20) / (np.sqrt(np.mean(np.abs(z) ** 2)) + 1e-12))

    def iq(self, k, n, centre):
        t = (k + np.arange(n)) / FS
        s = t * 12_000.0
        s = s % len(self.z)
        i = np.arange(len(self.z))
        base = np.interp(s, i, self.z.real, period=len(self.z)) + 1j * np.interp(s, i, self.z.imag,
                                                                                 period=len(self.z))
        return (base * np.exp(2j * np.pi * (self.hz - centre) * t)).astype(np.complex64)


class Wfm:
    """shack_sdr's wide FM test transmitter (stereo, RDS "TEST FM ") on
    `hz`, made at the receiver's own rate once, two seconds looped."""

    def __init__(self, hz, level_db=-30.0):
        from shack_sdr import _native
        self.hz = hz
        z = np.frombuffer(_native.testsig_wfm(seconds=2.0, rate=FS), np.complex64)
        self.z = (z * np.float32(10 ** (level_db / 20) / (np.sqrt(np.mean(np.abs(z) ** 2)) + 1e-12)))

    def iq(self, k, n, centre):
        t = (k + np.arange(n)) / FS
        return (self.z[(k + np.arange(n)) % len(self.z)] * np.exp(2j * np.pi * (self.hz - centre) * t)) \
            .astype(np.complex64)


class Iq12k:
    """A signal made at 12 kHz as complex baseband (`z`), looped, put on
    `hz` at the receiver's rate. Each 12 kHz sample is held, not
    interpolated as the Rtty class does: its images sit 12 kHz away, where
    the bank's 12 kHz channel never reaches, and np.interp on three such
    stations at 2.4 MS/s cost the stand-in so much time that the engine
    lost receive blocks (overruns) and an SSTV header with them."""

    def __init__(self, hz, z, level_db=-40.0):
        self.hz = hz
        z = np.asarray(z, np.complex64)
        self.z = z * np.float32(10 ** (level_db / 20) / (np.sqrt(np.mean(np.abs(z) ** 2)) + 1e-12))

    def iq(self, k, n, centre):
        idx = ((k + np.arange(n)) * (12_000.0 / FS)).astype(np.int64) % len(self.z)
        t = (k + np.arange(n)) / FS
        return (self.z[idx] * np.exp(2j * np.pi * (self.hz - centre) * t)).astype(np.complex64)


def psk_stations(dial, level_db=-40.0):
    """Two PSK31 stations from shack_sdr's PSK test transmitter on a USB
    `dial`: G4AAA at 1000 Hz, M0BBB at 1650 Hz - one template, both put
    at their audio offsets at 12 kHz, so the stand-in mixes one signal."""
    from shack_sdr import _native
    parts = []
    for audio_hz, text in ((1000.0, "CQ DE G4AAA G4AAA K "), (1650.0, "QRZ DE M0BBB M0BBB ")):
        z = np.frombuffer(_native.testsig_psk(text, rate=12_000.0, centre=0.0, iq=True, lead_s=1.0, tail_s=2.0),
                          np.complex64)
        parts.append(z * np.exp(2j * np.pi * audio_hz * np.arange(len(z)) / 12_000.0))
    n = max(len(p) for p in parts)
    z = np.zeros(n, np.complex64)
    for p in parts:
        z[:len(p)] += p
    return [Iq12k(dial, z, level_db + 3.0)]


def sstv_station(leader_hz, level_db=-40.0):
    """A Robot 36 picture from shack_sdr's SSTV test transmitter, its 1900 Hz
    leader on `leader_hz`, then quiet for as long again."""
    from shack_sdr import sstv
    z, sent = sstv.testsig("robot36", rate=12_000.0, iq=True, lead_s=1.0, tail_s=2.0)
    st = Iq12k(leader_hz, np.concatenate([z, np.zeros(len(z), np.complex64)]), level_db)
    st.sent = sent
    return st


MORSE = {"C": "-.-.", "Q": "--.-", "T": "-", "E": ".", "S": "...", "D": "-..", "G": "--.", "M": "--",
         "4": "....-", "B": "-...", "R": ".-.", "I": ".."}


class Cw:
    """A keyed carrier on `hz` sending `text` at `wpm`, over and over."""

    def __init__(self, hz, text, wpm=20, level_db=-40.0):
        self.hz, self.amp = hz, 10 ** (level_db / 20)
        dot = 1.2 / wpm
        keys = []
        for word in text.split():
            for ch in word:
                for sym in MORSE[ch]:
                    keys += [1] * (1 if sym == "." else 3) + [0]
                keys += [0, 0]
            keys += [0] * 4
        keys += [0] * 7
        per = int(round(dot * 1000))                  # 1 ms steps
        env = np.repeat(np.array(keys, np.float32), per)
        ramp = np.hanning(11)[:5]                     # 5 ms edges, as a keyer shapes them
        e = np.convolve(env, np.concatenate([ramp, ramp[::-1]]) / ramp.sum(), "same")
        self.env = np.clip(e, 0, 1)

    def iq(self, k, n, centre):
        t = (k + np.arange(n)) / FS
        env = self.env[((t * 1000).astype(np.int64)) % len(self.env)]
        return (self.amp * env * np.exp(2j * np.pi * (self.hz - centre) * t)).astype(np.complex64)


class RspStandIn:
    """SdrplaySource's shape (shack_sdr.sources.sdrplay): its constructor,
    open/close, antennas, centre and gain, and read() handing back 50 ms
    IqBlocks of complex64 at x/32768 numbered from the open, in real time.
    What it receives is `AIR` (class level, set by each test) plus a noise
    floor, and with `DIP` set a 1 ms stretch of nothing once every half
    second while it sits on an empty block."""

    AIR: list = []
    DIP = False
    ANTENNAS = ("Antenna A", "Antenna B", "Antenna C")

    def __init__(self, centre, rate, gain, *, serial=None, lna_state=4, antenna=None,
                 gain_model="reduction", agc_setpoint=-60):
        self.centre, self.rate, self.gain = float(centre), float(rate), gain
        self.antenna = antenna or self.ANTENNAS[0]
        self.gain_model = gain_model
        self.opened = False
        self.k = 0
        self.t0 = None
        self.rng = np.random.default_rng(5)

    def open(self):
        self.opened = True

    def close(self):
        self.opened = False

    def antennas(self):
        return list(self.ANTENNAS)

    def set_antenna(self, name):
        self.antenna = name

    def set_centre(self, hz):
        self.centre = float(hz)

    def set_gain(self, gain):
        self.gain = gain

    def gain_now(self):
        return 40.0

    def gain_sense(self):
        return {"gainIsReduction": True, "gainModel": self.gain_model, "rfgrRange": [0, 27]}

    def status(self):
        return {"kind": "sdrplay", "centre": self.centre, "rate": self.rate, "antenna": self.antenna,
                "apiGaps": 0, "apiLost": 0}

    def read(self):
        from shack_sdr.sources import IqBlock
        n = int(round(self.rate * BLOCK_S))
        now = time.monotonic()
        if self.t0 is None:
            self.t0 = now
        due = self.t0 + (self.k + n) / self.rate
        if due > now:
            time.sleep(due - now)
        z = (self.rng.standard_normal(2 * n).astype(np.float32) * np.float32(1e-3)).view(np.complex64)
        for st in self.AIR:
            if abs(st.hz - self.centre) > self.rate / 2:
                continue                # outside what the receiver hears (and it would alias in)
            y = st.iq(self.k, n, self.centre)
            if y is not None:
                z = z + y
        if self.DIP and abs(self.centre - float(sdr.load().dab.block_centre(EMPTY_BLOCK))) < 1.0:
            # What comes in through the antenna fades for a millisecond; the
            # receiver's own DC residue stays.
            t = self.k + np.arange(n)
            z = z * ((t % int(self.rate / 2)) >= int(self.rate / 1000))
        z = z + DC
        # SDRplay's int16 I and Q, scaled as SdrplaySource scales them.
        q = np.clip(np.round(z.view(np.float32) * 32768.0), -32768, 32767).astype(np.float32) / np.float32(32768)
        block = IqBlock(q.view(np.complex64), self.k, time.time(), 0)
        self.k += n
        return block


def rsp_radio(test, **over):
    """Radio on `device soapy` driver=sdrplay as ohs-box is configured,
    opened by SoapySdrplayDevice over the stand-in."""
    for p in (mock.patch("shack_sdr.sources.SdrplaySource", RspStandIn),
              mock.patch("ohscore.devices.sdrsource.soapy_has_driver", lambda d: False)):
        p.start()
        test.addCleanup(p.stop)
    from ohscore.devices import registry
    from ohscore.devices.sdrsource import SoapySdrplayDevice
    tmp = tempfile.TemporaryDirectory()
    test.addCleanup(tmp.cleanup)
    cfg = {"device": "soapy", "sampleRate": FS, "soapyArgs": "driver=sdrplay,rfgain_sel=4",
           "soapyAntenna": "Antenna C", "audioBackend": "null", "callsign": "GM4BRI", "licenceClass": "full",
           "vfo": HOME, "mode": "fm", **over}
    dev = registry.DeviceRegistry().make(dict(cfg))
    test.assertIsInstance(dev, SoapySdrplayDevice)
    audio = TapAudio()
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio, device=dev)
    r.start()
    test.addCleanup(r.stop)
    test.assertEqual((r.geo.fs, r.dev.kind), (FS, "soapy"))
    # The DC blocker, made with the first block, on the path every session
    # reads (Engine._rx_block).
    test.assertTrue(wait(r, lambda: r.dcblock is not None, timeout=5.0))
    return r, audio


def text_of(view):
    return "".join(i.get("text", "") for i in view["results"] if i.get("type") == "text")


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class ThroughTheRsp(unittest.TestCase):
    def setUp(self):
        RspStandIn.AIR = [Dab(DAB_BLOCK), Rtty(RTTY_HZ, TEXT), Cw(CW_HZ, TEXT), Wfm(WFM_HZ)]
        RspStandIn.DIP = False

    def test_a_dab_station_plays_at_2_4_ms_with_nothing_dropped(self):
        r, audio = rsp_radio(self)
        centre = float(sdr.load().dab.block_centre(DAB_BLOCK))
        sess = r.decoders.start("dab", centre, {"service": MP2})
        self.assertTrue(wait(r, lambda: (lambda m: m is not None and m.get("dls") == DLS and m.get("complete"))(
            r.decoders.session(sess["id"])["meta"])), r.decoders.session(sess["id"]))
        view = r.decoders.session(sess["id"])
        self.assertEqual((view["state"], view["why"]), ("synced", None))
        self.assertTrue(view["stats"]["sync"])
        self.assertGreater(view["stats"]["frames"], 0)
        self.assertGreater(view["stats"]["cpu"], 0)
        self.assertEqual(view["stats"]["dropped"], 0)
        self.assertEqual(r.centre, centre)
        # Its sound, 1 kHz left and 1.5 kHz right, is the receive audio.
        mark = len(audio.chunks)
        self.assertTrue(wait(r, lambda: sum(len(c) for c in audio.chunks[mark:] if c.ndim == 2) >= 48_000))
        lr = np.concatenate([c for c in audio.chunks[mark:] if c.ndim == 2])[-48_000:]
        self.assertAlmostEqual(peak_hz(lr[:, 0]), 1000.0, delta=3.0)
        self.assertAlmostEqual(peak_hz(lr[:, 1]), 1500.0, delta=3.0)

    def test_rtty_and_cw_sessions_decode_at_2_4_ms(self):
        r, _audio = rsp_radio(self)
        rtty = r.decoders.start("rtty", RTTY_HZ)
        cw = r.decoders.start("cw", CW_HZ)
        self.assertTrue(wait(r, lambda: "CQ TEST" in text_of(r.decoders.session(rtty["id"]))),
                        r.decoders.session(rtty["id"]))
        self.assertTrue(wait(r, lambda: "CQ" in text_of(r.decoders.session(cw["id"]))),
                        r.decoders.session(cw["id"]))
        for sid in (rtty["id"], cw["id"]):
            view = r.decoders.session(sid)
            self.assertIsNone(view["why"], view)
            self.assertGreater(view["stats"]["fed"], 0, view)
            self.assertEqual(view["stats"]["dropped"], 0, view)


    def test_a_wide_fm_session_reads_its_rds_at_2_4_ms(self):
        # Refused on every receiver before 23/10/2026: every unheld session
        # was started at 12 kHz. Its channel is now 240 kS/s from the bank.
        r, _audio = rsp_radio(self)
        sess = r.decoders.start("wfm", WFM_HZ)
        self.assertEqual(sess["panel"], "meta")
        self.assertTrue(wait(r, lambda: ((r.decoders.session(sess["id"])["meta"] or {}).get("ps") or "").strip()
                             == "TEST FM"), r.decoders.session(sess["id"]))
        view = r.decoders.session(sess["id"])
        self.assertIsNone(view["why"], view)
        self.assertEqual(view["stats"]["dropped"], 0, view)
        self.assertEqual(r.decoders.host.status(sess["id"])["rate"], 240_000.0)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class PskAndSstvThroughTheRsp(unittest.TestCase):
    """Milestone 2's decoders on the RSP's path, at its pace (module
    docstring). Real time: a Robot 36 picture takes 37 s."""

    def setUp(self):
        self.sstv = sstv_station(SSTV_HZ)
        RspStandIn.AIR = [*psk_stations(PSK_HZ), self.sstv]
        RspStandIn.DIP = False

    def test_an_sstv_session_at_2_4_ms(self):
        r, _audio = rsp_radio(self)
        sst = r.decoders.start("sstv", SSTV_HZ)
        self.assertTrue(wait(r, lambda: any(i.get("event") == "done" for i in r.decoders.session(sst["id"])["results"]),
                             timeout=90.0), r.decoders.session(sst["id"]))
        done = next(i for i in r.decoders.session(sst["id"])["results"] if i.get("event") == "done")
        from shack_sdr import sstv
        self.assertGreater(sstv.score(self.sstv.sent, sstv.png_rgb(r.decoders.file(done["file"])))["psnr"], 20.0)
        view = r.decoders.session(sst["id"])
        self.assertIsNone(view["why"], view)
        self.assertEqual(view["stats"]["dropped"], 0, view)

    @unittest.skipUnless(sdr.PSK_ON_SHACK_SDR, PARKED)
    def test_psk_and_sstv_sessions_at_2_4_ms(self):
        r, _audio = rsp_radio(self)
        psk = r.decoders.start("psk", PSK_HZ + 1000.0, {"channels": "0,650"})
        sst = r.decoders.start("sstv", SSTV_HZ)

        def psk_text(chan):
            return "".join(i["text"] for i in r.decoders.session(psk["id"])["results"]
                           if i.get("type") == "text" and abs(float(i["offsetHz"]) - chan) < 100)
        self.assertTrue(wait(r, lambda: "G4AAA G4AAA" in psk_text(0.0) and "M0BBB M0BBB" in psk_text(650.0)),
                        r.decoders.session(psk["id"]))
        self.assertTrue(wait(r, lambda: any(i.get("event") == "done" for i in r.decoders.session(sst["id"])["results"]),
                             timeout=90.0), r.decoders.session(sst["id"]))
        done = next(i for i in r.decoders.session(sst["id"])["results"] if i.get("event") == "done")
        from shack_sdr import sstv
        self.assertGreater(sstv.score(self.sstv.sent, sstv.png_rgb(r.decoders.file(done["file"])))["psnr"], 20.0)
        for sid in (psk["id"], sst["id"]):
            view = r.decoders.session(sid)
            self.assertIsNone(view["why"], view)
            self.assertGreater(view["stats"]["fed"], 0, view)
            self.assertEqual(view["stats"]["dropped"], 0, view)

    def test_psk_and_sstv_as_the_mode_at_2_4_ms_with_48_khz_audio(self):
        r, audio = rsp_radio(self, mode="psk31", vfo=PSK_HZ)
        self.assertEqual(r.OUT_RATE, 48_000)
        events = r.subscribe("events", 50000)
        rust = sdr.PSK_ON_SHACK_SDR
        if rust:
            r.set(pskChannels=[1650.0])
        got = []

        def heard(mode, cond):
            def check():
                got.extend(e for e in events.drain() if e.get("mode") == mode)
                return cond()
            return check
        # psk.py (the shipped decoder, ohscore/sdr.py PSK_ON_SHACK_SDR) hears
        # the station on its own channel; the Rust one, switched on, both.
        by = lambda c: "".join(e["text"] for e in got if e.get("channel", 1000.0) == c)  # noqa: E731
        self.assertTrue(wait(r, heard("psk31", lambda: "G4AAA G4AAA K" in by(1000.0)
                                      and (not rust or "M0BBB M0BBB" in by(1650.0)))), (by(1000.0), by(1650.0)))
        # The receive audio is 48 kHz all along; the decoders hear 12.
        self.assertEqual(audio.out_rate, 48_000)
        self.assertTrue(audio.chunks)
        got.clear()
        r.set(mode="sstv", vfo=SSTV_HZ - 1900.0)

        def whole():
            # Tuned in part way through a picture, the decoder starts it
            # from its line syncs (partial); the next one, a cycle later,
            # comes from its header and is whole.
            starts = {e["name"]: e for e in got if e.get("state") == "start" and not e.get("partial")}
            return any(e.get("state") == "done" and e["name"] in starts for e in got)
        self.assertTrue(wait(r, heard("sstv", whole), timeout=150.0),
                        [(e["state"], e.get("name"), e.get("partial"), e.get("fmt")) for e in got if e["state"] != "line"])
        name = next(e["name"] for e in got if e.get("state") == "start" and not e.get("partial"))
        self.assertGreater(len({e["line"] for e in got if e.get("state") == "line" and e["name"] == name}), 230)
        self.assertEqual(r.decoders.session("vfo")["stats"]["dropped"], 0)


@unittest.skipUnless(sdr.available(), "no shack_sdr for this machine")
class AFadingEmptyBlock(unittest.TestCase):
    """The input that held ohs-box's decoder thread (module docstring),
    with the shack_sdr whose search always moves on (ohs-libs 23b437c)."""

    def setUp(self):
        RspStandIn.AIR = [Dab(DAB_BLOCK), Rtty(RTTY_HZ, TEXT)]
        RspStandIn.DIP = True

    def test_decodes_as_noise_says_nothing_false_and_the_next_station_plays(self):
        r, _audio = rsp_radio(self)
        toasts = r.subscribe("toast", 100)
        said = Said()
        self.addCleanup(logging.getLogger("ohscore.decoders").removeHandler, said)
        dab = r.decoders.start("dab", None, {"block": EMPTY_BLOCK, "service": ""})
        # The fade comes round twice a second; with the old search the
        # decoder stuck within two seconds and the watch said so five
        # seconds after that. Twelve seconds of it here, decoded.
        until = time.monotonic() + 12.0
        wait(r, lambda: time.monotonic() > until, timeout=20.0)
        view = r.decoders.session(dab["id"])
        stats = view["stats"]
        self.assertEqual((view["state"], view["why"]), ("nosignal", None), view)
        self.assertEqual(stats["dropped"], 0, view)
        self.assertGreater(stats["fed"], 10 * FS, view)
        self.assertGreater(stats["cpu"], 0, view)
        self.assertEqual(said.about(dab["id"]), [])
        self.assertEqual([it for it in toasts.drain() if "stopped responding" in it.get("text", "")], [])
        # Stopping it gives the receiver back: an RTTY session decodes, and
        # the next DAB station plays.
        self.assertTrue(r.decoders.stop(dab["id"]))
        self.assertEqual(r.state()["rxOwner"], {})
        RspStandIn.DIP = False
        self.assertTrue(wait(r, lambda: abs(r.centre - HOME) < FS / 2 and r._rx_settled()))
        rtty = r.decoders.start("rtty", RTTY_HZ)
        self.assertTrue(wait(r, lambda: "CQ TEST" in text_of(r.decoders.session(rtty["id"]))),
                        r.decoders.session(rtty["id"]))
        self.assertTrue(r.decoders.stop(rtty["id"]))
        centre = float(sdr.load().dab.block_centre(DAB_BLOCK))
        again = r.decoders.start("dab", centre, {"service": MP2})
        self.assertTrue(wait(r, lambda: (r.decoders.session(again["id"])["meta"] or {}).get("dls") == DLS),
                        r.decoders.session(again["id"]))


class Said(logging.Handler):
    """The decoders' log warnings from now until the test ends."""

    def __init__(self):
        super().__init__(logging.WARNING)
        self.lines: list[str] = []
        logging.getLogger("ohscore.decoders").addHandler(self)

    def emit(self, record):
        self.lines.append(record.getMessage())

    def about(self, sid):
        return [m for m in self.lines if sid in m and "dropped" in m]


class TheWatch(unittest.TestCase):
    """decoders.starvation on (t, fed, dropped) once a second."""

    def series(self, fed_per_s, dropped_per_s, n=4, start=(0, 0)):
        return [(float(i), start[0] + i * fed_per_s, start[1] + i * dropped_per_s) for i in range(n)]

    def test_everything_dropped_is_stuck(self):
        self.assertEqual(decoders.starvation(self.series(2_400_000, 2_400_000), None, 0.0), "decoder_stuck")
        # Exactly all of it, whatever the CPU figure says.
        self.assertEqual(decoders.starvation(self.series(2_400_000, 2_400_000), None, 0.3), "decoder_stuck")

    def test_most_dropped_with_no_decoding_time_is_stuck(self):
        # A channel of the bank: blocks of uneven length, so not quite all.
        self.assertEqual(decoders.starvation(self.series(12_000, 11_500), None, 0.0), "decoder_stuck")

    def test_most_dropped_while_decoding_is_behind(self):
        self.assertEqual(decoders.starvation(self.series(2_400_000, 2_200_000), None, 0.8), "decoder_behind")

    def test_a_ring_still_filling_is_not_starved(self):
        # Two seconds of ring take two seconds of a stuck decoder's input.
        self.assertIsNone(decoders.starvation(self.series(2_400_000, 800_000), None, 0.0))

    def test_it_ends_when_less_than_half_is_dropped(self):
        self.assertEqual(decoders.starvation(self.series(12_000, 7_000), "decoder_behind", 0.1), "decoder_behind")
        self.assertIsNone(decoders.starvation(self.series(12_000, 5_000), "decoder_behind", 0.1))

    def test_too_short_a_window_or_nothing_fed_keeps_what_was_said(self):
        self.assertEqual(decoders.starvation(self.series(12_000, 12_000, n=2), "decoder_stuck", 0.0),
                         "decoder_stuck")
        self.assertIsNone(decoders.starvation(self.series(12_000, 12_000, n=2), None, 0.0))
        self.assertEqual(decoders.starvation(self.series(0, 0), "decoder_behind", 0.0), "decoder_behind")


if __name__ == "__main__":
    unittest.main()
