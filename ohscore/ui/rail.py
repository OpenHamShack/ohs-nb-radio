"""The right-hand rail: mode selector and receive controls. The transmit card
is the app's (NB's power is the Pluto's gain in dB beside the beacon meter;
HAM's will be drive, watts and SWR): ohsnb/ui/rail.py. The mode selector
itself lives in ohscore/ui/modegrid.py since the UI overhaul gave it forms
of its own; it is re-exported here for the code that imports it from here.

The Receive card has two forms since the overhaul's workspaces (section
2.1): "full", everything, and "compact" - the S-meter, SNR, volume and
mute, AGC, and a "More receive controls" line that opens the rest in
place. Digital and Watch want the rail's room for other things; Voice,
where the passband is what matters, shows it all. Which form, and whether
the operator opened the rest, is the window's to keep per workspace.

In the window's Tight tier (overhaul section 3) the whole rail moves into
a RailDrawer that the tab row's Controls button opens over the right of
the lower panel: the same widgets, moved rather than made again."""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, QEvent, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QFontMetrics, QPainter, QPen
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ..dsp.autotune import LISTEN_SECONDS
from ..modegroups import MODE_LABELS  # noqa: F401  re-exported: ohscore/ui/logbook.py and older callers
from . import theme
from .controls import Button, Card, Segmented, Slider, Toggle
from .meters import BarMeter
from .modegrid import ModeCell, ModeGrid  # noqa: F401  re-exported
from .smeter import SMeter


FORMS = ("full", "compact")


class NoteLabel(QLabel):
    """A sentence under the card's buttons: wrapped in full where there is
    room for it, or one line, cut with an ellipsis and whole in the
    tooltip, where there is not. Auto-tune's refusals run to three lines
    ("after 12 s, the best fit (+212 Hz) puts the carrier 86 Hz from the
    voice's edge, nearer than a...") and were cut off at the foot of the
    rail on the Mac (FINDINGS 6); one line that says there is more is
    better than half a sentence."""

    def __init__(self):
        super().__init__("")
        self.full = ""
        self.one_line = False
        self.setObjectName("Faint")
        self.setTextFormat(Qt.TextFormat.PlainText)
        self.setWordWrap(True)

    def set_note(self, text: str) -> None:
        self.full = text
        self._show()

    def set_one_line(self, on: bool) -> None:
        if on == self.one_line:
            return
        self.one_line = on
        self.setWordWrap(not on)
        # One line must not ask for the sentence's width: that would widen
        # the whole rail to fit it. Ignored lets the card decide, and the
        # text is cut to what it gets.
        self.setSizePolicy(QSizePolicy.Policy.Ignored if on else QSizePolicy.Policy.Preferred,
                           QSizePolicy.Policy.Preferred)
        self._show()

    def _show(self) -> None:
        if self.one_line:
            cut = QFontMetrics(self.font()).elidedText(self.full, Qt.TextElideMode.ElideRight, max(20, self.width()))
            super().setText(cut)
            self.setToolTip(self.full if cut != self.full else "")
        else:
            super().setText(self.full)
            self.setToolTip("")
        self.updateGeometry()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.one_line:
            self._show()


AUTO_KEYS = ("autoBusy", "autoHeard", "autoTune", "autoTuneRefused", "autoAudio", "autoAudioRefused", "autoAudioWhy", "mode")


