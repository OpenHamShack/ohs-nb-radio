#!/usr/bin/env python3
"""The half of tools/capture-and-test.sh and tools/store-post-install.sh
that runs ON the controller, as root: it alone reads the local-screen
token, so the token never leaves the box, never crosses ssh and is never
printed (anything this prints is scrubbed of it first, in case an error
body ever echoed a header back).

    box_api.py smoke   --prefix radio <smoke.json>
    box_api.py capture --prefix radio --decoder dmr|ais|adsb|dab --freq HZ --seconds S
                       [--rate S/s] [--antenna "Antenna A"] [--drop-sessions] [--keep]
                       --result FILE --log FILE
    box_api.py delete  --prefix radio <recording-id>

The API is the app's own, through the controller's proxy on the box:
http://127.0.0.1/<prefix>/api/..., with "Authorization: Bearer <token>"
from /etc/openhamshack/local-screen.token, as the local screen itself
calls it (the pattern of the hand-run /var/tmp/dmrcapture.py that took the
first DMR net, 28/10/2026). OHS_API_ROOT and OHS_TOKEN_FILE point it
elsewhere: the tests run it against a fake controller on a local socket
(with OHS_CAPTURE_SETTLE_S, the pause after tuning, set to 0).

`capture` is receive only - it records IQ, and refuses outright while the
radio is on the air - and puts the receiver back exactly as it found it:
the dial, mode, antenna and (with --rate) the sample rate are read first
and set again in a `finally`, which Ctrl-C (SIGINT, forwarded by ssh -tt),
a dropped connection (SIGHUP) and SIGTERM all reach, so an interrupted
capture still restores. While it restores, further signals are ignored: a
second Ctrl-C must not leave the radio half put back. It ends by checking
the state against what it saved and says which keys, if any, differ.

How each decoder's signal is tuned (SERVER-API.md): dmr tunes the dial,
FM; dab starts a DAB decoder session listing the block (no service), which
puts the receiver's centre on the block centre, as the real-file test
needs; ais and adsb open their map sessions as a client named
"capture-and-test" and keep them alive every 10 s, so the session itself
sets the centre and (ADS-B) the 6 MS/s rate, and gives the receiver back
when closed.
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
import time
import urllib.error
import urllib.request

API_ROOT = os.environ.get("OHS_API_ROOT", "http://127.0.0.1/")
TOKEN_FILE = os.environ.get("OHS_TOKEN_FILE", "/etc/openhamshack/local-screen.token")
CLIENT = "capture-and-test"
SAVED = ("vfo", "mode", "soapyAntenna")

_token = ""
_log = None


def scrub(text: str) -> str:
    return text.replace(_token, "<token>") if _token else text


def say(*parts) -> None:
    line = time.strftime("%H:%M:%S ") + scrub(" ".join(str(p) for p in parts))
    if _log:
        _log.write(line + "\n")
        _log.flush()
    try:
        print(line, flush=True)
    except OSError:          # the terminal went with the connection (SIGHUP): the log still has it
        pass


class ApiError(Exception):
    def __init__(self, method: str, path: str, status: int, body: dict):
        self.status, self.body = status, body
        super().__init__(f"{method} {path}: {status} {body.get('code') or ''} {body.get('error') or body}".strip())


class Api:
    def __init__(self, prefix: str):
        global _token
        _token = open(TOKEN_FILE).read().strip()
        self.base = API_ROOT.rstrip("/") + "/" + prefix.strip("/") + "/api/"

    def call(self, method: str, path: str, body: dict | None = None, timeout: float = 30) -> dict:
        req = urllib.request.Request(self.base + path, method=method,
                                     data=None if body is None else json.dumps(body).encode(),
                                     headers={"Authorization": "Bearer " + _token, "Content-Type": "application/json",
                                              "Accept": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                raw = r.read()
        except urllib.error.HTTPError as e:
            try:
                got = json.loads(e.read() or b"{}")
            except ValueError:
                got = {}
            raise ApiError(method, path, e.code, got if isinstance(got, dict) else {}) from None
        try:
            return json.loads(raw or b"{}")
        except ValueError:
            return {}


# ---------------------------------------------------------------- smoke

def smoke(api: Api, checks_file: str) -> int:
    """Each check is {"get": "api/...", "keys": [...]?}: the path must
    answer 200 (JSON), and an object answer must hold every key named.
    GET only: a smoke check must never change the radio."""
    checks = json.load(open(checks_file)).get("checks", [])
    bad = 0
    for c in checks:
        path = str(c["get"])
        rel = path[len("api/"):] if path.startswith("api/") else path
        try:
            got = api.call("GET", rel)
        except (ApiError, OSError) as e:
            say("FAIL", "GET", path, e)
            bad += 1
            continue
        missing = [k for k in c.get("keys", []) if not (isinstance(got, dict) and k in got)]
        if missing:
            say("FAIL", "GET", path, "has no", ", ".join(missing))
            bad += 1
        else:
            say("ok", "GET", path)
    say(f"smoke: {len(checks) - bad} of {len(checks)} passed")
    return 1 if bad else 0


# -------------------------------------------------------------- capture

class Interrupted(Exception):
    pass


def _interrupt(signum, _frame):
    raise Interrupted(signal.Signals(signum).name)


def _ignore_signals() -> None:
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, signal.SIG_IGN)


def _wait(cond, seconds: float, step: float = 0.5) -> bool:
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(step)
    return cond()


# An AIS or ADS-B session ended with DELETE still holds the receiver for
# its linger (60 s on ohs-box, 28/10/2026), and every tune or session POST
# in that window is 409 receiver_busy; so wait for rxOwner to clear, with
# room over the linger.
GIVE_BACK_S = float(os.environ.get("OHS_CAPTURE_GIVE_BACK_S", "90"))


def _given_back(api: "Api") -> bool:
    return _wait(lambda: not api.call("GET", "status").get("rxOwner"), GIVE_BACK_S)


def _restart(api: Api) -> None:
    """A sample rate takes effect when the radio restarts (state.py's
    restart=True): stop and start it, as Settings does."""
    api.call("POST", "stop", {})
    api.call("POST", "start", {})
    if not _wait(lambda: api.call("GET", "status").get("running"), 30):
        raise RuntimeError("the radio did not start again")


def capture(api: Api, a) -> int:
    for s in (signal.SIGINT, signal.SIGTERM, signal.SIGHUP):
        signal.signal(s, _interrupt)
    # Until the finally below overwrites it: whatever stops this before the
    # try (a refusal, an error reading the state) has changed nothing.
    with open(a.result, "w") as f:
        json.dump({"untouched": True}, f)
    result: dict = {"decoder": a.decoder, "freqHz": a.freq, "restored": False}
    st = api.call("GET", "state")
    status = api.call("GET", "status")
    if status.get("onAir"):
        say("refused: the radio is on the air; a capture only ever receives")
        return 3
    owner = status.get("rxOwner") or {}
    if owner and not a.drop_sessions:
        say(f"refused: the receiver is held by {owner.get('by')} ({owner.get('text') or owner.get('block')});",
            "pass --drop-sessions to stop it first")
        return 3
    if owner:
        # Stopped first, and the dial read only once it is given back: read
        # while a session holds the receiver, "before" would be the
        # session's tuning (162 MHz for AIS) and the restore would put the
        # receiver there rather than where the operator had it. This is the
        # one change made outside the restore below, with --drop-sessions as
        # its consent; what was stopped is not started again.
        by = owner.get("by")
        try:
            if by in ("ais", "adsb"):
                say("stopping", by, api.call("DELETE", f"{by}/session?all=1").get("state"))
            elif by == "dab" and owner.get("session"):
                api.call("DELETE", f"decoders/sessions/{owner['session']}")
                say("stopped the DAB session", owner["session"])
            else:
                say(f"refused: cannot stop what holds the receiver ({by})")
                return 3
        except ApiError as e:
            say("error stopping what holds the receiver:", e)
            return 1
        if not _given_back(api):
            say("the receiver was not given back within", GIVE_BACK_S, "s; nothing else was changed")
            return 1
        st = api.call("GET", "state")
        status = api.call("GET", "status")
    before = {k: st.get(k) for k in SAVED}
    if a.rate:
        before["sampleRate"] = st.get("sampleRate")
    running = bool(status.get("running"))
    say("before", json.dumps(before), "running" if running else "stopped")
    session = None
    rec_id = None
    recording = False
    keepalive_stop = threading.Event()
    rate_changed = False
    rc = 1
    try:
        if a.rate and int(a.rate) != int(st.get("sampleRate") or 0):
            api.call("POST", "set", {"changes": {"sampleRate": int(a.rate)}})
            rate_changed = True
            if running:
                _restart(api)
            say("rate", a.rate)
        if a.antenna:
            api.call("POST", "set", {"changes": {"soapyAntenna": a.antenna}})
        drop = {"dropSessions": True} if a.drop_sessions else {}
        if a.decoder == "dmr":
            api.call("POST", "set", {"changes": {"vfo": a.freq, "mode": "fm"}, **drop})
        elif a.decoder == "dab":
            got = api.call("POST", "decoders/sessions", {"decoder": "dab", "freqHz": a.freq, "params": {}, **drop})
            if not got.get("id"):
                raise RuntimeError("the DAB session started with no id")
            session = ("dab", got.get("id"))
        else:
            # Marked before the POST: one that timed out here may still have
            # started there, and closing a session we never joined is harmless.
            # A refusal (409 receiver_busy, rate_too_low...) raises, so nothing
            # is ever recorded on a session that did not start.
            session = (a.decoder, None)
            got = api.call("POST", f"{a.decoder}/session", {"client": CLIENT, **drop}, timeout=60)
            if got.get("state") != "running":
                raise RuntimeError(f"the {a.decoder} session is {got.get('state')}: {got.get('text') or got.get('why')}")
            say(a.decoder, "session", got.get("state"), "centre", got.get("centreHz"), "rate", got.get("rateHz"))

            def keepalive(kind=a.decoder):
                while not keepalive_stop.wait(10):
                    try:
                        api.call("POST", f"{kind}/session", {"client": CLIENT})
                    except (ApiError, OSError) as e:
                        say("keepalive:", e)
            threading.Thread(target=keepalive, daemon=True).start()
        # The device settles on the new centre before the first sample is kept.
        time.sleep(float(os.environ.get("OHS_CAPTURE_SETTLE_S", "3")))
        ds = api.call("GET", "state").get("deviceStatus") or {}
        result.update(centreHz=ds.get("rxLo"), rateHz=ds.get("fs"), antenna=ds.get("antenna"))
        say("tuned: centre", ds.get("rxLo"), "rate", ds.get("fs"), "antenna", ds.get("antenna"))
        api.call("POST", "recordings/start", {"kind": "iq"})
        recording = True
        say("recording", a.seconds, "s")
        end = time.monotonic() + a.seconds
        while time.monotonic() < end:
            time.sleep(min(1.0, max(0.0, end - time.monotonic())))
        if a.decoder in ("ais", "adsb"):
            # What the live decoder heard while this recorded: no message at
            # all means a quiet sky or sea, which the real-file test must
            # not be blamed for (capture-and-test.sh then calls it inconclusive).
            # Unknown (an older Radio, a failed read) is not "none": the test then runs.
            try:
                view = api.call("GET", f"{a.decoder}/session")
                result["messages"] = view.get("frames" if a.decoder == "ais" else "messages")
            except ApiError as e:
                say("could not read the session's message count:", e)
        stop = api.call("POST", "recordings/stop", {"kind": "iq"})
        recording = False
        rec = (stop.get("stopped") or [{}])[0]
        rec_id = rec.get("id")
        result.update(id=rec_id, bytes=rec.get("bytes"), seconds=rec.get("seconds"),
                      droppedSeconds=rec.get("droppedSeconds"))
        say("recorded", rec_id, rec.get("bytes"), "B", rec.get("seconds"), "s")
        if not rec_id:
            raise RuntimeError("the recording stopped with no id")
        rc = 0
    except Interrupted as e:
        say("interrupted by", e, "- putting the receiver back")
        rc = 130
    except (ApiError, OSError, RuntimeError) as e:
        say("error:", e)
        rc = 1
    finally:
        _ignore_signals()
        keepalive_stop.set()
        rc = _restore(api, a, before, running, session, recording, rate_changed, rec_id, rc, result)
        with open(a.result, "w") as f:
            json.dump(result, f)
    return rc


def _restore(api, a, before, running, session, recording, rate_changed, rec_id, rc, result) -> int:
    steps = []

    def step(what, fn):
        try:
            fn()
        except (ApiError, OSError, RuntimeError) as e:
            steps.append(f"{what}: {e}")
            say("restore:", what, "failed:", e)

    if recording:
        def stop_rec():
            got = api.call("POST", "recordings/stop", {"kind": "iq"})
            rid = ((got.get("stopped") or [{}])[0]).get("id")
            if rid and not a.keep:
                api.call("POST", "recordings/delete", {"id": rid})
                say("deleted the unfinished recording", rid)
        step("stop the recording", stop_rec)
    if session:
        kind, sid = session
        if kind == "dab":
            step("stop the DAB session", lambda: api.call("DELETE", f"decoders/sessions/{sid}"))
        else:
            def close():
                left = api.call("DELETE", f"{kind}/session?client={CLIENT}")
                # Nobody else has the map open: end it now rather than after
                # its linger, so the receiver is back before this returns.
                if not left.get("clients"):
                    api.call("DELETE", f"{kind}/session?all=1")
            step(f"close the {kind} session", close)

        def given_back():
            if not _given_back(api):
                raise RuntimeError("something still holds it")
        step("the receiver given back", given_back)
    if rate_changed:
        def rate_back():
            api.call("POST", "set", {"changes": {"sampleRate": before["sampleRate"]}})
            if running:
                _restart(api)
        step("the sample rate", rate_back)
    step("the dial, mode and antenna",
         lambda: api.call("POST", "set", {"changes": {k: before[k] for k in SAVED}}))
    try:
        now = api.call("GET", "state")
        differ = {k: (before[k], now.get(k)) for k in before if now.get(k) != before[k]}
    except (ApiError, OSError) as e:
        differ = {"state": str(e)}
    if differ or steps:
        say("NOT restored:", json.dumps(differ), "; ".join(steps))
        result["notRestored"] = differ
        return rc or 4
    result["restored"] = True
    result["before"] = before
    say("restored", json.dumps(before))
    return rc


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="box_api.py")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("smoke")
    s.add_argument("--prefix", required=True)
    s.add_argument("checks")
    c = sub.add_parser("capture")
    c.add_argument("--prefix", required=True)
    c.add_argument("--decoder", required=True, choices=["dmr", "ais", "adsb", "dab"])
    c.add_argument("--freq", required=True, type=int)
    c.add_argument("--seconds", required=True, type=float)
    c.add_argument("--rate", type=int)
    c.add_argument("--antenna")
    c.add_argument("--drop-sessions", action="store_true")
    c.add_argument("--keep", action="store_true")
    c.add_argument("--result", required=True)
    c.add_argument("--log", required=True)
    d = sub.add_parser("delete")
    d.add_argument("--prefix", required=True)
    d.add_argument("id")
    a = p.parse_args(argv)
    global _log
    try:
        api = Api(a.prefix)
    except OSError as e:
        print(f"box_api: cannot read the local-screen token ({e.strerror})", file=sys.stderr)
        return 2
    if a.cmd == "smoke":
        return smoke(api, a.checks)
    if a.cmd == "delete":
        try:
            api.call("POST", "recordings/delete", {"id": a.id})
        except (ApiError, OSError) as e:
            say("delete failed:", e)
            return 1
        say("deleted", a.id, "from the box")
        return 0
    _log = open(a.log, "a")
    try:
        return capture(api, a)
    except Interrupted:
        say("interrupted before anything was changed")
        return 130
    except (ApiError, OSError) as e:
        say("error before anything was changed:", e)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
