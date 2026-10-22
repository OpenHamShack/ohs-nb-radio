"""Can this run transmit, and if not, can the operator do anything about it?

The transmit card, the TX tile, the QSO card's Halt TX and the pad's HALT
key each want the same answer, in one of four words
(docs/ui-overhaul-2026-10.md section 5.9):

  ok     a key-up would be attempted
  here   refused here and now - the band plan, the segment, a beacon,
         a recording playing, the radio not running - and the reason is
         the engine's own sentence (Bridge.can_key)
  setup  a real radio and no licence acknowledgement: Settings fixes it
  never  this run cannot transmit at all: started --receive-only, or a
         receive-only device (a SoapySDR); nothing short of a restart
         with other settings changes that

Before this, every widget read can_key()'s sentence and the card told a
receive-only run that "nothing is refused" (Mac test FINDINGS 4). The
classification is a pure function of the state so the rules are tested
without a window; of_bridge() reads it off a live Bridge.

What a widget may do with it is the overhaul's safety rule, kept here
beside the classifier as may_collapse(): a "never" or "setup" card may
shrink to one line, but never while anything is on the air (including an
IC-9700 keyed at its own microphone) or a transmit warning stands.
Halting is never part of this: Escape, the tile and the pad's HALT still
halt whatever the class.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..config import RECEIVE_ONLY_REFUSAL

OK, HERE, SETUP, NEVER = "ok", "here", "setup", "never"

# What can_key() says for a device that cannot transmit and gave no
# reason of its own (ohscore/engine.py _tx_blocked).
RECEIVE_ONLY_DEVICE = "This device is receive-only"


@dataclass(frozen=True)
class TxState:
    kind: str           # OK, HERE, SETUP or NEVER
    why: str = ""       # the sentence to show (the engine's, or the licence one)


def classify(st: dict, licence_locked: bool, receive_only: bool = False, licence_why: str = "") -> TxState:
    """`st` is the engine's state; `licence_locked` whether the licence
    acknowledgement stops a key-up now (Bridge.licence_locked: a real
    radio, or a simulator the app gates, with the box unticked);
    `receive_only` whether the run was started --receive-only (the engine
    says so before its device is open, when canTx is not yet known);
    `licence_why` the sentence to give for SETUP."""
    if receive_only:
        return TxState(NEVER, RECEIVE_ONLY_REFUSAL)
    running = bool(st.get("running"))
    if running and not st.get("canTx"):
        why = st.get("txBlocked") or RECEIVE_ONLY_DEVICE
        # A recording being played has no transmitter, for now: back to
        # the radio and it has one again. Any other device that cannot
        # transmit cannot this run.
        return TxState(HERE if st.get("playing") else NEVER, why)
    if licence_locked:
        return TxState(SETUP, licence_why)
    if not running:
        return TxState(HERE, st.get("error") or "The radio is not running")
    if st.get("txBlocked"):
        return TxState(HERE, st["txBlocked"])
    return TxState(OK)


def of_bridge(bridge) -> TxState:
    """classify() for a live window's Bridge."""
    from .bridge import LICENCE_SENTENCE
    return classify(bridge.st, bridge.licence_locked(), bool(getattr(bridge.radio, "receive_only", False)),
                    LICENCE_SENTENCE)


def may_collapse(state: TxState, st: dict, on_air: bool) -> bool:
    """Whether a transmit widget may shrink or hide for `state`: only when
    this run cannot transmit or needs setting up, and never while anything
    is on the air (`on_air`: Face.on_air, which covers a radio keyed at its
    own microphone) or a transmit warning stands (st["txWarning"]).

    A warning at level "info" does not count: it is a fact, not a danger,
    and the engine shows one only when nothing graver stands (it ranks
    them, Engine.tx_warn). The one there is today is the receive-only
    reason itself (ohsnb/radio.py), which the collapsed card says anyway;
    counting it kept a --receive-only card at full size for ever."""
    if state.kind not in (NEVER, SETUP):
        return False
    w = st.get("txWarning") or {}
    # Nor does "no licence class chosen" (ohsnb/radio.py's "licence" warning):
    # Brian, 17/10/2026, chose to let the card shrink for it - it is a setup
    # reminder the first-run setup asks about, not a danger on the air.
    warning = (bool(w.get("text")) and w.get("level", "warn") != "info"
               and w.get("key") != "licence")
    return not on_air and not warning and not st.get("keyed")
