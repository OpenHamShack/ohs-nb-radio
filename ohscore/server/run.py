"""`--server`: run one app's engine headless behind the API.

What differs from the desktop: no window, no sound card (StreamAudio),
the station's store on the data volume (SHACK_STATION_DB), and - on an
OpenHamShack controller, where the edition puts DOCK360_SHACK_URL and
DOCK360_SHACK_TOKEN in the environment - the broker lends the radio and
the shared store syncs with the controller under this app's own token
(as the QO-100 WB store app does: "one code path, and a platform update
never stops an app logging", SYNC.md section 8).

Without those variables it still runs, for a developer: no broker, no
sync. Without DOCK360_SHACK_PROXY_SECRET every request is refused
(401 proxy_required): nobody can reach a transmitter through a server
that cannot tell who is asking. A developer sets the secret and sends it
in the header, as the proxy would.
"""
from __future__ import annotations

import logging
import os
import signal
import threading
import time

from ..i18n.text import _
from . import shack
from .app import AppInfo, Server
from .audio import StreamAudio

log = logging.getLogger("ohscore.server")
SYNC_EVERY_S = 30.0


def platform_broker():
    url, token = os.environ.get(shack.SHACK_URL_ENV, ""), os.environ.get(shack.SHACK_TOKEN_ENV, "")
    if not url or not token:
        return None
    return shack.BrokerClient(shack.shack_http(url, token))


def pair_store(radio) -> str:
    """Keep the shared store paired with the controller under the app
    token; '' or why not (retried by the caller)."""
    url, token = os.environ.get(shack.SHACK_URL_ENV, ""), os.environ.get(shack.SHACK_TOKEN_ENV, "")
    if not url or not token:
        return ""
    st = radio.station
    base = url.rstrip("/")
    base = base[: -len("/api/shack/v1")] if base.endswith("/api/shack/v1") else base
    base += "/"
    have = st.pairing_info() or {}
    if have.get("token") != token or have.get("baseUrl") != base:
        try:
            code, index = shack.shack_http(url, token)("GET", "/")
        except OSError as e:
            return _("The controller's services did not answer ({why})").format(why=e)
        if code != 200 or not index.get("controllerId"):
            return _("The controller's services answered HTTP {code}").format(code=code)
        st._write_pairing({"controllerId": index["controllerId"], "baseUrl": base, "token": token,
                           "deviceId": "", "user": "", "maxLevel": "control", "name": "",
                           "pairedAt": st.store.now_iso()})
    st.sync.start()
    return ""


def main(radio_factory, info: AppInfo, host: str = "0.0.0.0", port: int | None = None) -> int:
    port = port if port is not None else int(os.environ.get("SHACK_PORT", "8080"))
    audio = StreamAudio()
    radio = radio_factory(audio)
    srv = Server(radio, info, audio, broker=platform_broker())
    if not srv.secret:
        log.warning("%s is not set: every request will be refused", shack.PROXY_SECRET_ENV)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_a: stop.set())
    signal.signal(signal.SIGINT, lambda *_a: stop.set())
    srv.serve(host, port)
    print(f"{info.name} {info.version} serving on {host}:{port}", flush=True)
    why = srv.start_radio()
    if why:
        print(f"radio not started: {why}", flush=True)
    next_pair = 0.0
    retry_at = time.monotonic() + 10.0
    try:
        while not stop.wait(1.0):
            now = time.monotonic()
            if now >= next_pair:
                next_pair = now + SYNC_EVERY_S
                err = pair_store(radio)
                if err:
                    log.info("%s", err)
            # A radio that failed or never opened is tried again every
            # 10 s, unless a person stopped it or it was handed to another
            # app (Server.wanted). While the broker loop is re-claiming a
            # claim the broker lost (Server.reclaim) it owns the retries:
            # a plain claim here would only meet 503 broker_restarting.
            if srv.wanted and srv.reclaim is None and not radio.state().get("running") and now >= retry_at:
                retry_at = now + 10.0
                srv.start_radio()
    finally:
        srv.shutdown()
    return 0
