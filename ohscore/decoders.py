"""Decoder sessions inside the engine: shack_sdr's host, fed from the
engine's own filter bank (RADIO-SDR-PLAN §3, §4.3).

    radio.decoders.catalogue()                     every decoder, whichever library decodes it
    radio.decoders.start("rtty", 14_083_500, baud=45.45)   -> the session (a dict); raises Refused
    radio.decoders.stop(id); .sessions(); .session(id, since=rev); .codecs(rescan=False)

**One host per running radio**, made by Engine.start() and closed by
Engine.stop() before the device is: its worker threads decode with the GIL
released, so a session costs the receive thread one channel of the bank
and a copy, never the decoding. The host holds no hardware, so closing it
never delays the broker's release.

**Two kinds of session.** The mode decoder - RTTY today - is a session
whose input is the VFO's 12 kHz audio (modes/sdrmode.py); it is listed as
`vfo` and its results become today's `events` items. A fixed session is
independent of the dial: the engine cuts a 12 kHz channel at its frequency
from the bank (the same `Channel` the VFO, zoom and the CW skimmer use;
no second channeliser, §3.3) and feeds that IQ. Fixed sessions are saved in
the settings (decoderSessions) and start again with the radio.

**The span.** The receiver covers what its sample rate covers around the
dial, so a session the operator tuned away from goes `outside` and is fed
nothing, and comes back by itself when the span covers it again - the CW
skimmer's rule (ENGINE-API "cwskim"). Its results stop; it is not stopped.

**Results** carry `session`, `rev` (rising by one per result, so a gap says
one was missed), `t` (UTC from the samples) and `type`. The supervisor
polls the host ten times a second: each result goes on the `decoders`
feed, and the last RESULTS_KEPT (or RESULTS_S seconds) of each session are
kept for a client that missed some (api/decoders/sessions/{id}?since=).

**Codes, not sentences, from shack_sdr.** Its `why`s and refusals are
codes; this module words them (WHY, Refused) from the catalog, and keeps
the code beside the sentence so a client can prefer its own translation.

**Held sessions: a decoder that takes the whole receiver.** DAB decodes a
1.536 MHz block from IQ at 2.048 MS/s or more - no channel of the bank is
that wide - so a DAB session is not cut from the bank: it takes the
receiver (Engine.hold_receiver), which goes to the block's centre and is
fed whole, at the device's own rate (shack_sdr resamples anything above
2.048 MS/s). Its sound replaces the demodulator's on the ordinary receive
audio at the app's rate (held_audio), so every listener and every
recording hears the station with no new path. Only one session may hold
the receiver; it is never saved in decoderSessions or started again with
the radio, because a start that silently retuned the radio to Band III
would be a surprise and would lose the operator's dial. Stopping it, or
the radio, gives the receiver back with the dial and mode from before.

The block comes from `freqHz` (the block's centre, the dial a client
shows) or `params.block` ("11D"), either one; both must agree. What plays
is `params.service` (a service id in hex, "" to list the ensemble without
playing), changed live (configure). The session's `meta` is the
ensemble's feed (shack_sdr README "DAB"): each `why` in it is worded here
as `whyText`, the feed's and each service's, and `dls` is the playing
service's programme text.
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np

from . import host, hostlibs, sdr
from .dsp.bank import Channel
from .i18n.text import _

log = logging.getLogger("ohscore.decoders")

AUDIO_RATE = 12_000.0
VFO = "vfo"
# A decoder needing this many samples a second or more cannot be cut from
# the bank (its widest channel is wide FM's 240 kS/s): it holds the receiver.
RECEIVER_RATE = 1_000_000.0
# How long a held session may give no sound before silence is played in its
# place: DAB's sound comes a 24 ms frame or a 120 ms super frame at a time,
# so most blocks bring none, but a session with no sync (or a DAB+ station
# without faad2) must not leave listeners with no stream at all.
DRY_S = 0.5
RESULTS_KEPT = 500
RESULTS_S = 30 * 60.0
# How much of each edge of the bank's span a session's channel may not
# reach into: the bank's own guard (the wide scope shows USABLE of fs).
SPAN_USABLE = 0.9


def _why_text(code: str | None) -> str:
    """The catalog's sentence for a session's `why` code ("" for none)."""
    if not code:
        return ""
    words = {
        "outside_span": _("Its frequency is outside what the receiver covers now; it carries on when you tune back."),
        "cpu_budget": _("Paused: the decoders are using all the processor time they are allowed (Settings › "
                        "Decoders)."),
        "panic": _("The decoder failed and was stopped; the log has the details."),
        "exception": _("The decoder failed and was stopped; the log has the details."),
        "not_installed": _("The library that decodes this is not installed."),
        "mode_only": _("This decoder runs only as the radio's mode, not on a frequency of its own."),
        "radio_stopped": _("The radio is not running."),
        "receiver_fixed": _("This app's receiver stays on its own frequencies and cannot play DAB"),
        # DAB (shack_sdr README "DAB": the feed's and a service's codes,
        # worded as the README suggests).
        "no_signal": _("No DAB signal on this block."),
        "no_sync": _("A signal, but not DAB, or too weak to lock to."),
        "fic_errors": _("DAB heard, but too weak to read the station list."),
        "service_not_found": _("This station is not on this block."),
        "needs_codec:faad2": faad2_sentence(),
        "codec_config": _("faad2 could not play this station's sound."),
        "codec_open": _("faad2 could not play this station's sound."),
        "unsupported_protection": _("This station uses a coding Radio cannot read."),
    }
    return words.get(code, _("Stopped ({code}).").format(code=code))


def faad2_sentence() -> str:
    """Why a DAB+ station is silent without faad2, for where this runs: a
    desktop installs it, a controller's administrator does, and a
    controller too old for host libraries has to be updated first."""
    if hostlibs.controller_too_old():
        return hostlibs.update_sentence()
    if host.STORE:
        return _("Needs faad2: ask your controller's administrator to install it (Controller › Optional "
                 "libraries) to hear DAB+ stations.")
    return _("Needs faad2: install it to hear DAB+ stations. Radio never includes it: see Help › Codecs.")


class Refused(ValueError):
    """A session that cannot start: `code` for clients (SERVER-API
    api/decoders), the sentence as the message, `needs` naming a codec."""

    def __init__(self, code: str, sentence: str, needs: str | None = None):
        super().__init__(sentence)
        self.code = code
        self.needs = needs


class Link:
    """What the mode decoder (modes/sdrmode.py) needs of the engine's host:
    the host itself, and a place to receive its session's results."""

    def __init__(self, owner: "Decoders", host):
        self.owner = owner
        self.host = host

    def attach(self, sid: str, decoder) -> None:
        with self.owner.lock:
            self.owner.vfo = (sid, decoder)

    def detach(self, sid: str) -> None:
        with self.owner.lock:
            if self.owner.vfo is not None and self.owner.vfo[0] == sid:
                self.owner.vfo = None


