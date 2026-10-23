"""OpenHamShack Radio's main window: the shared window (ohscore/ui/window.py) with
the band bar under the header, the licence and sequencer chips where NB
has its lock badges, HAM's transmit card on the rail, its mode keys, steps
and shortcuts, and its Settings, Welcome and About dialogs."""
from __future__ import annotations

from PyQt6.QtCore import QT_TRANSLATE_NOOP, Qt, QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QVBoxLayout

from ohscore.ui.window import BaseWindow

from .. import bands, plutofix, xvtr
from .rail import TransmitCard
from .widgets import SEQ, BandBar, Chip, licence_chip_text

MODE_KEYS = {Qt.Key.Key_1: "usb", Qt.Key.Key_2: "lsb", Qt.Key.Key_3: "cw", Qt.Key.Key_4: "am", Qt.Key.Key_5: "fm",
             Qt.Key.Key_6: "ft8", Qt.Key.Key_7: "ft4", Qt.Key.Key_8: "psk31", Qt.Key.Key_9: "rtty",
             Qt.Key.Key_0: "freedv"}
STEPS = [1, 10, 50, 100, 500, 1000, 5000, 6250, 10000, 12500, 25000, 100000]

# The "?" sheet (ohscore/ui/chrome.py ShortcutOverlay). Keys are written as
# they are, never translated; what they do is, through the "Shortcuts"
# context (QT_TRANSLATE_NOOP marks a string for the catalog, the sheet
# translates it as it draws).
SHORTCUTS = [
    (QT_TRANSLATE_NOOP("Shortcuts", "Tuning & bands"), [
        ("← / →", QT_TRANSLATE_NOOP("Shortcuts", "Tune down / up one step")),
        ("Shift + ← / →", QT_TRANSLATE_NOOP("Shortcuts", "Ten steps")),
        ("Ctrl + ← / →", QT_TRANSLATE_NOOP("Shortcuts", "1 Hz")),
        ("[ / ]", QT_TRANSLATE_NOOP("Shortcuts", "Smaller / larger step")),
        ("Wheel", QT_TRANSLATE_NOOP("Shortcuts", "Step (over a digit: that digit)")),
        ("F or Enter", QT_TRANSLATE_NOOP("Shortcuts", "Type a frequency")),
        ("Click", QT_TRANSLATE_NOOP("Shortcuts", "Tune to the click")),
        ("Ctrl + wheel", QT_TRANSLATE_NOOP("Shortcuts", "Zoom a scope")),
        ("B / Shift + B", QT_TRANSLATE_NOOP("Shortcuts", "Next / previous band")),
        ("V", QT_TRANSLATE_NOOP("Shortcuts", "Next register of this band"))]),
    (QT_TRANSLATE_NOOP("Shortcuts", "Transmit"), [
        ("Space", QT_TRANSLATE_NOOP("Shortcuts", "PTT (hold, or toggle - Settings)")),
        ("Esc", QT_TRANSLATE_NOOP("Shortcuts", "Unkey, stop queue / CQ loop")),
        ("T", QT_TRANSLATE_NOOP("Shortcuts", "1750 Hz toneburst (FM)")),
        ("F1 … F8", QT_TRANSLATE_NOOP("Shortcuts", "Send macro or voice memory n"))]),
    # Ctrl + E is the only key for JS8, PSK63, PSK125 and SSTV (Mac test
    # FINDINGS 13), so it comes first and names some of them.
    (QT_TRANSLATE_NOOP("Shortcuts", "Modes & filter"), [
        ("Ctrl + E", QT_TRANSLATE_NOOP("Shortcuts", "Mode menu: type a name (JS8, PSK63, SSTV…)")),
        ("Ctrl + 1 … 5", QT_TRANSLATE_NOOP("Shortcuts", "USB, LSB, CW, AM, FM")),
        ("Ctrl + 6 … 0", QT_TRANSLATE_NOOP("Shortcuts", "FT8, FT4, PSK31, RTTY, FreeDV")),
        (", / .", QT_TRANSLATE_NOOP("Shortcuts", "Filter narrower / wider")),
        ("R / X / S", QT_TRANSLATE_NOOP("Shortcuts", "RIT / XIT / split")),
        ("N / M", QT_TRANSLATE_NOOP("Shortcuts", "Noise blanker / mute")),
        ("Shift + N", QT_TRANSLATE_NOOP("Shortcuts", "Noise reduction")),
        ("A", QT_TRANSLATE_NOOP("Shortcuts", "Auto-tune onto the SSB station on the dial")),
        ("Shift + A", QT_TRANSLATE_NOOP("Shortcuts", "Best audio for the station on the dial")),
        ("Right-click", QT_TRANSLATE_NOOP("Shortcuts", "Auto-tune there (scopes, USB and LSB)"))]),
    (QT_TRANSLATE_NOOP("Shortcuts", "Views"), [
        ("W", QT_TRANSLATE_NOOP("Shortcuts", "Next workspace: Digital, Voice, Watch")),
        ("Shift + W", QT_TRANSLATE_NOOP("Shortcuts", "Workspace follows the mode (Auto)")),
        ("L", QT_TRANSLATE_NOOP("Shortcuts", "Signal labels on the scopes on / off")),
        ("Alt + 1 … 9", QT_TRANSLATE_NOOP("Shortcuts", "Recall memory 1 … 9")),
        ("Ctrl + J", QT_TRANSLATE_NOOP("Shortcuts", "Operate")),
        ("Ctrl + L", QT_TRANSLATE_NOOP("Shortcuts", "Logbook")),
        ("Ctrl + B", QT_TRANSLATE_NOOP("Shortcuts", "Memories")),
        ("Ctrl + K", QT_TRANSLATE_NOOP("Shortcuts", "CW Activity")),
        ("Ctrl + Shift + D", QT_TRANSLATE_NOOP("Shortcuts", "Decoders")),
        ("Ctrl + Shift + L", QT_TRANSLATE_NOOP("Shortcuts", "Local frequencies")),
        ("Ctrl + Shift + S", QT_TRANSLATE_NOOP("Shortcuts", "Stations (FM and DAB)")),
        ("Ctrl + D", QT_TRANSLATE_NOOP("Shortcuts", "Second display")),
        ("Ctrl + ,", QT_TRANSLATE_NOOP("Shortcuts", "Settings")),
        ("Ctrl + Shift + R", QT_TRANSLATE_NOOP("Shortcuts", "Record receive IQ / stop")),
        ("Ctrl + Shift + P", QT_TRANSLATE_NOOP("Shortcuts", "Play an IQ recording / back to the radio")),
        ("Ctrl + T", QT_TRANSLATE_NOOP("Shortcuts", "Light / dark theme")),
        ("F11", QT_TRANSLATE_NOOP("Shortcuts", "Full screen")),
        ("?", QT_TRANSLATE_NOOP("Shortcuts", "This list")),
        ("Ctrl + Q", QT_TRANSLATE_NOOP("Shortcuts", "Quit"))]),
]


