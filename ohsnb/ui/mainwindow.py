"""QO-100 NB's main window: the shared window (ohscore/ui/window.py) with
the beacon-lock and TX-lock badges in the header, NB's transmit card on the
rail, its mode keys and shortcuts, rxCorr and txCorr in the status strip,
and its Settings, Welcome and About dialogs.

Beacon lock is worked from here as well as Settings: the RX badge's panel
(Auto / Hold / Manual, and nudging rxCorr in Manual), the wheel over the
badge, H for Hold, and a right-click on a beacon on either scope - "Lock to
this as the ... beacon" (Radio.beacon_here), under the "What is this?"
card a right-click opens (scope_menu, ohsnb/whatis.py)."""
from __future__ import annotations

import dataclasses
import time

from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QAction, QKeySequence, QShortcut
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from ohscore.ui.status import fmt_hz
from ohscore.ui.window import BaseWindow

from .. import bandplan
from ..kgstvrx import DIAL as KGSTV_DIAL
from .chrome import SHORTCUTS, status_items
from .rail import TransmitCard
from .status import LockBadge, RxBadge, hz_forms, ppm_forms

MODE_KEYS = {Qt.Key.Key_1: "usb", Qt.Key.Key_2: "lsb", Qt.Key.Key_3: "cw", Qt.Key.Key_4: "am", Qt.Key.Key_5: "ft8",
             Qt.Key.Key_6: "ft4", Qt.Key.Key_7: "psk31", Qt.Key.Key_8: "rtty", Qt.Key.Key_9: "freedv",
             Qt.Key.Key_0: "sstv"}
LOCK_KEYS = ("rxLock", "rxErr", "rxRate", "rxSnr", "rxCorr", "beaconUsed", "txLockState", "txErr", "txCorr", "txPpm",
             "txConfidence", "vsBeacon", "beaconLevel", "keyed", "rigKeyed", "rigTxCorr", "rigTxCorrTrusted",
             "txRadio", "beaconMode", "rxCorrHand", "rxWindow", "rxReject")
# What click-to-lock offers, in band order; the one nearest the click is the
# menu's default.
CLICK_BEACONS = ("lower", "middle", "upper")
MODE_NAMES = {"auto": "Auto", "hold": "Hold", "manual": "Manual"}


