"""Halt TX for the slot panels (FT8, FT4, Q65 and JS8's send card).

It was a solid red button at all times, so a receive-only run and an idle
station looked as if something were on the air (the overhaul's section
5.3: red means on the air, armed, or danger). Now it is a neutral button
with a stop glyph that turns red while Enable TX is on or anything is on
the air, and hides only when this run cannot transmit at all (txstate
NEVER) and nothing is on the air - the safety rule of section 7.1: halting
never gets harder, and hiding is allowed only when there is nothing it
could halt. A licence still to acknowledge (SETUP) keeps it shown: the
radio is real, and the acknowledgement can be ticked mid-session.

Whatever it looks like, a click always halts (the panel's halt_tx).
"""
from __future__ import annotations

from .. import txstate
from ..controls import Button


class HaltButton(Button):
    def __init__(self, text: str, parent=None):
        super().__init__(text, icon="stop", kind="plain", parent=parent, small=True)
        self.hot = False

    def show_state(self, armed: bool, bridge) -> None:
        """Follow the transmitter: `armed` is the panel's Enable TX; the
        rest comes from the bridge (on the air, and what txstate says)."""
        on_air = bool(bridge.face.on_air(bridge.st)) or bool(bridge.st.get("keyed"))
        hot = bool(armed) or on_air
        if hot != self.hot:
            self.hot = hot
            self.kind = "danger" if hot else "plain"
            self.update()
        state = txstate.of_bridge(bridge)
        hide = state.kind == txstate.NEVER and not hot and txstate.may_collapse(state, bridge.st, on_air)
        if hide != self.isHidden():
            # Only on a change (isHidden, not isVisible: the panel itself
            # may be out of sight): setVisible every tick relays out the card.
            self.setVisible(not hide)
