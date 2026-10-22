"""Render OpenHamShack Radio's screenshots into docs/ham/screenshots from a live
simulated radio.

    QT_QPA_PLATFORM=offscreen python3 -m ohsradio.ui.screenshots [outdir] [--only name,...] [--quick]

Runs the real window against the band simulator in real time (FT8 decodes
need real 15 s slots), with a throw-away config and data directory, so
nothing of the operator's is touched. Transmitting shots key the
simulator only. `--only` renders just the named shots.

`--matrix ...` renders the overhaul's screenshot matrix instead
(ohscore/ui/shotmatrix.py): every mode x size x text size x theme asked
for, into the folder given, which it requires.
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from ohscore.ui import shotmatrix
    matrix, argv = shotmatrix.parse(argv)
    quick = "--quick" in argv
    only = None
    args = []
    it = iter(argv)
    for a in it:
        if a == "--only":
            only = set(next(it, "").split(","))
        elif not a.startswith("--"):
            args.append(a)
    if matrix is not None and not args:
        # Never into the docs by default: the matrix is for checking work.
        raise SystemExit("--matrix needs an output folder, e.g. ~/build/ui-shots/wpN")
    out = Path(args[0]) if args else Path(__file__).resolve().parents[2] / "docs" / "ham" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="ohsradio-shots-")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if matrix is not None and matrix.locale:
        os.environ["SHACK_LOCALE"] = matrix.locale       # before make_app installs the catalogs
    os.environ["OHS_RADIO_CONF"] = str(Path(tmp) / "config.json")
    os.environ["OHS_RADIO_DATA"] = str(Path(tmp) / "data")
    os.environ["OHS_RADIO_UI_CONF"] = str(Path(tmp) / "ui.json")

    import numpy as np

    from ohscore.audio import NullAudio
    from ohscore.ui.prefs import Prefs

    from .. import config, state
    from ..radio import Radio
    from . import build, make_app

    app = make_app(["shots"])
    rng = np.random.default_rng(3)

    def mic(n):
        t = np.arange(n) / 12000.0 + time.time()
        env = 0.25 + 0.2 * np.abs(np.sin(2 * np.pi * 2.3 * t))
        return (env * rng.standard_normal(n)).astype(np.float32)

    def wait(sec):
        end = time.monotonic() + (sec * (0.25 if quick else 1.0))
        while time.monotonic() < end:
            app.processEvents()
            time.sleep(0.005)

    def want(*names):
        return not only or bool(only & set(names))

    def shot(widget, name, size=None):
        if size:
            widget.resize(*size)
            wait(0.8)
        if not want(name):
            return
        wait(0.3)
        p = out / f"{name}.png"
        widget.grab().save(str(p))
        print("wrote", p, flush=True)

    def new_window(theme_name="dark", scale=1.0, band=None, **over):
        cfg = state.defaults(("setting", "control"))
        cfg.update(device="sim", audioBackend="null", callsign="GM4BRI", locator="IO86ha", simSeed=11,
                   licenceClass="full", drive=0.4)
        cfg.update(over)
        radio = Radio(cfg, persist=False, data_dir=Path(tmp) / "data", audio=NullAudio(realtime=True, source=mic))
        # Three voice memories, so the keyer row shows what it is for.
        for i, name in enumerate(("CQ", "CQ contest", "QRZ?")):
            radio.keyer.slots.store(i, mic(int(12000 * (2.0 + i))))
            radio.keyer.slots.rename(i, name)
        if band and "vfo" not in over:
            # band() on the band the radio is already in steps to its next
            # register, so it is only used when no dial is given.
            radio.band(band)
            if "mode" in over:
                radio.set(mode=over["mode"])
        prefs = Prefs(config.CONFIG)
        prefs["welcomed"] = True
        prefs["licenceAck"] = True
        prefs["theme"] = theme_name
        prefs["textScale"] = scale
        win, bridge = build(radio, prefs)
        win.resize(1920, 1080)
        win.show()
        return win, bridge, radio, prefs

    def close(win, bridge):
        win.close()
        bridge.stop()
        wait(0.2)

    if matrix is not None:
        # ohscore/ui/shotmatrix.py: every mode from a voice dial, each tuned
        # to its usual place as a mode button would.
        def open_window(theme_name, scale, **extra):
            return new_window(theme_name, scale, vfo=14_195_000.0, mode="usb", simHourUtc=13.0, **extra)
        shotmatrix.run(matrix, out, state.MODES, open_window, wait, close)
        from ohscore.ui.qtapp import shutdown
        shutdown()
        return 0

    def stage_20m():
        win, bridge, radio, prefs = new_window(band="20m", vfo=14_195_000.0, mode="usb", simHourUtc=13.0)
        for call, f, mode in (("DL1ABC", 14_074_000.0, "ft8"), ("G4XYZ", 145_500_000.0, "fm"),
                              ("EA4QRP", 7_030_000.0, "cw"), ("OH8ZZ", 14_195_000.0, "usb")):
            radio.log_qso(call, rf=f, mode=mode, rstSent="59", rstRcvd="57")
        wait(20)
        shot(win, "main-20m-usb-1920")
        shot(win, "main-20m-usb-1366", (1366, 768))
        win.resize(1920, 1080)
        # A resized waterfall keeps the rows it had and fills the rest from
        # the top: a second after the 1366 shot, the shortcuts and logbook
        # shots showed the wide waterfall's lower part black.
        wait(10)
        if want("shortcuts-1920"):
            win.overlay.open()
            shot(win, "shortcuts-1920")
            win.overlay.close_()
        if want("settings-licence", "settings-power", "settings-sequencer", "settings-radio"):
            from .settings import SettingsDialog
            d = SettingsDialog(bridge, prefs, win, page=2)
            d.show()
            shot(d, "settings-licence")
            d.nav.select(3)
            shot(d, "settings-power")
            d.nav.select(5)
            shot(d, "settings-sequencer")
            d.nav.select(1)
            shot(d, "settings-radio")
            d.reject()
        if want("welcome-licence"):
            from .welcome import Welcome
            # As a new operator sees it: no class chosen, nothing preselected.
            radio.set(authorise=True, licenceClass="")
            prefs["licenceAck"] = False
            w = Welcome(bridge, prefs, win)
            w.show()
            w.go(1)
            shot(w, "welcome-licence")
            w.reject()
            prefs["licenceAck"] = True
            radio.set(authorise=True, licenceClass="full")
        win.show_view("log")
        shot(win, "logbook-1920")
        close(win, bridge)

    def stage_ft8():
        win, bridge, radio, prefs = new_window(band="20m", vfo=14_074_000.0, mode="ft8", simHourUtc=13.0)
        wait(40)
        shot(win, "main-ft8-20m-1920")
        close(win, bridge)

    def stage_fm():
        win, bridge, radio, prefs = new_window(band="2m", vfo=145_500_000.0, mode="fm", simHourUtc=20.0)
        end = time.monotonic() + 15
        while time.monotonic() < end and not getattr(radio.dev, "repeaters", None):
            app.processEvents()
            time.sleep(0.05)
        reps = [r for r in getattr(radio.dev, "repeaters", []) if 144e6 < r.dl < 146e6]
        if reps:
            r = reps[0]
            bridge.set(vfo=r.dl, ctcssTx=r.tone, rptShift="auto")
        wait(14)
        shot(win, "main-2m-fm-repeater-1920")
        if reps and want("transmitting-fm-repeater-1920"):
            bridge.ptt(True)
            wait(4)
            shot(win, "transmitting-fm-repeater-1920")
            bridge.ptt(False)
            wait(2)
        close(win, bridge)

    def stage_light():
        win, bridge, radio, prefs = new_window("light", band="2m", vfo=144_300_000.0, mode="usb", simHourUtc=20.0)
        wait(14)
        shot(win, "main-2m-ssb-light-1920")
        bridge.set(mode="cw", vfo=144_050_000.0)
        wait(10)
        shot(win, "main-2m-cw-light-1366", (1366, 768))
        close(win, bridge)

    def stage_night():
        win, bridge, radio, prefs = new_window(band="80m", vfo=3_700_000.0, mode="lsb", simHourUtc=21.0,
                                               licenceClass="foundation")
        wait(16)
        shot(win, "main-80m-lsb-foundation-1920")
        close(win, bridge)

    def stage_refused():
        # A Foundation licensee on 23 cm: the licence chip red with the reason,
        # the TX button locked saying why.
        win, bridge, radio, prefs = new_window(band="23cm", vfo=1_296_200_000.0, mode="usb", simHourUtc=20.0,
                                               licenceClass="foundation")
        wait(10)
        shot(win, "main-23cm-foundation-refused-1366", (1366, 768))
        close(win, bridge)

    def stage_diag():
        # The two diagnostics dialogs a tester with a stock Pluto meets.
        # The simulator stands in for the radio and a fixed answer for the
        # Pluto's identity: no radio is looked for.
        from .. import plutofix
        win, bridge, radio, prefs = new_window(band="70cm", licenceClass="intermediate")
        wait(2)
        radio.dev.kind, radio.dev.identity, radio.dev.uri = "pluto", "ad9363", "ip:192.168.2.1"
        win.pick_band("2m")
        wait(0.5)
        shot(win.dialog, "diag-chip-mode")
        win.dialog.reject()
        win.identify = lambda uri: plutofix.PlutoInfo(
            uri, True, model="Analog Devices PlutoSDR Rev.B (Z7010-AD9363)", serial="104473dc5996000c0d00",
            fw_version="v0.38", identity="ad9363")
        radio.dev.kind = "sim"            # so Check radio… asks the fixed answer, not the simulator
        win.check_radio()
        wait(1.5)
        shot(win.dialog, "diag-check-radio")
        win.dialog.reject()
        close(win, bridge)

    t0 = time.monotonic()
    if want("main-20m-usb-1920", "main-20m-usb-1366", "shortcuts-1920", "settings-licence", "settings-power",
            "settings-sequencer", "settings-radio", "welcome-licence", "logbook-1920"):
        stage_20m()
    if want("main-ft8-20m-1920"):
        stage_ft8()
    if want("main-2m-fm-repeater-1920", "transmitting-fm-repeater-1920"):
        stage_fm()
    if want("main-2m-ssb-light-1920", "main-2m-cw-light-1366"):
        stage_light()
    if want("main-80m-lsb-foundation-1920"):
        stage_night()
    if want("main-23cm-foundation-refused-1366"):
        stage_refused()
    if want("diag-chip-mode", "diag-check-radio"):
        stage_diag()
    print(f"done in {time.monotonic() - t0:.0f} s", flush=True)
    from ohscore.ui.qtapp import shutdown
    shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
