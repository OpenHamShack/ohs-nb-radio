"""Automatic diagnostics upload: the half with no window in it.

Brian's decision (12/10/2026): "fully automatic, with opt in". An operator
who switches it on (Settings › Station, off by default, with the consent
text beside the switch) has NB or Radio send its diagnostics bundle to
openhamshack.com by itself - once a day when anything new was logged, and
soon after a fault - and anyone can send one by hand from Help › Send
diagnostics… whether or not it is on. Each upload gets a short reference
code to quote: SHACK-7KQ4, never OHS- (the brand never uses those
initials, brand/README.md). The site deletes reports after 30 days; we
fetch them to the development machine (openhamshack-os tools/fetch-diag.sh, docs/DIAGNOSTICS.md).

Why upload at all, when Help › Save diagnostics… already makes a zip:
Ray's IC-9700 problems in October took a day each round trip, because the
zip was only made after Brian asked for it, and by then the run that went
wrong had rotated out of the log. A report sent minutes after the fault,
without anyone being asked, is the one that still holds it.

Decisions:

- **Consent is a record, not just a switch.** Sending needs the ui.json
  switch on *and* a consent stamp naming CONSENT_VERSION, which only the
  Settings dialog writes when the operator turns the switch on with the
  text in front of them. A config edited by hand, a remote client, or a
  later version that sends more (a new CONSENT_VERSION) all mean "ask
  again", never "send".
- **A client upload, not a server.** NB only ever makes one outgoing HTTPS
  POST (the family rule: no servers inside the desktop apps).
- **Never in the radio's way.** The bundle is built and sent on a thread
  with a timeout; nothing is sent while transmitting (put off, not
  dropped) or on a connection the system says is metered; a failure is a
  log line and a later retry, never a dialog.
- **Small and scrubbed.** gzip'd JSON, at most MAX_BYTES: the log is cut
  from the oldest end until it fits. Every text goes through diag's
  redaction (secret-looking keys, URL passwords, token shapes); the
  callsign and locator stay, as in the saved zip, and the consent text
  says so. No screenshot: a picture is the one thing in the zip a person
  should look at before it leaves.
- **A random install id, not a hardware one,** made on first use and kept
  beside the config: enough to tell one station's reports from another's
  and nothing that identifies the machine.
- **Limits:** a fault report waits SETTLE_S for the lines after the fault,
  then at most one per DEBOUNCE_S; the daily one is separate. A fault
  during the wait joins the waiting report rather than making another.
"""
from __future__ import annotations

import gzip
import json
import logging
import os
import re
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path

from . import diag

log = logging.getLogger("ohscore.diagupload")

URL = "https://openhamshack.com/api/diag/upload.php"
PRIVACY_URL = "https://openhamshack.com/privacy/"
SCHEMA = 1
# What the operator agreed to. Raise it when what is sent changes in a way
# the consent text has to say: every installation then asks again.
CONSENT_VERSION = 1
MAX_BYTES = 2_000_000
# Raw log text kept before compression is tried: plenty more than 2 MB of
# gzip'd log (text compresses about 8:1), so the cap is what cuts it.
LOG_RAW_MAX = 12_000_000
DEBOUNCE_S = 30 * 60.0
DAILY_S = 24 * 3600.0
SETTLE_S = 60.0
# The first daily report of a run: not in the first minutes (a start-up is
# when the operator is busiest, and a crash at start-up is a fault anyway).
FIRST_DAILY_S = 10 * 60.0
RETRY_S = 15 * 60.0
RETRY_MAX_S = 6 * 3600.0
TIMEOUT_S = 30.0
RESPONSE_MAX = 4096
CODE = re.compile(r"^SHACK-[0-9A-HJKMNP-TV-Z]{4,8}$")
INSTALL = re.compile(r"^[0-9a-f]{32}$")
FAULTS = frozenset(diag.TRIGGERS) - {"ic9700-diagnostic", "ic9700-level-set"}


class UploadError(Exception):
    """An upload that did not happen; str() is a sentence for the log and
    for Help › Send diagnostics…."""


# ------------------------------------------------------------------ the triggers
class Watcher(logging.Handler):
    """Hears diag.notable() and uncaught exceptions (ohscore.crash) from any
    thread and keeps them until the uploader takes them."""

    def __init__(self, clock=time.time):
        super().__init__(logging.WARNING)
        self.clock = clock
        self.lock_ = threading.Lock()
        self.seen: deque = deque(maxlen=100)

    def emit(self, record: logging.LogRecord) -> None:
        trigger = getattr(record, "ohs_trigger", None) or ("crash" if record.name == "ohscore.crash" else "")
        if trigger:
            with self.lock_:
                self.seen.append((trigger, record.getMessage()[:300], self.clock()))

    def take(self) -> list[tuple[str, str, float]]:
        with self.lock_:
            out = list(self.seen)
            self.seen.clear()
        return out

    def install(self) -> "Watcher":
        for name in (diag.NOTABLE_LOGGER, "ohscore.crash"):
            logging.getLogger(name).addHandler(self)
        return self

    def remove(self) -> None:
        for name in (diag.NOTABLE_LOGGER, "ohscore.crash"):
            logging.getLogger(name).removeHandler(self)


