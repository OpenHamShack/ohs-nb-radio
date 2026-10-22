"""Who is the pile-up on, who is calling, and where do we stand in it.

The slot panel's one-line summary above the band activity (FT8, FT4 and
Q65; docs/ui-overhaul-2026-10.md section 5.7). An operator in a pile-up
reads twenty lines a slot to answer three questions - who is everyone
calling, how many and how strong are they, and has the DX heard me - and
WSJT-X answers none of them. This answers them from the decodes the
panel already has.

No Qt and no app here: plain decode dicts in, a Pileup out, so the rules
are tested on synthetic decodes (tests/test_pileup.py) and the store form
or Remote's NB kind can use the same ones later. The words are the
panel's, so they can be translated.

The rules:

- **Who:** the station in the QSO card's DX call when one is set; else the
  station with the most distinct callers. Callers are counted over the
  last two slots of one parity, since everyone calling a DX calls in the
  parity opposite to it, and a caller usually takes two or three overs to
  be heard. At least two callers, or it is a QSO and not a pile-up.
- **Callers:** how many, the strongest first. We are counted when we
  called (or were heard calling) but never listed: the "you" part says it.
- **You:** "answered" when the DX's latest message names us first;
  "heard" when our own call to it came back through the satellite (NB
  hears its own downlink, so this is proof our signal reached the
  transponder); "calling" when our last over went to it; else "not".
  Separately, `working` names whoever else the DX's latest message
  answered.

A decode is a dict as the engine's events carry it: `text`, `slot` (the
period start, UTC seconds), `snr`, optionally `call` (the sender, when the
decoder named one).
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Distinct callers (we included) before a station counts as a pile-up.
MIN_CALLERS = 2
# Callers named on the line; the rest are "+N more".
SHOW_CALLERS = 3
NOT, CALLING, HEARD, ANSWERED = "not", "calling", "heard", "answered"


@dataclass(frozen=True)
class Pileup:
    dx: str
    callers: list = field(default_factory=list)   # [(call, snr)], strongest first, without us
    count: int = 0                                # every distinct caller, us included
    you: str = NOT                                # NOT, CALLING, HEARD or ANSWERED
    working: str = ""                             # whom the DX last answered, when not us

    @property
    def shown(self) -> list:
        return self.callers[:SHOW_CALLERS]

    @property
    def more(self) -> int:
        """Callers not named on the line (we are never named)."""
        return max(0, len(self.callers) - SHOW_CALLERS)


def _words(text: str) -> list[str]:
    return [w.strip("<>") for w in str(text or "").upper().split()]


def _is_call(w: str) -> bool:
    # Calls have a digit and a letter; CQ, RR73, reports and grids are
    # told apart by the place they stand in, this only keeps out words
    # like "CQ", "DE" and "TNX".
    return any(c.isdigit() for c in w) and any(c.isalpha() for c in w) and w not in ("RR73", "73")


def _addressed(ev: dict) -> tuple[str, str] | None:
    """(to, from) of a standard message "TO FROM ...", or None for a CQ,
    a free text or anything else that calls no one in particular."""
    w = _words(ev.get("text"))
    if len(w) < 2 or w[0] in ("CQ", "QRZ", "DE") or not _is_call(w[0]):
        return None
    frm = (ev.get("call") or "").upper() or w[1]
    if not _is_call(frm) or frm == w[0]:
        return None
    return w[0], frm


def _index(slot: float, period: float) -> int:
    return int(round(float(slot) / period))


def summarise(decodes: list[dict], period: float, mycall: str = "", dx: str = "", sent: str = "",
              now: float | None = None) -> Pileup | None:
    """The pile-up the decodes show, or None when there is none.

    `period` is the mode's slot length; `mycall` ours; `dx` the QSO card's
    DX call ("" when none); `sent` the text of our last over ("" when
    none); `now` (UTC seconds) ends the window, else the latest decode
    does."""
    mycall, dx = (mycall or "").upper(), (dx or "").upper()
    if not decodes:
        return None
    latest = _index(now, period) if now is not None else max(_index(d.get("slot") or 0, period) for d in decodes)
    # Per parity, the last two slots of it up to `latest`: callers per DX.
    calls: dict[tuple[int, str], dict[str, int]] = {}
    for ev in decodes:
        k = _index(ev.get("slot") or 0, period)
        if not latest - 3 <= k <= latest:
            continue
        a = _addressed(ev)
        if a is None:
            continue
        to, frm = a
        got = calls.setdefault((k % 2, to), {})
        snr = int(ev.get("snr") or 0)
        got[frm] = max(snr, got.get(frm, snr))
    my_sent = _words(sent)
    we_call = bool(mycall) and len(my_sent) >= 2 and my_sent[1] == mycall and _is_call(my_sent[0])

    def callers_of(target: str) -> dict[str, int]:
        best: dict[str, int] = {}
        for (_par, to), got in calls.items():
            if to == target and len(got) > len(best):
                best = got
        out = dict(best)
        if mycall and mycall not in out and (heard_by(target) or (we_call and my_sent[0] == target)):
            out[mycall] = 0            # counted, never listed
        return out

    def heard_by(target: str) -> bool:
        # Our own call to it, decoded off the downlink, in either parity.
        return bool(mycall) and any(to == target and mycall in got for (_p, to), got in calls.items())

    if dx:
        target = dx
    else:
        ranked = sorted({to for (_p, to) in calls}, key=lambda t: -len(callers_of(t)))
        target = ranked[0] if ranked else ""
    if not target or target == mycall:
        return None
    who = callers_of(target)
    if len(who) < MIN_CALLERS:
        return None
    listed = sorted(((c, s) for c, s in who.items() if c != mycall), key=lambda cs: (-cs[1], cs[0]))
    # The DX's own latest message: whom it answered.
    theirs = [ev for ev in decodes if (a := _addressed(ev)) is not None and a[1] == target]
    answered = _addressed(max(theirs, key=lambda ev: float(ev.get("slot") or 0)))[0] if theirs else ""
    if mycall and answered == mycall:
        you = ANSWERED
    elif heard_by(target):
        you = HEARD
    elif we_call and my_sent[0] == target:
        you = CALLING
    else:
        you = NOT
    return Pileup(dx=target, callers=listed, count=len(who), you=you,
                  working=answered if answered and answered != mycall else "")

