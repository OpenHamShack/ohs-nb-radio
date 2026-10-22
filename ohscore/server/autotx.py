"""Automatic transmit for the digital modes in the store form: the
operator arms it (WSJT-X's Enable TX), chooses what to send - call CQ,
answer a decode, or a line of text - and the server keys the radio itself
for each over and unkeys at its end, as WSJT-X does with CAT PTT. Before
11/10/2026 the store API had no route to the engine's send() at all, so
from OpenHamShack Remote the only way to transmit FT8 was to hold PTT,
which sends the microphone: an FT8 signal had to be played into it.

Nothing here keys around the server's own path. Every over goes through
Server.key - the Transmit level was checked when the arm was taken, then
the engine's key-up check (licence, band plan, the occupied band measured
from the rendered message, ohscore/txguard.py), the broker's tx claim and
on-air answer, and the over is held under the arming remote's lease. So
the lease loop ends each over the same way it ends a PTT over (broker told,
claim back to rx), and a remote that goes quiet for LEASE_S unkeys and
disarms. The engine's own time-out and watchdog still apply to every over.

The arm is deliberately fragile, because the safe direction is off:
- it is never on after a restart (it lives only in memory);
- it is held by one remote, which must heartbeat it (api/ptt/heartbeat)
  whether or not an over is on the air;
- halt, PTT off, stop, a lost broker claim, a hand-over, a change of mode,
  any refused or cut-short over, the QSO ending, and IDLE_S without the
  operator choosing anything (WSJT-X's Tx watchdog) all disarm it;
- it never re-arms by itself.

The slotted modes (ft8, ft4, q65) are sequenced with ohscore.ft8seq, the
desktop FT8 panel's own sequencer: each decode addressed to us moves the
QSO on, and the next over goes out in our parity's next slot. The text
modes (psk, rtty, cw) send one line per request, keyed for its length.
"""
from __future__ import annotations

import logging
import math
import time

from .. import engine
from ..ft8seq import Sequencer, sender
from ..i18n.text import _

log = logging.getLogger("ohscore.server.autotx")

SEQ_MODES = ("ft8", "ft4", "q65")
TEXT_MODES = ("psk31", "psk63", "psk125", "rtty", "cw")
# WSJT-X's Tx watchdog default: six minutes calling with nobody answering
# and nobody at the controls stops it. Heartbeats do not count as someone
# at the controls - a phone left on a table sends them by itself.
IDLE_S = 360.0
# How long before our slot starts the over is handed to the engine. Late
# enough that the slot before (theirs) has been decoded - its early pass
# lands at about 13.5 s of 15 (ohscore/modes/ft8.py EARLY_S) - and early
# enough to render it and be keyed on the boundary (engine SLOT_LEAD).
DECIDE_LEAD_S = 0.4
# The audio offsets a slotted over may use: FT8 is 50 Hz wide, kept inside
# the 200-3000 Hz the transmit chain passes (the desktop's own limits).
OFFSET_MIN, OFFSET_MAX = 200.0, 2900.0
TEXT_MAX = 200


class Refused(ValueError):
    """An arm or a choice that cannot be taken: `code` for the client."""

    def __init__(self, text: str, code: str, status: int = 409):
        super().__init__(text)
        self.code, self.status = code, status