class _Fixed:
    """A fixed session the engine feeds: its channel and its kept results."""

    def __init__(self, sid: str, decoder: str, freq: float, params: dict, panel: str):
        self.id, self.decoder, self.freq, self.params, self.panel = sid, decoder, float(freq), dict(params), panel
        self.ch: Channel | None = None
        self.index = 0
        self.outside = False
        self.results: collections.deque = collections.deque(maxlen=RESULTS_KEPT)
        # A held session (module docstring): fed the device's samples, not
        # a channel; its block, the phase of any offset it is mixed by, and
        # its sound's channels and how long it has been silent.
        self.held = False
        self.block = ""
        self.phase = 0.0
        self.channels = 1
        self.dry = 0.0


class Decoders:
    """The engine's decoder sessions (module docstring)."""

    def __init__(self, engine):
        self.engine = engine
        self.lock = threading.RLock()
        self.host = None
        self.fixed: dict[str, _Fixed] = {}
        self.vfo: tuple[str, object] | None = None
        self.vfo_results: collections.deque = collections.deque(maxlen=RESULTS_KEPT)
        self._codecs: list[dict] | None = None
        self._codec_scan: threading.Thread | None = None

    # ------------------------------------------------------------ lifecycle
    def open(self, realtime: bool = True) -> None:
        """Make the host (Engine.start). A simulator running faster than
        real time feeds a minute of signal in a second, so its rings hold
        more than a real radio's two seconds."""
        m = sdr.load()
        if m is None or self.host is not None:
            return
        s = self.engine.st
        n = int(s.get("decodersMax", 4))
        cpu = float(s.get("decodeCpuMax", 0.25))
        self.host = m.Host(threads=1, cpu_max=cpu, ring_s=2.0 if realtime else 120.0, max_sessions=n + 1)
        self._publish_status()

    def close(self) -> bool:
        """Stop every session and the host's threads (Engine.stop, before the
        device closes). True when its workers joined within a second."""
        with self.lock:
            host, self.host = self.host, None
            fixed = list(self.fixed.values())
            self.fixed.clear()
            self.vfo = None
        # The first codec scan (scan_codecs_later) writes its probe cache
        # into the data folder: let it finish, within a second, so nothing
        # is written there after the radio has stopped.
        scan = self._codec_scan
        if scan is not None and scan.is_alive():
            scan.join(1.0)
        # The dial and mode a held session took, back before the engine
        # saves its settings (Engine.stop saves after this).
        for f in fixed:
            if f.held:
                self.engine.release_receiver(f.id)
        if host is None:
            return True
        joined = host.close()
        if not joined:
            log.warning("a decoder worker did not stop within a second")
        for f in fixed:
            log.info("decoder session %s (%s at %.0f Hz) stopped with the radio", f.id, f.decoder, f.freq)
        self._publish_status()
        return joined

    def link(self) -> Link | None:
        return Link(self, self.host) if self.host is not None else None

    def restore(self) -> None:
        """Start the saved fixed sessions again (the radio has just started)."""
        for want in list(self.engine.st.get("decoderSessions") or []):
            try:
                self.start(want["decoder"], want["freqHz"], want.get("params") or {}, save=False)
            except (Refused, KeyError, TypeError) as e:
                log.info("saved decoder session %r not restarted: %s", want, e)

    # ------------------------------------------------------------ the API
    def catalogue(self) -> list[dict]:
        """Every decoder, with `available`/`why` (codes) and `whyText`."""
        m = sdr.load()
        if m is None:
            return []
        out = []
        lends = bool(getattr(self.engine, "HOLDS_RECEIVER", False))
        for e in m.catalogue():
            e = dict(e)
            if not lends and _takes_receiver(e):
                # QO-100 NB: its receiver never leaves the transponder.
                e.update(available=False, why="receiver_fixed")
            e["whyText"] = _why_text(e.get("why")) if e.get("why") else ""
            # Partly available (DAB without faad2: old DAB plays, DAB+ does
            # not): the sentence for what is missing, beside the codes.
            missing = e.get("missing") or []
            e["missingText"] = (faad2_sentence() if "faad2" in missing else
                                _("Needs {codec} for part of what it decodes.").format(codec=missing[0])) \
                if missing else ""
            out.append(e)
        return out

    def holds_receiver(self, decoder: str) -> bool:
        """Whether a session of `decoder` takes the whole receiver (DAB)."""
        m = sdr.load()
        if m is None:
            return False
        entry = next((e for e in m.catalogue() if e["id"] == decoder), None)
        return entry is not None and _takes_receiver(entry)

    def limits(self) -> dict:
        s = self.engine.st
        return {"sessions": int(s.get("decodersMax", 4)), "cpuMax": float(s.get("decodeCpuMax", 0.25)),
                "threads": 1}

    def start(self, decoder: str, freq_hz: float, params: dict | None = None, *, save: bool = True) -> dict:
        """A fixed session on `freq_hz` (a dial frequency). Raises Refused."""
        m = sdr.load()
        if m is None:
            raise Refused("decoder_unavailable", sdr.why())
        params = dict(params or {})
        entry = next((e for e in m.catalogue() if e["id"] == decoder), None)
        if entry is None:
            raise Refused("unknown_decoder", _("There is no decoder called {name}").format(name=repr(decoder)))
        if not entry["available"]:
            raise Refused("decoder_unavailable", _why_text(entry.get("why")), needs=(entry.get("needs") or [None])[0])
        if not entry.get("fixed"):
            raise Refused("decoder_unavailable", _why_text("mode_only"))
        if self.holds_receiver(decoder):
            return self._start_held(m, entry, freq_hz, params)
        try:
            freq = float(freq_hz)
        except (TypeError, ValueError):
            raise Refused("bad_params", _("The frequency must be a number of hertz")) from None
        with self.lock:
            host = self.host
            if host is None or not self.engine.running:
                raise Refused("not_running", _("Start the radio before adding a decoder"))
            if len(self.fixed) >= self.limits()["sessions"]:
                raise Refused("too_many_sessions",
                              _("There are already {n} decoders running, the most Settings › Decoders allows")
                              .format(n=len(self.fixed)))
            if not self._covers(freq, entry):
                raise Refused("outside_span", _("{freq} is outside what the receiver covers now")
                              .format(freq=_mhz(freq)))
            inputs = entry.get("inputs") or []
            kind = "iq" if "iq" in inputs else "audio"
            try:
                sid = host.start(decoder, params, input=kind, rate=AUDIO_RATE)
            except m.DecoderError as e:
                raise self._refusal(e) from None
            f = _Fixed(sid, decoder, freq, params, entry.get("panel", "text"))
            f.kind = kind
            # A decoder that takes only audio (CW through shack_cw) is fed the
            # channel as USB audio with its signal at its pitch, so its
            # channel is centred that far below the signal (rx()).
            f.pitch = float(params.get("pitchHz", 700.0)) if kind == "audio" else 0.0
            self.fixed[sid] = f
        log.info("decoder session %s: %s at %.0f Hz %s", sid, decoder, freq, params)
        if save:
            self._save()
        self._publish_status()
        return self._view(f)

    def _start_held(self, m, entry: dict, freq_hz, params: dict) -> dict:
        """A session that takes the receiver (module docstring, "Held
        sessions"). Raises Refused."""
        decoder = entry["id"]
        centre, block = self._tuning(m, decoder, freq_hz, params)
        if block:
            params["block"] = block
        with self.lock:
            host = self.host
            if host is None or not self.engine.running:
                raise Refused("not_running", _("Start the radio before adding a decoder"))
            if any(f.held for f in self.fixed.values()):
                h = next(f for f in self.fixed.values() if f.held)
                raise Refused("receiver_busy", _("A DAB station on block {block} already has the receiver: stop "
                                                 "it first").format(block=h.block))
            if len(self.fixed) >= self.limits()["sessions"]:
                raise Refused("too_many_sessions",
                              _("There are already {n} decoders running, the most Settings › Decoders allows")
                              .format(n=len(self.fixed)))
        least = float(entry.get("minRateHz") or entry.get("rateHz"))
        # The receiver first: it refuses with the reason an operator can act
        # on (transmitting, too slow, out of range) before a session exists.
        # A placeholder id holds it until the host has made the session.
        token = f"pending-{id(params):x}"
        self.engine.hold_receiver(token, decoder, centre, block, least)
        try:
            # Pinned, as the mode's decoder is: it is what the operator is
            # listening to, so the CPU budget never pauses it.
            sid = host.start(decoder, params, input="iq", rate=float(self.engine.geo.fs), pinned=True)
        except m.DecoderError as e:
            self.engine.release_receiver(token)
            raise self._refusal(e) from None
        except Exception:
            self.engine.release_receiver(token)
            raise
        self.engine.rename_hold(token, sid)
        f = _Fixed(sid, decoder, centre, params, entry.get("panel", "meta"))
        f.kind, f.pitch, f.held, f.block = "iq", 0.0, True, block
        with self.lock:
            self.fixed[sid] = f
        log.info("decoder session %s: %s on %s (%.0f Hz) %s, holding the receiver", sid, decoder, block, centre,
                 params)
        self._publish_status()
        return self._view(f)

    @staticmethod
    def _tuning(m, decoder: str, freq_hz, params: dict) -> tuple[float, str]:
        """(centre Hz, block name) a held session tunes to, from `freq_hz`
        and/or params.block; Refused bad_params when neither names one, or
        they disagree."""
        freq = None
        if freq_hz is not None:
            try:
                freq = float(freq_hz)
            except (TypeError, ValueError):
                raise Refused("bad_params", _("The frequency must be a number of hertz")) from None
        if decoder != "dab":
            if freq is None:
                raise Refused("bad_params", _("The frequency must be a number of hertz"))
            return freq, ""
        dab = m.dab
        named = str(params.get("block") or "").strip().upper()
        if named:
            c = dab.block_centre(named)
            if c is None:
                raise Refused("bad_params", _("There is no DAB block called {block}").format(block=named))
            if freq is not None and dab.block_at(freq) != named:
                raise Refused("bad_params", _("Block {block} is centred on {centre}, not {freq}").format(
                    block=named, centre=_mhz(c), freq=_mhz(freq)))
            return float(c), named
        if freq is None:
            raise Refused("bad_params", _("Give the block's centre frequency (freqHz) or its name (params.block)"))
        named = dab.block_at(freq)
        if named is None:
            raise Refused("bad_params", _("{freq} is not the centre of a DAB block (5A-13F)").format(freq=_mhz(freq)))
        return float(dab.block_centre(named)), named

    def configure(self, sid: str, params: dict) -> dict:
        """Change a running session's parameters live (DAB's `service`).
        Raises Refused; None-free: answers the session."""
        with self.lock:
            f = self.fixed.get(sid)
            host = self.host
        if f is None or host is None:
            raise Refused("unknown_session", _("There is no decoder session called {id}").format(id=sid))
        params = dict(params)
        if f.held and "block" in params:
            # Another block is another tuning: a new session, never a
            # retune behind the receiver's owner's back.
            if str(params["block"] or "").strip().upper() != f.block:
                raise Refused("bad_params", _("A session stays on its block: stop it and start one on {block}")
                              .format(block=str(params["block"]).strip().upper()))
            params.pop("block")
        if not params:
            return self._view(f)
        m = sdr.load()
        try:
            host.configure(sid, params)
        except m.DecoderError as e:
            raise self._refusal(e) from None
        f.params.update(params)
        log.info("decoder session %s now %s", sid, f.params)
        if not f.held:
            self._save()
        return self._view(f)

    def stop(self, sid: str) -> bool:
        with self.lock:
            f = self.fixed.pop(sid, None)
            host = self.host
        if f is None:
            return False
        if host is not None:
            try:
                host.stop(sid)
            except Exception:  # noqa: BLE001 - a session already gone is stopped
                pass
        if f.held:
            self.engine.release_receiver(sid)
        log.info("decoder session %s stopped", sid)
        self._save()
        self._publish_status()
        return True

    def sessions(self) -> list[dict]:
        with self.lock:
            fixed = list(self.fixed.values())
            vfo = self.vfo
        out = []
        if vfo is not None:
            out.append(self._vfo_view(vfo))
        out += [self._view(f) for f in fixed]
        return out

    def session(self, sid: str, since: int | None = None) -> dict | None:
        """One session, with its kept results newer than `since`."""
        with self.lock:
            if sid == VFO:
                vfo = self.vfo
                if vfo is None:
                    return None
                view = self._vfo_view(vfo)
                kept = list(self.vfo_results)
            else:
                f = self.fixed.get(sid)
                if f is None:
                    return None
                view = self._view(f)
                kept = list(f.results)
        view["results"] = [r for r in kept if since is None or r["rev"] > since]
        return view

    def codecs(self, rescan: bool = False) -> list[dict]:
        """Each codec's status (shack_sdr codecs), with `whyText`. The first
        call scans (a probe child per new file); later ones are cached
        until `rescan` (Settings › Decoders "Look again")."""
        c = sdr.codecs()
        if c is None:
            return []
        out = []
        for st in c.status(rescan=rescan):
            st = dict(st)
            st["whyText"] = codec_sentence(st)
            out.append(st)
        with self.lock:
            self._codecs = out
        self._publish_status()
        try:
            self.engine._status(hostLibs=hostlibs.status())
        except Exception:  # noqa: BLE001 - an engine without the key (a test's stand-in)
            pass
        return out

    def scan_codecs_later(self) -> None:
        """The first codec scan, off the caller's thread (Engine.start): it
        runs ldconfig and may probe a new file in a child process, and
        api/status reports what is missing without ever scanning itself."""
        if self._codecs is not None or self._codec_scan is not None:
            return

        def run():
            try:
                self.codecs()
            except Exception:  # noqa: BLE001 - a scan that fails leaves the list unknown, never the radio
                log.warning("codec scan failed", exc_info=True)

        self._codec_scan = threading.Thread(target=run, name="ohscore-codecs", daemon=True)
        self._codec_scan.start()

    def status(self) -> dict:
        """api/status's `decoders`, without a scan."""
        with self.lock:
            n = len(self.fixed) + (1 if self.vfo is not None else 0)
            missing = None if self._codecs is None else [c["id"] for c in self._codecs if c["state"] != "found"]
        return {"available": sdr.available(), "sessions": n, "cpuMax": self.limits()["cpuMax"],
                "codecsMissing": missing}

    # ------------------------------------------------------------ the engine's threads
    def rx(self, X: np.ndarray, starts: np.ndarray, utc: float) -> None:
        """The receive thread, once per block: each fixed session's channel
        from the bank, into its ring. `utc` is the block's first sample's
        time (Engine._audio_utc)."""
        host = self.host
        if host is None or not self.fixed:
            return
        geo = self.engine.geo
        with self.lock:
            fixed = list(self.fixed.values())
        for f in fixed:
            if f.held:
                continue
            off = self.engine._off(f.freq - f.pitch)
            inside = abs(off) + 1500.0 <= SPAN_USABLE * geo.fs / 2
            if inside == f.outside:
                f.outside = not inside
                try:
                    host.set_outside(f.id, f.outside)
                except Exception:  # noqa: BLE001 - a session the host dropped is reported by poll
                    pass
            if f.outside:
                continue
            if f.ch is None or f.ch.g is not geo:
                f.ch = Channel(geo, geo.decimation_for(AUDIO_RATE), freq=off)
            f.ch.set_freq(off)
            iq = f.ch.take(X, starts)
            if not len(iq):
                continue
            x = iq if f.kind == "iq" else _usb(iq)
            try:
                host.feed(f.id, x, utc, f.index)
            except Exception:  # noqa: BLE001 - the host closing under us: the radio is stopping
                return
            f.index += len(iq)

    def rx_held(self, raw: np.ndarray, utc: float, settled: bool) -> None:
        """The receive thread, once per block, while a session holds the
        receiver: the device's samples, mixed to the block's centre if the
        receiver is not exactly on it (it is, once settled: Radio puts DC
        there). Nothing is fed until the retune has reached the samples,
        and the index still counts them, so the session's times stay true."""
        host = self.host
        f = self._held()
        if host is None or f is None:
            return
        n = len(raw)
        if not settled:
            f.index += n
            return
        geo = self.engine.geo
        off = self.engine._off(f.freq)
        x = raw
        if off:
            ph = f.phase + 2 * np.pi * (-off / geo.fs) * np.arange(n)
            x = (raw * np.exp(1j * ph)).astype(np.complex64)
            f.phase = float((f.phase - 2 * np.pi * off / geo.fs * n) % (2 * np.pi))
        m = sdr.load()
        outside = m is not None and m.dab.span_check(f.freq, self.engine._dial_at(0.0), geo.fs) is not None
        if outside != f.outside:
            f.outside = outside
            try:
                host.set_outside(f.id, outside)
            except Exception:  # noqa: BLE001 - a session the host dropped is reported by poll
                pass
        if f.outside:
            f.index += n
            return
        try:
            host.feed(f.id, x, utc, f.index)
        except Exception:  # noqa: BLE001 - the host closing under us: the radio is stopping
            return
        f.index += n

    def held_audio(self, block_s: float, rate: int) -> np.ndarray | None:
        """The receive thread: the held session's sound since the last block,
        at `rate`, mono (n,) or stereo (n, 2) as it was made; silence for the
        block once it has given none for DRY_S; None for a block to pass
        over without playing (its sound is in the next one)."""
        host = self.host
        f = self._held()
        if host is None or f is None:
            return None
        try:
            runs = host.audio(f.id, max_s=1.0, rate=int(rate))
        except Exception:  # noqa: BLE001 - closed between the read above and now
            runs = []
        parts = []
        for r in runs:
            ch = int(r.get("channels") or 1)
            pcm = np.asarray(r["pcm"], np.float32)
            parts.append(pcm.reshape(-1, 2) if ch == 2 else pcm)
            f.channels = ch
        if parts:
            f.dry = 0.0
            if any(p.ndim == 2 for p in parts):
                parts = [p if p.ndim == 2 else np.repeat(p[:, None], 2, axis=1) for p in parts]
            return np.concatenate(parts)
        f.dry += block_s
        if f.dry < DRY_S:
            return None
        n = int(round(block_s * rate))
        return np.zeros((n, 2) if f.channels == 2 else n, np.float32)

    def held_channels(self) -> int:
        """The held session's sound's channels (1 until it has made any)."""
        f = self._held()
        return f.channels if f is not None else 1

    def _held(self) -> _Fixed | None:
        with self.lock:
            return next((f for f in self.fixed.values() if f.held), None)

    def tick(self) -> None:
        """The supervisor, ten times a second: every result out of the host,
        to the mode decoder, the `decoders` feed and the kept lists."""
        host = self.host
        if host is None:
            return
        try:
            items = host.poll(2000)
        except Exception:  # noqa: BLE001 - closed between the read above and now
            return
        if not items:
            return
        with self.lock:
            vfo = self.vfo
            fixed = dict(self.fixed)
        for it in items:
            sid = it.get("session")
            if it.get("type") == "state" and it.get("why"):
                it = dict(it, whyText=_why_text(it["why"]))
            elif it.get("type") == "meta" and isinstance(it.get("fields"), dict):
                it = dict(it, fields=_worded_meta(it["fields"]))
            if vfo is not None and sid == vfo[0]:
                try:
                    vfo[1].deliver(it)
                except Exception:  # noqa: BLE001 - a broken event costs that event
                    log.warning("mode decoder result not delivered", exc_info=True)
                out = dict(it, session=VFO)
                self.vfo_results.append(out)
            elif sid in fixed:
                out = dict(it)
                fixed[sid].results.append(out)
            else:
                continue
            self.engine._publish("decoders", out)
        cutoff = time.time() - RESULTS_S
        for f in fixed.values():
            while f.results and f.results[0].get("t", cutoff) < cutoff:
                f.results.popleft()

    # ------------------------------------------------------------ helpers
    def _covers(self, freq: float, entry: dict) -> bool:
        geo = getattr(self.engine, "geo", None)
        if geo is None:
            return False
        half = float(entry.get("bandwidthHz") or 3000.0) / 2
        return abs(self.engine._off(freq)) + half <= SPAN_USABLE * geo.fs / 2

    def _refusal(self, e) -> Refused:
        code = e.args[0] if e.args else "error"
        detail = e.args[1] if len(e.args) > 1 else None
        if code == "bad_params":
            return Refused("bad_params", _("The decoder does not take those settings ({detail})")
                           .format(detail=detail or code))
        if code == "too_many_sessions":
            return Refused("too_many_sessions", _("No more decoders can run at once"))
        if code == "unknown_decoder":
            return Refused("unknown_decoder", _("There is no decoder called {name}").format(name=repr(detail)))
        if code == "decoder_unavailable":
            return Refused("decoder_unavailable", _why_text(detail))
        if code == "closed":
            return Refused("not_running", _("Start the radio before adding a decoder"))
        if code == "bad_input":
            return Refused("bad_params", _("The receiver's samples do not suit this decoder ({detail})")
                           .format(detail=detail or code))
        if code == "unknown_session":
            return Refused("unknown_session", _("There is no decoder session called {id}").format(id=detail or ""))
        return Refused(code, _("The decoder would not start ({code})").format(code=code))

    def _status_of(self, sid: str) -> dict:
        host = self.host
        if host is None:
            return {}
        try:
            return host.status(sid)
        except Exception:  # noqa: BLE001 - gone since: no status
            return {}

    def _view(self, f: _Fixed) -> dict:
        st = self._status_of(f.id)
        stats = st.get("stats") or {}
        state = "outside" if f.outside else st.get("state", "stopped")
        why = "outside_span" if f.outside else st.get("why")
        view = {"id": f.id, "decoder": f.decoder, "freqHz": f.freq, "params": dict(f.params), "state": state,
                "why": why, "whyText": _why_text(why), "since": _iso(st.get("since")), "rev": st.get("rev", 0),
                "stats": _stats(stats), "panel": f.panel}
        if f.held:
            view.update(holdsReceiver=True, block=f.block,
                        meta=_worded_meta(st["meta"]) if isinstance(st.get("meta"), dict) else None)
        return view

    def _vfo_view(self, vfo) -> dict:
        sid, dec = vfo
        st = self._status_of(sid)
        s = self.engine.st
        return {"id": VFO, "decoder": getattr(dec, "decoder", ""), "freqHz": s.get("rxDial"),
                "params": dict(getattr(dec, "params", {})), "state": st.get("state", "stopped"),
                "why": st.get("why"), "whyText": _why_text(st.get("why")), "since": _iso(st.get("since")),
                "rev": st.get("rev", 0), "stats": _stats(st.get("stats") or {}), "panel": "text", "mode": True}

    def _save(self) -> None:
        with self.lock:
            saved = [{"decoder": f.decoder, "freqHz": f.freq, "params": dict(f.params)} for f in self.fixed.values()
                     if not f.held]
        self.engine._keep_setting("decoderSessions", saved)

    def _publish_status(self) -> None:
        try:
            self.engine._status(decoders=self.status())
        except Exception:  # noqa: BLE001 - an engine without the key (a test's stand-in)
            pass


