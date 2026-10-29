"""Client presence (CLIENT-UI-PLAN 7.2-7.4): which of this app's
client-scoped holds belong to which client, and hearing from the platform
when that client has gone, so what it held is ended at once.

    watch = PresenceWatch("shack-radio", shack_http(url, token), events_opener(url, token),
                          on_gone=srv.client_gone, on_arrive=srv.client_arrived)
    watch.run(stop_ev)        # its own thread: the services map, the event stream, reconnects
    watch.tick()              # once a second: clients a reconcile could not find
    holds = Holds()           # who made each hold, and each client's streams

**The platform is the server, the app a subscriber.** The controller keeps
one lease per client (renewed every 10 s, gone 30 s after the last) and
says so on `GET api/shack/v1/presence/events`: `arrived`, `moved` and
`gone{why: goodbye|expired}`. The app reads it under its own app token
(the broker's, SERVICES.md 6) and only when the services map lists
`"presence": 1`. Without that (an older platform, a desktop form, a
developer's run with no token) nothing here runs and every hold keeps its
own lease as before: the overwhelming common case, so it is one GET at
start-up and a look every SERVICES_RECHECK_S after.

**Subscribe first, then list.** Events do not replay who is already
there, so the stream is opened and only then `GET presence` read: a
client arriving between the two is in one or the other, never neither.
The list is also the **reconcile**. The platform keeps presence in
memory, so a controller restart sends no `gone` at all - everyone simply
vanishes from the next list - and a stream that dropped may have missed a
`gone`. Every connect, and every RECONCILE_S while connected, a client
this app has seen present that the list no longer has is given one lease
(LEASE_S) to come back - which is exactly what a client that is still
there does within one renewal after a restart - and is gone, `expired`,
if it does not. Freeing everything on the first empty list would stop
every DAB station in the house on each platform update.

**Only clients with presence are judged by it** (CLIENT-UI-PLAN 12, "an
old client with no presence looks gone"): a hold whose client id was
never seen in presence, or that was made with no id at all, is never
ended here. It keeps its own lease (AIS's session) or lasts until someone
stops it, as before. `gone` and the reconcile name only clients the
platform has seen, so this holds by construction; `Holds` keeps a client
that gave no id as None, which no `gone` can remove.

**Transmit is never touched** (7.4): nothing here keys, unkeys, or
frees a transmitter; the app's own on_gone decides what a client's
leaving ends, and refuses while on the air.
"""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.request

log = logging.getLogger("ohscore.server.presence")

SERVICE = "presence"
# The contract's lease (7.2): a client renews every 10 s and is gone 30 s
# after its last renewal. Used only for the reconcile's grace; the
# platform's own `expired` is what ends a client normally.
LEASE_S = 30.0
RECONCILE_S = 60.0
# A stream that ended or would not open: try again after BACKOFF_FIRST_S,
# doubling to BACKOFF_MAX_S, as the broker's re-claim does.
BACKOFF_FIRST_S = 1.0
BACKOFF_MAX_S = 30.0
# No presence in the services map: look again this often (a platform
# update may add it without restarting the app).
SERVICES_RECHECK_S = 300.0
# The platform sends a keepalive comment every 15 s (dock360
# services events.KEEPALIVE_S on the platform): three missed is a dead connection.
READ_TIMEOUT_S = 45.0


def events_opener(base: str, token: str, timeout: float = READ_TIMEOUT_S):
    """A function opening `presence/events` under the app token, returning
    an iterable of its lines (bytes) and a close(); OSError when the
    controller cannot be reached or refuses. The same Bearer header as
    shack.shack_http, which cannot stream."""
    def open_events():
        req = urllib.request.Request(base.rstrip("/") + "/presence/events", method="GET",
                                     headers={"Authorization": f"Bearer {token}", "Accept": "text/event-stream"})
        try:
            res = urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            raise OSError(f"presence/events answered HTTP {exc.code}") from None
        return res
    return open_events


def sse_events(lines):
    """(event, data) for each event in a text/event-stream, data parsed as
    JSON ({} when it is not an object). Comments (": keepalive") and
    fields other than event and data are skipped, as the standard says."""
    event, data = "", []
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        line = line.rstrip("\r\n")
        if not line:
            if data:
                try:
                    parsed = json.loads("\n".join(data))
                except ValueError:
                    parsed = {}
                yield event or "message", parsed if isinstance(parsed, dict) else {}
            event, data = "", []
            continue
        if line.startswith(":"):
            continue
        field, _sep, value = line.partition(":")
        value = value[1:] if value.startswith(" ") else value
        if field == "event":
            event = value
        elif field == "data":
            data.append(value)