class AutoTx:
    def __init__(self, srv, wall=time.time):
        self.srv = srv
        self.radio = srv.radio
        self.wall = wall              # UTC seconds: slots are UTC
        self.lock = srv.lock
        self.remote: str | None = None
        self.acting = "-"
        self.last = 0.0               # last heartbeat, srv.clock
        self.last_action = 0.0        # last operator choice (or the DX answering), srv.clock
        self.mode = ""
        self.seq = Sequencer()
        self.active = False           # a CQ or a QSO is under way: overs are due
        self.period = 0               # our slot parity, 0 even / 1 odd
        self.offset = 1500.0
        self.sent_slot: int | None = None
        self.in_flight = False        # an over handed to the engine and not yet ended
        self.end_after_over = False   # the QSO is done once this over has gone
        self.why_off = ""
        self._events = self.radio.subscribe("events", 256)

    # ---------------------------------------------------------- view
    def view(self) -> dict:
        with self.lock:
            msg = self.seq.message() if self.active and self.mode in SEQ_MODES else ""
            return {"armed": self.remote is not None, "remote": self.remote, "mode": self.mode or None,
                    "active": self.active, "dx": self.seq.dx or None, "next": msg,
                    "period": ("even", "odd")[self.period], "offset": self.offset,
                    "sequenced": list(SEQ_MODES), "text": list(TEXT_MODES), "why": self.why_off}

    # ---------------------------------------------------------- the operator
    def arm(self, remote: str, acting: str) -> None:
        """Enable TX for `remote`. Sends nothing by itself."""
        with self.lock:
            if self.remote is not None and self.remote != remote:
                raise Refused(_("Automatic transmit is armed by another remote"), "armed_elsewhere")
            lease = self.srv.lease
            if lease is not None and lease["id"] != remote and self.radio.state().get("keyed"):
                raise Refused(_("Another remote is transmitting"), "not_lease_holder")
            st = self.radio.state()
            mode = st.get("mode") or ""
            if mode not in SEQ_MODES + TEXT_MODES:
                raise Refused(_("Automatic transmit is for the digital modes; the radio is in {mode}").format(
                    mode=mode.upper()), "not_digital")
            if not (st.get("modes", {}).get(mode) or {}).get("encode", mode == "cw"):
                raise Refused(_("{mode} cannot transmit here").format(mode=mode.upper()), "no_encoder")
            call = str(st.get("callsign") or "").strip().upper()
            if not call:
                # Every over names the sender; NOCALL on the air is not lawful.
                raise Refused(_("Set your callsign in the station profile before transmitting"), "no_callsign")
            if self.remote is None or self.mode != mode:
                self.seq = Sequencer(call, str(st.get("locator") or ""))
                self.active = False
                self.sent_slot = None
                self.end_after_over = False
            self.remote, self.acting, self.mode = remote, acting, mode
            self.last = self.last_action = self.srv.clock()
            self.why_off = ""
            log.info("automatic transmit armed by %s in %s", remote, mode)

    def disarm(self, why: str = "") -> bool:
        """Off. True if it was armed. Never unkeys by itself: the caller
        decides how the over on the air ends (halt, or let it finish)."""
        with self.lock:
            was = self.remote is not None
            self.remote = None
            self.active = False
            self.end_after_over = False
            # Whoever disarms ends the over too, or lets it finish; either
            # way it is no longer this sequence's, and a stale "in flight"
            # would greet the next arm with the old over's txError.
            self.in_flight = False
            if was:
                self.why_off = why
                log.info("automatic transmit off%s", f": {why}" if why else "")
            return was

    def _holder(self, remote: str) -> None:
        if self.remote is None:
            raise Refused(_("Automatic transmit is not armed"), "not_armed")
        if self.remote != remote:
            raise Refused(_("Automatic transmit is armed by another remote"), "armed_elsewhere")

    def cq(self, remote: str, period: str | None = None, offset: float | None = None) -> None:
        with self.lock:
            self._holder(remote)
            self._slotted()
            self.seq.reset()
            if period in ("even", "odd"):
                self.period = 0 if period == "even" else 1
            else:
                # Whichever slot the engine would start in now - this one
                # while it is young enough (SLOT_LATE), else the next:
                # calling starts as soon as it can.
                slot = engine.SLOT_SEC[self.mode]
                self.period = math.floor(engine.slot_start(self.wall(), self.mode) / slot + 1e-9) % 2
            if offset is not None:
                self.offset = self._offset(offset)
            self._start()

    def reply(self, remote: str, ev: dict) -> None:
        """Answer a decode as the desktop's double-click does: the call and
        grid from it, our report from its SNR, the other parity from its
        slot's, and our transmit on its frequency."""
        with self.lock:
            self._holder(remote)
            self._slotted()
            # WSJT-X's reading (ft8seq.sender): "CQ DX OH8ZZ KP20" is
            # OH8ZZ. It took the second word until 12/10/2026, and so
            # answered DX.
            call, grid = sender(str(ev.get("text") or ""), str(ev.get("call") or ""))
            if not call or call == self.seq.mycall:
                raise Refused(_("There is no call in that message to answer"), "no_call", 400)
            try:
                their_slot = float(ev["slot"])
            except (KeyError, TypeError, ValueError):
                raise Refused(_("A reply needs the decode's slot"), "bad_request", 400) from None
            slot = engine.SLOT_SEC[self.mode]
            self.seq.answer(call, str(ev.get("grid") or grid), ev.get("snr"))
            self.period = 1 - int(round(their_slot / slot)) % 2
            if ev.get("df") is not None:
                self.offset = self._offset(ev["df"])
            self._start()

    def send_text(self, remote: str, text: str) -> None:
        """One line in a text mode, keyed now for as long as it takes."""
        with self.lock:
            self._holder(remote)
            if self.mode not in TEXT_MODES:
                raise Refused(_("Lines of text are sent in the text modes; the radio is in {mode}").format(
                    mode=self.mode.upper()), "not_text_mode")
            text = str(text or "")[:TEXT_MAX].strip()
            if not text:
                raise Refused(_("There is nothing to send"), "bad_request", 400)
            if self.in_flight or self.radio.state().get("keyed"):
                raise Refused(_("Already transmitting"), "busy")
            self.last_action = self.srv.clock()
            opts = {} if self.mode == "cw" else {"freq": _text_offset(self.mode)}
            mode = self.mode
            if not self._over(lambda: self.radio.send(mode, text=text + " ", **opts)):
                raise Refused(self.why_off, "tx_refused")

    def _slotted(self) -> None:
        if self.mode not in SEQ_MODES:
            raise Refused(_("CQ and replies are sequenced in FT8, FT4 and Q65; the radio is in {mode}").format(
                mode=self.mode.upper()), "not_sequenced")

    @staticmethod
    def _offset(v) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            raise Refused(_("offset must be a number of hertz"), "bad_request", 400) from None
        return min(OFFSET_MAX, max(OFFSET_MIN, f))

    def _start(self) -> None:
        self.active = True
        self.end_after_over = False
        self.sent_slot = None
        self.last_action = self.srv.clock()

    # ---------------------------------------------------------- the loop
    def tick(self) -> None:
        """Ten times a second, on the server's own thread. A stop decided
        here ends any over on the air after the lock is let go: ending a
        lease waits for the radio to drain, and http requests (a halt among
        them) must not queue behind that."""
        events = self._events.drain()
        with self.lock:
            stop = self._step(events)
        if stop:
            self.srv.halt_if_keyed(stop)

    def _step(self, events: list) -> str:
        """Under the lock: '' to carry on, or why automatic transmit has
        just stopped (and any over on the air must end)."""
        if self.remote is None:
            return ""
        now = self.srv.clock()
        why = ""
        if now - self.last > self.srv.LEASE_S:
            why = _("Automatic transmit stopped: remote controller lost (no word from {id} for {s:.0f} s)").format(
                id=self.remote, s=self.srv.LEASE_S)
        elif (self.radio.state().get("mode") or "") != self.mode:
            why = _("Automatic transmit stopped: the mode changed")
        elif now - self.last_action > IDLE_S:
            why = _("Automatic transmit stopped: nothing chosen for {m:.0f} minutes").format(m=IDLE_S / 60)
        if why:
            self.disarm(why)
            return why
        if self.in_flight and not self.radio.state().get("keyed") and self.srv.lease is None:
            # The over has ended and the lease loop has finished with it.
            self.in_flight = False
            if self.srv.tx_error:
                # Cut short or refused at the radio (time-out, a guard on
                # re-check, the broker): never tried again by itself.
                self.disarm(self.srv.tx_error)
                return ""
            if self.end_after_over:
                self.disarm(_("QSO with {call} complete").format(call=self.seq.dx) if self.seq.dx else "")
                return ""
        for ev in events:
            self._heard(ev)
        if self.remote is not None and self.active and self.mode in SEQ_MODES and not self.in_flight:
            self._next_over()
        return ""

    def _heard(self, ev: dict) -> None:
        if not self.active or ev.get("mode") != self.mode or "text" not in ev or ev.get("error"):
            return
        res = self.seq.heard(str(ev["text"]), ev.get("snr"))
        if res["next"] is None:
            return
        self.last_action = self.srv.clock()      # the other station is answering: someone is there
        if res["log"]:
            self._log()
            self.disarm(_("QSO with {call} logged").format(call=self.seq.dx))

    def _log(self) -> None:
        try:
            self.radio.log_qso(self.seq.dx, mode=self.mode, rstSent=self.seq.sent, rstRcvd=self.seq.rcvd,
                               grid=self.seq.dxgrid)
        except ValueError as e:
            log.warning("could not log %s: %s", self.seq.dx, e)

    def _next_over(self) -> None:
        slot = engine.SLOT_SEC[self.mode]
        now = self.wall()
        period = ("even", "odd")[self.period]
        start = engine.slot_start(now, self.mode, period)
        k = math.floor(start / slot + 1e-9)
        if k == self.sent_slot or start - now > DECIDE_LEAD_S:
            return
        if self.radio.state().get("keyed"):
            return                        # someone else's over: wait for it to end
        n = self.seq.next
        msg = self.seq.message()
        self.sent_slot = k
        ok = self._over(lambda: self.radio.send(self.mode, text=msg, freq=self.offset, period=period))
        if not ok:
            return
        self._sent(k * slot, msg)          # the slot itself, as decodes name theirs (start is its key-up, 0.5 s in)
        if self.seq.sent_now(n):
            self._log()
        if n == 5:
            # 73 is the last over of a QSO (the desktop stops there too).
            self.end_after_over = True

    def _sent(self, slot: float, msg: str) -> None:
        """Our own over, on api/events beside the decodes, so a remote's
        Band Activity can show it in its slot as the desktop's FT8 panel
        shows its "TX" rows (Brian, 12/10/2026). Nested under "tx", with
        no top-level "text" or "slot", on purpose: every reader of decodes
        - a Remote built before this, the sequencer here (_heard), the
        desktop panel - takes an event with "text" for a station heard,
        and our own message read as heard would answer ourselves. Published
        straight to the feed, not through _emit_event, so the spotter and
        the skimmer never see it either."""
        self.radio._publish("events", {"mode": self.mode, "t": self.wall(), "dial": self.radio.state().get("rxDial"),
                                       "tx": {"slot": slot, "df": round(self.offset), "text": msg}})

    def _over(self, start) -> bool:
        """Key one over under the arming remote's lease, through the
        server's own key-up path. A refusal disarms with the reason."""
        why = self.srv.key(self.remote, self.acting, start=start, digital=True)
        if why:
            self.disarm(why)
            return False
        self.in_flight = True
        return True


def _text_offset(mode: str) -> float:
    """Where a text mode's signal sits, as the desktop's text panel puts
    it: the mode's own default offset."""
    try:
        from ..modes import MODES
        return float(MODES[mode].offset_hz)
    except Exception:  # noqa: BLE001 - the registry may be missing; the decoders' default
        return 1000.0