def codec_sentence(st: dict) -> str:
    """What Settings › Decoders and a client say about one codec."""
    cid, state, why = st.get("id"), st.get("state"), st.get("why")
    if state == "found":
        return _("Found: {path}").format(path=st.get("path") or "")
    if state == "refused":
        reasons = {"crashed": _("it crashed when it was tested"), "timeout": _("it did not answer when it was tested"),
                   "bad_output": _("it gave a wrong answer when it was tested"),
                   "noexec": _("its folder does not allow programs to run")}
        return _("The {codec} in {path} was refused: {reason}.").format(
            codec=cid, path=st.get("path") or "", reason=reasons.get(why, why or ""))
    if not st.get("shippable") and hostlibs.controller_too_old():
        return hostlibs.update_sentence()
    if st.get("host"):
        return _("Ask your controller's administrator to install {codec} (Controller › Optional libraries).") \
            .format(codec=cid)
    if st.get("shippable"):
        return _("Not found: {codec} is normally included; reinstalling the program puts it back.").format(codec=cid)
    return _("Not installed. This program never includes {codec}: install it yourself, or put it in the codecs folder.") \
        .format(codec=cid)


def _takes_receiver(entry: dict) -> bool:
    """Whether a catalogue entry's decoder needs the whole receiver."""
    return float(entry.get("minRateHz") or entry.get("rateHz") or 0.0) >= RECEIVER_RATE