class ReceiveCard(Card):
    # The operator opened (True) or closed the compact form's "More
    # receive controls"; the window keeps it for the workspace.
    expand_toggled = pyqtSignal(bool)

    def __init__(self, bridge, parent=None, prefs=None):
        super().__init__(QCoreApplication.translate("ReceiveCard", "Receive"), parent)
        self.bridge = bridge
        sp = bridge.radio.STATE.spec
        st = bridge.st
        self.s = SMeter(bridge, prefs)
        self.snr = BarMeter(self.tr("SNR in passband"), 0, 40, lambda v: f"{v:.0f}", ticks=(0, 10, 20, 30, 40),
                            zones=((0, 6, "warn"), (6, 40, "ok")), unit="dB", compact=True)
        self.lay.addWidget(self.s)
        self.lay.addWidget(self.snr)
        vol = QHBoxLayout()
        vol.setSpacing(10)
        self.vol = Slider(self.tr("Volume"), 0, 1, st.get("volume", 0.5), 0.02, lambda v: f"{v * 100:.0f}", default=0.5)
        self.vol.changed.connect(lambda v: bridge.set(quiet=True, volume=v))
        self.mute = Toggle(self.tr("Mute"), bool(st.get("mute")), colour="warn")
        self.mute.toggled.connect(lambda on: bridge.set(mute=on))
        vol.addWidget(self.vol, 1)
        vol.addWidget(self.mute)
        self.lay.addLayout(vol)
        agc_names = {"off": self.tr("Off"), "slow": self.tr("Slow"), "medium": self.tr("Med"), "fast": self.tr("Fast")}
        self.agc = Segmented([(a, agc_names.get(a, a.capitalize())) for a in sp["agc"]["choices"]],
                             st.get("agc", "medium"), compact=True)
        self.agc.picked.connect(lambda v: bridge.set(agc=v))
        row = QHBoxLayout()
        lab = QLabel(self.tr("AGC"))
        lab.setFont(theme.caps())
        lab.setStyleSheet(f"color: {theme.t()['text3']};")
        # At least 34 px, so the row lines up as it always has in English,
        # but as wide as the word needs: fixed at 34 it cut a longer
        # language's word off (en-XA at 1024 x 600, WP9).
        lab.setMinimumWidth(34)
        row.addWidget(lab)
        row.addWidget(self.agc, 1)
        self.lay.addLayout(row)
        self.rf = Slider(self.tr("Gain (AGC off)"), sp["rfGain"]["min"], sp["rfGain"]["max"], st.get("rfGain", 0), 1,
                         lambda v: f"{v:+.0f} dB", default=0)
        self.rf.changed.connect(lambda v: bridge.set(quiet=True, rfGain=v))
        self.lay.addWidget(self.rf)
        flt = QHBoxLayout()
        flt.setSpacing(10)
        self.flo = Slider(self.tr("Filter low"), sp["filterLo"]["min"], sp["filterLo"]["max"], st.get("filterLo", 300),
                          50, lambda v: f"{v:.0f}", default=300)
        self.fhi = Slider(self.tr("high"), sp["filterHi"]["min"], sp["filterHi"]["max"], st.get("filterHi", 2700), 50,
                          lambda v: f"{v:.0f}", default=2700)
        self.flo.changed.connect(lambda v: bridge.set(quiet=True, filterLo=v))
        self.fhi.changed.connect(lambda v: bridge.set(quiet=True, filterHi=v))
        flt.addWidget(self.flo)
        flt.addWidget(self.fhi)
        self.lay.addLayout(flt)
        self.nb = Toggle(self.tr("Noise blanker"), bool(st.get("nb")))
        self.nb.toggled.connect(lambda on: bridge.set(nb=on))
        # NR beside NB, its strength under both: the two noise controls
        # read as one group, and the slider is greyed while NR is off.
        self.nr = Toggle(self.tr("Noise reduction"), bool(st.get("nr")))
        self.nr.toggled.connect(lambda on: bridge.set(nr=on))
        noise = QHBoxLayout()
        noise.setSpacing(10)
        noise.addWidget(self.nb)
        noise.addWidget(self.nr)
        noise.addStretch(1)
        self.lay.addLayout(noise)
        self.nrs = Slider(self.tr("NR strength"), sp["nrStrength"]["min"], sp["nrStrength"]["max"],
                          st.get("nrStrength", sp["nrStrength"]["default"]), 5, lambda v: f"{v:.0f} %",
                          default=sp["nrStrength"]["default"])
        self.nrs.changed.connect(lambda v: bridge.set(quiet=True, nrStrength=v))
        self.lay.addWidget(self.nrs)
        # Auto-tune and best audio (Engine.auto_tune / best_audio): one
        # press each, a few seconds' listening, then a line saying what was
        # done or why not - the engine's own sentence, as beacon lock's
        # "Last refused" is. Nothing keeps adjusting afterwards.
        auto = QHBoxLayout()
        auto.setSpacing(10)
        self.tune_btn = Button(self.tr("Auto-tune"), small=True)
        self.tune_btn.setToolTip(self.tr("Listen to the SSB station on the dial and tune onto its suppressed carrier "
                                         "(A). Right-click a scope to do it on another signal."))
        self.tune_btn.clicked.connect(lambda: self.request("tune"))
        self.audio_btn = Button(self.tr("Best audio"), small=True)
        self.audio_btn.setToolTip(self.tr("Listen to the station on the dial and set the filter, AGC, noise "
                                          "reduction and noise blanker for it, once (Shift+A). Your own changes "
                                          "afterwards stand."))
        self.audio_btn.clicked.connect(lambda: self.request("audio"))
        auto.addWidget(self.tune_btn, 1)
        auto.addWidget(self.audio_btn, 1)
        self.lay.addLayout(auto)
        self.auto_note = NoteLabel()
        self.lay.addWidget(self.auto_note)
        self.auto_last = ""
        self.auto_seen: dict = {}
        # Compact keeps what is touched while listening; the rest is
        # behind this line. A Button, so it is reached by Tab and read by
        # a screen reader like any other.
        self.more = Button("", kind="ghost", small=True)
        self.more.clicked.connect(lambda: self._toggle_more())
        self.lay.addWidget(self.more)
        self.extras = [self.rf, self.flo, self.fhi, self.nb, self.nr, self.nrs, self.tune_btn, self.audio_btn]
        self.form = "full"
        self.expanded = False
        self._apply_form()
        self._sync(st)

    # ---------------------------------------------------------------- forms
    def set_form(self, form: str) -> None:
        """"full" or "compact" (the workspace decides). Shows and hides the
        widgets the card already has; nothing is built."""
        if form in FORMS and form != self.form:
            self.form = form
            self._apply_form()

    def set_expanded(self, on: bool) -> None:
        """Whether the compact form shows the rest, as the workspace last
        had it. Says nothing back: expand_toggled is the operator's."""
        if bool(on) != self.expanded:
            self.expanded = bool(on)
            self._apply_form()

    def _toggle_more(self) -> None:
        self.expanded = not self.expanded
        self._apply_form()
        self.expand_toggled.emit(self.expanded)

    def showing_all(self) -> bool:
        return self.form == "full" or self.expanded

    def _apply_form(self) -> None:
        everything = self.showing_all()
        for w in self.extras:
            w.setVisible(everything)
        # In compact, auto-tune's outcome still matters (A and a scope's
        # right-click start it with the buttons hidden): one line of it.
        self.auto_note.set_one_line(not everything)
        self.auto_note.setVisible(everything or bool(self.auto_note.full))
        self.more.setVisible(self.form == "compact")
        self.more.set_text(self.tr("▾ Fewer receive controls") if self.expanded
                           else self.tr("▸ More receive controls"))

    def _sync(self, ch):
        if "volume" in ch:
            self.vol.set_value(ch["volume"])
        if "mute" in ch:
            self.mute.set_on(ch["mute"])
        if "agc" in ch:
            self.agc.set_value(ch["agc"])
            self.rf.setEnabled(ch["agc"] == "off")
        if "rfGain" in ch:
            self.rf.set_value(ch["rfGain"])
        if "filterLo" in ch:
            self.flo.set_value(ch["filterLo"])
        if "filterHi" in ch:
            self.fhi.set_value(ch["filterHi"])
        if "nb" in ch:
            self.nb.set_on(ch["nb"])
        if "nr" in ch:
            self.nr.set_on(ch["nr"])
            self.nrs.setEnabled(bool(ch["nr"]))
        if "nrStrength" in ch:
            self.nrs.set_value(ch["nrStrength"])
        if "mode" in ch:
            ssb = ch["mode"] in ("usb", "lsb")
            self.flo.setEnabled(ssb)
            self.fhi.setEnabled(ssb)
        if any(k in ch for k in AUTO_KEYS):
            self._sync_auto()

    def request(self, kind: str):
        """Start auto-tune ("tune") or best audio ("audio"); a refusal to
        start (wrong mode, already listening) is said on the card."""
        try:
            (self.bridge.radio.auto_tune if kind == "tune" else self.bridge.radio.best_audio)()
        except ValueError as e:
            self._note(str(e))
            return
        self.bridge.st["autoBusy"] = kind
        self._sync_auto()

    def _sync_auto(self):
        st = self.bridge.st
        busy = st.get("autoBusy", "")
        ssb = st.get("mode") in ("usb", "lsb")
        heard = int(st.get("autoHeard") or 0)
        for b, kind, idle in ((self.tune_btn, "tune", self.tr("Auto-tune")),
                              (self.audio_btn, "audio", self.tr("Best audio"))):
            b.set_text((self.tr("Listening… {secs} s").format(secs=heard) if heard else self.tr("Listening…"))
                       if busy == kind else idle)
            b.setEnabled(ssb and not busy)
        if busy == "tune":
            # Auto-tune listens until it is sure (autotune.Listener): the
            # seconds say it is still at it, and how long it may take.
            text = self.tr("Listening to the station on the dial… {secs} s, until sure (at most {most} s)").format(
                secs=heard, most=f"{LISTEN_SECONDS:.0f}")
        elif busy:
            text = self.tr("Listening to the station on the dial for a few seconds…")
        else:
            # The newest outcome of either, worded as the engine gave it;
            # each lead is a whole line with the engine's sentence in it.
            text = self.auto_last
            for key, lead in (("autoTuneRefused", self.tr("Auto-tune refused: {why}")),
                              ("autoAudioRefused", self.tr("Best audio refused: {why}")),
                              ("autoTune", self.tr("Auto-tune: {what}")), ("autoAudio", self.tr("Best audio: {what}"))):
                if st.get(key) and st.get(key) != self.auto_seen.get(key):
                    text = lead.format(why=st[key], what=st[key])
            self.auto_seen = {k: st.get(k) for k in AUTO_KEYS}
            self.auto_last = text
        if not ssb and not busy:
            text = self.tr("Auto-tune and best audio work in USB and LSB.")
        self._note(text)
        why = st.get("autoAudioWhy") or ""
        self.audio_btn.setToolTip(self.tr("What best audio chose last time, and why:\n{why}").format(why=why) if why
                                  else self.audio_btn.toolTip())

    def _note(self, text: str) -> None:
        self.auto_note.set_note(text)
        self.auto_note.setVisible(self.showing_all() or bool(text))

    def on_state(self, ch):
        self._sync(ch)

    def on_meter(self, m):
        rx = m.get("rx")
        self.s.feed(rx if rx is not None and rx > -199 else None, m.get("beacon"))

    def set_snr(self, v, noise_dbfs=None):
        self.snr.set_value(v)
        self.s.set_noise(noise_dbfs)

    def tick(self, dt):
        self.s.tick(dt)
        self.snr.tick(dt)


