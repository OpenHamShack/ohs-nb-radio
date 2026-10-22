"""A simulated QO-100 narrowband downlink, and our own uplink coming back.

The default device: the whole program can be built, demonstrated and tested
without a dish. It produces the IF the SDR would see - transponder noise
hump over the receiver floor, the four beacons (the middle one sending
text blocks, midbeacon.py), a KG-STV picture now and then (kgsim.py), a
population of SSB, CW, FT8, Q65, JS8 (digisim.py),
PSK31 and RTTY stations - with an LNB that is off frequency and wanders, and
it closes the loop: whatever the engine writes to the transmitter is shifted
by a chosen uplink error, sent "up" and comes back ~0.25 s later at a level
set by the TX gain. That is what lets beacon lock and TX lock be proven end
to end in tests.

The population is sized for what the band actually looks like on a weekend
evening - 15-30 SSB QSOs, a CW segment that is never quite empty, a cluster
around the FT8 calling frequency, a handful of PSK/RTTY - but nobody is on
frequency for the whole session: each station has a `Presence`, on the air
for a few minutes then gone for a few more, the way operators actually come
up, work a contact or two and leave. A roster that is only ever partly on
air is also how the population stays affordable: `_generate()` skips a
silent station before it reaches the synthesiser, so the cost that matters
(concurrently active stations) stays well short of the roster size.

Cost: every station is a precomputed 12 kHz loop placed by the same
overlap-save synthesis the transmitter uses (one inverse FFT per 15 ms frame
for the whole band), and the noise is drawn from a bank of pre-shaped random
spectra. Generating 1.2 MS/s costs a few tens of a per cent of one core -
`python3 -m ohsnb.bench` reports it, and is how this population was sized.

Frequency model (all Hz), matching DESIGN.md's vocabulary:
  received IF of a downlink signal  = dl - LNB LO + rxErr(t)   (LO: the receive converter's)
  rxErr(t) = simRxErrorHz + slow drift        (what beacon lock must find)
  our real uplink = TX LO + baseband offset + simUlErrorHz   (what TX lock must find)
  our downlink    = real uplink + 8089.5 MHz
"""
from __future__ import annotations

import math
import threading
import time

import numpy as np

from ohscore.devices import simsignals as sg
from ohscore.devices.simcore import FT8Activity, Presence, SimCore, Station
from ohscore.dsp.bank import Geometry, Source, Synthesis
from ohscore.dsp.mod import SsbMod

from ohsnb.i18n import _

from .. import bandplan
from .. import converters as nbconv
from ..kgstvrx import DL as KGSTV_DL
from . import digisim, kgsim, midbeacon, mmbeacon

BEACON_DB = -40.0          # middle beacon level, dBFS
NOISE_DB_HZ = -101.0       # transponder noise density in the passband, dBFS/Hz
FLOOR_DB_HZ = -110.0       # receiver noise floor outside it


