"""The standard FT8/FT4 QSO, as WSJT-X sequences it - kept free of Qt so it
can be tested on its own.

    Tx1  DX MYCALL GRID      answer a CQ
    Tx2  DX MYCALL -12       report
    Tx3  DX MYCALL R-12      roger + report
    Tx4  DX MYCALL RR73      roger, 73
    Tx5  DX MYCALL 73
    Tx6  CQ MYCALL GRID

`heard()` takes a decode addressed to us and says what to send next, and
whether the QSO is now complete enough to log (WSJT-X's rule: once reports
have been exchanged and a 73/RR73 has gone either way).

It lives in ohscore rather than ohscore/ui, where it began beside the
desktop's FT8 panel, because the store form's automatic transmit
(ohscore/server/autotx.py) sequences QSOs with it too, and the store image
ships without ohscore/ui (tools/build-store.sh). One sequencer for both, so
a Remote's QSO and a desktop's go the same way.
"""
from __future__ import annotations

import math
import re

GRID = re.compile(r"^[A-R]{2}[0-9]{2}$")
REPORT = re.compile(r"^[+-]\d{2}$")
RREPORT = re.compile(r"^R[+-]\d{2}$")


def is_cq_modifier(w: str) -> bool:
    """A CQ's modifier, as WSJT-X allows one between CQ and the call:
    one to four letters (DX, NA, TEST, POTA, SOTA...) or three digits (a
    frequency to answer on, CQ 290)."""
    return (w.isalpha() and 1 <= len(w) <= 4) or (w.isdigit() and len(w) == 3)


def sender(text: str, call: str = "") -> tuple[str, str]:
    """(call, grid) of the station that sent `text`, for an answer: the
    decoder's own `call` when it named one; else, for a CQ, the word after
    CQ and its modifier ("CQ DX OH8ZZ KP20" is OH8ZZ, not DX); else the
    second word ("GM4BRI EA8XYZ -12"). Up to 12/10/2026 both the store
    form's reply and the desktop's double-click took the second word, so
    "CQ DX ..." and "CQ POTA ..." were answered as DX and POTA. The grid
    is the word after the call when it is one. ("", "") when there is no
    call to answer."""
    words = [w.strip("<>") for w in str(text or "").upper().split()]
    i = 1
    if words[:1] == ["CQ"] and len(words) > 2 and is_cq_modifier(words[1]):
        i = 2
    found = words[i] if len(words) > i else ""
    who = (call or "").upper() or found
    if not who or who == "CQ" or not any(c.isdigit() for c in who):
        return "", ""
    grid = words[i + 1] if found == who and len(words) > i + 1 and GRID.match(words[i + 1]) else ""
    return who, grid


def fmt_report(snr) -> str:
    v = max(-30, min(49, int(round(float(snr)))))
    return f"{v:+03d}"


def plan_over(now: float, slot: float, ours: int, sent_slot: int | None, fresh: bool, late_until: float,
              decode_wait: float = 2.5, cutoff: float = 0.8) -> int | None:
    """Which slot (its index, floor(utc / slot)) the panel should queue its
    next over for at `now`, or None to wait. `ours` is our parity (0 even,
    1 odd), `sent_slot` the slot already queued or sent, `fresh` that what
    goes next has just been decided (the operator clicked a station, picked
    a Tx row or switched Enable TX on, or a decode moved the QSO on) and
    `late_until` how far into a slot an
    over may still start (the engine's SLOT_LEAD + SLOT_LATE, less the time
    rendering takes).

    Two ways to an over:
    - In one of our own slots, a fresh decision goes in that slot itself,
      late-started, while there is still time. The decodes of the slot
      just ended - the other station's - land a second or so into ours,
      and a click on one of them is exactly this case. Up to 16/10/2026
      the panel only ever queued for the *next* slot, so a click on a
      station decoded in the slot just ended (which, being theirs, makes
      the current slot ours) skipped the current slot and the whole of
      theirs: 27 s from click to key-up (Ray, QO-100 FT8 on an IC-9700).
      The returned slot may be `sent_slot`: the caller replaces what it
      queued there, if the message has changed.
    - From the other station's slot, the next slot (ours) once that slot
      is `decode_wait` s old - time for the decodes of the slot before to
      have changed what we say - and not later than `cutoff` s before it
      ends, so the engine can render and start on the boundary. A fresh
      decision does not wait for decodes it does not depend on.

    A decision that is not fresh never late-starts: a repeat goes on the
    boundary or not at all, as the other station's DT tolerance is better
    spent on their clock than on our scheduling."""
    cur = math.floor(now / slot)
    into = now - cur * slot
    if cur % 2 == ours:
        return cur if fresh and into <= late_until else None
    nxt = cur + 1
    if into > slot - cutoff or (nxt == sent_slot and not fresh):
        return None
    if fresh or into >= min(decode_wait, slot * 0.25):
        return nxt
    return None


