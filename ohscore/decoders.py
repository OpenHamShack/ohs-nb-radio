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

**The span.** The receiver covers what its sample rate covers around its
centre. In an app whose centre follows the dial (Radio, Engine.PINS_SPAN)
the fixed sessions **pin** it (Brian, 23/10/2026; RADIO-SDR-PLAN §8.5):
starting one chooses a centre that holds every session and the dial
(Engine.pin_plan; ohscore/span.py) or is refused `outside_span`, and while
any runs the dial moves inside that span and a tune out of it is refused
(SpanPinned) unless the operator lets it stop them (stop_background). The
last one stopping unpins it (Engine.span_changed). Elsewhere (QO-100 NB) a
session the span no longer covers goes `outside` and is fed nothing, and
comes back by itself when the span covers it again - the CW skimmer's rule
(ENGINE-API "cwskim"). Its results stop; it is not stopped.

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

**A held session has a host of its own.** One worker thread decodes every
session on a host, so a decoder that never returns from a block starves
every session beside it. shack_sdr 0.2.0's DAB search does exactly that on
some input (a buffer that starts just before a short deep dip, with no
phase reference to lock to: `ofdm.rs` search() drops nothing and tries
the same samples again, for ever), and it is data the simulator never
makes but a real RSP on Band III can: Store Radio 0.1.22-beta.5 on ohs-box
had its one worker at 100 % of a core while every session after the first
stayed `starting` with all its input dropped - every later DAB station,
and once DAB was stopped every fixed session and the mode's own decoder
too, until Radio restarted. A thread inside a decoder cannot be stopped,
so what a separate host buys is containment: the DAB session alone goes
quiet, and stopping it (which closes its host, leaving the stuck thread
behind, said in the log) lets everything else, and the next DAB station
on a fresh thread, carry on.

