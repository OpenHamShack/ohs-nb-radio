"""The AKP03E (or a USB keypad) on the desktop: shack_pad's DesktopPad, fed
by this app's pad declaration and ohscore/padactions.py.

CONTROLLER-PAD.md section 6.2: no service and no socket on the desktop.
The pad belongs to whichever OpenHamShack app the operator is using,
through a lock file beside the station's store: this window gaining focus
asks for it, the owner hands it over within a second unless it is on the
air from the pad. Remaps go into the station profile's controllerMaps, so
they sync with a controller when paired; Settings › Control pad edits them
(ohscore/padmap.py has the rules) and apply_map() puts them in use.

Transmit: `ptt` keys through shack_pad's LocalLease (REMOTE-API section 7's
rules, in process), whose key-up is Engine.ptt with every check the
window's own PTT button gets; a pad that goes quiet or is unplugged while
keyed unkeys within the lease (section 7.2). The pad never touches the
radio by any other way.

Off for transmitting until the operator says otherwise (12/10/2026): the
first real pads go to people nobody can stand beside, on Windows where the
pad has never run, and a key that transmits is the one thing a pad must
not do by surprise. So until Settings › Control pad's "The pad may
transmit" is ticked (ui.json `padTransmit`, false when the file is
missing or unreadable), K1's key-up is refused like any other refusal: the
key shows why and nothing keys. Every other action - tuning, mode, mute -
works from the first plug-in, which is what lets the operator see the pad
work before trusting it with the transmitter.

Diagnostics for a remote operator (Settings › Control pad,
ohscore/ui/padpage.py): status() says whether the pad is found, open,
held by another app or refused, and why in words; the last few problems
are kept with their times; report() is the text to paste to the
developers; the test mode lights every key and shows each event without
acting on it.

Optional: without shack_pad's HID transport (hidapi on Windows and macOS;
hidraw on Linux needs nothing) or with no pad plugged in, nothing happens
except that the settings page says so.
"""
from __future__ import annotations

import collections
import logging
import time
from pathlib import Path

from PyQt6.QtCore import QEvent, QObject, pyqtSignal

from .. import padactions, padmap, padreport, shacklibs
from ..engine import TxRefused
from ..i18n.text import _
from . import txstate

log = logging.getLogger("ohscore.ui.padlink")

# The one PadLink of this process (one window, one pad), for the settings
# page; and why there is none when start() could not make one.
_current: "PadLink | None" = None
_failure = ""


def current() -> "PadLink | None":
    return _current


def failure() -> str:
    return _failure


