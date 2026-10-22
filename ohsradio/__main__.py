"""python3 -m ohsradio [--headless] [--device sim|pluto|hl2|soapy] [--band 2m] [--rf MHz] [--seconds N]

Without --headless this opens the window (ohsradio/ui). --headless runs the
engine alone and prints one status line a second; it heartbeats the
watchdog itself and never transmits: nothing here calls ptt().

Either way the run is logged to <data>/logs/openhamshack-radio.log (ohscore/diag.py).
-v makes that log and the console DEBUG.
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

from . import config
from .radio import Radio


def status_line(s: dict, counts: dict) -> str:
    info = s.get("licenceInfo") or {}
    lim = info.get("limitW")
    # Apart, not nested: the same quote inside a nested f-string is Python
    # 3.12 syntax, and Radio must load on 3.11 (Debian 12, the AppImage).
    limit = "" if lim is None else f"{lim:g} W {info.get('limitKind', '')}"
    return (f"{time.strftime('%H:%M:%S')} {s['band'] or '--':5s} {s['mode'].upper():4s} {s['vfo'] / 1e6:11.6f} MHz "
            f"seg {s.get('segment') or '-'} | "
            f"{info.get('class') or 'no-class'} {limit} "
            f"tx:{info.get('level', '')} | cpu {100 * s['cpu']:4.1f}% wide {counts['wide']} zoom {counts['zoom']}"
            f" rx {counts.get('rx', 0):.1f} dBFS" + (f"  ! {s['error']}" if s.get("error") else ""))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python3 -m ohsradio", description="OpenHamShack Radio, an all-amateur-bands SDR transceiver")
    ap.add_argument("--headless", action="store_true", help="run the engine without a window")
    ap.add_argument("--server", action="store_true",
                    help="the store form: run the engine headless behind its HTTP/WebSocket API "
                         "(docs/SERVER-API.md); for a container on an OpenHamShack controller")
    ap.add_argument("--port", type=int, default=None, help="--server's port (default $SHACK_PORT or 8080)")
    ap.add_argument("--device", choices=["sim", "pluto", "hl2", "soapy"], help="override the configured device")
    ap.add_argument("--band", help="start on this band (e.g. 20m, 2m, 70cm)")
    ap.add_argument("--rf", type=float, help="start on this frequency, MHz")
    ap.add_argument("--mode", help="start in this mode")
    ap.add_argument("--seconds", type=float, default=0.0, help="stop after this long (0 = until Ctrl-C)")
    ap.add_argument("--no-audio", action="store_true", help="run with the null audio backend")
    ap.add_argument("--receive-only", action="store_true",
                    help="never transmit this run: every over is refused, whatever the window asks for; "
                         "the radio opens as it always does, its transmitter quiet. Not saved")
    ap.add_argument("--pad-report", action="store_true",
                    help="print the controller report (the Ajazz AKP03E pad: what is plugged in, what this "
                         "installation has for it, what is wrong) and exit; opens no radio and no window")
    ap.add_argument("--cw-skim-selftest", action="store_true",
                    help="decode a synthetic CW band in the CW skimmer's worker process and exit (0 if every "
                         "station is spotted); proves a frozen build can start the worker. Opens no radio")
    ap.add_argument("--decode", action="append", default=[], metavar="DECODER@MHZ",
                    help="--headless: also run this decoder on a frequency of its own, e.g. rtty@14.0835 "
                         "(the Decoders view's sessions; repeat for more); its text is printed as it comes")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="log in detail (DEBUG), to the log file and the console")
    argv = sys.argv[1:] if argv is None else list(argv)
    if argv[:1] == ["--codec-probe"]:
        # The codec loader's child process in a frozen build (ohscore/sdr.py):
        # load one library and print one line. Before anything else - no
        # logging, no config, no radio, no window.
        from ohscore import sdr
        return sdr.main_probe(argv[1:])
    a = ap.parse_args(argv)
    if a.cw_skim_selftest:
        # Like --pad-report: no logging setup, no config, no radio.
        from .cwskim import selftest
        return selftest()
    if a.pad_report:
        # Before logging and config: it reads neither, touches no radio,
        # and must work on a machine where nothing else does yet.
        from ohscore import padreport
        print(padreport.text("OpenHamShack Radio", "ohsradio"), end="")
        return 0
    setup = diag.start_logging(config.APP.name, config.data_dir(), a.verbose)
    try:
        return _run(a)
    except Exception:
        logging.getLogger("ohsradio").exception("OpenHamShack Radio stopped on an error")
        raise
    finally:
        logging.getLogger("ohsradio").info("OpenHamShack Radio exiting")
        setup.stop()


def _run(a) -> int:
    notes: list[str] = []
    cfg = config.load(notes=notes)
    for n in notes:
        print("config:", n)
        logging.getLogger("ohsradio.config").warning("%s", n)
    override = bool(a.device or a.no_audio or a.band or a.rf or a.mode)
    if a.device:
        override_device(cfg, a.device)
    if a.no_audio:
        cfg["audioBackend"] = "null"
    if a.receive_only:
        receive_only(cfg)
    diag.record_facts(diag.current(), "OpenHamShack Radio", "ohsradio", config.data_dir(), cfg)
    if a.server:
        return _serve(a, cfg)
    if not a.headless:
        try:
            from .ui import run
        except ImportError as e:
            print(f"The window needs PyQt6 (Debian: python3-pyqt6): {e}\n"
                  f"Run with --headless to start the engine on its own.", file=sys.stderr)
            return 2
        return run(cfg, persist=not override, band=a.band, rf=a.rf, mode=a.mode)
    radio = Radio(cfg, persist=not override)
    feeds = {k: radio.subscribe(k, 256) for k in ("wide", "zoom", "toast", "events", "meter", "state", "decoders")}
    stop = {"now": False}
    signal.signal(signal.SIGINT, lambda *_: stop.__setitem__("now", True))
    signal.signal(signal.SIGTERM, lambda *_: stop.__setitem__("now", True))
    try:
        radio.start_on(band=a.band, rf=a.rf, mode=a.mode)
        radio.start()
    except Exception as e:  # noqa: BLE001
        print(f"Could not start: {e}", file=sys.stderr)
        return 1
    for want in a.decode:
        name, _, mhz = want.partition("@")
        try:
            sess = radio.decoders.start(name, float(mhz) * 1e6)
            print(f"decoder session {sess['id']}: {name} at {float(mhz):.4f} MHz ({sess['state']})")
        except ValueError as e:
            print(f"--decode {want}: {e}", file=sys.stderr)
    st = radio.state()
    if st["simWhy"] and not st["simFallback"]:     # a fallback says so in its own warning
        print(f"SIMULATOR: {st['simWhy']}")
    t0 = time.monotonic()
    next_line = t0 + 1.0
    counts = {"wide": 0, "zoom": 0, "rx": -200.0}
    try:
        while not stop["now"] and (a.seconds <= 0 or time.monotonic() - t0 < a.seconds):
            time.sleep(0.05)
            radio.heartbeat()
            for k, f in feeds.items():
                items = f.drain()
                if k in ("wide", "zoom"):
                    counts[k] += len(items)
                elif k == "meter" and items:
                    counts["rx"] = items[-1]["rx"]
                elif k == "toast":
                    for it in items:
                        print(f"[{it['level']}] {it['text']}")
                elif k == "events":
                    for it in items:
                        print("decode:", {x: y for x, y in it.items() if x != "t"})
                elif k == "decoders":
                    for it in items:
                        if it.get("type") == "text":
                            print(f"decoder {it['session']}: {it['text']!r}")
                        elif it.get("type") == "state":
                            print(f"decoder {it['session']}: {it['state']}"
                                  f"{' (' + it['whyText'] + ')' if it.get('whyText') else ''}")
            if time.monotonic() >= next_line:
                next_line += 1.0
                print(status_line(radio.state(), counts), flush=True)
                counts.update(wide=0, zoom=0)
    finally:
        radio.stop()
    st = radio.state()
    print(f"stopped; dial was {st['vfo'] / 1e6:.6f} MHz in {st['band'] or 'no band'}"
          f"{' (' + st['segment'] + ')' if st['segment'] else ''}")
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
    # The CW skimmer's worker is a spawned child process (ohsradio/cwskim.py).
    # In a frozen build the child is this program run again; freeze_support
    # turns that run into the worker instead of a second Radio. A no-op
    # anywhere else.
    import multiprocessing
    multiprocessing.freeze_support()
    sys.exit(main())