class MainWindow(BaseWindow):
    TAGLINE = "All-band transceiver"
    MODE_KEYS = MODE_KEYS
    SHORTCUTS = SHORTCUTS
    STEPS = STEPS
    # The CW skimmer's view beside Mode / Logbook / Memories (ohscore/ui/
    # cwskimview.py). Ctrl+K, as NB's band skimmer's Band view. Then the
    # decoders running on frequencies of their own (ohscore/ui/
    # decodersview.py, RADIO-SDR-PLAN §4.5), Ctrl+Shift+D. The labels are
    # translated where the window shows them, under MainWindow. Then what
    # there is to listen to near the station (ohsradio/ui/localview.py),
    # Ctrl+Shift+L, and the FM and DAB station lists the weekly band scan
    # makes (ohsradio/ui/broadcast.py), Ctrl+Shift+S; both leave the tab row
    # below Full (View menu and their shortcuts).
    EXTRA_VIEWS = [("cwskim", QT_TRANSLATE_NOOP("MainWindow", "CW Activity"), "Ctrl+K"),
                   ("decoders", QT_TRANSLATE_NOOP("MainWindow", "Decoders"), "Ctrl+Shift+D"),
                   ("local", QT_TRANSLATE_NOOP("MainWindow", "Local"), "Ctrl+Shift+L"),
                   ("stations", QT_TRANSLATE_NOOP("MainWindow", "Stations"), "Ctrl+Shift+S")]
    TIGHT_MENU_VIEWS = ("decoders", "local", "stations")
    COMPACT_MENU_VIEWS = ("local", "stations")

    def watch_view(self) -> str:
        """Watch opens on CW Activity, the band view; Decoders came after it."""
        return "cwskim"

    # Diagnostics (ohsradio/ui/diagnostics.py). The two hooks are what tests
    # replace with fakes: nothing here may reach a real radio in a test.
    make_fixer = None                 # (uri, progress) -> plutofix.Fixer; None: the real one
    identify = staticmethod(plutofix.probe)
    dialog = None                     # the diagnostics dialog showing now, if any
    flow = None                       # the AD9364 fix in progress, if any
    report_job = None

    def __init__(self, bridge, prefs, start_error: str = ""):
        self._span = None
        super().__init__(bridge, prefs, start_error)
        # Queued, after the base class's toast: a dialog over a window that
        # is not on screen yet would open in the wrong place.
        # A bound method, not a lambda, so Qt drops the call if the window
        # is gone by then.
        self._start_error = start_error
        QTimer.singleShot(450, self._after_first_start)

    def window_title(self) -> str:
        return self.tr("OpenHamShack Radio")

    def _after_first_start(self):
        self.after_start(self._start_error)

    # ------------------------------------------------------------ mode card
    def build(self):
        super().build()
        # The shared window makes the Mode card without the preferences;
        # the recent modes (its compact form and Ctrl+E) come from them.
        # On every build: a theme change makes a new card.
        self.modegrid.attach(self.prefs)

    def _shortcuts(self):
        super()._shortcuts()
        # Ctrl+E: every mode by name (Ctrl+1 ... 0 cover ten of fourteen;
        # JS8, PSK63, PSK125 and SSTV had no key; Mac test FINDINGS 13).
        s = QShortcut(QKeySequence("Ctrl+E"), self)
        s.setContext(Qt.ShortcutContext.WindowShortcut)
        s.activated.connect(self.open_mode_menu)

    def open_mode_menu(self):
        return self.modegrid.open_menu(self)

    def _menu(self):
        super()._menu()
        from PyQt6.QtGui import QAction
        h = self.help_menu
        # Beside the shared Save diagnostics… and Open log folder, before
        # the separator above About.
        before = h.actions()[-2]
        a = QAction(self.tr("Check radio…"), self)
        a.triggered.connect(lambda _=False: self.check_radio())
        h.insertAction(before, a)

    # ----------------------------------------------------------- the app's parts
    def _header_status(self, head) -> None:
        # Wide FM's station by the frequency: its name large, STEREO, and
        # what it is playing (ohsradio/ui/broadcast.py); hidden in other modes.
        from .broadcast import RdsStrip
        self.rds_strip = RdsStrip()
        self.rds_strip.on_state(self.bridge.st)
        head.addWidget(self.rds_strip)
        col = QVBoxLayout()
        col.setSpacing(6)
        self.lic_chip = Chip(self.tr("Licence"), "lock")
        self.seq_chip = Chip(self.tr("PTT sequence"), "antenna")
        col.addWidget(self.lic_chip)
        col.addWidget(self.seq_chip)
        head.addLayout(col)
        self.tickers = [self.lic_chip, self.seq_chip]

    def _under_header(self, body) -> None:
        self.bandbar = BandBar(self.bridge)
        self.bandbar.picked.connect(self.pick_band)
        self.bandbar.action.connect(self.band_action)
        body.addWidget(self.bandbar)

    def _transmit_card(self):
        return TransmitCard(self.bridge)

    def status_items(self, st: dict) -> list[tuple[str, str]]:
        info = st.get("licenceInfo") or {}
        cls = info.get("class", "")
        # Amber: a setting to make, not a fault (overhaul section 5.3).
        items = [(f"{cls} licence", "text2") if cls else ("no licence class: TX locked", "warn")]
        if st.get("ppm"):
            items.append((f"ref {float(st['ppm']):+.2f} ppm", "text2"))
        if st.get("channel"):
            items.append((st["channel"], "text2"))
        return items

    def _sync_header(self, ch: dict | None) -> None:
        st = self.bridge.st
        if ch is None or any(k in ch for k in ("rds", "mode")):
            self.rds_strip.on_state(st)
        if ch is None or any(k in ch for k in ("licenceInfo", "estPep", "licenceClass", "band")):
            title, word, detail, colour, tip = licence_chip_text(st)
            self.lic_chip.set(word, detail, colour, tip, title=title)
        if ch is None or any(k in ch for k in ("seqState", "keyed", "seqOutput")):
            word, colour, detail = SEQ.get(st.get("seqState", "rx"), SEQ["rx"])
            out = st.get("seqOutput", "none")
            line = {"none": "no PA line", "serial": f"{st.get('seqPort') or 'serial'} {st.get('seqLine', 'rts').upper()}"}
            self.seq_chip.set(word, detail or line.get(out, out), colour,
                              f"PTT sequencer: {line.get(out, out)}, {float(st.get('seqDelayMs') or 0):.0f} ms "
                              f"each way.")
        if ch is None or any(k in ch for k in ("spanLo", "spanHi")):
            span = (st.get("spanLo"), st.get("spanHi"))
            if span != self._span and all(span):
                self._span = span
                self.wide.reset_view()

    def on_meter(self, m: dict):
        super().on_meter(m)
        strip = getattr(self, "rds_strip", None)
        if strip is not None:
            strip.on_meter(m)

    # ------------------------------------------------------------- CW Activity
    def make_extra_view(self, key: str):
        if key == "decoders":
            return self._make_decoders_view()
        if key == "local":
            return self._make_local_view()
        if key == "stations":
            from .broadcast import StationsView
            old = getattr(self, "stations_view", None)
            if old is not None:
                old.detach()
            self.stations_view = StationsView(self.bridge, self.prefs,
                                              lambda text: self.on_toast({"level": "warn", "text": text}))
            return self.stations_view
        from ohscore.ui.cwskimview import CwSkimStore, CwSkimView
        # The store outlives the view (a theme change rebuilds the window):
        # made once, on the first build.
        if getattr(self, "cwskim_store", None) is None:
            self.cwskim_store = CwSkimStore(self.bridge)
            self.cwskim_store.changed.connect(self._cwskim_marks)
            self.cwskim_store.spotted.connect(self._cwskim_label)
        old = getattr(self, "cwskim_view", None)
        if old is not None:
            old.detach()
        self.cwskim_view = CwSkimView(self.bridge, self.prefs, self.cwskim_store, self.cwskim_tune)
        return self.cwskim_view

    # ------------------------------------------------------------- Local
    def _make_local_view(self):
        from .localview import LocalView
        old = getattr(self, "local_view", None)
        if old is not None:
            old.detach()
        self.local_view = LocalView(self.bridge, self.prefs, self.local_tune)
        return self.local_view

    def local_tune(self, entry: dict):
        """Tune to a local frequency: its mode, its dial exactly (an 8.33 kHz
        channel to the hertz), and its step when the step list has it (the
        list has no 8.33 kHz step; a grid of 8333 Hz from 0 would not land
        on the channels, so airband keeps the mode's own). Receive only:
        the dial is set as any other, and transmit there is the licence's
        to refuse."""
        sp = self.bridge.spec("vfo")
        mode = entry["mode"] if entry["mode"] in self.bridge.radio.STATE.modes else self.bridge.st.get("mode")
        f = float(entry["freqHz"])
        if not sp["min"] <= f <= sp["max"]:
            self.on_toast({"level": "warn", "text": self.tr("{freq} is outside what this radio tunes").format(
                freq=f"{f / 1e6:.4f} MHz")})
            return
        if not self.bridge.set(mode=mode, vfo=f):
            return
        step = entry.get("step")
        if step in self.STEPS:
            self.step = step
            self.readout.set_step(step)

    # ------------------------------------------------------------- Decoders
    def _make_decoders_view(self):
        from ohscore.ui.decodersview import DecodersStore, DecodersView
        if getattr(self, "decoders_store", None) is None:
            self.decoders_store = DecodersStore(self.bridge)
        old = getattr(self, "decoders_view", None)
        if old is not None:
            old.detach()
        self.decoders_view = DecodersView(self.bridge, self.prefs, self.decoders_store, self.decoder_tune)
        return self.decoders_view

    def decoder_tune(self, f: float, decoder: str, params: dict | None = None):
        """Put the dial on a decoder session's signal, in that mode where
        Radio has it (RTTY's dial is its tones' middle less the mode's
        1000 Hz offset, as a click on the scope would put it; a PSK session
        is the PSK mode of its speed; SSTV's frequency is its 1900 Hz leader,
        so the dial goes 1900 Hz below it). Only tunes."""
        from ohscore.ui.tuning import click_to_dial
        st = self.bridge.st
        params = params or {}
        if decoder == "psk":
            decoder = {62.5: "psk63", 125.0: "psk125"}.get(float(params.get("baud", 31.25)), "psk31")
        mode = decoder if decoder in self.bridge.radio.STATE.modes else st.get("mode", "usb")
        target = click_to_dial(mode, float(f), st) if mode != "sstv" else round(float(f) - 1900.0)
        if st.get("ritOn"):
            target -= float(st.get("rit") or 0)
        sp = self.bridge.spec("vfo")
        self.bridge.set(mode=mode, vfo=max(sp["min"], min(sp["max"], target)))

    def scope_menu_items(self, f: float):
        """The core's entries, then "Decode here as": a decoder session on
        the signal under the mouse, in any mode, whatever the dial is on."""
        items = list(super().scope_menu_items(f))
        if getattr(self, "decoders_store", None) is None:
            self._make_decoders_view()
        from ohscore.ui.decodersview import scope_menu_entries
        entries = scope_menu_entries(self.decoders_store)
        if entries:
            items.append((self.tr("Decode here as"),
                          [(label, lambda did=did: self.decode_here(did, f)) for label, did in entries], False))
        return items

    def decode_here(self, decoder: str, f: float):
        try:
            self.decoders_store.start(decoder, float(f), {})
        except ValueError as e:
            self.on_toast({"level": "warn", "text": str(e)})
            return
        self.on_toast({"level": "info", "text": self.tr("{decoder} decoding at {freq} (Decoders view)").format(
            decoder=decoder.upper(), freq=f"{float(f) / 1e6:.4f} MHz")})

    def _cwskim_marks(self):
        """The spots along the foot of the wide scope (set_band_marks); a
        click on one tunes to it, as a click on its row does."""
        wide = getattr(self, "wide", None)
        if wide is None:
            return
        if getattr(self, "_cwskim_click_wired", None) is not wide:
            wide.mark_clicked.connect(lambda m: self.cwskim_tune(float(m["spot"]["f"])) if "spot" in m else None)
            self._cwskim_click_wired = wide
        wide.set_band_marks(self.cwskim_store.marks() if self.prefs.get("cwSkimMarks", True) else [])

    def _cwskim_label(self, spot: dict):
        """A newly spotted call on both waterfalls, as an FT8 decode's call
        is labelled (the label layer ages it away), CQ in the CQ colour."""
        if not self.prefs.get("cwSkimMarks", True):
            return
        import time
        kind = "cq" if spot.get("kind") == "cq" else ""
        for s in (getattr(self, "wide", None), getattr(self, "zoom", None)):
            if s is not None:
                s.add_label(float(spot["f"]), spot["call"], time.time(), kind)

    def cwskim_tune(self, f: float):
        """Tune to a signal the skimmer heard at `f` on the air: CW, with
        the dial where a click on the scope at it would put it (the CW
        pitch below, on the 10 Hz grid), less RIT if it is on. Only tunes:
        the skimmer's spots are never answered from here (Brian,
        13/10/2026), and a set() is receive-side state."""
        from ohscore.ui.tuning import click_to_dial
        st = self.bridge.st
        target = click_to_dial("cw", float(f), st)
        if st.get("ritOn"):
            target -= float(st.get("rit") or 0)
        sp = self.bridge.spec("vfo")
        self.bridge.set(mode="cw", vfo=max(sp["min"], min(sp["max"], target)))

    # ------------------------------------------------------------------ bands
    def pick_band(self, name: str):
        # Through a converter the Pluto tunes the IF, not the band: its
        # AD9363 range is no reason to stop there (receiving through it: a
        # TX-only one leaves the Pluto receiving the band itself).
        b = plutofix.needs_ad9364(self.bridge.radio.dev, name) \
            if self.bridge.radio.converter_for(name, rx=True) is None else None
        if b is not None:
            self.show_chip_dialog(b)
            return
        if not self.bridge.tune_with(lambda: self.bridge.radio.band(name)):
            return
        self.bridge.st.update(self.bridge.radio.state())
        self.on_state(dict(self.bridge.st))

    def band_action(self, key: str):
        st = self.bridge.st
        b = bands.BY_NAME.get(st.get("band", ""))
        if key in ("ft8", "ft4"):
            if b is None or not getattr(b, key):
                self.bridge.say(self.tr("No {mode} dial is listed for this band").format(mode=key.upper()))
                return
            self.bridge.set(vfo=getattr(b, key), mode=key)
        elif key == "a=b":
            self.bridge.set(txVfo=st.get("vfo"))
            self.bridge.say(self.tr("VFO B = A"), "info")
        elif key == "swap":
            a, bb = st.get("vfo"), st.get("txVfo")
            self.bridge.set(vfo=bb, txVfo=a)

    def step_band(self, d: int):
        names = [b.name for b in bands.BANDS if not xvtr.deferred(self.bridge.radio.st, b)]
        cur = self.bridge.st.get("band") or ""
        if cur in names:
            i = (names.index(cur) + d) % len(names)
        else:
            f = float(self.bridge.st.get("vfo") or 0.0)
            i = next((k for k, b in enumerate(bands.BANDS) if b.lo > f), 0)
        for k in range(len(names)):
            name = names[(i + k * d) % len(names)]
            st, _ = self.bandbar._status(bands.BY_NAME[name])
            if st != "off":
                self.pick_band(name)
                return

    def eventFilter(self, obj, ev):
        from PyQt6.QtCore import QEvent
        if ev.type() == QEvent.Type.KeyPress and not self._typing() and not (
                ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            from PyQt6.QtWidgets import QWidget
            if isinstance(obj, QWidget) and obj.window() is self and not self.overlay.isVisible():
                t = ev.text()
                if t in ("b", "B"):
                    self.step_band(-1 if t == "B" else 1)
                    return True
                if t == "v":
                    cur = self.bridge.st.get("band")
                    if cur:
                        self.pick_band(cur)
                    return True
                if t == "t" and self.bridge.st.get("mode") == "fm":
                    self.panels.get("fm") and self.panels["fm"]._burst()
                    return True
        return super().eventFilter(obj, ev)

    # ------------------------------------------------------------------ dialogs
    def settings_dialog(self):
        from .settings import SettingsDialog
        return SettingsDialog(self.bridge, self.prefs, self)

    def welcome_dialog(self):
        from .welcome import Welcome
        return Welcome(self.bridge, self.prefs, self)

    def about_dialog(self):
        from .welcome import About
        return About(self)

    # ------------------------------------------------------------------ diagnostics
    def after_start(self, error: str = ""):
        """After the radio starts (or fails to): a device error gets the
        dialog with the report button; a Pluto that came up as an AD9363
        on a band it cannot tune gets the chip dialog. Either is the moment
        a tester would otherwise be looking at an empty scope."""
        if error:
            self.show_device_error(error)
            return
        st = self.bridge.radio.state()
        b = plutofix.needs_ad9364(self.bridge.radio.dev, f=st.get("vfo")) if not st.get("converter") else None
        if b is not None:
            self.show_chip_dialog(b)

    def restart_radio(self):
        err = self.bridge.restart()
        self.on_toast({"level": "error" if err else "info",
                       "text": err or "The radio restarted with the new settings (receiving, not transmitting)."})
        self.after_start(err)

    def _uri(self) -> str:
        dev = self.bridge.radio.dev
        if dev is not None and getattr(dev, "kind", "") == "pluto":
            return dev.uri
        return self.bridge.radio.cfg.get("plutoUri") or plutofix.DEFAULT_URI

    def _show(self, dlg):
        self.dialog = dlg
        dlg.open()
        return dlg

    def show_device_error(self, text: str):
        from .diagnostics import DeviceErrorDialog
        return self._show(DeviceErrorDialog(self, text, self.save_diagnostics, self.check_radio))

    def show_chip_dialog(self, band):
        from .diagnostics import ChipModeDialog
        self.bridge.radio.log.info("chip check: %s refused, the Pluto runs as an AD9363", band.name)
        return self._show(ChipModeDialog(self, plutofix.band_label(band), self.apply_ad9364, self.save_diagnostics))

    def check_radio(self):
        from .diagnostics import CheckRadioDialog
        st = self.bridge.radio.state()
        return self._show(CheckRadioDialog(self, self._uri(), st.get("licenceClass", ""), self.bridge.radio.dev,
                                           identify=self.identify, on_apply=self.apply_ad9364,
                                           on_undo=lambda: self.apply_ad9364(undo=True),
                                           on_report=self.save_diagnostics))

    def apply_ad9364(self, undo: bool = False):
        from .diagnostics import FixFlow
        self.flow = FixFlow(self, self._uri(), undo=undo, make_fixer=self.make_fixer)
        return self.flow

    def save_diagnostics(self):
        """Help › Save diagnostics…, with HAM's findings in the report
        (ohsradio/diagnostics.py); the shared dialog is opened, not exec'd."""
        from .diagnostics import ReportJob

        def showing(d):
            self.dialog = d
        self.report_job = ReportJob(self, on_dialog=showing, identify=self.identify)
        return self.report_job
