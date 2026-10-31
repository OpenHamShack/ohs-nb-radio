#!/usr/bin/env python3
"""Serve QO-100 NB's ui/2 screens from this checkout to a renderer, with no
box and no radio: the way to look at NB's screens in the Android or Swift
renderer while they are being built (SCREENS.md §16 step 6).

    tools/screens-dev.py [--host 127.0.0.1] [--port 8791] [--level control]
                         [--transmit none] [--token shackdev_fixture] [--pidfile F]

Then, for the Android renderer on an emulator (`adb reverse tcp:8791
tcp:8791` first):

    adb shell am start -n com.openhamshack.remote/.ScreensActivity \\
        --es base http://127.0.0.1:8791/ --es token shackdev_fixture [--es form tv]

What runs, all in this process:
- NB's engine on the **simulator** (device `sim`, realtime, with simulated
  signals) and NB's store server on a loopback port of its own. There is
  no broker, so nothing here can claim or key a radio; the level defaults
  to Control, under which NB refuses every key-up anyway.
- In front of it, the part of an OpenHamShack controller a renderer needs,
  shaped like the fixture server's (openhamshack tools/screens-fixture):
  `.well-known/openhamshack` with `services.ui: 2` (no token), the
  platform launcher built from NB's own descriptor and its status poll, a
  device token (`Authorization: Bearer <token>`) on everything else, and
  `shack-qo100nb/...` passed to NB with the identity headers the
  controller's proxy adds (the proxy secret, user, `--level`,
  `--transmit`, device, `X-Forwarded-Prefix`). Each request is passed on
  as raw bytes after its head, so the live socket, spectrum/1 and the
  receive audio stream through unchanged.

Stop it by its PID (`--pidfile`), never by name: every app here is
`python3 -m something`.
"""
from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import signal
import socket
import socketserver
import sys
import tempfile
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

APP = "shack-qo100nb"
# The refusals this stand-in controller sends. English only and outside the
# catalogs on purpose: they are the controller's words, not NB's, and this
# tool is never shipped (a renderer shows its own words for both codes).
CONTROLLER_WORDS = {"credentials_required": "Sign in with the device token",
                    "not_found": "There is nothing at {path}"}


def read_head(sock: socket.socket) -> tuple[bytes, bytes]:
    """The request head (up to the blank line) and whatever followed it."""
    buf = b""
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(65536)
        if not chunk:
            raise ConnectionError("closed before a request")
        buf += chunk
        if len(buf) > 1 << 16:
            raise ConnectionError("request head too large")
    head, rest = buf.split(b"\r\n\r\n", 1)
    return head, rest


def splice(a: socket.socket, b: socket.socket) -> None:
    """Copy both ways until either side closes."""
    def pump(src, dst):
        try:
            while True:
                d = src.recv(65536)
                if not d:
                    break
                dst.sendall(d)
        except OSError:
            pass
        for s in (src, dst):
            try:
                s.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
    t = threading.Thread(target=pump, args=(b, a), daemon=True)
    t.start()
    pump(a, b)
    t.join(timeout=5)


