"""The controller's host libraries, as an app in the store form sees them
(RADIO-SDR-PLAN §5.6, §6.3): what Radio may not carry in its image - faad2
for DAB+, SDRplay's API for an RSP - is installed by the controller's
administrator on the host and mounted read-only at
`$SHACK_HOSTLIBS/<name>/` (the platform sets SHACK_HOSTLIBS=/opt/hostlibs
for an app whose manifest declares `host_libraries`).

**Without SHACK_HOSTLIBS the controller is too old to know the key.** The
platform added `host_libraries` in OpenHamShack beta.9; an older one
installs the app with the key silently ignored, mounts nothing and sets
nothing. Nothing an administrator could install there would ever reach
the app, so "ask your administrator to install it" would send them to a
page their controller does not have. The sentence is "Update the
controller to use SDRplay radios and DAB+", in the state (`hostLibs`), on
the status page, and wherever the missing library would otherwise be
named (the RSP's open, the faad2 codec, a DAB+ station's `why`). The app
runs on regardless: everything else needs neither library.

Only the folders are looked at here, never loaded: the codec loader
(shack_sdr.codecs) and the SDRplay binding (shack_sdr.sources.sdrplay)
find and prove the files themselves, from the same SHACK_HOSTLIBS.
"""
from __future__ import annotations

import os
from pathlib import Path

from . import host
from .i18n.text import _

# What each library this app declares stages (the controller's allow-list
# fixes the patterns; these are the names the loaders look for first).
LIBRARIES = {
    "faad2": ("libfaad.so.2",),
    "sdrplay-api": ("libsdrplay_api.so.3", "sdrplay_apiService"),
    # DMR's voice: the platform builds it from upstream (szechyjs/mbelib
    # 1.3.0) and stages libmbe.so.1.0 with libmbe.so.1 beside it.
    "mbelib": ("libmbe.so.1",),
}


def root() -> str | None:
    """$SHACK_HOSTLIBS, or None where the platform set none."""
    return os.environ.get("SHACK_HOSTLIBS") or None


def controller_too_old() -> bool:
    """True in the store form on a controller that predates host libraries."""
    return bool(host.STORE) and root() is None


def update_sentence() -> str:
    return _("Update the controller to use SDRplay radios and DAB+")


def status() -> dict:
    """{} outside the store form; on a controller {"supported", "root",
    "libraries": {name: installed}, "why"} (`why` the update sentence when
    the controller is too old, else "")."""
    if not host.STORE:
        return {}
    r = root()
    if r is None:
        return {"supported": False, "root": None, "libraries": {}, "why": update_sentence()}
    libs = {name: all((Path(r) / name / f).exists() for f in files) for name, files in LIBRARIES.items()}
    return {"supported": True, "root": r, "libraries": libs, "why": ""}