class Holds:
    """Who made each client-scoped hold, and each client's open streams.

    A hold is a key - ("held", <session id>) for a decoder session holding
    the receiver (DAB), ("listen", <session id>) for a session listened to
    - and the set of clients that asked for it. None stands for a client
    that gave no id (an older client): no presence can remove it, so the
    hold outlives every client that does have presence. AIS and ADS-B keep
    their own client lists (ohsradio/ais.py), which already say this.

    A stream is registered for as long as it is open, with an Event its
    handler watches: setting it ends the stream on its own thread."""

    def __init__(self):
        self.lock = threading.Lock()
        self.holders: dict[tuple, set] = {}
        self.streams: dict[int, tuple[str | None, threading.Event]] = {}
        self.ended = threading.Condition(self.lock)
        self._n = 0

    def add(self, key: tuple, client: str | None) -> None:
        with self.lock:
            self.holders.setdefault(key, set()).add(client or None)

    def drop(self, key: tuple, client: str | None) -> None:
        """`client` no longer wants `key` (it said so: listen false)."""
        with self.lock:
            who = self.holders.get(key)
            if who is not None:
                who.discard(client or None)
                if not who:
                    del self.holders[key]

    def forget(self, key: tuple) -> None:
        """`key` has ended, whoever had it."""
        with self.lock:
            self.holders.pop(key, None)

    def leave(self, client: str) -> list[tuple]:
        """`client` has gone: it is taken off every hold, and the holds no
        client is left on are returned for the caller to end."""
        out = []
        with self.lock:
            for key, who in list(self.holders.items()):
                if client in who:
                    who.discard(client)
                    if not who:
                        del self.holders[key]
                        out.append(key)
        return out

    def of(self, client: str) -> list[tuple]:
        with self.lock:
            return [k for k, who in self.holders.items() if client in who]

    def clients(self) -> set:
        with self.lock:
            return {c for who in self.holders.values() for c in who if c} | \
                {c for c, _ev in self.streams.values() if c}

    # -- streams -------------------------------------------------------------
    def open_stream(self, client: str | None) -> tuple[int, threading.Event]:
        with self.lock:
            self._n += 1
            ev = threading.Event()
            self.streams[self._n] = (client or None, ev)
            return self._n, ev

    def close_stream(self, token: int) -> None:
        """The stream's handler, as it ends (in a finally)."""
        with self.lock:
            self.streams.pop(token, None)
            self.ended.notify_all()

    def end_streams(self, client: str, wait_s: float = 3.0) -> int:
        """Tell `client`'s streams to end, and wait up to `wait_s` for their
        handlers to have finished (so the listener and spectrum counts no
        longer include them). The number told."""
        with self.lock:
            mine = [t for t, (c, _ev) in self.streams.items() if c == client]
            for t in mine:
                self.streams[t][1].set()
            end = time.monotonic() + wait_s
            while any(t in self.streams for t in mine):
                left = end - time.monotonic()
                if left <= 0:
                    break
                self.ended.wait(left)
        return len(mine)


