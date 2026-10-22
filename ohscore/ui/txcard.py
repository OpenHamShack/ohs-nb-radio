"""What both apps' transmit cards share: how much of the card shows.

Three forms, set by the window's workspace (docs/ui-overhaul-2026-10.md
sections 2.1 and 5.9; the window calls set_form() if the card has one):

  full     everything, as the card always was
  compact  the power control, the standing warning and the meter the app
           names (NB: own signal vs beacon); the rest (ALC, the level
           guard's sentence, Radio's forward/SWR/temperature) comes back
           while on the air, which is when they say anything
  hidden   Watch: the card is gone until something transmits or a warning
           stands

Whatever the form, a run that cannot transmit (txstate NEVER) or needs
setting up first (SETUP) shows one line instead of controls that can do
nothing - "Receive only this run", or "Set up to transmit" and a button to
Settings › Station - which is the fix for the Mac test's FINDINGS 4 (a
receive-only card telling the operator that nothing was refused).

The one rule that is not negotiable (overhaul section 7.3): no form and no
collapse hides the card while anything is on the air - an IC-9700 keyed at
its own microphone included, which is why it asks Face.on_air and not the
engine's keyed alone - or while a transmit warning stands. That judgement
is txstate.may_collapse(); this module only applies it, and re-applies it
on every state change and frame tick so a radio keyed by hand brings the
card back within a frame of the window hearing it.
"""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from . import theme, txstate
from .controls import Button, Card
from .theme import S2

FORMS = ("full", "compact", "hidden")


class TxCard(Card):
    """A Card whose controls live in `self.body` (lay them out on
    `self.blay`), with the collapsed line beside it. Subclasses call
    sync_form() at the end of on_state(), and read detail() for the parts
    the compact form drops."""

    def __init__(self, title: str, bridge, parent=None):
        super().__init__(title, parent)
        self.bridge = bridge
        self.form = "full"
        self.collapsed = False
        self.body = QWidget()
        self.blay = QVBoxLayout(self.body)
        self.blay.setContentsMargins(0, 0, 0, 0)
        self.blay.setSpacing(S2)
        self.lay.addWidget(self.body)
        # The one line a run that cannot transmit gets instead.
        self.short = QWidget()
        row = QHBoxLayout(self.short)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(S2)
        self.short_text = QLabel("")
        self.short_text.setWordWrap(True)
        self.short_text.setTextFormat(Qt.TextFormat.PlainText)
        self.short_text.setObjectName("Muted")
        row.addWidget(self.short_text, 1)
        # translate(), not self.tr(): each app's card is a subclass (docs/I18N.md, the subclass trap).
        self.short_btn = Button(QCoreApplication.translate("TxCard", "Settings…"), small=True)
        self.short_btn.clicked.connect(self._open_station)
        row.addWidget(self.short_btn)
        self.short.hide()
        self.lay.addWidget(self.short)
        self._last: tuple | None = None
        self._hid = False                          # whether the hidden form hid it

    # ------------------------------------------------------------ the rules
    def on_air(self) -> bool:
        st = self.bridge.st
        try:
            return bool(self.bridge.face.on_air(st))
        except Exception:  # noqa: BLE001 - unsure counts as on the air: the card stays in full
            return True

    def busy(self) -> bool:
        """On the air, keyed, or a warning standing: the times nothing of
        the card may be hidden (may_collapse with a class that would allow it)."""
        return not txstate.may_collapse(txstate.TxState(txstate.NEVER), self.bridge.st, self.on_air())

    def detail(self) -> bool:
        """Whether the parts the compact form drops are shown."""
        return self.form == "full" or self.on_air() or bool(self.bridge.st.get("keyed"))

    def set_form(self, form: str) -> None:
        self.form = form if form in FORMS else "full"
        self._last = None
        self.on_state(self.bridge.st)

    def _form_key(self) -> tuple:
        state = txstate.of_bridge(self.bridge)
        collapse = txstate.may_collapse(state, self.bridge.st, self.on_air())
        hide = self.form == "hidden" and not self.busy()
        return state, collapse, hide, self.form, self.detail()

    def sync_form(self) -> None:
        key = self._form_key()
        state, collapse, hide = key[:3]
        if key == self._last:
            return
        self._last = key
        self.collapsed = collapse
        if collapse:
            if state.kind == txstate.NEVER:
                self.short_text.setText(QCoreApplication.translate("TxCard", "Receive only this run"))
            else:
                self.short_text.setText(QCoreApplication.translate("TxCard", "Set up to transmit: Settings › Station"))
            self.short_text.setToolTip(state.why)
            self.short_text.setStyleSheet(f"color: {theme.t()['text2']};")
            self.short_btn.setVisible(state.kind == txstate.SETUP)
        self.body.setVisible(not collapse)
        self.short.setVisible(collapse)
        # Visibility is touched only by the hidden form (and on leaving it):
        # otherwise it is the window's, and a card not yet in the rail
        # shown here would open as a window of its own.
        if self.form == "hidden" or self._hid:
            self.setVisible(not hide)
            self._hid = hide

    def tick_form(self) -> None:
        """Every frame: a few dictionary lookups when nothing changed. When
        something did - the class, on the air, a warning - the whole card is
        brought up to date, since the compact form's parts follow the air too."""
        if self._form_key() != self._last:
            self.on_state(self.bridge.st)

    def _open_station(self) -> None:
        win = self.window()
        if hasattr(win, "open_settings"):
            win.open_settings("page_station")