class SimDevice(SimCore):
    kind = "sim"

    def __init__(self, cfg: dict, fs: float = 1_200_000.0):
        self.cfg = cfg
        self.fs = float(fs)
        self.geo = Geometry(self.fs)
        self.syn = Synthesis(self.geo)
        # The simulated LNB is the receive converter the settings name, and
        # the Pluto's transmit converter (if any) sits in its loop, so the
        # simulator hears exactly what the engine's conversions would put
        # on the air (ohsnb/converters.py).
        self.lnb_lo = nbconv.rx_lo(cfg)
        self.tx_conv = nbconv.tx_converter(cfg) if cfg.get("txRadio", "sdr") == "sdr" else None
        self.rx_err0 = float(cfg.get("simRxErrorHz", 1800.0))
        self.drift_hz = float(cfg.get("simDriftHz", 400.0))
        self.drift_sec = float(cfg.get("simDriftSec", 600.0))
        self.ul_err = float(cfg.get("simUlErrorHz", -11_000.0))
        self.ref_gain = float(cfg.get("simRefGainDb", -20.0))
        self.signals = bool(cfg.get("simSignals", True))
        self.realtime = bool(cfg.get("simRealtime", True))
        self.rtt = 0.25
        seed = int(cfg.get("simSeed", 0)) or None
        self.rng = np.random.default_rng(seed)
        self.drift_phase = self.rng.uniform(0, 2 * math.pi, 2)
        self.rx_if = bandplan.BEACONS["middle"]["dl"] - 3500.0 - self.lnb_lo
        self.n = 0                      # samples produced
        self.out = np.zeros(0, np.complex64)
        self.opened = False
        self.external = None
        self.ext_hist: list = []
        # Other simulated stations this one's transponder relays to
        # (attach_peer), and what they have sent this one, not yet heard.
        self.peers: list = []
        self.peer_cond = threading.Condition()
        self.peer_q: list[tuple[np.ndarray, float]] = []
        self.peer_len = 0
        self.peer_phase = 0.0
        self.peer_src = None
        self._init_loop()
        self.loop_invert = bool(self.tx_conv is not None and self.tx_conv.inverted)

    # -- the LNB ------------------------------------------------------------
    def rx_err(self, t: float) -> float:
        """How far high everything appears at sim time t (s since open): a
        smooth temperature-like wander of +-simDriftHz over simDriftSec,
        starting exactly at simRxErrorHz."""
        a, T = self.drift_hz, self.drift_sec
        p1, p2 = self.drift_phase

        def w(tt):
            return 0.75 * math.sin(2 * math.pi * tt / T + p1) + 0.25 * math.sin(2 * math.pi * tt * 2.7 / T + p2)

        return self.rx_err0 + a * (w(t) - w(0.0))

    # -- set-up -------------------------------------------------------------
    def open(self) -> None:
        if self.opened:
            return
        rng = self.rng
        self.t_epoch = time.time()
        self.t_wall0 = time.monotonic()
        B = bandplan.BEACONS
        bdb = BEACON_DB
        # The middle beacon used to be random BPSK drawn from rng; it is now
        # real text blocks (midbeacon.py). The draw is still made, and
        # discarded, so a seeded simulator's band - every station after the
        # beacons - is the same as it always was.
        sg.bpsk_beacon(rng, 20.0)
        self.stations: list = [
            Station("lower beacon", B["lower"]["dl"],
                    sg.f1a_beacon(sg.BEACON_TEXT, sg.BEACON_WPM, carrier=sg.BEACON_CARRIER_S,
                                  tail=sg.BEACON_GAP_S), bdb + 1),
            Station("middle beacon", B["middle"]["dl"], midbeacon.template(), bdb),
            Station("multimedia beacon", B["mm"]["dl"], mmbeacon.template(rng), bdb - 3),
            # Space 10490.000, mark 400 Hz below, keyed as the lower beacon
            # is (bandplan.BEACONS, from the recording of 07/10/2026).
            Station("upper beacon", B["upper"]["dl"],
                    sg.f1a_beacon(sg.BEACON_TEXT, sg.BEACON_WPM, mark_high=False, carrier=sg.BEACON_CARRIER_S,
                                  tail=sg.BEACON_GAP_S), bdb - 2),
            # Not a beacon, but always there, as the beacons are: a KG-STV
            # picture every ~90 s (kgsim.py), so the picture receiver has
            # something to show with the band's population off. No draw
            # from rng: a seeded band stays as it was.
            Station("KG-STV", KGSTV_DL, kgsim.template(), bdb - 6),
        ]
        if self.signals:
            self._populate(rng)
            # After the rest, and drawing nothing from rng: the band a seed
            # gave before Q65 and JS8 were on it is the band it gives now.
            self.stations.extend(digisim.stations())
        for st in self.stations:
            st.src = Source(self.geo, int(round(self.fs / sg.RATE)), 0.0)
        self._noise_bank(self.rx_err(0.0))
        # Real-time pacing starts now, not before the templates were built,
        # or the first read would race to "catch up" a second of signal.
        self.t_wall0 = time.monotonic()
        self.opened = True

    # What add_station() can put on the band. Each is something that has
    # fooled, or could fool, beacon lock on the air: a bare carrier, a
    # voice station (Ray, 05/10: SSB next to the middle beacon pulled the
    # lock onto itself), and a second BPSK beacon, which no detector can
    # tell from the real one - only the operator can (click-to-lock).
    # "talk-usb" and "talk-lsb" are conversational voices (sg.voice, the
    # band's own SSB template, talking all the time) for auto-tune and best
    # audio, whose harmonic stage needs the pitch to move as speech does.
    # "leila" is AMSAT-DL's LEILA siren as measured on 17/10/2026 (docs/
    # qo100-research.md section 9): tones at `dl` and 205 Hz above it, 200 ms
    # each in turn, for 5 s of every 15 - for the over-power watch.
    EXTRA_KINDS = ("carrier", "usb", "lsb", "bpsk", "talk-usb", "talk-lsb", "leila")

    def add_station(self, kind: str, dl: float, level_db: float, seed: int = 11) -> None:
        """Put one more signal on the simulated band after open(): `kind`
        from EXTRA_KINDS at downlink `dl` (an SSB station's dial), at
        `level_db` dBFS (the middle beacon is BEACON_DB). For the tests
        that prove beacon lock is not fooled, and for trying it by hand."""
        if kind not in self.EXTRA_KINDS:
            raise ValueError(_("kind must be one of {kinds}").format(kinds=", ".join(self.EXTRA_KINDS)))
        rng = np.random.default_rng(seed)
        if kind == "carrier":
            tpl = np.ones(4096, np.complex64)
        elif kind == "bpsk":
            tpl = sg.bpsk_beacon(rng, 20.0)
        elif kind == "leila":
            t = np.arange(int(15.0 * sg.RATE)) / sg.RATE
            upper = (t // 0.2).astype(int) % 2 == 1
            ph = 2 * np.pi * np.cumsum(np.where(upper, 205.0, 0.0)) / sg.RATE
            tpl = (np.exp(1j * ph) * (t < 5.0)).astype(np.complex64)
        elif kind.startswith("talk-"):
            tpl = sg.voice(rng, 30.0)
            if kind == "talk-lsb":
                tpl = np.conj(tpl)
        else:
            # Sustained vowels, talking all the time: the worst case for a
            # squaring detector (sg.sustained_voice says why).
            tpl = sg.sustained_voice(rng, 30.0)
            if kind == "lsb":
                tpl = np.conj(tpl)
        st = Station(f"extra {kind}", float(dl), tpl, level_db)
        st.src = Source(self.geo, int(round(self.fs / sg.RATE)), 0.0)
        self.stations.append(st)

    @staticmethod
    def _level(rng, lo: float, hi: float, strong: tuple[float, float] = (-45.0, -38.0),
               strong_p: float = 0.12) -> float:
        """Most stations sit somewhere in the ordinary [lo, hi] range (down to
        barely poking out of the noise); occasionally, like a real band, one
        is running enough power to sit close under the beacon."""
        return float(rng.uniform(*strong) if rng.random() < strong_p else rng.uniform(lo, hi))

    def _spaced_dial(self, rng, lo: float, hi: float, used: list[float], min_spacing: float = 1800.0) -> float:
        """A dial inside [lo, hi), kept at least `min_spacing` from every
        dial already chosen where that's achievable - real signals do sit
        close together, so a handful of tries (not an exhaustive search) is
        enough: it thins out crowding without forcing a perfect grid."""
        best, best_gap = None, -1.0
        for _ in range(12):
            cand = float(rng.integers(int(lo), int(hi)) // 100 * 100)
            gap = min((abs(cand - u) for u in used), default=min_spacing)
            if gap >= min_spacing:
                return cand
            if gap > best_gap:
                best, best_gap = cand, gap
        return best

    def _populate(self, rng):
        calls = ["G4XYZ", "DL1ABC", "EA4QRP", "F5KLM", "OH8ZZ", "PA3QOS", "ON4BB", "SV1QO", "I0XYZ", "OE3ABC",
                 "SP5QO", "HB9QQ", "GM4SAT", "CT1QO", "LA9NB", "EI7ABC", "F4GHI", "DK2JKL", "SM0MNO", "9A1PQR",
                 "IW2STU", "OZ3VWX", "PE1YZA", "HA5BCD"]
        rng.shuffle(calls)

        def ident():
            return calls[int(rng.integers(0, len(calls)))]

        # SSB QSOs: two stations on (almost) the same dial taking turns, like
        # a real contact - 15-30 of them on a busy evening, spread over both
        # SSB-only segments plus the mixed-modes/contest segment where SSB
        # also runs. Each dial's Presence covers both halves: the pair comes
        # up and leaves together, since they're one QSO, not two stations.
        n_ssb = int(rng.integers(18, 28))
        ssb_bands = [(10_489_655_000.0, 10_489_740_000.0), (10_489_760_000.0, 10_489_845_000.0),
                     (10_489_870_000.0, 10_489_980_000.0)]
        weights = np.array([hi - lo for lo, hi in ssb_bands])
        weights = weights / weights.sum()
        used: list[float] = []
        for _ in range(n_ssb):
            lo, hi = ssb_bands[int(rng.choice(len(ssb_bands), p=weights))]
            dial = self._spaced_dial(rng, lo, hi, used)
            used.append(dial)
            loop = float(rng.uniform(24, 40))
            # A real evening has the SSB segments close to full most of the
            # time - the 15-30 QSOs this is sized for are meant to be seen
            # together, not glimpsed one at a time - so on (4-12 min) far
            # outweighs off (20-90 s): a contact finishing clears a slot for
            # only a little while before someone else is on it.
            pres = Presence(rng, (240.0, 720.0), (20.0, 90.0))
            level = self._level(rng, -70.0, -50.0)
            for talk, d in [((0.0, 0.5), 0.0), ((0.5, 1.0), rng.uniform(-40, 40))]:
                self.stations.append(Station(f"SSB {dial / 1e6:.3f}", dial + d, sg.voice(rng, loop, talk),
                                             level, presence=pres))
        # CW segment: never silent for long, but not every station there all
        # the time either.
        for _ in range(int(rng.integers(6, 9))):
            a, b = ident(), ident()
            dial = float(rng.integers(10_489_508_000, 10_489_538_000) // 10 * 10)
            wpm = float(rng.uniform(16, 28))
            text = f"CQ CQ DE {a} {a} K   {a} DE {b} GM UR 599 599 TU {b} K"
            self.stations.append(Station(f"CW {a}", dial, sg.cw_station(rng, text, wpm, 40.0),
                                         self._level(rng, -68.0, -50.0, strong_p=0.08),
                                         presence=Presence(rng, (60.0, 240.0), (60.0, 480.0))))
        self.stations.append(FT8Activity(rng, 10_489_540_000.0, float(rng.uniform(-62, -56)), 0.0))
        # PSK31 shares one carrier dial (as it does in practice, in the
        # narrow-digimode segment); RTTY gets two dials in the wider
        # digimode segment. "A few" of each, each with its own comings and
        # goings - digital QSOs tend to run longer than voice ones.
        for k in range(3):
            self.stations.append(Station(f"PSK31 {k}", 10_489_568_500.0,
                                         sg.psk_like(rng, 40.0, 31.25, 500 + 700 * k, (0.08 * k, 0.55 + 0.25 * k)),
                                         self._level(rng, -66.0, -56.0, strong_p=0.05),
                                         presence=Presence(rng, (180.0, 600.0), (120.0, 900.0))))
        for k in range(2):
            self.stations.append(Station(f"RTTY {k}", 10_489_596_000.0 + k * 2500.0,
                                         sg.fsk_tones(rng, 40.0, 45.45, 170.0, 2000.0 + k * 300.0, (0.0, 0.7)),
                                         self._level(rng, -64.0, -56.0, strong_p=0.05),
                                         presence=Presence(rng, (150.0, 480.0), (120.0, 720.0))))

    def _noise_density(self, f: np.ndarray, err: float) -> np.ndarray:
        dl = f + self.rx_if + self.lnb_lo - err
        # Transponder hump with ~8 kHz raised-cosine skirts over the receiver floor.
        edge = 8_000.0
        inside = np.clip(np.minimum(dl - (bandplan.DL_LO - edge / 2), (bandplan.DL_HI + edge / 2) - dl) / edge, 0, 1)
        hump = 0.5 - 0.5 * np.cos(np.pi * inside)
        return 10 ** (FLOOR_DB_HZ / 10) + 10 ** (NOISE_DB_HZ / 10) * hump

    # -- receive ------------------------------------------------------------
    def set_rx_if(self, hz: float) -> None:
        self.rx_if = float(hz)

    def _generate(self, m: int) -> np.ndarray:
        g = self.geo
        t_mid = (self.n + m * g.L / 2) / self.fs
        err = self.rx_err(t_mid)
        if abs(err - self.bank_err) > 1500 or self.rx_if != self.bank_if:
            self._noise_bank(err)
        hop = g.L // int(round(self.fs / sg.RATE))
        feeds = []
        t_abs = self.t_epoch + self.n / self.fs
        for st in self.stations:
            st.src.freq = st.dl - self.lnb_lo + err - self.rx_if
            if abs(st.src.freq) > self.fs * 0.5 - 8000:
                continue
            if isinstance(st, (FT8Activity, digisim.SlotActivity)):
                feeds.append((st.src, st.take(m * hop, t_abs)))
                continue
            # A station whose Presence says it's off air right now costs
            # nothing beyond this check: skipped before take() or the
            # synthesiser's FFT, which is where a roster this size would
            # otherwise be spent - see the module docstring. Presence runs on
            # t_mid (seconds since this sim opened), not t_abs (wall-clock
            # epoch, which the slotted modes need for real UTC slot timing): a
            # station's schedule must depend only on simSeed, not on what
            # time of day the test or demo happens to run.
            gain = st.presence.gain(t_mid) if st.presence is not None else 1.0
            if gain <= 0.0:
                continue
            feeds.append((st.src, st.take(m * hop, gain)))
        if self.external is not None:
            feeds.extend(self._external_feed(m * hop, t_mid, err))
        pick = self.rng.integers(0, len(self.bank), m)
        rot = np.array([1, 1j, -1, -1j], np.complex64)[self.rng.integers(0, 4, m)]
        extra = self.bank[pick] * rot[:, None]
        y = self.syn.render(m, feeds, extra)
        if self.peers_in:
            self._peer_feed(y, err)
        self._loopback(y, err)
        self.n += m * g.L
        return y

    # -- an external transmitter ---------------------------------------------
    def attach_external(self, fn, audio=None) -> None:
        """Put another transmitter's signal through the simulated transponder:
        `fn()` returns (uplink Hz, "carrier", "voice" or "audio", level in dB
        relative to the beacon) while it transmits, else None. It is asked as
        each block is generated and what it says comes down `rtt` later, as a
        real uplink would. This is how the IC-9700 emulator
        (ohscore/rig/civsim.py) is heard on the simulator: tests and the demo
        hand it a function that reads the emulated radio's frequency and
        transmit state.

        "audio" is what the radio's USB sound device is playing, in USB:
        `audio(n)` gives the next n samples at 12 kHz (real, the radio's
        modulator input), asked for only while it transmits. That is how
        NB's own CAT PTT overs (FT8, PSK...) go up through the emulated
        9700 with their real tones, for TX lock to find."""
        ext_rng = np.random.default_rng(4242)
        self.ext_st = {"carrier": Station("external carrier", 0.0, np.ones(4096, np.complex64), 0.0),
                       "voice": Station("external voice", 0.0, sg.voice(ext_rng, 8.0), 0.0)}
        for st in self.ext_st.values():
            st.src = Source(self.geo, int(round(self.fs / sg.RATE)), 0.0)
        self.ext_hist = []
        self.external = fn
        # The radio's modulator: the sound card's audio as USB baseband,
        # through a delay line `rtt` long so it comes down when the rest does.
        self.ext_audio = audio
        self.ext_mod = SsbMod(sg.RATE)
        self.ext_mod.configure(100.0, 2950.0, 0.0, 0.0, False, "usb")
        self.ext_line = np.zeros(int(round(self.rtt * sg.RATE)), np.complex64)
        self.ext_audio_src = Source(self.geo, int(round(self.fs / sg.RATE)), 0.0)

    def _external_feed(self, n: int, t: float, err: float) -> list:
        try:
            now = self.external()
        except Exception:  # noqa: BLE001 - a test's emulator going away mid-run is silence, not a crash
            now = None
        self.ext_hist.append((t, now))
        sent = None
        if self.ext_audio is not None:
            a = np.zeros(n, np.float32)
            if now and now[1] == "audio":
                got = np.asarray(self.ext_audio(n), np.float32)[:n]
                a[:len(got)] = got
            z = self.ext_mod(a)
            # Above its Po knee the radio's output is its RF POWER setting,
            # whatever the audio level (GUIDE §5): full scale here, so
            # `level` alone sets where it comes down against the beacon.
            peak = float(np.max(np.abs(z))) if len(z) else 0.0
            if peak > 1e-3:
                z = z / np.float32(peak)
            self.ext_line = np.concatenate([self.ext_line, z])
            sent, self.ext_line = self.ext_line[:n], self.ext_line[n:]
        past = None
        while self.ext_hist and self.ext_hist[0][0] <= t - self.rtt:
            past = self.ext_hist.pop(0)
        if past is not None:
            self.ext_now = past[1]
        cur = getattr(self, "ext_now", None)
        if not cur:
            return []
        ul_hz, kind, level = cur
        if kind == "audio":
            if sent is None:
                return []
            src = self.ext_audio_src
            src.freq = ul_hz + bandplan.TRANSPONDER_LO - self.lnb_lo + err - self.rx_if
            if abs(src.freq) > self.fs * 0.5 - 8000:
                return []
            return [(src, sent * np.float32(10 ** ((BEACON_DB + level) / 20)))]
        st = self.ext_st[kind]
        st.amp = 10 ** ((BEACON_DB + level) / 20)
        st.src.freq = ul_hz + bandplan.TRANSPONDER_LO - self.lnb_lo + err - self.rx_if
        if abs(st.src.freq) > self.fs * 0.5 - 8000:
            return []
        return [(st.src, st.take(n))]

    # -- other simulated stations ----------------------------------------------
    # Two engines on two simulators, one transponder: what one sends, the
    # other hears - as it hears itself, through the same delay, level and
    # uplink error, then through its own LNB's error. For station-to-station
    # modes (HSmodem) tested end to end with no radio. The simulators run
    # in lock step while one transmits: the listener waits for the sender's
    # next block rather than hearing a gap, and the sender waits while the
    # listener has more than PEER_AHEAD seconds unheard, so two simulators
    # running faster than real time stay together.
    PEER_AHEAD = 1.0
    PEER_WAIT = 2.0

    @property
    def peers_in(self) -> bool:
        return bool(getattr(self, "senders", None))

    def attach_peer(self, other: "SimDevice") -> None:
        """Let `other` hear what this simulator transmits (one way; call
        both ways round for a two-way link)."""
        self.peers.append(other)
        if not hasattr(other, "senders"):
            other.senders = []
        other.senders.append(self)

    def _sending(self) -> bool:
        with self.cond:
            return self.tx_active or self.fifo_len > 0 or self.delay_live > 0

    def _uplink_out(self, back: np.ndarray, tx_lo: float) -> None:
        if not self.peers:
            return
        up = (self.tx_conv.air(tx_lo, tx=True) if self.tx_conv is not None else tx_lo) + self.ul_err
        for p in self.peers:
            p._peer_in(back, up)

    def _peer_in(self, x: np.ndarray, ul: float) -> None:
        with self.peer_cond:
            deadline = time.monotonic() + self.PEER_WAIT
            while self.peer_len > self.PEER_AHEAD * self.fs and not self.closed and time.monotonic() < deadline:
                self.peer_cond.wait(0.1)
            self.peer_q.append((np.asarray(x, np.complex64), float(ul)))
            self.peer_len += len(x)
            self.peer_cond.notify_all()

    def _peer_feed(self, y: np.ndarray, err: float) -> None:
        """Add what the attached senders sent (their uplink, through our
        LNB) to this block, waiting for it while one of them is on air."""
        k = len(y)
        take = np.zeros(k, np.complex64)
        ul = None
        with self.peer_cond:
            deadline = time.monotonic() + self.PEER_WAIT
            while (self.peer_len < k and any(s._sending() for s in self.senders) and not self.closed
                   and time.monotonic() < deadline):
                self.peer_cond.wait(0.05)
            i = 0
            while self.peer_q and i < k:
                a, ul = self.peer_q[0]
                c = min(len(a), k - i)
                take[i:i + c] = a[:c]
                if c == len(a):
                    self.peer_q.pop(0)
                else:
                    self.peer_q[0] = (a[c:], ul)
                i += c
            self.peer_len -= i
            self.peer_cond.notify_all()
        if ul is None:
            return
        shift = ul + bandplan.TRANSPONDER_LO - self.lnb_lo + err - self.rx_if
        ph = self.peer_phase + 2 * np.pi * shift / self.fs * np.arange(k)
        y += take * np.exp(1j * ph).astype(np.complex64)
        self.peer_phase = float((self.peer_phase + 2 * np.pi * shift / self.fs * k) % (2 * np.pi))

    def _loopback_amp(self, tx_gain: float) -> float:
        # Our signal comes down at the beacon's level when the TX gain is
        # simRefGainDb, and scales dB for dB from there.
        return 10 ** (BEACON_DB / 20) * 10 ** ((tx_gain - self.ref_gain) / 20)

    def _loopback_shift(self, tx_lo: float, err: float) -> float:
        # Up at the TX LO plus the uplink error, through the transponder,
        # down through the LNB, relative to where the receiver is tuned.
        up = self.tx_conv.air(tx_lo, tx=True) if self.tx_conv is not None else tx_lo
        return up + self.ul_err + bandplan.TRANSPONDER_LO - self.lnb_lo + err - self.rx_if

    def status(self) -> dict:
        return {
            "kind": "sim", "fs": self.fs, "rxIf": self.rx_if, "simRxErr": round(self.rx_err(self.n / self.fs), 1),
            "simUlErr": self.ul_err, "txLo": self.tx_lo, "txGain": self.tx_gain, "txActive": self.tx_active,
            "underruns": self.underruns, "stations": len(getattr(self, "stations", [])),
            "seconds": round(self.n / self.fs, 1),
        }
