"""A fake controller for the tools that talk to the box's Radio API through
the local-screen token (tools/box_api.py, used by capture-and-test.sh and
store-post-install.sh): an HTTP server on a local socket answering the
few routes those tools use, as SERVER-API.md describes them, and keeping
a list of every call. It refuses any request without the right Bearer
token, so a test also proves the token was sent.

Not the app: the receiver holding (rxOwner), the AIS/ADS-B lease and the
recordings are modelled only as far as the tools see them.
"""
from __future__ import annotations

import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

TOKEN = "s3cret-local-screen-token-do-not-print"


class FakeRadio:
    def __init__(self, recdir: Path, prefix: str = "radio"):
        self.recdir = recdir
        self.prefix = prefix
        self.lock = threading.Lock()
        self.calls: list[tuple[str, str, dict]] = []
        self.st = {"vfo": 145500000, "mode": "usb", "soapyAntenna": "Antenna B", "sampleRate": 2400000}
        self.running = True
        self.on_air = False
        self.owner: dict = {}
        self.prior: dict = {}
        self.clients: set[str] = set()
        self.recording: str | None = None
        self.n = 0
        self.fail = {}            # "recordings/start" or "POST ais/session" -> (status, code): refuse it
        self.linger_s = 0.0       # an ended AIS/ADS-B session holds the receiver this long, as the app's does
        self.release_at = None
        self.recorded_while_held = False
        self.extra = {}           # GET path -> JSON answered (smoke checks)
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def root(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}/"

    def start(self) -> "FakeRadio":
        self.thread.start()
        return self

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()

    def paths(self, method: str | None = None) -> list[str]:
        return [p for m, p, _ in self.calls if method in (None, m)]

    # ------------------------------------------------------------ state

    def device(self) -> dict:
        if self.owner.get("by") == "adsb":
            return {"rxLo": 1090000000.0, "fs": 6000000.0, "antenna": self.st["soapyAntenna"]}
        centre = self.owner.get("freqHz") or self.st["vfo"] + 100000
        return {"rxLo": float(centre), "fs": float(self.st["sampleRate"]), "antenna": self.st["soapyAntenna"]}

    def _hold(self, by: str, freq: int, session: str) -> None:
        self.prior = {"vfo": self.st["vfo"], "mode": self.st["mode"]}
        self.owner = {"by": by, "session": session, "freqHz": freq, "text": f"held by {by}", "prior": dict(self.prior)}
        self.release_at = None
        self.st["vfo"] = freq

    def _end_session(self) -> None:
        """What the app does when its last client goes: hold on for the
        linger, then give the receiver back."""
        self.clients.clear()
        if self.linger_s:
            self.release_at = self.release_at or time.monotonic() + self.linger_s
        else:
            self._release()

    def _release(self) -> None:
        self.release_at = None
        if self.owner:
            self.st.update(self.prior)
        self.owner, self.prior = {}, {}
        self.clients.clear()

    def _session_view(self, kind: str) -> dict:
        held = self.owner.get("by") == kind
        return {"state": "running" if held else "idle", "clients": len(self.clients) if held else 0,
                "centreHz": float(self.owner.get("freqHz") or 0), "rateHz": self.device()["fs"]}

    # ---------------------------------------------------------- routes

    def route(self, method: str, path: str, q: dict, body: dict) -> tuple[int, dict]:
        if self.release_at and time.monotonic() >= self.release_at:
            self._release()
        for key, (status, code) in self.fail.items():
            if key in (path, f"{method} {path}"):
                return status, {"error": f"refused by the test ({code})", "code": code}
        if method == "GET" and path in self.extra:
            return 200, self.extra[path]
        if method == "GET" and path == "state":
            return 200, {**self.st, "deviceStatus": self.device(), "rxOwner": self.owner}
        if method == "GET" and path == "status":
            return 200, {"running": self.running, "onAir": self.on_air, "rxOwner": self.owner, "app": "radio"}
        if method == "POST" and path == "set":
            changes = body.get("changes", body)
            if self.owner and ({"vfo", "mode"} & set(changes)):
                return 409, {"error": "The receiver is busy", "code": "receiver_busy"}
            self.st.update(changes)
            return 200, {"changed": changes}
        if method == "POST" and path in ("stop", "start"):
            self.running = path == "start"
            return 200, {"running": self.running}
        if method == "POST" and path == "recordings/start":
            if self.recording:
                return 409, {"error": "already", "code": "already_recording"}
            self.n += 1
            self.recorded_while_held = self.recorded_while_held or bool(self.release_at)
            self.recording = f"openhamshack-radio-2026102{self.n}-{self.st['vfo']}"
            return 200, {"active": [{"kind": "iq", "id": self.recording}]}
        if method == "POST" and path == "recordings/stop":
            if not self.recording:
                return 200, {"stopped": []}
            rid, self.recording = self.recording, None
            data = bytes(range(256)) * 64
            (self.recdir / f"{rid}.sigmf-data").write_bytes(data)
            d = self.device()
            (self.recdir / f"{rid}.sigmf-meta").write_text(json.dumps({
                "global": {"core:datatype": "ci16_le", "core:sample_rate": d["fs"]},
                "captures": [{"core:sample_start": 0, "core:frequency": d["rxLo"]}]}))
            return 200, {"stopped": [{"id": rid, "kind": "iq", "bytes": len(data), "seconds": 1.0}]}
        if method == "POST" and path == "recordings/delete":
            for f in self.recdir.glob(f"{body['id']}.*"):
                f.unlink()
            return 200, {"deleted": body["id"]}
        for kind, freq in (("ais", 162000000), ("adsb", 1090000000)):
            if path != f"{kind}/session":
                continue
            if method == "POST":
                if self.owner and (self.owner.get("by") != kind or self.release_at):
                    return 409, {"error": "The receiver is busy", "code": "receiver_busy"}
                if not self.owner:
                    self._hold(kind, freq, kind)
                self.clients.add(body["client"])
                return 200, self._session_view(kind)
            if method == "DELETE":
                if q.get("all") == ["1"]:
                    if self.owner.get("by") == kind:
                        self._end_session()
                else:
                    self.clients.discard(q.get("client", [""])[0])
                    if self.owner.get("by") == kind and not self.clients:
                        self._end_session()
                return 200, self._session_view(kind)
        if method == "POST" and path == "decoders/sessions" and body.get("decoder") == "dab":
            if self.owner:
                return 409, {"error": "The receiver is busy", "code": "receiver_busy"}
            self._hold("dab", int(body["freqHz"]), "ds_dab1")
            return 201, {"id": "ds_dab1", "decoder": "dab"}
        if method == "DELETE" and path.startswith("decoders/sessions/"):
            if self.owner.get("session") == path.rsplit("/", 1)[1]:
                self._release()
                return 200, {"stopped": True}
            return 404, {"error": "no such session", "code": "unknown_session"}
        return 404, {"error": "not found", "code": "not_found"}

    def _handler(self):
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _do(self, method):
                u = urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}") if n else {}
                base = f"/{fake.prefix}/api/"
                if self.headers.get("Authorization") != f"Bearer {TOKEN}":
                    status, out = 401, {"error": "sign in", "code": "unauthorised"}
                elif not u.path.startswith(base):
                    status, out = 404, {"error": "not found", "code": "not_found"}
                else:
                    path = u.path[len(base):]
                    with fake.lock:
                        fake.calls.append((method, path, body))
                        status, out = fake.route(method, path, parse_qs(u.query), body)
                raw = json.dumps(out).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def do_GET(self):
                self._do("GET")

            def do_POST(self):
                self._do("POST")

            def do_DELETE(self):
                self._do("DELETE")

        return H


def token_file(folder: Path) -> Path:
    p = folder / "local-screen.token"
    p.write_text(TOKEN + "\n")
    os.chmod(p, 0o600)
    return p
