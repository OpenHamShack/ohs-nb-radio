"""Render the screenshots in docs/screenshots from a live simulated radio.

    QT_QPA_PLATFORM=offscreen python3 -m ohsnb.ui.screenshots [outdir] [--only name,...] [--quick]

Runs the real window against the simulator in real time (FT8 decodes need
real 15 s slots), with a throw-away config and data directory, so nothing of
the operator's is touched. A full run takes about five minutes: each shot
lets the waterfall fill and the decoders catch up first. `--only` renders
just the named shots (and only runs the stages they need). Prints the
measured frame costs at the end of the first stage.

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
    out = Path(args[0]) if args else Path(__file__).resolve().parents[2] / "docs" / "screenshots"
    out.mkdir(parents=True, exist_ok=True)
    tmp = tempfile.mkdtemp(prefix="ohsnb-shots-")
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if matrix is not None and matrix.locale:
        os.environ["SHACK_LOCALE"] = matrix.locale       # before make_app installs the catalogs
    os.environ["OHS_NB_CONF"] = str(Path(tmp) / "config.json")
    os.environ["OHS_NB_DATA"] = str(Path(tmp) / "data")
    os.environ["OHS_NB_UI_CONF"] = str(Path(tmp) / "ui.json")

    import numpy as np

    from ohscore.audio import NullAudio
    from ohscore.ui.prefs import Prefs

    from .. import config, state
    from ..radio import Radio
    from . import build, make_app

    app = make_app(["shots"])
    rng = np.random.default_rng(3)

    def mic(n):
        # Speech-like: noise with a syllabic envelope, so dead air never trips.
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
            wait(0.6)
        if not want(name):
            return
        wait(0.3)
        p = out / f"{name}.png"
        widget.grab().save(str(p))
        print("wrote", p, flush=True)

    def new_window(theme_name="dark", scale=1.0, **over):
        cfg = state.defaults(("setting", "control"))
        cfg.update(device="sim", audioBackend="null", callsign="GM4BRI", locator="IO86ha", simSeed=11,
                   simRxErrorHz=1800.0, simUlErrorHz=-2900.0, txGain=-30.0, simRefGainDb=-20.0)
        cfg.update(over)
        radio = Radio(cfg, persist=False, data_dir=Path(tmp) / "data", audio=NullAudio(realtime=True, source=mic))
        # Three voice memories, so the keyer row shows what it is for.
        for i, name in enumerate(("CQ QO-100", "CQ contest", "QRZ?")):
            radio.keyer.slots.store(i, mic(int(12000 * (2.0 + i))))
            radio.keyer.slots.rename(i, name)
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
            return new_window(theme_name, scale, vfo=10_489_700_000.0, mode="usb", **extra)
        shotmatrix.run(matrix, out, state.MODES, open_window, wait, close)
        from ohscore.ui.qtapp import shutdown
        shutdown()
        return 0

    def stage_usb():
        win, bridge, radio, prefs = new_window(vfo=10_489_700_000.0, mode="usb")
        for call, mode in (("DL1ABC", "ft8"), ("G4XYZ", "usb"), ("EA4QRP", "cw")):
            radio.log_qso(call, dl=10_489_540_000.0 if mode == "ft8" else 10_489_700_000.0, mode=mode,
                          rstSent="-10" if mode == "ft8" else "59", rstRcvd="-12" if mode == "ft8" else "57")
        wait(22)
        shot(win, "main-usb-1920")
        shot(win, "main-usb-1366", (1366, 768))
        win.resize(1920, 1080)
        # A resized waterfall keeps the rows it had and fills the rest from
        # the top, so after the 1366 shot it needs a few seconds before the
        # transmitting shots, or they show a black band along its foot.
        wait(8)
        bridge.ptt(True)
        # The moment TX lock first finds our signal 2.9 kHz from where it was
        # aimed - then, a few seconds later, corrected onto the dial.
        end = time.monotonic() + 12
        while time.monotonic() < end and not (bridge.st.get("ownDl") and
                                              abs(bridge.st["ownDl"] - bridge.st["txDial"]) > 500):
            wait(0.05)
        shot(win, "transmitting-landed-1920")
        wait(8)
        shot(win, "transmitting-txlock-1920")
        bridge.ptt(False)
        wait(1)
        if want("voice-memories"):
            from ohscore.ui.keyer import VoiceKeyerDialog
            d = VoiceKeyerDialog(bridge, win)
            d.show()
            wait(0.5)
            shot(d, "voice-memories")
            d.done(0)
        if want("shortcuts-1920"):
            win.overlay.open()
            shot(win, "shortcuts-1920")
            win.overlay.close_()
        if want("settings-station", "settings-radio", "settings-transmit", "settings-display"):
            from .settings import SettingsDialog
            d = SettingsDialog(bridge, prefs, win, page=0)
            d.show()
            # By page name, not position: the IC-9700's Transmitter page
            # went in at index 2 and silently turned "transmit" and
            # "display" into pictures of LNB & locks and Audio.
            for name, builder in (("settings-station", "page_station"), ("settings-radio", "page_radio"),
                                  ("settings-transmit", "page_transmit"), ("settings-display", "page_display")):
                d.show_page(builder)
                shot(d, name)
            d.reject()
        if want("scope-adjust-peaks"):
            # The wide scope's adjust panel on its Peaks tab, with the
            # strongest signals labelled. The panel is a popup - a window of
            # its own, which grabbing the main window leaves out - so it is
            # painted over the scope where it opened.
            from PyQt6.QtGui import QPainter

            from ohscore.ui.wfpanel import AdjustPopover
            prefs["specMarks"] = True
            prefs["adjustTab"] = "peaks"
            win.wide.refresh_marks()
            wait(4)
            win.wide.open_levels()
            pop = win.wide.findChildren(AdjustPopover)[-1]
            wait(0.8)
            # On the window, not the scope: the panel is taller than the wide
            # scope and hangs over the zoom scope below it, as on screen.
            img = win.grab()
            origin = win.mapToGlobal(win.rect().topLeft())
            at = pop.mapToGlobal(pop.rect().topLeft()) - origin
            p = QPainter(img)
            p.drawPixmap(at, pop.grab())
            p.end()
            # The right-hand 1000 px of the wide scope, down to the panel's
            # foot: the middle beacon and the SSB segment around it.
            top = win.wide.mapToGlobal(win.wide.rect().topLeft()) - origin
            right = top.x() + win.wide.width()
            img = img.copy(right - 1000, top.y(), 1000, at.y() + pop.height() + 10 - top.y())
            pop.close()
            prefs["specMarks"] = False
            win.wide.refresh_marks()
            p = out / "scope-adjust-peaks.png"
            img.save(str(p))
            print("wrote", p, flush=True)
        if want("smeter-analogue"):
            # The analogue meter in S-units, calibrated as the guide says to:
            # a level typed against a measured one. On the simulator that is
            # pretend - whatever the passband held for the last three
            # seconds is called S9+10 - but it
            # is the real calibrate(), so the meter draws exactly what it
            # would after Calibrate….
            from ohscore.ui import smeter
            m = win.rxcard.s
            avg = m.average_dbfs()
            measured = avg[0] if avg else -60.0
            prefs["sMeterCal"] = smeter.calibrate({}, bridge.st, measured, -93.0 + 10.0)
            m.set_pref("sMeterUnit", "s")
            m.set_pref("sMeterStyle", "analog")
            wait(4)
            shot(win.rxcard, "smeter-analogue")
            m.set_pref("sMeterStyle", "bar")
            m.set_pref("sMeterUnit", "dbfs")
            prefs["sMeterCal"] = {}
        if want("welcome-1", "welcome-2", "welcome-3"):
            from .welcome import Welcome
            w = Welcome(bridge, prefs, win)
            w.show()
            shot(w, "welcome-1")
            w.go(1)
            shot(w, "welcome-2")
            w.go(2)
            shot(w, "welcome-3")
            w.reject()
        print(f"frame cost: pump {bridge.frame_ms:.2f} ms, wide paint {win.wide.cost_paint:.2f} ms, "
              f"wide line {win.wide.cost_ingest:.3f} ms, zoom paint {win.zoom.cost_paint:.2f} ms, "
              f"zoom line {win.zoom.cost_ingest:.3f} ms", flush=True)
        close(win, bridge)

    def stage_light():
        win, bridge, radio, prefs = new_window("light", vfo=10_489_700_000.0, mode="usb")
        wait(15)
        shot(win, "main-usb-light-1920")
        bridge.set(mode="cw", vfo=10_489_520_000.0)
        wait(12)
        shot(win, "main-cw-light-1366", (1366, 768))
        close(win, bridge)

    def stage_ft8():
        win, bridge, radio, prefs = new_window(vfo=10_489_540_000.0, mode="ft8")
        wait(40)
        # Answer the most recent CQ, as an operator clicking it would.
        ft8 = win.panel
        rows = [r for r in range(ft8.table.rowCount())
                if (ft8.table.item(r, 5) and ft8.table.item(r, 5).text().startswith("CQ "))]
        if rows:
            ft8._row_clicked(rows[-1], 5)
        wait(4)
        shot(win, "main-ft8-1920")
        shot(win, "main-ft8-1366", (1366, 768))
        win.resize(1920, 1080)
        if want("second-display-waterfall", "second-display-panel"):
            win.toggle_second()
            sec = win.second
            sec.resize(1600, 900)
            # The big waterfall is about 540 rows and fills at 6-7 a second:
            # 45 s left its lower third black (as every copy before 0.1.3 shows).
            wait(90)
            shot(sec, "second-display-waterfall")
            prefs["secondContent"] = "panel"
            sec.rebuild()
            wait(16)
            shot(sec, "second-display-panel")
            sec.close()
        close(win, bridge)

    def test_card():
        """A test picture for SSTV, drawn here (no image files)."""
        from PyQt6.QtCore import QRectF, Qt
        from PyQt6.QtGui import QColor, QImage, QLinearGradient, QPainter
        from ohscore.ui import theme

        from . import appicon
        img = QImage(320, 240, QImage.Format.Format_RGB888)
        p = QPainter(img)
        g = QLinearGradient(0, 0, 0, 240)
        g.setColorAt(0, QColor("#16213a"))
        g.setColorAt(1, QColor("#05070c"))
        p.fillRect(img.rect(), g)
        bars = ["#ffffff", "#ffd166", "#4fd1e8", "#3ddc84", "#c39bff", "#ff4d5e", "#3f74e0", "#111111"]
        for i, c in enumerate(bars):
            p.fillRect(QRectF(i * 40, 170, 40, 70), QColor(c))
        p.drawPixmap(14, 18, appicon.pixmap(84))
        p.setPen(QColor("#e8edf4"))
        p.setFont(theme.font(34, theme.QFont.Weight.Bold))
        p.drawText(QRectF(108, 22, 210, 44), Qt.AlignmentFlag.AlignVCenter, "GM4BRI")
        p.setFont(theme.font(17))
        p.setPen(QColor("#4fd1e8"))
        p.drawText(QRectF(108, 66, 210, 30), Qt.AlignmentFlag.AlignVCenter, "QO-100 \u00b7 IO86ha")
        p.setPen(QColor("#a3adbb"))
        p.setFont(theme.font(13))
        p.drawText(QRectF(14, 118, 300, 40), Qt.AlignmentFlag.AlignVCenter, "OpenHamShack \u2014 Robot 36 test card")
        p.end()
        ptr = img.constBits()
        ptr.setsize(img.sizeInBytes())
        arr = np.frombuffer(ptr, np.uint8).reshape(240, img.bytesPerLine())[:, :320 * 3].reshape(240, 320, 3)
        return arr.copy()

    def stage_text():
        # A near-perfect uplink, so our own transmissions come back on the
        # decoders' frequency at once: the terminals show what we sent (red)
        # and what the satellite returned, decoded.
        win, bridge, radio, prefs = new_window(vfo=10_489_531_000.0, mode="cw", cwWpm=22.0, simUlErrorHz=25.0)
        radio.log_qso("G4XYZ", dl=10_489_700_000.0, mode="usb", rstSent="59", rstRcvd="57", name="Dave")
        wait(6)
        win.panel.qso.call.setText("DL1ABC")
        win.panel._macro(prefs["cwMacros"][0])
        wait(16)
        shot(win, "main-cw-1920")
        # RTTY rather than PSK31 for the keyboard-mode picture: the PSK31
        # decoder loses our own echo at the sim's noise level (see the report
        # that came with this UI); RTTY reads it back.
        bridge.set(mode="rtty", vfo=10_489_575_000.0)
        wait(4)
        win.panel.qso.call.setText("EA4QRP")
        win.panel._macro(prefs["textMacros"][0])
        wait(18)
        shot(win, "main-rtty-1920")
        # SSTV: the decoder does not survive the simulator's noise floor (see
        # the report that came with this UI), so the picture here is decoded,
        # by the real decoder, from clean rendered audio, and its events are
        # fed to the window exactly as the engine would deliver them: one
        # finished picture for the gallery, then a second caught mid-frame.
        bridge.set(mode="sstv", vfo=10_489_600_000.0)
        wait(3)
        from ohscore import modes_glue
        enc = modes_glue.encoder("sstv")
        card = test_card()
        events = []
        dec = modes_glue.decoder("sstv", events.append, out_dir=str(radio.sstv_dir()))
        for img in (card, card):
            audio = np.concatenate([np.zeros(6000, np.float32), enc.render(image=img).astype(np.float32),
                                    np.zeros(12000, np.float32)])
            for i in range(0, len(audio), 1200):
                dec.feed(audio[i:i + 1200], i / 12000.0)
        first = next(i for i, e in enumerate(events) if e.get("state") == "done") + 1
        for e in events[:first]:
            bridge.decoded.emit(dict(e, t=time.time(), dial=bridge.st.get("rxDial")))
        wait(0.5)
        second = events[first:]
        for e in second[:int(len(second) * 0.62)]:
            bridge.decoded.emit(dict(e, t=time.time(), dial=bridge.st.get("rxDial")))
        wait(1.5)
        shot(win, "main-sstv-1920")
        bridge.set(mode="freedv", vfo=10_489_640_000.0)
        wait(6)
        shot(win, "main-freedv-1920")
        win.show_view("log")
        shot(win, "logbook-1920")
        win.show_view("mem")
        shot(win, "memories-1920")
        close(win, bridge)

    def stage_beacon():
        # The multimedia beacon view, fed by the simulator's real HSmodem
        # beacon. Its loop is ~36 s; a bulletin, the picture and the spots
        # are all in by ~45 s. Tuned elsewhere on purpose: the beacon is
        # decoded from its own channel whatever the dial says.
        win, bridge, radio, prefs = new_window(vfo=10_489_700_000.0, mode="usb")
        win.show_view("mmb")
        end = time.monotonic() + (90 if not quick else 45)
        st = win.mmb_store
        while time.monotonic() < end and not (st.bulletins and st.pictures and len(st.spots) >= 8):
            wait(0.5)
        wait(2)
        for page, name in (("bulletins", "beacon-bulletins-1920"), ("dx", "beacon-dx-1920"),
                           ("pictures", "beacon-pictures-1920")):
            win.mmb_view.show_page(page)
            shot(win, name)
        close(win, bridge)

    def stage_hsmodem():
        # HSmodem station to station: what "G4XYZ" sent (a picture and a
        # message, rendered by the real encoder and decoded by the real
        # receiver from clean audio, its events fed to the window as the
        # engine delivers them - as for SSTV), and a picture of our own
        # going out on the simulator, the send panel part-way through.
        win, bridge, radio, prefs = new_window(vfo=10_489_620_000.0, mode="hsmodem")
        wait(3)
        from ohscore import modes_glue
        enc = modes_glue.encoder("hsmodem")
        events = []
        dec = modes_glue.decoder("hsmodem", events.append, folder=str(radio.hsmodem_dir()), speed=4410)
        card = Path(__file__).resolve().parents[1] / "devices" / "mmb-testcard.jpg"
        noise = np.random.default_rng(5)
        for msg in ({"name": "g4xyz-station.jpg", "data": card.read_bytes()},
                    {"text": "Hello from G4XYZ - picture of the station sent with HSmodem 4410, QPSK. 73"}):
            a = enc.render(speed=4410, callsign="G4XYZ", locator="IO91wm", **msg)
            a = np.concatenate([np.zeros(6000, np.float32), a, np.zeros(12000, np.float32)])
            a = a + 0.01 * noise.standard_normal(len(a)).astype(np.float32)
            for i in range(0, len(a), 1200):
                dec.feed(a[i:i + 1200], i / 12000.0)
        for e in events:
            bridge.decoded.emit(dict(e, t=time.time(), dial=bridge.st.get("rxDial")))
        wait(0.5)
        p = win.panel
        p.list.setCurrentRow(1)
        p._show_item(p.list.item(1))
        p.res.setCurrentIndex(p.res.findData("320x240"))
        p.set_picture(str(test_card_file()))
        wait(0.5)
        p.send()
        wait(12)
        shot(win, "main-hsmodem-1920")
        shot(p, "hsmodem-panel")
        bridge.halt()
        close(win, bridge)

    def test_card_file() -> Path:
        """The SSTV test card as a PNG on disk, for a file dialog's choice."""
        from PyQt6.QtGui import QImage
        img = np.ascontiguousarray(test_card())
        q = QImage(img.data, img.shape[1], img.shape[0], img.shape[1] * 3, QImage.Format.Format_RGB888)
        f = Path(tmp) / "testcard-640.png"
        q.scaled(640, 480).save(str(f))
        return f

    def stage_auto():
        # Auto-tune and best audio on a talking station the simulator puts
        # in a quiet stretch of the SSB segment (the populated band's own
        # QSOs take turns, and auto-tune wants someone talking): clicked
        # 150 Hz low, then landed, then given its best audio.
        dial = 10_489_812_000.0
        win, bridge, radio, prefs = new_window(vfo=dial - 150.0, mode="usb", simSignals=False, rxCorr=1800.0,
                                               beaconMode="hold")
        wait(2)
        radio.dev.add_station("talk-usb", dial, -48.0, seed=5)
        wait(10)
        # As an operator would: press again if it refused (the voice paused).
        for _ in range(3):
            win.rxcard.request("tune")
            end = time.monotonic() + 15
            while time.monotonic() < end and radio.state()["autoBusy"]:
                wait(0.2)
            if not radio.state()["autoTuneRefused"]:
                break
        wait(2)
        shot(win, "main-autotune-1920")
        shot(win.rxcard, "receive-autotune")
        win.rxcard.request("audio")
        end = time.monotonic() + 15
        while time.monotonic() < end and radio.state()["autoBusy"]:
            wait(0.2)
        wait(1)
        shot(win.rxcard, "receive-bestaudio")
        close(win, bridge)

    def stage_leila():
        # The over-power watch on the simulated band: a carrier 7 dB over the
        # beacon in the SSB segment and LEILA's siren (as measured on
        # 17/10/2026) near the FT8 window, on the wide scope and in the Band
        # view's table.
        win, bridge, radio, prefs = new_window(vfo=10_489_540_000.0, mode="usb", rxCorr=1800.0)
        wait(3)
        radio.dev.add_station("carrier", 10_489_812_400.0, -33.0)
        radio.dev.add_station("leila", 10_489_541_300.0, -38.0)
        wait(4)
        win.show_view("skim")
        wait(3)
        shot(win, "main-leila-1920")
        shot(win.op_panel, "band-overpower")
        close(win, bridge)

    def stage_dish():
        # Dish alignment on a weak dish, as Brian's on 07/10/2026: both
        # beacons 17 dB down on the simulator's (the middle one ~10 dB over
        # the noise), the tone and the phone page on. The page's address is
        # an example one, not whatever machine renders the shots.
        from .. import dishmeter
        dishmeter.lan_addresses = lambda: ["10.0.0.50"]
        win, bridge, radio, prefs = new_window(vfo=10_489_700_000.0, mode="usb")
        wait(4)
        for st in radio.dev.stations:
            if "beacon" in st.name:
                st.amp *= 10 ** (-17 / 20)
        d = win.open_dish()
        d.tone.setChecked(True)
        d.phone.setChecked(True)
        wait(2)
        d.reset_best()             # the best before the fade would read 20 dB
        wait(3)
        shot(d, "dish-alignment")
        d.close()
        close(win, bridge)

    t0 = time.monotonic()
    if want("dish-alignment"):
        stage_dish()
    if want("main-leila-1920", "band-overpower"):
        stage_leila()
    if want("main-autotune-1920", "receive-autotune", "receive-bestaudio"):
        stage_auto()
    if want("beacon-bulletins-1920", "beacon-dx-1920", "beacon-pictures-1920"):
        stage_beacon()
    if want("main-usb-1920", "main-usb-1366", "transmitting-landed-1920", "transmitting-txlock-1920", "voice-memories",
            "shortcuts-1920", "settings-station", "settings-radio", "settings-transmit", "settings-display",
            "scope-adjust-peaks", "smeter-analogue", "welcome-1", "welcome-2", "welcome-3"):
        stage_usb()
    if want("main-usb-light-1920", "main-cw-light-1366"):
        stage_light()
    if want("main-ft8-1920", "main-ft8-1366", "second-display-waterfall", "second-display-panel"):
        stage_ft8()
    if want("main-cw-1920", "main-rtty-1920", "main-sstv-1920", "main-freedv-1920", "logbook-1920",
            "memories-1920"):
        stage_text()
    if want("main-hsmodem-1920", "hsmodem-panel"):
        stage_hsmodem()
    print(f"done in {time.monotonic() - t0:.0f} s", flush=True)
    from ohscore.ui.qtapp import shutdown
    shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