class PadLink(QObject):
    # The MODE key was pressed: a request to operate, as a mode button is
    # (overhaul decision 2), so the window brings that mode's workspace even
    # from one pinned by hand. A signal because the pad's actions run on
    # shack_pad's thread, and a window is only touched from its own.
    mode_asked = pyqtSignal()

    def __init__(self, window, radio, kind: str, name: str, package_dir: Path, *, prefs=None, open_device=None):
        super().__init__(window)
        self.window = window
        if hasattr(window, "operate_requested"):
            self.mode_asked.connect(window.operate_requested)
        shacklibs.pad()
        from shack_pad.focus import DesktopPad
        from shack_pad.router import InProcessApp, InputHost
        from shack_pad.tx import LocalLease
        self.radio = radio
        self.kind = kind
        self.name = name
        self.prefs = prefs
        self.package = package_dir.name
        self.errors: collections.deque[tuple[float, str]] = collections.deque(maxlen=8)
        decl, layout = padactions.declaration(package_dir)
        self.actions = radio.pad_actions()
        self.lease = LocalLease(on_key=self._key, on_unkey=self._unkey)
        self.lease.start()
        app = InProcessApp(kind, name, decl, layout, perform=self._perform, faces=self._faces,
                           lease=self.lease)
        prof = radio.station.profile.get()
        self.host = InputHost([app], maps=padmap.clean_maps(prof.get("controllerMaps") or {}, kind),
                              on_maps=self._save_maps,
                              log=self._log)
        self.pad = DesktopPad(self.host, app=radio.APP_ID, store_dir=Path(radio.station.store.path).parent,
                              open_device=open_device)
        window.installEventFilter(self)
        self.pad.start()
        self.pad.focus_gained()

    # ---------------------------------------------------------- the lease
    def may_transmit(self) -> bool:
        """The operator has allowed the pad to key (Settings › Control pad).
        No prefs at all (a test, a broken ui.json) means no."""
        try:
            return bool(self.prefs is not None and self.prefs["padTransmit"])
        except (KeyError, TypeError):
            return False

    def _key(self) -> str | None:
        if not self.may_transmit():
            return _("The pad may not transmit: allow it in Settings › Control pad")
        try:
            self.radio.ptt(True)
        except (TxRefused, ValueError) as e:
            return str(e)
        return None

    def _unkey(self) -> None:
        self.radio.ptt(False)

    # ---------------------------------------------------------- actions
    def _perform(self, action) -> None:
        try:
            self.actions.perform(action.action, action.kind, action.step)
            if action.action == "mode:next":
                self.mode_asked.emit()
        except ValueError as e:
            self.radio.toast(str(e), "warn")
        except Exception:  # noqa: BLE001  a pad press must never take the window down
            log.exception("pad action %s", action.action)

    def _faces(self) -> dict:
        out = self.actions.faces()
        if not self.may_transmit():
            # Said on K1 itself, not only in Settings: a pad that will not
            # key should look like one. ON AIR (keyed from the window) still
            # wins: shack_pad draws that over any face an app sends.
            out.setdefault("faces", {})["ptt"] = {"l1": _("PTT"), "l2": _("off"), "tone": "disabled"}
        if self._set_up_to_transmit():
            out.setdefault("faces", {}).setdefault("halt", {"l1": "HALT", "l2": "TX"})["tone"] = "disabled"
        return out

    def _set_up_to_transmit(self) -> bool:
        """Whether this window cannot transmit until the operator sets it
        up (txstate SETUP: a real radio and the licence not acknowledged),
        and nothing is on the air or warned about. Then HALT TX is dimmed as
        it is for a run that can never transmit (padactions._halt_face):
        the pad looks like what it is. The engine cannot tell, because the
        acknowledgement is the window's (Bridge.licence_ok), so this is the
        desktop's own addition to the faces; the store form has its own
        licence gate. Dimmed is a face only: HALT still halts (section 7.1).
        Never while anything is on the air - an IC-9700 keyed at its own
        microphone included - or a transmit warning stands: there HALT is
        the key that matters (txstate.may_collapse has the rule)."""
        bridge = getattr(self.window, "bridge", None)
        if bridge is None:
            return False
        try:
            state = txstate.of_bridge(bridge)
            if state.kind != txstate.SETUP:
                return False
            # The engine's own state over the window's copy, which can trail
            # a key-up by a tenth of a second.
            st = {**bridge.st, **self.radio.state()}
            return txstate.may_collapse(state, st, bool(bridge.face.on_air(st)))
        except Exception:  # noqa: BLE001  a face is not worth a pad that stops drawing
            log.exception("pad halt face")
            return False

    def _save_maps(self, maps: dict) -> None:
        try:
            self.radio.station.profile.update({"controllerMaps": maps})
        except Exception:  # noqa: BLE001
            log.exception("pad remap not stored")

    def apply_map(self, pm: "padmap.PadMap") -> None:
        """Settings › Control pad's Save: the edited mapping, stored and in
        use from the next press. ValueError (a sentence) if it would move or
        remove the PTT key while this app is on the air - the operator would
        then be pressing a key that no longer stops the carrier."""
        from shack_pad import mapping
        kind = pm.kind
        new = mapping.with_entry(self.host.maps, kind, padmap.MODEL, pm.entry())
        if kind in self.host.on_air_apps():
            before = mapping.tx_holders(self.host.pages(kind, padmap.MODEL)[0][0], self.host.actions(kind))
            if before != mapping.tx_holders(pm.page(), pm.acts):
                raise ValueError(_("Not while on the air: the PTT key stays where it is until you stop transmitting"))
        padmap.store(self.radio.station.profile, kind, pm.entry())
        self.host.set_maps(new)

    def _log(self, message: str) -> None:
        log.info("pad: %s", message)

    # ---------------------------------------------------------- diagnostics
    def status(self) -> dict:
        """DesktopPad.status() (state, name, path, error) and whether the
        pad may transmit; a new problem is remembered with its time."""
        st = dict(self.pad.status())
        st["transmit"] = self.may_transmit()
        err = st.get("error") or ""
        if err and (not self.errors or self.errors[-1][1] != err):
            self.errors.append((time.time(), err))
        return st

    def report(self) -> str:
        st = self.status()
        lines = [f"pad state: {st['state']}" + (f" ({st['name']}, {st['path']})" if st.get("path") else ""),
                 f"pad may transmit: {'yes' if st['transmit'] else 'no'}",
                 f"pad lock folder: {self.pad.focus.dir}"]
        lines += [f"problem at {time.strftime('%H:%M:%S', time.localtime(t))}: {e}" for t, e in self.errors]
        return padreport.text(self.name, self.package, lines)

    def start_test(self) -> None:
        """RuntimeError (a sentence) while on the air."""
        self.host.start_test()

    def stop_test(self) -> None:
        self.host.stop_test()

    def testing(self) -> bool:
        return self.host.testing()

    def add_listener(self, fn) -> None:
        self.host.listeners.append(fn)

    def remove_listener(self, fn) -> None:
        try:
            self.host.listeners.remove(fn)
        except ValueError:
            pass

    # ---------------------------------------------------------- focus
    def eventFilter(self, obj, ev) -> bool:
        if ev.type() == QEvent.Type.WindowActivate:
            self.pad.focus_gained()
        return False

    def close(self) -> None:
        global _current
        self.lease.unkey()
        self.lease.stop()
        self.pad.close()
        if _current is self:
            _current = None


def start(window, radio, kind: str, name: str, prefs=None):
    """A PadLink, or None when the pad library cannot run here (it is
    optional; the window works the same without it, and Settings › Control
    pad says why)."""
    global _current, _failure
    try:
        pkg = Path(__import__(type(radio).__module__.split(".")[0]).__file__).resolve().parent
        _current = PadLink(window, radio, kind, name, pkg, prefs=prefs)
        _failure = ""
        return _current
    except Exception as e:  # noqa: BLE001
        log.info("no pad support here", exc_info=True)
        _failure = f"{type(e).__name__}: {e}"
        return None