# ------------------------------------------------------------------ what is kept
class State:
    """diag-upload.json beside the config: the install id, when reports
    went, the codes they got, what is waiting. Lost or unreadable means a
    fresh start (a new id), never a failure."""

    HISTORY = 10

    def __init__(self, path: Path):
        self.path = Path(path)
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            self.d = {}

    def __getitem__(self, k):
        return self.d.get(k)

    def get(self, k, default=None):
        return self.d.get(k, default)

    def set(self, **kv) -> None:
        self.d.update(kv)
        self.save()

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_name(self.path.name + ".tmp")
            tmp.write_text(json.dumps(self.d, indent=1, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as e:
            log.info("diagnostics upload: could not save %s: %s", self.path, e)

    def install_id(self) -> str:
        v = self.d.get("install")
        if not (isinstance(v, str) and INSTALL.match(v)):
            # secrets, not uuid1 or anything read from the machine: the id
            # must say nothing about the computer it came from.
            v = secrets.token_hex(16)
            self.set(install=v)
        return v

    def history(self) -> list[dict]:
        h = self.d.get("history")
        return [x for x in h if isinstance(x, dict)] if isinstance(h, list) else []


def consented(stamp) -> bool:
    """A consent stamp ("<version>@<time>") for the current CONSENT_VERSION."""
    if not isinstance(stamp, str) or "@" not in stamp:
        return False
    v, _at = stamp.split("@", 1)
    return v == str(CONSENT_VERSION)


def consent_stamp(now: float | None = None) -> str:
    now = time.time() if now is None else now
    return f"{CONSENT_VERSION}@{time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(now))}"


class Plan:
    """When a report is due. Pure: the caller says what time it is and
    what the radio and the network are doing; tests drive it with numbers."""

    def __init__(self, state: State, started: float):
        self.state = state
        self.started = started
        self.pending: list[tuple[str, str, float]] = []

    def note(self, events) -> None:
        for e in events:
            if e[0] in diag.TRIGGERS and len(self.pending) < 50:
                self.pending.append(e)

    def due(self, now: float, *, enabled: bool, keyed: bool, metered: bool, logged_since: float) -> str:
        """"fault", "daily" or "" (nothing now). `logged_since` is the
        newest log file's modification time: the daily report goes only if
        something was written since the last one."""
        if not enabled or keyed or metered:
            return ""
        retry_at = self.state.get("retryAt") or 0.0
        if now < retry_at:
            return ""
        if self.pending:
            first = min(t for _k, _d, t in self.pending)
            last = self.state.get("lastFault") or 0.0
            if now - first >= SETTLE_S and now - last >= DEBOUNCE_S:
                return "fault"
        last_daily = self.state.get("lastDaily") or 0.0
        last_any = self.state.get("lastSent") or 0.0
        if (now - self.started >= FIRST_DAILY_S and now - last_daily >= DAILY_S and logged_since > last_any):
            return "daily"
        return ""

    def taken(self) -> list[tuple[str, str, float]]:
        """The waiting triggers, for the report about to go."""
        out, self.pending = self.pending, []
        return out

    def sent(self, now: float, kind: str, code: str, trigger: str) -> None:
        h = (self.state.history() + [{"code": code, "at": now, "trigger": trigger, "kind": kind}])[-State.HISTORY:]
        kv = {"lastSent": now, "lastCode": code, "history": h, "retryAt": 0.0, "failures": 0, "lastError": ""}
        if kind == "fault":
            kv["lastFault"] = now
        if kind in ("daily", "fault"):
            # A fault report carries the day's log too: no daily one hard after it.
            kv["lastDaily"] = now
        self.state.set(**kv)

    def failed(self, now: float, kind: str, error: str, events) -> None:
        """Quietly: try again later, backing off, with the triggers kept."""
        n = int(self.state.get("failures") or 0) + 1
        wait = min(RETRY_MAX_S, RETRY_S * 2 ** (n - 1))
        self.state.set(failures=n, retryAt=now + wait, lastError=error[:300])
        if kind == "fault":
            self.pending = list(events) + self.pending


def trigger_text(events, kind: str) -> str:
    """The report's trigger in a word or two: the first fault, "daily", "manual"."""
    if kind == "fault" and events:
        return events[0][0]
    return kind


# ------------------------------------------------------------------ the bundle
def tail_text(paths: list[Path], limit: int) -> tuple[str, bool]:
    """The newest `limit` bytes of the log files (newest first in `paths`,
    as LogSetup.files() lists them), oldest line first; True if cut."""
    chunks, total, cut = [], 0, False
    for p in paths:
        try:
            data = Path(p).read_bytes()
        except OSError as e:
            data = f"(could not read {Path(p).name}: {e})\n".encode()
        if total + len(data) > limit:
            data = data[len(data) - (limit - total):]
            nl = data.find(b"\n")
            data = data[nl + 1:] if nl >= 0 else data
            chunks.append(data)
            cut = True
            break
        chunks.append(data)
        total += len(data)
    return b"".join(reversed(chunks)).decode("utf-8", errors="replace"), cut


def pack(payload: dict, log_text: str, cap: int = MAX_BYTES) -> tuple[bytes, dict]:
    """gzip'd JSON of `payload` plus the log, at most `cap` bytes: the log
    is cut from its oldest end (half of what is left each time) until it
    fits. Returns the bytes and what was cut."""
    text = log_text
    info = {"logBytes": len(log_text.encode("utf-8")), "logCut": False}
    while True:
        doc = dict(payload, log=text, logCut=info["logCut"])
        body = gzip.compress(json.dumps(doc, ensure_ascii=False, default=str).encode("utf-8"), 6)
        if len(body) <= cap:
            info["sentLogBytes"] = len(text.encode("utf-8"))
            return body, info
        if not text:
            raise UploadError(f"the report is {len(body)} bytes without any log, more than {cap}")
        info["logCut"] = True
        # The newer half, from its first whole line; always shorter, so
        # this ends (with no log at all, at worst).
        keep = text[len(text) // 2:] if len(text) > 64 else ""
        nl = keep.find("\n")
        text = keep[nl + 1:] if nl >= 0 else keep


def build(*, app: str, version: str, install: str, kind: str, events, report: str, status_lines: list[str],
          conf_path: Path | None, ui_path: Path | None, log_paths: list[Path], fault_path: Path | None,
          now: float | None = None) -> tuple[bytes, dict]:
    """The bundle that is uploaded: what Help › Save diagnostics… saves,
    minus the screenshot, as one gzip'd JSON document, scrubbed."""
    now = time.time() if now is None else now
    setup = diag.current()
    if setup is not None:
        setup.flush()

    def conf(p):
        if p is None:
            return None
        data = diag.redact_json_file(p)
        if data is None:
            return None
        # Serial numbers out of the JSON text, not the parsed values: a
        # saved civPort is a by-id path with the IC-9700's serial in it,
        # and redact() looks only for secrets. The replacement holds no
        # quote or backslash, so the text is still the same JSON.
        text = diag.scrub_serials(data.decode("utf-8", errors="replace"))
        try:
            return json.loads(text)
        except ValueError:
            return text

    faults = ""
    if fault_path is not None:
        faults, _cut = tail_text([fault_path], 200_000)
    raw, _cut = tail_text(log_paths, LOG_RAW_MAX)
    payload = {
        "schema": SCHEMA, "app": app, "version": version, "install": install,
        "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now)),
        "trigger": trigger_text(events, kind), "kind": kind,
        "triggers": [{"trigger": k, "detail": diag.redact_text(d), "at": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ", time.gmtime(t))} for k, d, t in events],
        "report": diag.redact_text(report),
        "status": [diag.redact_text(s) for s in status_lines],
        "config": conf(conf_path), "ui": conf(ui_path),
        "attachments": {k: diag.redact_text(v) for k, v in diag.attachments().items()},
        "faults": diag.redact_text(faults),
    }
    return pack(payload, diag.redact_text(raw))


# ------------------------------------------------------------------ sending
def post(url: str, body: bytes, *, app: str, version: str, install: str, timeout: float = TIMEOUT_S,
         opener=urllib.request.urlopen) -> str:
    """POST the bundle; the reference code the site gave it. Raises
    UploadError for anything else (offline, refused, a strange answer)."""
    q = urllib.parse.urlencode({"app": app, "version": version, "install": install})
    req = urllib.request.Request(f"{url}?{q}", data=body, method="POST",
                                 headers={"Content-Type": "application/gzip", "User-Agent": f"{app}/{version}"})
    try:
        with opener(req, timeout=timeout) as r:
            data = r.read(RESPONSE_MAX + 1)
    except urllib.error.HTTPError as e:
        why = ""
        try:
            why = json.loads(e.read(RESPONSE_MAX).decode("utf-8")).get("error", "")
        except (ValueError, OSError, AttributeError):
            pass
        raise UploadError(f"the site answered {e.code}{': ' + why if why else ''}") from None
    except (urllib.error.URLError, OSError) as e:
        raise UploadError(f"could not reach the site ({getattr(e, 'reason', e)})") from None
    try:
        code = json.loads(data[:RESPONSE_MAX].decode("utf-8")).get("code", "")
    except (ValueError, UnicodeDecodeError, AttributeError):
        code = ""
    if not (isinstance(code, str) and CODE.match(code)):
        raise UploadError("the site's answer had no reference code")
    return code