class MainWindow(BaseWindow):
    TAGLINE = "QO-100 narrowband"
    MODE_KEYS = MODE_KEYS
    SHORTCUTS = SHORTCUTS
    # The multimedia beacon's view and the band skimmer's beside Mode /
    # Logbook / Memories.
    EXTRA_VIEWS = [("mmb", "Beacon", "Ctrl+M"), ("skim", "Band", "Ctrl+K")]

    def __init__(self, bridge, prefs, start_error: str = ""):
        self.dish_dialog = None
        super().__init__(bridge, prefs, start_error)
        bridge.lock.connect(self.on_lock)
        # The over-power watch's alerts are on the wide scope whether or
        # not the Band view (where its table is) has ever been opened.
        self._op_store()

    def window_title(self) -> str:
        return self.tr("OpenHamShack QO-100 NB")

    # ------------------------------------------------------------ mode card
    def build(self):
        super().build()
        # The Mode card is made by the shared window, which has neither the
        # preferences' recent modes nor NB's KG-STV button in mind; both are
        # given to it here, on every build (a theme change makes a new card).
        self.modegrid.attach(self.prefs, buttons=("kgstv",))
        self.modegrid.over_picked.connect(self.over_button)
        if self.workspace is not None:
            self._fit_rail()

    def _shortcuts(self):
        super()._shortcuts()
        # Ctrl+E: every mode by name. Ctrl+1 ... 0 are ten keys for fifteen
        # modes, and Q65, JS8, PSK63, PSK125 and HSmodem had no key at all
        # (Mac test FINDINGS 13).
        s = QShortcut(QKeySequence("Ctrl+E"), self)
        s.setContext(Qt.ShortcutContext.WindowShortcut)
        s.activated.connect(self.open_mode_menu)

    def open_mode_menu(self):
        return self.modegrid.open_menu(self)

    def over_button(self, which: str) -> None:
        """A button on the Mode card for something that is not a radio mode
        (ohscore/modegroups.py OVER_BUTTONS); KG-STV is the one."""
        if which == "kgstv":
            self.kgstv_button()

    def kgstv_button(self) -> None:
        """KG-STV (overhaul decision 4): Beacon › KG-STV, where pictures
        arrive and are sent from, and the receiver on KG-STV's frequency to
        listen. Not a rail mode: KG-STV is received in the background
        whatever the mode, and sent as an over (Engine.OVER_MODES).

        Nothing is retuned while anything is on the air, armed or queued: a
        mode change unkeys a picture going out (ohscore/engine.py, the
        OVER_MODES check in set()), and a button that looks like a mode
        must not do that. The page is shown either way."""
        st = self.bridge.st
        # Asked of the engine, not the window's copy of its state: a picture
        # sent a moment ago is keyed there before the state feed says so,
        # and the first version of this button, reading only the copy,
        # retuned under it and unkeyed it (tests/test_ui_modegrid.py).
        now = {**st, **self.bridge.radio.state()}
        busy = bool(self._keyed() or now.get("keyed") or self.face.on_air(now) or self._armed_at() is not None)
        if not busy:
            target = KGSTV_DIAL - (float(st.get("rit") or 0) if st.get("ritOn") else 0.0)
            self.bridge.set(mode="usb", vfo=target)
        self.show_view("mmb")
        self.mmb_view.show_page("kgstv")

    # ---------------------------------------------------------- dish alignment
    def radio_menu_extra(self, menu) -> None:
        menu.addSeparator()
        a = QAction(self.tr("Dish alignment…"), self)
        a.triggered.connect(self.open_dish)
        menu.addAction(a)
        self.act_dish = a

    def open_dish(self):
        from .dishmeter import open_dialog
        return open_dialog(self)

    def closeEvent(self, e):
        # The meter holds the gain and may be serving the phone page: both
        # end with it, and it ends with the window.
        if self.dish_dialog is not None:
            self.dish_dialog.close()
        super().closeEvent(e)

    # ------------------------------------------------------- multimedia beacon
    def make_extra_view(self, key: str):
        if key == "skim":
            return self._make_skim_view()
        from .mmbview import MmbStore, MmbView
        # The store outlives the view (a theme change rebuilds the window):
        # made once, on the first build.
        if getattr(self, "mmb_store", None) is None:
            self.mmb_store = MmbStore(self.bridge, self.bridge.radio.data_dir / "mmbeacon")
            self.mmb_store.qo100_spot.connect(self._mmb_spot)
        old = getattr(self, "mmb_view", None)
        if old is not None:
            old.detach()
        self.mmb_view = MmbView(self.bridge, self.prefs, self.mmb_store)
        return self.mmb_view

    # ------------------------------------------------------------ band skimmer
    def _make_skim_view(self):
        from .opview import BandView, OpPanel
        from .skimview import SkimStore, SkimView
        if getattr(self, "skim_store", None) is None:
            self.skim_store = SkimStore(self.bridge)
            self.skim_store.changed.connect(self._skim_marks)
        old = getattr(self, "band_view", None)
        if old is not None:
            old.detach()
        self.skim_view = SkimView(self.bridge, self.prefs, self.skim_store, self.skim_tune)
        self.op_panel = OpPanel(self.bridge, self._op_store(), self.op_tune)
        self.band_view = BandView(self.op_panel, self.skim_view)
        return self.band_view

    # ------------------------------------------------- over-power and LEILA
    def _op_store(self):
        from .opview import OpStore
        if getattr(self, "op_store", None) is None:
            self.op_store = OpStore(self.bridge)
            self.op_store.changed.connect(self._op_alerts)
        return self.op_store

    def _op_alerts(self):
        wide = getattr(self, "wide", None)
        if wide is None:
            return
        if getattr(self, "_op_click_wired", None) is not wide:
            wide.alert_clicked.connect(lambda a: self.op_tune(a["event"]))
            self._op_click_wired = wide
        wide.set_alerts(self.op_store.alerts())

    def op_tune(self, e: dict):
        """Tune the receiver to a signal over the beacon or a siren, in the
        mode it is in, as a click on the scope at its middle would. The
        dial only: nothing here keys or touches the transmitter's settings."""
        from ohscore.ui.panels.text import mode_offset
        from ohscore.ui.tuning import click_to_dial
        st = self.bridge.st
        mode = st.get("mode") or "usb"
        f = float(e["freq"])
        if mode in ("usb", "lsb"):
            # The middle of it at 1 kHz of audio, where a siren or a carrier
            # is heard; a click's own USB rule puts the dial on it, at 0 Hz.
            target = round((f - 1000.0 if mode == "usb" else f + 1000.0) / 10.0) * 10.0
        else:
            target = click_to_dial(mode, f, st, mode_offset(mode))
        if st.get("ritOn"):
            target -= float(st.get("rit") or 0)
        sp = self.bridge.spec("vfo")
        self.bridge.set(vfo=max(sp["min"], min(sp["max"], target)))

    def _skim_marks(self):
        wide = getattr(self, "wide", None)
        if wide is None:
            return
        if not getattr(self, "_skim_click_wired", None) is wide:
            wide.mark_clicked.connect(lambda m: self.skim_tune(m["entry"]))
            self._skim_click_wired = wide
        wide.set_band_marks(self.skim_store.marks() if self.prefs.get("skimMarks", True) else [])

    def skim_tune(self, e: dict):
        """Tune to one of the band skimmer's signals, in its mode: a measured
        dial (an SSB voice auto-tune answered for, KG-STV, a calling window)
        exactly; a voice not yet measured to where its spectrum puts the
        carrier, then auto-tune listens there, as a right-click's does;
        anything else as a click on the scope at it would."""
        st = self.bridge.st
        mode = e.get("mode") or "usb"
        if e["kind"] == "ssb" and not e["exact"] and e.get("dial") is not None:
            if not self.bridge.set(mode="usb"):
                return
            try:
                self.bridge.radio.auto_tune(e["dial"])
            except ValueError as ex:
                self.on_toast({"level": "warn", "text": str(ex)})
                return
            self.bridge.st["autoBusy"] = "tune"
            self.rxcard._sync_auto()
            return
        if e.get("dial") is not None and e["exact"]:
            target = float(e["dial"])
        else:
            from ohscore.ui.panels.text import mode_offset
            from ohscore.ui.tuning import click_to_dial
            target = click_to_dial(mode, float(e["f"]), st, mode_offset(mode))
        if st.get("ritOn"):
            target -= float(st.get("rit") or 0)
        sp = self.bridge.spec("vfo")
        self.bridge.set(mode=mode, vfo=max(sp["min"], min(sp["max"], target)))

    def _mmb_spot(self, spot: dict):
        if self.prefs.get("mmbSpots", True) and self.built:
            from .mmbview import spot_label
            spot_label(self.wide, spot)

    def _header_status(self, head) -> None:
        locks = QVBoxLayout()
        locks.setSpacing(6)
        self.rx_badge = RxBadge(self.tr("RX · beacon"))
        self.rx_badge.mode_chosen.connect(lambda m: self.bridge.set(beaconMode=m))
        self.rx_badge.nudged.connect(self.nudge_rx_corr)
        self.rx_badge.corr_typed.connect(lambda v: self.bridge.set(rxCorr=v))
        self.rx_badge.wheel_refused.connect(
            lambda: self.on_toast({"level": "info", "text": "The wheel sets rxCorr in Manual only: click the RX "
                                                             "badge and choose Manual"}))
        self.tx_badge = LockBadge(self.tr("TX · own signal"))
        locks.addWidget(self.rx_badge)
        locks.addWidget(self.tx_badge)
        head.addLayout(locks)
        self.tickers = [self.rx_badge, self.tx_badge]

    def _transmit_card(self):
        return TransmitCard(self.bridge)

    def status_items(self, st: dict) -> list[tuple[str, str]]:
        return status_items(st)

    def _sync_header(self, ch: dict | None) -> None:
        if ch is None or any(k in ch for k in LOCK_KEYS):
            self._sync_locks()

    def _sync_locks(self):
        st = self.bridge.st
        rl = st.get("rxLock", "off")
        mode = st.get("beaconMode", "auto")
        b = self.rx_badge
        b.mode, b.corr = mode, float(st.get("rxCorr") or 0.0)
        untracked = mode != "auto"
        if rl == "locked":
            detail = hz_forms(st.get("rxErr"))
        elif untracked:
            # Said on the badge itself, not only in the panel: the one thing
            # an operator who set Hold an hour ago must not forget.
            detail = "no tracking"
        elif rl == "searching" and st.get("rxWindow"):
            detail = f"±{float(st['rxWindow']) / 1000:g} kHz"
        else:
            detail = ""
        rows = [("Mode", MODE_NAMES.get(mode, mode) + ("" if not untracked else " — drift not followed")),
                ("Beacon", st.get("beaconUsed") or "—"), ("Error", fmt_hz(st.get("rxErr"))),
                ("Drift", "not tracked" if untracked else f"{float(st.get('rxRate') or 0):+.2f} Hz/s"),
                ("rxCorr", fmt_hz(st.get("rxCorr")) + (" (set by hand)" if st.get("rxCorrHand") else "")),
                ("Beacon SNR", f"{float(st.get('rxSnr') or 0):.1f} dB"),
                ("Beacon level", f"{float(st.get('beaconLevel') or -200):.1f} dBFS")]
        if rl == "searching" and st.get("rxWindow"):
            rows.insert(1, ("Searching", f"±{float(st['rxWindow']) / 1000:g} kHz"))
        if st.get("rxReject"):
            # Why the last thing looked at was not taken for the beacon: what
            # an on-air report needs (Ray, 05/10: SSB took the lock).
            rows.append(("Last refused", st["rxReject"]))
        b.set_state(rl, detail, rows)
        tl = st.get("txLockState", "idle")
        if not st.get("txLock", True):
            tl = "off"
        vs = st.get("vsBeacon")
        # With an IC-9700 as the transmitter the badge is about its
        # correction (rigTxCorr), kept apart from the Pluto's txCorr.
        rig = st.get("txRadio", "sdr") != "sdr"
        name, corr = ("rigTxCorr", st.get("rigTxCorr")) if rig else ("txCorr", st.get("txCorr"))
        trusted = st.get("rigTxCorrTrusted") if rig else st.get("txCorrTrusted")
        ppm = (-float(corr or 0) / 2_400_250_000.0 * 1e6) if rig else float(st.get("txPpm") or 0)
        keyed = st.get("rigKeyed") if rig else st.get("keyed")
        # The error only once this over has measured one (landed, locked):
        # while searching, txErr is the last over's - or the 0 it starts at,
        # which the badge showed as "SEARCHING +0.0 Hz", a lock nobody had.
        if tl in ("locked", "landed") and keyed:
            detail = hz_forms(st.get("txErr"))
        elif tl == "searching":
            detail = ""
        else:
            detail = ppm_forms(ppm) if trusted else ""
        self.tx_badge.set_state(tl, detail, [
            (name, fmt_hz(corr)), ("ppm", f"{ppm:+.3f}"),
            (self.tr("Last error"), fmt_hz(st.get("txErr"))),
            (self.tr("Confidence"), f"{float(st.get('txConfidence') or 0):.1f}"),
            (self.tr("vs beacon"), "—" if vs is None else self.tr("{vs:+.1f} dB").format(vs=vs)),
            (self.tr("From a lock"), self.tr("yes") if trusted else self.tr("not yet"))])

    # ------------------------------------------------------------ beacon lock
    def nudge_rx_corr(self, hz: float):
        st = self.bridge.st
        if st.get("beaconMode") != "manual":
            return
        self.bridge.set(rxCorr=round(float(st.get("rxCorr") or 0.0) + hz, 1))

    def toggle_hold(self):
        """H: Hold, or back to Auto from it (Manual goes to Hold too: H is
        "stop everything now")."""
        mode = "auto" if self.bridge.st.get("beaconMode") == "hold" else "hold"
        if self.bridge.set(beaconMode=mode):
            self.on_toast({"level": "info", "text": "Beacon lock on Hold: rxCorr kept as it is, drift not followed "
                                                    "(H for Auto)" if mode == "hold" else
                           "Beacon lock on Auto: looking for the beacon near the correction held"})

    def scope_menu_items(self, f: float):
        near = min(CLICK_BEACONS, key=lambda k: abs(bandplan.BEACONS[k]["dl"] - f))
        # Beacon lock keeps the menu's default (the beacon nearest the
        # click): a lock gone wrong can put the real beacon anywhere on the
        # scope, so no distance from a beacon says which a right-click
        # means. Auto-tune (USB, LSB) follows the beacons.
        return [(f"Lock to this as the {k} beacon", lambda k=k: self.lock_beacon_here(k, f), k == near)
                for k in CLICK_BEACONS] + super().scope_menu_items(f)

    def scope_menu(self, f: float, where) -> None:
        """A right-click on either scope: the "What is this?" card
        (ohsnb/ui/whatis.py) - what the signal at `f` is, its one-click
        actions, then the menu's own items - in place of the bare menu.
        It opens wherever the click was, even with nothing there, as the
        band-plan segment and the skimmer's state are still worth saying."""
        from .. import whatis
        from .whatis import WhatIsCard
        st = self.bridge.st
        entries = list(getattr(getattr(self, "skim_store", None), "entries", None) or [])
        events = list(self._op_store().events)
        ident = whatis.identify(f, entries, st, events, time.time())
        if ident.what == "kgstv":
            # The sender of the picture last received, when it said.
            store = getattr(self, "mmb_store", None)
            call = (getattr(store, "kg", None) or {}).get("call") if store is not None else ""
            if call:
                ident = dataclasses.replace(ident, entry={**ident.entry, "sender": call})
        # The menu's items are checked again when chosen, as the card's own
        # actions are: auto-tune retunes, and a beacon lock moves rxCorr.
        items = [(text, lambda fn=fn: self._not_on_air(fn), likeliest)
                 for text, fn, likeliest in self.scope_menu_items(f)]
        self.scope_menu_open = card = WhatIsCard(ident, items, self.whatis_do, self._tx_busy(), st, self)
        card.popup(where)

    def _tx_busy(self) -> bool:
        """On the air or armed: "What is this?" then retunes nothing. Asked
        of the engine as well as the state feed's copy, which can trail a
        key-up (kgstv_button has the story)."""
        now = {**self.bridge.st, **self.bridge.radio.state()}
        return bool(self._keyed() or now.get("keyed") or self.face.on_air(now) or self._armed_at() is not None)

    def _not_on_air(self, fn) -> None:
        if self._tx_busy():
            self.on_toast({"level": "warn", "text": self.tr("Not while transmitting")})
        else:
            fn()

    def whatis_do(self, a, ident) -> None:
        """One of the card's actions. The receiver only: a mode and a dial,
        or a Beacon page. Not while on the air or armed - asked again here,
        as an over may have started since the card opened. Tuning from the
        card leaves a workspace picked by hand as it is (decision 2): only
        the mode's own change moves an Auto workspace."""
        if self._tx_busy():
            self.on_toast({"level": "warn", "text": self.tr("Not while transmitting")})
            return
        if a.key == "view":
            self.show_view("mmb")
            self.mmb_view.show_page(a.page)
            return
        if a.key == "autotune" or (a.key == "decode" and ident.what == "window"):
            # skim_tune knows both: a calling window to its dial in its
            # mode, a voice not measured yet through auto-tune.
            self.skim_tune(ident.entry)
            return
        st = self.bridge.st
        if a.dial is not None:
            target = float(a.dial)
        else:
            from ohscore.ui.panels.text import mode_offset
            from ohscore.ui.tuning import click_to_dial
            target = click_to_dial(a.mode, float(a.f), st, mode_offset(a.mode))
        if st.get("ritOn"):
            target -= float(st.get("rit") or 0)
        sp = self.bridge.spec("vfo")
        self.bridge.set(mode=a.mode, vfo=max(sp["min"], min(sp["max"], target)))

    def lock_beacon_here(self, beacon: str, f: float):
        try:
            self.bridge.radio.beacon_here(beacon, f)
        except ValueError as e:
            self.on_toast({"level": "warn", "text": str(e)})

    def eventFilter(self, obj, ev):
        # H is NB's own key (beacon lock Hold); the shared keys are the
        # base class's. Same rules as those: not while typing, not with
        # Ctrl/Alt, not while the shortcut list is open, our window only.
        if (ev.type() == QEvent.Type.KeyPress and ev.text() in ("h", "H") and not self._typing()
                and not ev.modifiers() & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)
                and isinstance(obj, QWidget) and obj.window() is self and not self.overlay.isVisible()):
            self.toggle_hold()
            return True
        return super().eventFilter(obj, ev)

    def on_lock(self, it: dict):
        # TX lock saw our own signal: the scopes show where it landed.
        if it.get("kind") == "tx" and it.get("ownDl"):
            self.wide.own_seen_t = self.zoom.own_seen_t = time.time()

    def settings_dialog(self):
        from .settings import SettingsDialog
        return SettingsDialog(self.bridge, self.prefs, self)

    def welcome_dialog(self):
        from .welcome import Welcome
        return Welcome(self.bridge, self.prefs, self)

    def about_dialog(self):
        from .welcome import About
        return About(self)