class Front:
    def __init__(self, nb_port: int, secret: str, args):
        self.nb_port, self.secret, self.args = nb_port, secret, args
        self.controller = "d0c5c2ee-0000-4000-8000-5c4ee05dev00"

    def identity(self, form: str | None, client: str | None) -> dict:
        from ohscore.server import shack
        h = {shack.SHACK_SECRET_HEADER: self.secret, "X-OpenHamShack-User": "screens-dev",
             "X-OpenHamShack-Level": self.args.level, "X-OpenHamShack-Transmit": self.args.transmit,
             "X-OpenHamShack-Device": "dev_SCREENS", "X-OpenHamShack-Auth": "device",
             "X-Forwarded-Prefix": f"/{APP}"}
        if form:
            h["X-OpenHamShack-Form"] = form
        if client:
            h["X-OpenHamShack-Client"] = client
        return h

    def nb_get(self, path: str) -> dict:
        import http.client
        c = http.client.HTTPConnection("127.0.0.1", self.nb_port, timeout=10)
        c.request("GET", path, headers=self.identity(None, None))
        r = c.getresponse()
        body = json.loads(r.read() or b"{}")
        c.close()
        return body

    def well_known(self) -> dict:
        version = (ROOT / "ohsnb" / "VERSION").read_text().strip()
        return {"openhamshack": 1, "contract": "1.1", "controllerId": self.controller, "name": "NB-DEV",
                "version": "screens-dev", "time": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "station": {"callsign": "N0CALL", "locator": "IO75", "country": "GB"},
                "auth": {"token": "api/shack/token", "pair": "api/shack/pair/start", "totp": "per-user",
                         "anonymousView": []},
                "services": {"base": "api/shack/v1/", "ui": 2},
                "apps": [{"id": APP, "kind": "qo100nb", "name": "QO-100 NB", "version": version,
                          "base": f"{APP}/", "running": True, "txCapable": True, "anonymousView": False}]}

    def launcher(self) -> dict:
        """The platform's launcher (SCREENS.md §1) for this one app, from its
        descriptor, as the platform will build it."""
        from ohscore import shacklibs
        lib = shacklibs.ui()
        d = self.nb_get("/ui/v2/app")
        tiles = [{"type": "tile", "id": f"{APP}/{e['id']}", "title": e["title"], "icon": e.get("icon"),
                  "status": None, "tone": "muted", "level": self.args.level,
                  "transmit": self.args.transmit if self.args.transmit != "none" else "none",
                  "action": {"do": "open", "app": APP, "screen": e["screen"]}} for e in d.get("entries", [])]
        doc = {"ui": "2.0", "screen": "shack/launcher", "title": "NB-DEV", "form": "tv", "level": "view",
               "backdrop": {"style": "glass"}, "poll": {"path": "api/shack/v1/ui/launcher/status", "everyS": 5},
               "root": {"type": "grid", "id": "tiles", "columns": "fit", "tileW": 188, "aspect": 1.778, "gap": "m",
                        "children": tiles}}
        doc["rev"] = lib.rev(doc)
        return doc

    def launcher_status(self) -> dict:
        st = self.nb_get("/ui/v2/status").get("entries", {})
        return {"ops": [{"op": "set", "id": f"{APP}/{k}", "v": v} for k, v in st.items()]}

    def answer(self, conn: socket.socket, status: int, body) -> None:
        raw = json.dumps(body).encode()
        reason = {200: "OK", 401: "Unauthorized", 404: "Not Found"}.get(status, "OK")
        conn.sendall(f"HTTP/1.1 {status} {reason}\r\nContent-Type: application/json\r\nContent-Length: {len(raw)}"
                     f"\r\nCache-Control: no-cache\r\nConnection: close\r\n\r\n".encode() + raw)

    def handle(self, conn: socket.socket) -> None:
        head, rest = read_head(conn)
        lines = head.decode("latin-1").split("\r\n")
        method, target, version = lines[0].split(" ", 2)
        headers = [ln.split(":", 1) for ln in lines[1:] if ":" in ln]
        hmap = {k.strip().lower(): v.strip() for k, v in headers}
        path = target.lstrip("/")
        if path.split("?")[0] == ".well-known/openhamshack":
            return self.answer(conn, 200, self.well_known())
        if hmap.get("authorization") != f"Bearer {self.args.token}":
            return self.answer(conn, 401, {"error": CONTROLLER_WORDS["credentials_required"], "code": "credentials_required"})
        p = path.split("?")[0]
        if p == "api/shack/v1/ui/launcher":
            return self.answer(conn, 200, self.launcher())
        if p == "api/shack/v1/ui/launcher/status":
            return self.answer(conn, 200, self.launcher_status())
        if p.startswith("api/shack/v1/"):
            return self.answer(conn, 200, {})     # presence and the rest: accepted, as the fixture does
        if not p.startswith(f"{APP}/"):
            return self.answer(conn, 404, {"error": CONTROLLER_WORDS["not_found"].format(path=p), "code": "not_found"})
        keep = [(k, v) for k, v in headers if k.strip().lower() not in (
            "authorization", "connection", "x-openhamshack-level", "x-openhamshack-transmit",
            "x-openhamshack-device", "x-openhamshack-user", "x-forwarded-prefix", "host")]
        upgrade = hmap.get("upgrade", "").lower() == "websocket"
        out = [f"{method} /{path[len(APP) + 1:]} {version}", "Host: 127.0.0.1"]
        out += [f"{k}:{v}" for k, v in keep]
        out += [f"{k}: {v}" for k, v in self.identity(None, None).items()]
        out.append("Connection: Upgrade" if upgrade else "Connection: close")
        nb = socket.create_connection(("127.0.0.1", self.nb_port), timeout=None)
        nb.sendall(("\r\n".join(out) + "\r\n\r\n").encode("latin-1") + rest)
        splice(conn, nb)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8791)
    ap.add_argument("--level", default="control", choices=("view", "control", "transmit"))
    ap.add_argument("--transmit", default="none", choices=("none", "digital", "full"))
    ap.add_argument("--token", default="shackdev_fixture")
    ap.add_argument("--pidfile")
    args = ap.parse_args()

    from ohscore.server.app import Server
    from ohscore.server.audio import StreamAudio
    from ohsnb import server as nb_server
    from ohsnb import state
    from ohsnb.radio import Radio

    work = Path(tempfile.mkdtemp(prefix="screens-dev-", dir=Path.home() / "build"))
    cfg = state.defaults(("setting", "control"))
    # The simulator, always: never a radio from here.
    cfg.update(device="sim", simRealtime=True, simSignals=True, audioBackend="null", callsign="N0CALL",
               licenceClass="full")
    audio = StreamAudio()
    radio = Radio(cfg, persist=False, data_dir=str(work), audio=audio)
    secret = secrets.token_hex(16)
    version = (ROOT / "ohsnb" / "VERSION").read_text().strip()
    srv = Server(radio, nb_server.info(version), audio, secret=secret, broker=None)
    nb_port = srv.serve("127.0.0.1", 0).server_address[1]
    why = srv.start_radio()
    if why:
        print(f"the simulator did not start: {why}", file=sys.stderr)
        return 1
    front = Front(nb_port, secret, args)

    class Handler(socketserver.BaseRequestHandler):
        def handle(self):
            try:
                front.handle(self.request)
            except (OSError, ConnectionError, ValueError):
                pass

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    socketserver.ThreadingTCPServer.daemon_threads = True
    tcp = socketserver.ThreadingTCPServer((args.host, args.port), Handler)
    if args.pidfile:
        Path(args.pidfile).write_text(str(os.getpid()))
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_a: stop.set())
    threading.Thread(target=tcp.serve_forever, daemon=True).start()
    print(f"NB screens on http://{args.host}:{args.port}/ (token {args.token}, level {args.level}, "
          f"transmit {args.transmit}); NB itself on 127.0.0.1:{nb_port}", flush=True)
    try:
        while not stop.wait(1.0):
            pass
    except KeyboardInterrupt:
        pass
    finally:
        tcp.shutdown()
        srv.shutdown()
        time.sleep(0.2)
        shutil.rmtree(work, ignore_errors=True)
        if args.pidfile:
            Path(args.pidfile).unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
