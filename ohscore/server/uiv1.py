"""ui/1 routes (CLIENT-UI-PLAN.md §5.3, docs/SERVER-API.md "ui/1 screens"):
`GET ui/v1/app`, the app descriptor the launcher draws its tiles from, and
`GET ui/v1/screen/<id>`, one server-driven screen.

The shared server only serves them; what the screens say is the app's
(AppInfo.screens: ohsradio/screens.py for Radio). An app without screens
answers 404, so QO-100 NB, which serves none yet, keeps its hand-written
client screen (§5.8: a kind with no ui/v1/app opens the old one).

What a screen may know about the request is a `Request`, made here from
the headers and nothing else:

- `base`: X-Forwarded-Prefix as a path ending "/" (the same rule as the
  status page's <base>). Documents use relative paths only and need it
  for nothing today; it is here so an app never reads the header itself.
- `components`: what the client says it can draw
  (`X-OpenHamShack-Components: waterfall/1, map.ais/1, ...`), name to
  version, or None when the header is absent (a browser, curl, a test):
  then every native component goes out with its fallback beside it and the
  client chooses, as §5.3 allows.
- `level`: the caller's level for this app, so a screen may say "needs
  Control" beside a control the client will grey out anyway (§5.5).

The documents are built with ohs-libs shack_ui, which validates each
against the pinned schema as it is turned into JSON (Document.to_json):
a screen that would break a client, or that declares a transmit-level
action (§5.6), is a 500 here and never reaches a TV. They are sent as
they are, not through with_urls(): an action's "path" is relative to the
app's base by contract, and with_urls would put an absolute "url" beside
it.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re

log = logging.getLogger("ohscore.server.uiv1")

UI_VERSION = "1.0"
# `waterfall/1`, `map.ais/1`: a name (a native component, or one of its
# layers after a dot) and the newest version of it the client draws.
_COMPONENT_RE = re.compile(r"^([A-Za-z][A-Za-z0-9]*(?:\.[A-Za-z][A-Za-z0-9]*)?)/([0-9]+)$")
SCREEN_ID_RE = re.compile(r"^[a-z0-9-]+/[a-z0-9-]+$")


class UnknownScreen(LookupError):
    """No screen by that id (404 unknown_screen)."""


def parse_components(header: str | None) -> dict[str, int] | None:
    """X-OpenHamShack-Components as {name: version}; None when absent.
    A malformed entry is skipped rather than refusing the request: an
    older server must never break a newer client over a spelling."""
    if header is None:
        return None
    out: dict[str, int] = {}
    for part in header.split(","):
        m = _COMPONENT_RE.match(part.strip())
        if m:
            out[m.group(1)] = max(out.get(m.group(1), 0), int(m.group(2)))
    return out


class Request:
    """What a screen may know about the request (module docstring)."""

    def __init__(self, base: str = "/", components: dict[str, int] | None = None, level: str = "view",
                 ui: str | None = None):
        self.base, self.components, self.level, self.ui = base, components, level, ui

    def lacks(self, name: str, v: int = 1) -> bool:
        """True only when the client said what it has and `name` (at `v` or
        newer) is not among it: then the screen sends the fallback alone.
        A layer (`map.ais`) needs its own entry; the bare component is not
        taken to mean every layer."""
        return self.components is not None and self.components.get(name, 0) < v


def rev_of(doc: dict) -> str:
    """A short hash of the document as served: its `rev` and ETag (§5.7).
    Built from the document without its rev, so the same screen in the same
    state always has the same rev."""
    raw = json.dumps({k: v for k, v in doc.items() if k != "rev"}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def ui_major_ok(header: str | None) -> bool:
    """Whether a client's X-OpenHamShack-UI can take a 1.x document: no
    header (an older client, a browser) or major 1. A client that says only
    2.x is told so (406) rather than handed a document it may misdraw."""
    if header is None or not header.strip():
        return True
    return header.strip().split(".", 1)[0] == "1"