class Sequencer:
    def __init__(self, mycall: str = "", mygrid: str = ""):
        self.mycall = mycall.upper()
        self.mygrid = (mygrid or "")[:4].upper()
        self.reset()

    def reset(self):
        self.dx = ""
        self.dxgrid = ""
        self.sent = "-10"          # report we send them
        self.rcvd = ""             # report they sent us
        self.next = 6              # Tx6: CQ
        self.logged = False
        self.sent_rr73 = False

    def messages(self) -> dict[int, str]:
        m, g, d = self.mycall or "NOCALL", self.mygrid, self.dx
        if not d:
            return {6: f"CQ {m} {g}".strip()}
        return {1: f"{d} {m} {g}".strip(), 2: f"{d} {m} {self.sent}", 3: f"{d} {m} R{self.sent}",
                4: f"{d} {m} RR73", 5: f"{d} {m} 73", 6: f"CQ {m} {g}".strip()}

    def message(self, n: int | None = None) -> str:
        msgs = self.messages()
        return msgs.get(self.next if n is None else n, msgs[6])

    def answer(self, call: str, grid: str = "", snr=None):
        """Operator clicked a CQ (or any line from `call`): start a QSO with them."""
        self.reset()
        self.dx = call.upper()
        self.dxgrid = grid.upper() if grid and GRID.match(grid.upper()) else ""
        if snr is not None:
            self.sent = fmt_report(snr)
        self.next = 1

    def sent_now(self, n: int) -> bool:
        """We have just queued Tx n. True if that completes the QSO (log it)."""
        if n == 4:
            self.sent_rr73 = True
        if n == 5 and self.rcvd and not self.logged:
            self.logged = True
            return True
        return False

    def heard(self, text: str, snr=None) -> dict:
        """A decode. Returns {"next": n or None, "log": bool, "new_dx": call or ""}."""
        out = {"next": None, "log": False, "new_dx": ""}
        words = text.upper().split()
        if len(words) < 2 or not self.mycall or words[0] != self.mycall:
            return out
        frm = words[1]
        rest = words[2] if len(words) > 2 else ""
        if not self.dx:
            # Someone answered our CQ.
            self.dx = frm
            out["new_dx"] = frm
            if snr is not None:
                self.sent = fmt_report(snr)
        elif frm != self.dx:
            return out
        if snr is not None and self.next in (1, 6):
            self.sent = fmt_report(snr)
        # RR73 first: it also matches the grid pattern (R, R, 7, 3), and taking
        # it for a locator would restart the QSO at the report.
        if rest in ("RR73", "RRR"):
            self.next = 5
        elif GRID.match(rest):
            self.dxgrid = rest
            self.next = 2
        elif REPORT.match(rest):
            self.rcvd = rest
            self.next = 3
        elif RREPORT.match(rest):
            self.rcvd = rest[1:]
            self.next = 4
        elif rest == "73":
            if self.sent_rr73 and not self.logged and self.rcvd:
                self.logged = True
                out["log"] = True
            self.next = 6
        out["next"] = self.next
        return out