class PresenceWatch:
    """The platform's presence feed, for one app (module docstring).

    `request` is shack.shack_http's call ((method, path) -> (status, json)
    under the app token); `open_events` opens the event stream (an
    iterable of lines with close()); `on_gone(client, why)` is called on
    this thread when a client the platform had seen is gone, and
    `on_arrive(client)` when a client arrives in, or moves to, this app."""

    def __init__(self, app_id: str, request, open_events, on_gone, on_arrive=None, clock=time.monotonic):
        self.app_id = app_id
        self.request = request
        self.open_events = open_events
        self.on_gone = on_gone
        self.on_arrive = on_arrive
        self.clock = clock
        self.lock = threading.Lock()
        # client -> its last renewal ({client, app, screen, holds}), any app
        self.present: dict[str, dict] = {}
        # Every client seen present since this app started: the only ones
        # presence may end anything for.
        self.seen: set[str] = set()
        # Seen, missing from the last list: client -> when it counts as gone.
        self.missing: dict[str, float] = {}
        self.available: bool | None = None      # the services map lists presence
        self.connected = False
        self.last_reconcile = 0.0
        self._stream = None

    # -- what the app asks ---------------------------------------------------
    def governs(self, client: str | None) -> bool:
        """Whether `client` has presence, so presence decides its holds."""
        with self.lock:
            return bool(client) and client in self.seen

    def renews(self, client: str, hold: str) -> bool:
        """Whether `client` is present in this app with `hold` in its holds:
        a present client with "ais" in holds is renewing its AIS lease
        (7.2), so the app need not wait for it to renew AIS separately."""
        with self.lock:
            p = self.present.get(client)
            return p is not None and p.get("app") == self.app_id and hold in (p.get("holds") or [])

    def view(self) -> dict:
        with self.lock:
            here = sorted(c for c, p in self.present.items() if p.get("app") == self.app_id)
            return {"service": bool(self.available), "connected": self.connected, "clients": here}

    # -- the feed ------------------------------------------------------------
    def check_service(self) -> bool:
        """Whether the controller lists presence (SERVICES.md 6)."""
        try:
            status, index = self.request("GET", "/")
        except OSError as e:
            log.info("presence: the controller's services did not answer (%s)", e)
            return False
        services = index.get("services") if status == 200 else None
        ok = isinstance(services, dict) and services.get(SERVICE) == 1
        if ok != self.available:
            log.info("presence: %s", "the controller has it" if ok else "the controller does not have it")
        self.available = ok
        return ok

    def run(self, stop_ev: threading.Event) -> None:
        delay = BACKOFF_FIRST_S
        while not stop_ev.is_set():
            if not self.check_service():
                stop_ev.wait(SERVICES_RECHECK_S)
                continue
            began = self.clock()
            try:
                self.follow(stop_ev)
            except OSError as e:
                log.info("presence: the event stream ended (%s)", e)
            except Exception:  # noqa: BLE001  the watch must outlive one bad pass
                # stop() closes the stream under the reading thread, and
                # http.client then fails with whatever it was holding (an
                # AttributeError on beta.17's shutdown): not worth a traceback.
                if not stop_ev.is_set():
                    log.exception("presence")
            self.connected = False
            if self.clock() - began > BACKOFF_MAX_S:
                delay = BACKOFF_FIRST_S          # it ran a while: a fresh failure, not a loop
            stop_ev.wait(delay)
            delay = min(delay * 2, BACKOFF_MAX_S)

    def stop(self) -> None:
        s = self._stream
        if s is not None:
            try:
                s.close()
            except Exception:  # noqa: BLE001
                pass

    def follow(self, stop_ev: threading.Event) -> None:
        """One connection: open the stream, then list and reconcile, then
        each event until the stream ends. OSError when it cannot."""
        stream = self.open_events()
        self._stream = stream
        try:
            self.connected = True
            self.reconcile()
            for event, data in sse_events(stream):
                if stop_ev.is_set():
                    return
                self.handle(event, data)
        finally:
            self._stream = None
            try:
                stream.close()
            except Exception:  # noqa: BLE001
                pass

    def handle(self, event: str, data: dict) -> None:
        client = data.get("client")
        if not isinstance(client, str) or not client:
            return
        if event in ("arrived", "moved"):
            with self.lock:
                was = self.present.get(client)
                self.present[client] = data
                self.seen.add(client)
                self.missing.pop(client, None)
            if data.get("app") == self.app_id and (was is None or was.get("app") != self.app_id) \
                    and self.on_arrive is not None:
                self.on_arrive(client)
        elif event == "gone":
            self._gone(client, str(data.get("why") or "expired"))

    def _gone(self, client: str, why: str) -> None:
        with self.lock:
            self.present.pop(client, None)
            self.missing.pop(client, None)
            known = client in self.seen
        if known:
            log.info("presence: %s gone (%s)", client, why)
            self.on_gone(client, why)

    def reconcile(self) -> None:
        """`GET presence`: who is here now. Anyone seen who is not is given
        one lease to come back (module docstring)."""
        status, answer = self.request("GET", "/presence")
        if status != 200 or not isinstance(answer.get("clients"), list):
            raise OSError(f"presence answered HTTP {status}")
        now = self.clock()
        listed = {}
        for c in answer["clients"]:
            if isinstance(c, dict) and isinstance(c.get("client"), str) and c["client"]:
                listed[c["client"]] = c
        arrived = []
        with self.lock:
            self.last_reconcile = now
            for client, c in listed.items():
                was = self.present.get(client)
                self.present[client] = c
                self.seen.add(client)
                self.missing.pop(client, None)
                if c.get("app") == self.app_id and (was is None or was.get("app") != self.app_id):
                    arrived.append(client)
            for client in self.seen - set(listed):
                self.present.pop(client, None)
                self.missing.setdefault(client, now + LEASE_S)
        if self.on_arrive is not None:
            for client in arrived:
                self.on_arrive(client)

    def tick(self) -> None:
        """Once a second: clients a reconcile missed that have not come back
        within their lease are gone; and the periodic reconcile."""
        now = self.clock()
        with self.lock:
            due = [c for c, at in self.missing.items() if at <= now]
            again = self.connected and now - self.last_reconcile >= RECONCILE_S
        for client in due:
            self._gone(client, "expired")
        if again:
            try:
                self.reconcile()
            except OSError as e:
                log.info("presence: reconcile failed (%s)", e)