class RailDrawer(QWidget):
    """The rail as a drawer, for the Tight tier: a card over the right
    edge of the window, below the wide scope, with a scroll area of its
    own. It holds the window's rail (the cards' widget, taken from the
    side scroll area) while the tier is Tight and gives it back after;
    the window places, opens and closes it. Moving the cards rather than
    the side scroll area keeps the side splitter's handle: taking a widget
    out of a QSplitter deletes its handle and putting it back makes a new
    one, which a tier change must not (plan section 7, rule 6). It never
    takes the keyboard focus itself - Space stays PTT and Esc still unkeys
    first (plan section 3's drawer rules; the window's key filter does Esc)."""

    MARGIN = 6

    def __init__(self, parent, scroll_style: str = ""):
        super().__init__(parent)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        lay = QVBoxLayout(self)
        m = self.MARGIN
        lay.setContentsMargins(m + 2, m, m, m)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.scroll.setStyleSheet(scroll_style)
        lay.addWidget(self.scroll)
        self.hide()

    def follow(self, place) -> None:
        """Call `place` (the window's _place_drawer) whenever the widget it
        lies over changes size. The window placed it from its own
        resizeEvent only, but a theme change rebuilds the window's insides
        at an unchanged window size: the new central widget starts at Qt's
        default 640 x 480 and grows when the layout runs, after the drawer
        (opened at once by a standing transmit warning) had been placed
        for 640 x 480 - 320 px wide and 100 tall, and never placed again
        (Radio, light theme, 1024 x 600, WP9)."""
        self._place = place
        self.parentWidget().installEventFilter(self)

    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Type.Resize and obj is self.parentWidget() and getattr(self, "_place", None):
            self._place()
        return False

    def hold(self, w: QWidget) -> None:
        self.scroll.setWidget(w)
        w.show()

    def release(self) -> QWidget | None:
        return self.scroll.takeWidget()

    def set_least_width(self, w: int) -> None:
        self.scroll.setMinimumWidth(w)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # A shadow on the open edge, so it reads as lying over the panel.
        for i in range(4):
            c = theme.c("bg0", 0.10 * (4 - i))
            p.setPen(QPen(c, 1))
            p.drawLine(int(r.x()) + i, int(r.y()) + 8, int(r.x()) + i, int(r.bottom()) - 8)
        p.setPen(QPen(theme.c("line2"), 1))
        p.setBrush(theme.c("bg0"))
        p.drawRoundedRect(r.adjusted(3, 0, 0, 0), 10, 10)
