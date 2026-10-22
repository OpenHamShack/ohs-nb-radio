"""The Qt window (docs/ham/DESIGN-HAM.md section 7). `run()` is what
`python3 -m ohsradio` calls when not --headless."""
from __future__ import annotations

from pathlib import Path

from ohscore.ui.qtapp import make_app as _make_app
from ohscore.ui.qtapp import shutdown


def make_app(argv=None):
    app = _make_app(argv, "OpenHamShack Radio", "openhamshack-radio")
    # Before any window exists: tr() is answered when a widget is built, so
    # a catalog installed later changes nothing on screen. On every call,
    # not just the first: the test suite makes both apps' windows in one
    # process, and each needs its own catalog in front (ohscore/i18n).
    from ohscore import i18n
    i18n.install(app, catalogs=i18n.app_catalogs(Path(__file__).resolve().parent.parent))
    return app


def build(radio, prefs, start: bool = True):
    """The window and its bridge for an existing Radio (tests use this)."""
    from PyQt6.QtWidgets import QApplication

    from ohscore.ui import theme
    from ohscore.ui.bridge import Bridge

    from .face import HamFace
    from .mainwindow import MainWindow
    theme.set_theme(prefs["theme"])
    theme.set_scale(prefs["textScale"])     # before any widget sizes a font
    app = QApplication.instance()
    app.setFont(theme.app_font())
    app.setStyleSheet(theme.stylesheet())
    face = HamFace()
    bridge = Bridge(radio, face=face)
    face.bridge = bridge
    bridge.licence_ok = bool(prefs["licenceAck"])
    err = bridge.start() if start else ""
    win = MainWindow(bridge, prefs, start_error=err)
    return win, bridge


def run(cfg: dict, persist: bool = True, band: str | None = None, rf: float | None = None,
        mode: str | None = None) -> int:
    app = make_app()
    from ohscore.ui import theme
    from ohscore.ui.prefs import Prefs

    from .. import config
    from ..radio import Radio
    from .appicon import app_icon
    app.setWindowIcon(app_icon())
    prefs = Prefs(config.CONFIG)
    theme.set_theme(prefs["theme"])
    theme.set_scale(prefs["textScale"])     # the Welcome is built at it too
    app.setFont(theme.app_font())
    app.setStyleSheet(theme.stylesheet())
    radio = Radio(cfg, persist=persist)
    try:
        radio.start_on(band=band, rf=rf, mode=mode)
    except ValueError as e:
        print(f"Ignored: {e}")
    if not prefs["welcomed"]:
        from ohscore.ui.bridge import Bridge

        from .face import HamFace
        from .welcome import Welcome
        face = HamFace()
        probe = Bridge(radio, face=face)
        face.bridge = probe
        w = Welcome(probe, prefs)
        w.exec()
        for f in probe.feeds.values():
            radio.unsubscribe(f)
        prefs["welcomed"] = True
        prefs.save()
    win, bridge = build(radio, prefs)
    win.show()
    # After the window is up, never before: the first check is seconds
    # later, on a thread (ohscore/ui/update.py).
    win.updates.start()
    win.diagsend.start()
    # The AKP03E or a keypad, when there is one (ohscore/ui/padlink.py).
    from ohscore.ui import padlink
    pad = padlink.start(win, radio, "radio", "Radio", prefs)
    if prefs["secondDisplay"]:
        win.toggle_second()
    # Ctrl-C, SIGTERM and SIGHUP quit as the Quit command does (windows
    # closed, unkeyed and saved), from the event loop, never from inside
    # whatever Qt call the signal landed in (ohscore/ui/qtapp.py says why).
    from ohscore.ui.qtapp import QuitOnSignals
    signals = QuitOnSignals(app)
    try:
        return app.exec()
    finally:
        if pad is not None:
            pad.close()
        bridge.stop()
        signals.close()
        shutdown()
