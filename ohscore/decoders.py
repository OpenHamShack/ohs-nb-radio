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
"""
from __future__ import annotations

import collections
import logging
import threading
import time
from datetime import datetime, timezone

import numpy as np

from . import sdr
from .dsp.bank import Channel
from .i18n.text import _

log = logging.getLogger("ohscore.decoders")

AUDIO_RATE = 12_000.0
VFO = "vfo"
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
    }
    return words.get(code, _("Stopped ({code}).").format(code=code))


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
        for e in m.catalogue():
            e = dict(e)
            e["whyText"] = _why_text(e.get("why")) if e.get("why") else ""
            out.append(e)
        return out

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
        return {"id": f.id, "decoder": f.decoder, "freqHz": f.freq, "params": dict(f.params), "state": state,
                "why": why, "whyText": _why_text(why), "since": _iso(st.get("since")), "rev": st.get("rev", 0),
                "stats": _stats(stats), "panel": f.panel}

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
            saved = [{"decoder": f.decoder, "freqHz": f.freq, "params": dict(f.params)} for f in self.fixed.values()]
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
    if st.get("host"):
        return _("Ask your controller's administrator to install {codec} (Controller › Optional libraries).") \
            .format(codec=cid)
    if st.get("shippable"):
        return _("Not found: {codec} is normally included; reinstalling the program puts it back.").format(codec=cid)
    return _("Not installed. This program never includes {codec}: install it yourself, or put it in the codecs folder.") \
        .format(codec=cid)


def _usb(iq: np.ndarray) -> np.ndarray:
    """Channel IQ to USB audio (the real part: the channel is centred on the
    carrier, so the signal sits at its offset above it)."""
    return np.ascontiguousarray(iq.real, dtype=np.float32)


def _stats(st: dict) -> dict:
    out = {"snrDb": st.get("snrDb"), "offsetHz": st.get("offsetHz"), "cpu": st.get("cpu"),
           "dropped": st.get("dropped", 0)}
    for k in ("baud", "sync", "chars", "wpm"):
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