**Files: the pictures decoders save** (SSTV's, RADIO-SDR-PLAN §4.4
`api/decoders/files`). The host writes each finished picture whole into
the data folder's `sstv` folder (Engine.sstv_dir, where sstv.py's pictures
always went, so the SSTV panel's gallery shows old and new alike) and
names it after its session; files() lists them and file() serves one by
name, the host refusing any name that could leave the folder. The host
keeps only a few in memory and never deletes from disk, so the cap is
here: after each picture, and when the radio starts, the oldest the host
made beyond decoderFilesKeep are deleted (prune_files). Pictures from
before the host named them (sstv.py's sstv_<mode>_NNNN.png) are the
operator's to delete: they are listed, never pruned.

**A session that is fed but decodes nothing says so.** The supervisor
compares each session's `fed` and `dropped` over STARVED_S: when the host
dropped nearly all of it the session's `why` is `decoder_behind` (the
decoder takes some, too slowly), or `decoder_stuck` and state `error`
when it took none at all - the host's own state would otherwise stay
`starting` for ever with no word anywhere. Each is logged once when it
begins and once when it ends, and a stuck one is a toast.
"""
from __future__ import annotations

import base64
import collections
import logging
import os
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
# The starvation watch (module docstring): over this long, a session that
# was fed and had at least STARVED_SHARE of it dropped is said to be
# starved. Longer than the host's two-second ring, so a ring that is still
# filling (a decoder settling in) never counts, and short enough that the
# operator hears why within a few seconds of starting a station.
STARVED_S = 3.0
STARVED_SHARE = 0.9
# ...and it is over once less than half of what is fed is dropped.
RECOVERED_SHARE = 0.5
# Finished files the host keeps in memory, beside the ones on disk.
FILES_IN_MEMORY = 16
# How the host names a file it made: the session's id first (shack_sdr
# README "Files are the host's"). Only these are ever pruned.
HOST_FILE_PREFIX = "ds_"


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
        # The starvation watch (module docstring).
        "decoder_stuck": _("The decoder has stopped responding and everything it is given is thrown away: stop "
                           "it and start it again (restart the app if that does not help)."),
        "decoder_behind": _("This computer cannot decode it fast enough: most of the signal is thrown away."),
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

    def __init__(self, code: str, sentence: str, needs: str | None = None, sessions: list | None = None):
        super().__init__(sentence)
        self.code = code
        self.needs = needs
        # span_pinned: the sessions holding the span ({id, decoder, freqHz, label}).
        self.sessions = sessions


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
        # How far either side of `freq` its channel reaches, for fitting it
        # into a pinned span (Engine.pin_plan).
        self.half = 1500.0
        self.index = 0
        self.outside = False
        self.results: collections.deque = collections.deque(maxlen=RESULTS_KEPT)
        # A held session (module docstring): fed the device's samples, not
        # a channel; its block, the phase of any offset it is mixed by, and
        # its sound's channels and how long it has been silent.
        self.held = False
        # What its decoder sends (the catalogue's `outputs`): a session whose
        # decoder sends `meta` shows the latest in its view.
        self.outputs: tuple = ()
        self.block = ""
        self.phase = 0.0
        self.channels = 1
        self.dry = 0.0
        # Its channel of the bank: the decimation (None: 12 kHz) and the
        # filter's edge (None: the bank's default for the rate).
        self.d: int | None = None
        self.cutoff: float | None = None
        # The host it runs on: the engine's, or a held session's own.
        self.host = None
        # The starvation watch: (monotonic t, fed, dropped) once a second
        # over the last STARVED_S, and the code while it is starved.
        self.watch: collections.deque = collections.deque()
        self.starved: str | None = None


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
        self._ring_s = 2.0
        self._vfo_watch: collections.deque = collections.deque()
        self._vfo_starved: str | None = None
        self._watch_due = 0.0

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
        self._ring_s = 2.0 if realtime else 120.0
        self.host = m.Host(threads=1, cpu_max=cpu, ring_s=self._ring_s, max_sessions=n + 1,
                           **self._files_opts())
        self.prune_files()
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
        # Nothing pins the span once they are gone (Engine.span_changed).
        self.engine.span_changed()
        self._vfo_watch.clear()
        self._vfo_starved = None
        joined = True
        for f in fixed:
            if f.held:
                joined = _close_own_host(f) and joined
        if host is None:
            return joined
        joined = host.close() and joined
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
            if e["id"] in switched_off():
                continue
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

    def start(self, decoder: str, freq_hz: float, params: dict | None = None, *, save: bool = True,
              drop_sessions: bool = False) -> dict:
        """A fixed session on `freq_hz` (a dial frequency). Raises Refused.
        `drop_sessions`: a session that takes the receiver (DAB) stops the
        background sessions pinning the span rather than being refused."""
        m = sdr.load()
        if m is None:
            raise Refused("decoder_unavailable", sdr.why())
        params = dict(params or {})
        entry = next((e for e in m.catalogue() if e["id"] == decoder and e["id"] not in switched_off()), None)
        if entry is None:
            raise Refused("unknown_decoder", _("There is no decoder called {name}").format(name=repr(decoder)))
        if not entry["available"]:
            raise Refused("decoder_unavailable", _why_text(entry.get("why")), needs=(entry.get("needs") or [None])[0])
        if not entry.get("fixed"):
            raise Refused("decoder_unavailable", _why_text("mode_only"))
        # A decoder wants the receiver where the operator left it: a band
        # scan holding it gives it back first (Engine.client_activity).
        self.engine.client_activity("decoder")
        if self.holds_receiver(decoder):
            return self._start_held(m, entry, freq_hz, params, drop_sessions)
        try:
            freq = float(freq_hz)
        except (TypeError, ValueError):
            raise Refused("bad_params", _("The frequency must be a number of hertz")) from None
        with self.lock:
            host = self.host
            if host is None or not self.engine.running:
                raise Refused("not_running", _("Start the radio before adding a decoder"))
            held = self.engine.held
            if held is not None:
                # DAB has the receiver in Band III: a session here would only
                # ever be `outside`, and pinning cannot move a held receiver.
                # The DAB station goes first (precedence: SERVER-API "The
                # pinned span").
                raise Refused("receiver_busy", _("The receiver is playing DAB from block {block}: stop the DAB "
                                                 "station to add a decoder").format(block=held["block"]))
            if len(self.fixed) >= self.limits()["sessions"]:
                raise Refused("too_many_sessions",
                              _("There are already {n} decoders running, the most Settings › Decoders allows")
                              .format(n=len(self.fixed)))
            inputs = entry.get("inputs") or []
            kind = "iq" if "iq" in inputs else "audio"
            # A decoder that takes only audio (CW through shack_cw) is fed the
            # channel as USB audio with its signal at its pitch, so its
            # channel is centred that far below the signal (rx()) and reaches
            # that much further down.
            pitch = float(params.get("pitchHz", 700.0)) if kind == "audio" else 0.0
            half = float(entry.get("bandwidthHz") or 3000.0) / 2 + pitch
            pin = self.engine.pin_plan(freq, half)
            if pin is None and not self._covers(freq, entry):
                raise Refused("outside_span", _("{freq} is outside what the receiver covers now")
                              .format(freq=_mhz(freq)))
            d, cutoff = self._channel_for(entry)
            rate = self.engine.geo.fs / d
            try:
                sid = host.start(decoder, params, input=kind, rate=rate)
            except m.DecoderError as e:
                raise self._refusal(e) from None
            f = _Fixed(sid, decoder, freq, params, entry.get("panel", "text"))
            f.kind, f.pitch, f.half, f.host = kind, pitch, half, host
            f.outputs = tuple(entry.get("outputs") or ())
            f.d, f.cutoff = d, cutoff
            self.fixed[sid] = f
            if pin is not None:
                self.engine.pin_to(pin)
        log.info("decoder session %s: %s at %.0f Hz %s", sid, decoder, freq, params)
        if save:
            self._save()
        self._publish_status()
        return self._view(f)

    def _channel_for(self, entry: dict) -> tuple[int, float | None]:
        """The bank's decimation and channel filter edge for an unheld
        session of `entry`: 12 kHz for the narrow decoders, as always; for
        one that needs wider IQ (wide FM: 240 kS/s, 144 at least) the
        bank's smallest decimation that gives its rate, the filter at the
        edges of its channel - the cut Radio's own wide FM mode makes
        (ohsradio/radio.py). Raises Refused rate_too_low when the receiver
        is too slow even for the least it takes.

        Before 23/10/2026 every unheld session started at 12 kHz, so `wfm`
        - fixed, available, in the catalogue - was refused on every
        receiver ("The receiver's samples do not suit this decoder (rate)").
        It is not a held session as DAB is: its 180 kHz channel is one the
        bank already cuts, so it can sit beside the dial and the other
        sessions in a pinned span instead of taking the receiver away."""
        want = float(entry.get("rateHz") or AUDIO_RATE)
        geo = self.engine.geo
        if want <= AUDIO_RATE:
            return geo.decimation_for(AUDIO_RATE), None
        d = geo.decimation_for(want)
        least = float(entry.get("minRateHz") or want)
        if geo.fs / d < least - 1e-6:
            raise Refused("rate_too_low", _("{decoder} needs the receiver to run at {least:g} kS/s or more, and it "
                                            "runs at {rate:g} kS/s").format(decoder=entry["id"].upper(),
                                                                           least=least / 1e3, rate=geo.fs / 1e3))
        edge = float(entry.get("bandwidthHz") or 0.0) / 2
        return d, (edge if 0 < edge < geo.fs / d / 2 else None)

    def _start_held(self, m, entry: dict, freq_hz, params: dict, drop_sessions: bool = False) -> dict:
        """A session that takes the receiver (module docstring, "Held
        sessions"). Raises Refused."""
        decoder = entry["id"]
        centre, block = self._tuning(m, decoder, freq_hz, params)
        if block:
            params["block"] = block
        pinning = self.pinned_by()
        if pinning and self.engine.PINS_SPAN:
            # The background sessions were there first and DAB would take
            # their span to Band III: refused, as a tune out of the span is,
            # unless the operator said to stop them (SERVER-API "The pinned
            # span": precedence).
            if not drop_sessions:
                raise Refused("span_pinned", _("Playing DAB takes the receiver to Band III and stops {sessions}")
                              .format(sessions=sessions_text(pinning)), sessions=pinning)
            self.stop_background()
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
        # Its own host (module docstring, "A held session has a host of its
        # own"): one worker, no budget - it is pinned, as the mode's decoder
        # is, because it is what the operator is listening to.
        own = m.Host(threads=1, cpu_max=0.0, ring_s=self._ring_s, max_sessions=1)
        try:
            sid = own.start(decoder, params, input="iq", rate=float(self.engine.geo.fs), pinned=True)
            # Each host numbers its own sessions; one id may not name two.
            while sid in self.fixed:
                own.stop(sid)
                sid = own.start(decoder, params, input="iq", rate=float(self.engine.geo.fs), pinned=True)
        except m.DecoderError as e:
            own.close()
            self.engine.release_receiver(token)
            raise self._refusal(e) from None
        except Exception:
            own.close()
            self.engine.release_receiver(token)
            raise
        self.engine.rename_hold(token, sid)
        f = _Fixed(sid, decoder, centre, params, entry.get("panel", "meta"))
        f.kind, f.pitch, f.held, f.block, f.host = "iq", 0.0, True, block, own
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
        host = f.host if f is not None else None
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
        if f is None:
            return False
        if f.held:
            # Its own host goes with it: a fresh one for the next station,
            # even when this one's thread is stuck inside its decoder.
            _close_own_host(f)
        elif f.host is not None:
            try:
                f.host.stop(sid)
            except Exception:  # noqa: BLE001 - a session already gone is stopped
                pass
        if f.held:
            self.engine.release_receiver(sid)
        log.info("decoder session %s stopped", sid)
        self._save()
        self._publish_status()
        if not f.held:
            self.engine.span_changed()
        return True

    def held_stats(self, sid: str) -> dict:
        """The counters of session `sid` if it holds the receiver, else {}:
        what Radio's broadcast gain reads ten times a second
        (ohsradio/bcastgain.py), so only the one host's status, not the
        whole session view."""
        with self.lock:
            f = self.fixed.get(sid)
        if f is None or not f.held:
            return {}
        return self._status_of(f.id, f.host).get("stats") or {}

    def background(self) -> list[_Fixed]:
        """The sessions that pin the span: fixed ones on frequencies of
        their own (not the mode's, not one holding the receiver)."""
        with self.lock:
            return [f for f in self.fixed.values() if not f.held]

    def pinned_by(self) -> list[dict]:
        """The background sessions as a client names them: {id, decoder,
        freqHz, label} ("RTTY on 14.0933 MHz")."""
        return [{"id": f.id, "decoder": f.decoder, "freqHz": f.freq, "label": session_label(f.decoder, f.freq)}
                for f in self.background()]

    def stop_background(self) -> list[dict]:
        """Stop every background session (the operator chose to tune out
        of their span, or to play DAB): the ones stopped. They leave
        decoderSessions too: the operator chose to end them."""
        gone = self.pinned_by()
        for g in gone:
            self.stop(g["id"])
        if gone:
            log.info("background decoder sessions stopped to free the span: %s",
                     ", ".join(g["label"] for g in gone))
        return gone

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

    # ------------------------------------------------------------ files
    def files_dir(self):
        """Where decoders' files are kept (the data folder's sstv folder),
        or None for an engine with no data folder (a test's stand-in)."""
        fn = getattr(self.engine, "sstv_dir", None)
        return fn() if fn is not None else None

    def _files_opts(self) -> dict:
        d = self.files_dir()
        if d is None:
            return {}
        try:
            d.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            log.warning("no folder for decoded pictures (%s): they are kept in memory only", e)
            return {"files_keep": FILES_IN_MEMORY}
        return {"files_dir": str(d), "files_keep": FILES_IN_MEMORY}

    def _files_host(self):
        """(a host that can list and serve the files, whether to close it):
        the running radio's, or one made for the question when the radio
        is stopped - the pictures are still there to look at."""
        if self.host is not None:
            return self.host, False
        m = sdr.load()
        if m is None or self.files_dir() is None:
            return None, False
        return m.Host(threads=1, cpu_max=0.0, max_sessions=1, **self._files_opts()), True

    def files(self) -> list[dict]:
        """The finished files, newest first: {name, session, decoder, t,
        size} (never the path: that is this computer's, not a client's)."""
        return [{k: f.get(k) for k in ("name", "session", "decoder", "t", "size")}
                for f in reversed(self._files_on_disk())]

    def _files_on_disk(self) -> list[dict]:
        """The host's list, oldest first, without what is no longer on disk:
        the host remembers the last few it made after prune_files (or the
        operator) deleted them."""
        host, own = self._files_host()
        if host is None:
            return []
        try:
            out = []
            for f in host.files():
                path = f.get("path")
                if path and not os.path.isfile(path):
                    continue
                out.append(dict(f))
            return out
        except Exception:  # noqa: BLE001 - a host closing under us: nothing to list
            return []
        finally:
            if own:
                host.close()

    def file(self, name: str) -> bytes | None:
        """One file's bytes by its name, or None (no such file, or a name
        that is not one of the listed files)."""
        if not isinstance(name, str) or name not in {f["name"] for f in self._files_on_disk()}:
            return None
        host, own = self._files_host()
        if host is None:
            return None
        try:
            return host.file(name)
        except Exception:  # noqa: BLE001 - refused or gone: no file
            return None
        finally:
            if own:
                host.close()

    def prune_files(self) -> int:
        """Delete the oldest files the host made beyond decoderFilesKeep;
        how many went. Never one the host did not name (module docstring)."""
        try:
            keep = int(self.engine.st.get("decoderFilesKeep", 100))
        except (AttributeError, TypeError, ValueError):
            keep = 100
        made = [f for f in self._files_on_disk() if str(f.get("name", "")).startswith(HOST_FILE_PREFIX)
                and f.get("path")]
        made.sort(key=lambda f: float(f.get("t") or 0.0))
        gone = 0
        for f in made[:max(0, len(made) - keep)]:
            try:
                os.remove(f["path"])
                gone += 1
            except OSError as e:
                log.warning("could not delete the old picture %s: %s", f["name"], e)
        if gone:
            log.info("deleted the %d oldest decoded pictures, keeping %d", gone, keep)
        return gone

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
            inside = abs(off) + max(1500.0, f.half) <= SPAN_USABLE * geo.fs / 2
            if inside == f.outside:
                f.outside = not inside
                try:
                    host.set_outside(f.id, f.outside)
                except Exception:  # noqa: BLE001 - a session the host dropped is reported by poll
                    pass
            if f.outside:
                continue
            if f.ch is None or f.ch.g is not geo:
                f.ch = Channel(geo, f.d or geo.decimation_for(AUDIO_RATE), freq=off, cutoff=f.cutoff)
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
        f = self._held()
        host = f.host if f is not None else None
        if host is None:
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
        f = self._held()
        host = f.host if f is not None else None
        if host is None:
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
        to the mode decoder, the `decoders` feed and the kept lists; and
        once a second, the starvation watch."""
        if self.host is None:
            return
        with self.lock:
            vfo = self.vfo
            fixed = dict(self.fixed)
        now = time.monotonic()
        if now >= self._watch_due:
            self._watch_due = now + 1.0
            self._watch(now, vfo, fixed)
        items = []
        # The engine's host, and each held session's own.
        for host in [self.host, *(f.host for f in fixed.values() if f.held)]:
            if host is None:
                continue
            try:
                items += host.poll(2000)
            except Exception:  # noqa: BLE001 - closed between the read above and now
                continue
        if not items:
            return
        saved = False
        for it in items:
            sid = it.get("session")
            raw = it
            if it.get("type") == "state" and it.get("why"):
                it = dict(it, whyText=_why_text(it["why"]))
            elif it.get("type") == "meta" and isinstance(it.get("fields"), dict):
                it = dict(it, fields=self._meta(it["fields"]))
            elif it.get("type") == "frame":
                # DAB's slides, logos and guide are kept (dabpics.py) and go
                # on as their details and path; no picture's bytes ever go
                # on a feed or into the kept results.
                pics = self._pictures()
                it = pics.take(it) if pics is not None else {k: v for k, v in it.items() if k != "raw"}
            elif it.get("type") == "image":
                # A picture's rows are bytes, which no feed client can read:
                # base64, as the SSTV events' rows always were; and a saved
                # file by its name only (api/decoders/files), never its path.
                it = _image_for_clients(it)
                saved = saved or it.get("event") == "done"
            if vfo is not None and sid == vfo[0]:
                try:
                    vfo[1].deliver(raw)
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
        if saved:
            self.prune_files()

    def _watch(self, now: float, vfo, fixed: dict) -> None:
        """The starvation watch (module docstring), once a second from tick:
        each session's fed and dropped, and whether it is starved now."""
        for f in fixed.values():
            if f.host is None:
                continue
            f.starved = self._watch_one(now, f.host, f.id, f.decoder, f.watch, f.starved)
        if vfo is not None and self.host is not None:
            self._vfo_starved = self._watch_one(now, self.host, vfo[0], getattr(vfo[1], "decoder", "mode"),
                                                self._vfo_watch, self._vfo_starved)
        else:
            self._vfo_watch.clear()
            self._vfo_starved = None

    def _watch_one(self, now: float, host, sid: str, decoder: str, watch: collections.deque,
                   was: str | None) -> str | None:
        try:
            stats = host.status(sid).get("stats") or {}
        except Exception:  # noqa: BLE001 - gone since: nothing to watch
            return was
        watch.append((now, int(stats.get("fed") or 0), int(stats.get("dropped") or 0)))
        while len(watch) > 1 and now - watch[1][0] >= STARVED_S:
            watch.popleft()
        cpu = stats.get("cpu")
        code = starvation(list(watch), was, float(cpu) if cpu is not None else None)
        if code == was:
            return code
        if code is not None:
            t0, fed0, drop0 = watch[0]
            _t1, fed1, drop1 = watch[-1]
            log.warning("decoder session %s (%s): %d of the %d samples fed in the last %.0f s were dropped, %s",
                        sid, decoder, drop1 - drop0, fed1 - fed0, now - t0,
                        "and its decoder took none: its thread is stuck inside the decoder"
                        if code == "decoder_stuck" else "its decoder cannot keep up")
            if code == "decoder_stuck":
                try:
                    self.engine.toast(_("The {decoder} decoder has stopped responding: stop it and start it "
                                        "again").format(decoder=decoder.upper()), "error")
                except Exception:  # noqa: BLE001 - an engine without toasts (a test's stand-in)
                    pass
        else:
            log.warning("decoder session %s (%s) is decoding what it is fed again", sid, decoder)
        self._publish_status()
        return code

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

    def _status_of(self, sid: str, host=None) -> dict:
        host = host if host is not None else self.host
        if host is None:
            return {}
        try:
            return host.status(sid)
        except Exception:  # noqa: BLE001 - gone since: no status
            return {}

    def _view(self, f: _Fixed) -> dict:
        st = self._status_of(f.id, f.host)
        stats = st.get("stats") or {}
        state = "outside" if f.outside else st.get("state", "stopped")
        why = "outside_span" if f.outside else st.get("why")
        state, why = _starved_view(state, why, f.starved)
        view = {"id": f.id, "decoder": f.decoder, "freqHz": f.freq, "params": dict(f.params), "state": state,
                "why": why, "whyText": _why_text(why), "since": _iso(st.get("since")), "rev": st.get("rev", 0),
                "stats": _stats(stats), "panel": f.panel}
        if f.held:
            view.update(holdsReceiver=True, block=f.block)
        if f.held or f.panel == "meta" or "meta" in f.outputs:
            # The decoder's last feed (DAB's ensemble, wide FM's RDS, PSK's
            # channels, the SSTV picture being received).
            view["meta"] = self._meta(st["meta"]) if isinstance(st.get("meta"), dict) else None
        return view

    def _meta(self, fields: dict) -> dict:
        """A session's feed as clients get it: worded (_worded_meta, with
        Radio's DAB pictures: dabpics.py), then whatever the app adds
        (Radio names DAB's transmitters from their TII codes:
        Engine.decoder_meta). What an app adds is never worth the feed: if
        it fails, the feed goes out without it."""
        out = _worded_meta(fields, self._pictures())
        add = getattr(self.engine, "decoder_meta", None)
        if add is not None:
            try:
                out = add(out)
            except Exception:  # noqa: BLE001 - see above
                log.warning("the app's addition to a decoder feed failed", exc_info=True)
        return out

    def _pictures(self):
        """Radio's store of DAB's pictures (dabpics.py); None in NB."""
        return getattr(self.engine, "dab_pictures", None)

    def _vfo_view(self, vfo) -> dict:
        sid, dec = vfo
        st = self._status_of(sid)
        s = self.engine.st
        state, why = _starved_view(st.get("state", "stopped"), st.get("why"), self._vfo_starved)
        decoder = getattr(dec, "decoder", "")
        entry = _catalogue_entry(decoder) or {}
        view = {"id": VFO, "decoder": decoder, "freqHz": s.get("rxDial"),
                "params": dict(getattr(dec, "params", {})), "state": state,
                "why": why, "whyText": _why_text(why), "since": _iso(st.get("since")),
                "rev": st.get("rev", 0), "stats": _stats(st.get("stats") or {}),
                "panel": entry.get("panel", "text"), "mode": True}
        if "meta" in (entry.get("outputs") or ()):
            view["meta"] = self._meta(st["meta"]) if isinstance(st.get("meta"), dict) else None
        # The mode decoder's IQ is the dial's audio, centred where the host's
        # adapter put it: PSK's channel offsets are from there (sdrmode.py).
        centre = getattr(dec, "host_center", None)
        if centre is not None and decoder == "psk":
            view["audioCentreHz"] = float(centre)
        return view

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


def session_label(decoder: str, freq: float) -> str:
    """How a sentence names a session: "RTTY on 14.0933 MHz"."""
    return _("{decoder} on {freq}").format(decoder=decoder.upper(), freq=_mhz(freq))


def sessions_text(sessions: list[dict]) -> str:
    """Several sessions' labels in one phrase ("RTTY on 14.0933 MHz, APRS
    on 144.8000 MHz")."""
    return ", ".join(s["label"] for s in sessions)


def switched_off() -> set[str]:
    """Decoders the library has that this app does not offer yet: `psk`
    while sdr.PSK_ON_SHACK_SDR is off (sdr.py says why). Not listed, and
    a session of one is refused as unknown_decoder."""
    return set() if sdr.PSK_ON_SHACK_SDR else {"psk"}


def _catalogue_entry(decoder: str) -> dict | None:
    m = sdr.load()
    if m is None or not decoder:
        return None
    return next((e for e in m.catalogue() if e["id"] == decoder), None)


def _takes_receiver(entry: dict) -> bool:
    """Whether a catalogue entry's decoder needs the whole receiver."""
    return float(entry.get("minRateHz") or entry.get("rateHz") or 0.0) >= RECEIVER_RATE


def _worded_meta(fields: dict, pictures=None) -> dict:
    """A DAB feed (a session's `meta`) with each `why` worded beside its
    code: the feed's own `whyText`, and each service's; each service's
    programme type named (`ptyName`, RDS's European table, which DAB shares:
    shack_sdr.wfm.pty_name), and with Radio's store its logo paths and the
    latest slide's (dabpics.py)."""
    out = dict(fields)
    out["whyText"] = _why_text(out.get("why")) if out.get("why") else ""
    services = out.get("services")
    if isinstance(services, list):
        out["services"] = [dict(sv, whyText=_why_text(sv.get("why")) if sv.get("why") else "",
                                ptyName=pty_name(sv.get("pty")))
                           if isinstance(sv, dict) else sv for sv in services]
    return pictures.decorate(out) if pictures is not None else out


def pty_name(pty) -> str | None:
    """A DAB service's programme type ({"code", "id", "dynamic"}) by name,
    in the app's language; None without one, or under a table we do not
    know (`id` null: shack_sdr names only the European one)."""
    if not isinstance(pty, dict) or pty.get("id") is None:
        return None
    m = sdr.load()
    try:
        return m.wfm.pty_name(pty.get("code")) if m is not None else None
    except AttributeError:
        return None


def starvation(watch: list[tuple[float, int, int]], was: str | None, cpu: float | None = None) -> str | None:
    """Whether a session is starved, from its (t, fed, dropped) samples over
    the last STARVED_S (oldest first), its decoder's `cpu` now (the host's
    two-second share) and what it was before: None, or "decoder_stuck"
    (the decoder took nothing, as a worker that never comes back out of a
    block) or "decoder_behind" (most of it dropped: the decoder takes some,
    too slowly).

    The host drops whole blocks from the front of a full ring, so a decoder
    that takes nothing loses exactly what it is fed once the ring is full -
    ohs-box's "dropped climbs by exactly 2.4 MS/s". Where the blocks are not
    all one length (a channel of the bank) the two differ by a block now and
    then, so most of it dropped with no decoding time charged at all is
    stuck too: the host charges a session's time only when a block comes
    back out of its decoder. Until a full window has passed the answer stays
    what it was."""
    if len(watch) < 2 or watch[-1][0] - watch[0][0] < STARVED_S - 0.5:
        return was
    fed = watch[-1][1] - watch[0][1]
    dropped = watch[-1][2] - watch[0][2]
    if fed <= 0:
        # Fed nothing (outside, paused, between blocks): nothing to judge.
        return was
    if dropped >= fed or (dropped >= STARVED_SHARE * fed and cpu is not None and cpu <= 0):
        return "decoder_stuck"
    if dropped >= STARVED_SHARE * fed:
        return "decoder_behind"
    if was is not None and dropped >= RECOVERED_SHARE * fed:
        return "decoder_behind"
    return None


def _starved_view(state: str, why: str | None, starved: str | None) -> tuple[str, str | None]:
    """A session's state and why as a client sees them: the host's, unless
    the starvation watch says it decodes nothing of what it is fed. A stuck
    decoder never leaves the host's `starting`, which is the silence this
    replaces with `error`."""
    if starved is None or state in ("outside", "budget", "stopped"):
        return state, why
    return ("error" if starved == "decoder_stuck" else state), starved


def _close_own_host(f: "_Fixed") -> bool:
    """Close a held session's own host (stop, Decoders.close). False when
    its worker did not come back: a thread stuck inside a decoder cannot be
    stopped, and is left behind, which is said once here."""
    host, f.host = f.host, None
    if host is None:
        return True
    try:
        joined = host.close()
    except Exception:  # noqa: BLE001 - closing what is already closed
        return True
    if not joined:
        log.warning("decoder session %s (%s): its decoder thread did not stop and is left running; "
                    "restart Radio to end it", f.id, f.decoder)
    return joined


def _image_for_clients(it: dict) -> dict:
    """An `image` result as the feed and api/decoders carry it: `rgb` as
    base64 text, and a saved file named but not placed (no `path`)."""
    out = {k: v for k, v in it.items() if k != "path"}
    rgb = out.get("rgb")
    if isinstance(rgb, (bytes, bytearray)):
        out["rgb"] = base64.b64encode(bytes(rgb)).decode("ascii")
    return out


def _usb(iq: np.ndarray) -> np.ndarray:
    """Channel IQ to USB audio (the real part: the channel is centred on the
    carrier, so the signal sits at its offset above it)."""
    return np.ascontiguousarray(iq.real, dtype=np.float32)


def _stats(st: dict) -> dict:
    out = {"snrDb": st.get("snrDb"), "offsetHz": st.get("offsetHz"), "cpu": st.get("cpu"),
           "fed": st.get("fed", 0), "dropped": st.get("dropped", 0)}
    for k in ("baud", "sync", "chars", "wpm", "frames", "fibsOk", "fibsBad", "audioFrames", "audioErrors",
              "superframes", "aus", "auErrors", "channels", "acquisitions", "images", "partials", "lines",
              "visHeard", "visBad"):
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