def _worded_meta(fields: dict) -> dict:
    """A DAB feed (a session's `meta`) with each `why` worded beside its
    code: the feed's own `whyText`, and each service's."""
    out = dict(fields)
    out["whyText"] = _why_text(out.get("why")) if out.get("why") else ""
    services = out.get("services")
    if isinstance(services, list):
        out["services"] = [dict(sv, whyText=_why_text(sv.get("why")) if sv.get("why") else "")
                           if isinstance(sv, dict) else sv for sv in services]
    return out


def _usb(iq: np.ndarray) -> np.ndarray:
    """Channel IQ to USB audio (the real part: the channel is centred on the
    carrier, so the signal sits at its offset above it)."""
    return np.ascontiguousarray(iq.real, dtype=np.float32)


def _stats(st: dict) -> dict:
    out = {"snrDb": st.get("snrDb"), "offsetHz": st.get("offsetHz"), "cpu": st.get("cpu"),
           "dropped": st.get("dropped", 0)}
    for k in ("baud", "sync", "chars", "wpm", "frames", "fibsOk", "fibsBad", "audioFrames", "audioErrors",
              "superframes", "aus", "auErrors"):
        if k in st:
            out[k] = st[k]
    return out


def _iso(t) -> str | None:
    if not t:
        return None
    return datetime.fromtimestamp(float(t), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _mhz(hz: float) -> str:
    try:
        from .i18n import fmt
        return fmt.frequency(int(round(hz)), "MHz", 4)
    except Exception:  # noqa: BLE001 - the words matter more than the format
        return f"{hz / 1e6:.4f} MHz"
