"""python3 -m ohsnb [--headless] [--device sim|pluto|soapy] [--receive-only] [--seconds N]
python3 -m ohsnb --analyse <file.sigmf-meta|.sigmf-data> [--out DIR] [--minutes N] [--extended] [--jobs N]

Without --headless this opens the window (ohsnb/ui). --headless runs the
engine alone and prints one status line a second; it heartbeats the
watchdog itself and never transmits: nothing here calls ptt().

--receive-only takes the transmitter away for the run (ohscore/config.py
RECEIVE_ONLY): the radio opens as usual and every over is refused with
config.RECEIVE_ONLY_REFUSAL. It is never saved.

--rig-diagnostic [FILE] runs the IC-9700 diagnostic (ohsnb/rigdiag.py)
headless and writes its report. It reads only, unless --keyed is given,
which transmits four short overs and is refused unless
--i-have-a-dummy-load-and-operator-present is given too: the one way this
command line keys a radio.

--analyse is a different command entirely (ohsnb/analyse.py): a report on a
receive IQ recording, for someone who is not a developer, with no radio
opened and no window. It is handled first, before the normal run's config
and logging set-up, since it needs neither.

Either way the run is logged to <data>/logs/openhamshack-nb.log (ohscore/diag.py).
-v makes that log and the console DEBUG: on Windows,
`openhamshack-nb-console.exe -v` is the window with a live debug console.
"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time
from pathlib import Path

from ohscore import diag
from ohscore.config import override_device, receive_only

from . import analyse as analyse_mod
from . import bandplan, config
from .radio import Radio


def status_line(s: dict, drained: dict) -> str:
    vs = s.get("vsBeacon")
    return (f"{time.strftime('%H:%M:%S')} {s['mode'].upper():4s} {s['vfo'] / 1e6:.4f} MHz "
            f"rx-lock {s['rxLock']:9s} corr {s['rxCorr']:+9.1f} Hz err {s['rxErr']:+6.1f} "
            f"snr {s['rxSnr']:5.1f} dB [{s['beaconUsed'] or '-':6s}] "
            f"tx-corr {s['txCorr']:+8.1f} Hz ({s['txPpm']:+.2f} ppm) "
            f"{'TX ' if s['keyed'] else ''}{'' if vs is None else f'vsBeacon {vs:+.1f} dB '}"
            f"cpu {100 * s['cpu']:4.1f}% wide {drained['wide']} zoom {drained['zoom']}"
            + (f"  ! {s['error']}" if s.get("error") else ""))


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--analyse" in argv:
        # A different command entirely (ohsnb/analyse.py): its own flags
        # (--out, --minutes) would otherwise collide with this parser's, so
        # it is dispatched before the normal run's argument parsing - and
        # before config/logging set-up, neither of which it needs.
        i = argv.index("--analyse")
        return analyse_mod.run(argv[i + 1:i + 2] + argv[:i] + argv[i + 2:])
    ap = argparse.ArgumentParser(prog="python3 -m ohsnb", description="OpenHamShack QO-100 NB, a QO-100 narrowband transceiver")
    ap.add_argument("--headless", action="store_true", help="run the engine without a window")
    ap.add_argument("--server", action="store_true",
                    help="the store form: run the engine headless behind its HTTP/WebSocket API "
                         "(docs/SERVER-API.md); for a container on an OpenHamShack controller")
    ap.add_argument("--port", type=int, default=None, help="--server's port (default $SHACK_PORT or 8080)")
    ap.add_argument("--device", choices=["sim", "pluto", "soapy"], help="override the configured device")
    ap.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = until Ctrl-C)")
    ap.add_argument("--no-audio", action="store_true", help="run with the null audio backend")
    ap.add_argument("--receive-only", action="store_true",
                    help="never transmit this run: every over is refused, whatever the window asks for; "
                         "the radio opens as it always does, its transmitter quiet. Not saved")
    ap.add_argument("--pad-report", action="store_true",
                    help="print the controller report (the Ajazz AKP03E pad: what is plugged in, what this "
                         "installation has for it, what is wrong) and exit; opens no radio and no window")
    ap.add_argument("--rig-diagnostic", nargs="?", const="", default=None, metavar="FILE",
                    help="run the IC-9700 diagnostic (ohsnb/rigdiag.py) with the saved settings and write its "
                         "report to FILE (default: Documents/ic9700-diagnostic-<time>.txt); reads only unless "
                         "--keyed")
    ap.add_argument("--keyed", action="store_true",
                    help="with --rig-diagnostic: also the keyed checks, four short overs of a tone into the "
                         "IC-9700 at the band and power it is set to. TRANSMITS; refused without the next flag")
    ap.add_argument("--i-have-a-dummy-load-and-operator-present", dest="promised", action="store_true",
                    help="with --keyed: you promise the IC-9700 is into a dummy load and someone is at the radio "
                         "(the window's dummy-load tick and confirmation, for a run with nobody to click them)")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="log in detail (DEBUG), to the log file and the console")
    a = ap.parse_args(argv)
    if a.keyed and (a.rig_diagnostic is None or not a.promised):
        # Before anything is opened: over SSH nobody is at the radio to
        # tick a box, so the promise is the box (ohsnb/rigdiag.py).
        print("--keyed transmits, and only with --rig-diagnostic: add --i-have-a-dummy-load-and-operator-present "
              "if, and only if, the IC-9700 is into a dummy load and someone is at the radio", file=sys.stderr)
        return 2
    if a.keyed and a.receive_only:
        print("--keyed transmits and --receive-only refuses to: pick one", file=sys.stderr)
        return 2
    if a.pad_report:
        # Before logging and config: it reads neither, touches no radio,
        # and must work on a machine where nothing else does yet.
        from ohscore import padreport
        print(padreport.text("OpenHamShack QO-100 NB", "ohsnb"), end="")
        return 0
    setup = diag.start_logging(config.APP.name, config.data_dir(), a.verbose)
    try:
        return _run(a)
    except Exception:
        logging.getLogger("ohsnb").exception("OpenHamShack QO-100 NB stopped on an error")
        raise
    finally:
        logging.getLogger("ohsnb").info("OpenHamShack QO-100 NB exiting")
        setup.stop()


def _run(a) -> int:
    notes: list[str] = []
    cfg = config.load(notes=notes)
    for n in notes:
        print("config:", n)
        logging.getLogger("ohsnb.config").warning("%s", n)
    if a.device:
        override_device(cfg, a.device)
    if a.no_audio:
        cfg["audioBackend"] = "null"
    if a.receive_only:
        receive_only(cfg)
    diag.record_facts(diag.current(), "OpenHamShack QO-100 NB", "ohsnb", config.data_dir(), cfg)
    if a.server:
        return _serve(a, cfg)
    if a.rig_diagnostic is not None:
        from . import rigdiag
        return rigdiag.run_cli(lambda: Radio(cfg, persist=False), a.rig_diagnostic or None, a.keyed, a.promised)
    if not a.headless:
        try:
            from .ui import run
        except ImportError as e:
            print(f"The window needs PyQt6 (Debian: python3-pyqt6): {e}\n"
                  f"Run with --headless to start the engine on its own.", file=sys.stderr)
            return 2
        # An override from the command line is for this run only: do not save it.
        return run(cfg, persist=not (a.device or a.no_audio))
    radio = Radio(cfg, persist=not a.device)
    feeds = {k: radio.subscribe(k, 256) for k in ("wide", "zoom", "toast", "events", "lock", "meter", "state")}
    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("now", True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("now", True))
    try:
        radio.start()
    except Exception as e:  # noqa: BLE001
        print(f"Could not start: {e}", file=sys.stderr)
        return 1
    st = radio.state()
    if st["simWhy"] and not st["simFallback"]:     # a fallback says so in its own warning
        print(f"SIMULATOR: {st['simWhy']}")
    t0 = time.monotonic()
    next_line = t0 + 1.0
    counts = {"wide": 0, "zoom": 0}
    try:
        while not stop["now"] and (a.seconds <= 0 or time.monotonic() - t0 < a.seconds):
            time.sleep(0.05)
            radio.heartbeat()
            for k, f in feeds.items():
                items = f.drain()
                if k in counts:
                    counts[k] += len(items)
                elif k == "toast":
                    for it in items:
                        print(f"[{it['level']}] {it['text']}")
                elif k == "events":
                    for it in items:
                        print("decode:", {x: y for x, y in it.items() if x != "t"})
            if time.monotonic() >= next_line:
                next_line += 1.0
                print(status_line(radio.state(), counts), flush=True)
                counts = {"wide": 0, "zoom": 0}
    finally:
        radio.stop()
    seg = bandplan.segment_at(radio.state()["vfo"])
    print(f"stopped; dial was in {seg['label'] if seg else 'no segment'}")
    return 0


def _serve(a, cfg) -> int:
    """The store form (ohscore/server). Imported only here: the window never
    loads the server (no servers inside the desktop apps)."""
    from ohscore.server import run as server_run
    from . import server as app_server
    version = (Path(__file__).resolve().parent / "VERSION").read_text().strip()
    commit_file = Path(__file__).resolve().parent / "COMMIT"
    commit = commit_file.read_text().strip() if commit_file.is_file() else ""
    return server_run.main(lambda audio: Radio(cfg, audio=audio, persist=True), app_server.info(version, commit),
                           port=a.port)


if __name__ == "__main__":
    sys.exit(main())
