"""The station's shared logbook and profile, and the controller link.

BETA-PLAN architecture change 2: every app keeps a local logbook and
station profile, offline first, and when an OpenHamShack controller is
present it pairs with it and syncs. Both are ohs-libs' shack_client
(SYNC.md, SERVICES.md): one SQLite store per user per machine, shared by
every OpenHamShack app on it, so QO-100 NB and Radio on one laptop keep
one log and pair once (SYNC.md section 2.1).

What this module adds to shack_client is the apps' side:

- Where the store is. The shared per-user path, except that an engine
  built with its own data folder (every test, `--data`) keeps its store
  inside that folder, and SHACK_STATION_DB overrides both (the store
  container's /data/shack/station.db).
- The station profile kept equal to the apps' own settings (callsign,
  locator, station country, licence, class, own licence, station
  conditions, PSK Reporter): settings an operator changes go into the
  profile, and a profile another app or the controller changed comes back
  into the settings. Only differing fields are written, so the two never
  echo each other forever.
- Pairing run off the caller's thread, and the status every app shows
  the same way (SYNC.md section 7).

Nothing here waits on the network on the caller's thread except the
discovery and pairing calls, which the UI runs in a worker.
"""
from __future__ import annotations

import logging
import os
import threading
from pathlib import Path

from . import shacklibs

log = logging.getLogger("ohscore.station")

# settings key -> profile field, for the scalar ones. The licence is one
# profile field built from three settings (below).
SCALAR = {"callsign": "callsign", "locator": "locator", "stationCountry": "dxccPrefix",
          "pskReporter": "pskReporter"}
LICENCE_KEYS = ("licence", "licenceClass", "customLicence")
PROFILE_SETTINGS = tuple(SCALAR) + LICENCE_KEYS + ("stationConditions",)


def store_path(data_dir: Path | None) -> Path:
    env = os.environ.get("SHACK_STATION_DB", "").strip()
    if env:
        return Path(env)
    if data_dir is not None:
        return Path(data_dir) / "station.db"
    shacklibs.client()
    from shack_client.store import default_path
    return default_path()


def open_station(app: str, version: str, data_dir: Path | None = None, background: bool = True):
    return shacklibs.client().Station.open(app=app, app_version=version, path=store_path(data_dir),
                                           background=background)


# ------------------------------------------------------------------ profile <-> settings
def settings_to_profile(st: dict) -> dict:
    """The profile fields an app's settings say."""
    out = {}
    for k, f in SCALAR.items():
        if k in st:
            v = st[k]
            out[f] = v.strip().upper() if isinstance(v, str) and f in ("callsign", "dxccPrefix") else v
    if "licence" in st or "licenceClass" in st:
        lic = {"regime": st.get("licence") or "auto", "class": st.get("licenceClass", "") or ""}
        lic["custom"] = list(st.get("customLicence") or [])
        out["licence"] = lic
    if "stationConditions" in st:
        out["conditions"] = {k: bool(v) for k, v in (st.get("stationConditions") or {}).items()}
    return out


def profile_to_settings(p: dict) -> dict:
    """The app settings a profile says (only fields it has)."""
    out = {}
    for k, f in SCALAR.items():
        if f in p and p[f] is not None:
            out[k] = p[f]
    lic = p.get("licence")
    if isinstance(lic, dict):
        out["licence"] = lic.get("regime") or "auto"
        out["licenceClass"] = lic.get("class", "") or ""
        out["customLicence"] = list(lic.get("custom") or [])
    if isinstance(p.get("conditions"), dict):
        out["stationConditions"] = {k: bool(v) for k, v in p["conditions"].items()}
    return out


def _norm(v):
    if isinstance(v, str):
        return v.strip()
    return v


class StationLink:
    """One engine's view of the shared store. `engine` needs `st`, `set`,
    `STATE` and `toast`; it is called back on the store's watch thread."""

    def __init__(self, station, engine=None):
        self.station = station
        self.engine = engine
        self._applying = threading.Lock()
        self._busy = threading.Event()

    # ---------------------------------------------------------- profile
    def adopt(self) -> None:
        """At start: the profile wins where it says something, the settings
        fill what it does not (a first run after the upgrade puts the
        operator's callsign and licence into the shared profile)."""
        prof = self.station.profile.get()
        mine = settings_to_profile(self.engine.st)
        missing = {f: v for f, v in mine.items() if f not in prof and v not in ("", None, [], {})}
        if missing:
            self.station.profile.update(missing)
        self.pull()
        self.station.on_change(self._changed)

    def push(self, changed: dict) -> None:
        """Settings the operator changed -> the profile, field by field,
        only where the profile differs."""
        if self._applying.locked() or not any(k in changed for k in PROFILE_SETTINGS):
            return
        want = settings_to_profile({k: self.engine.st.get(k) for k in PROFILE_SETTINGS if k in self.engine.st})
        have = self.station.profile.get()
        diff = {f: v for f, v in want.items() if _norm(have.get(f)) != _norm(v)}
        if diff:
            try:
                self.station.profile.update(diff)
            except ValueError as e:              # a locator shack_client will not store
                log.warning("station profile not updated: %s", e)

    def pull(self) -> dict:
        """The profile -> the settings, where they differ. Returns what
        changed. A value this app cannot hold (a class from a licence this
        version does not know) is left out, never forced in."""
        prof = self.station.profile.get()
        want = profile_to_settings(prof)
        st = self.engine.st
        spec = self.engine.STATE.spec
        clean = {}
        for k, v in want.items():
            if k not in spec or _norm(st.get(k)) == _norm(v):
                continue
            try:
                clean[k] = self.engine.STATE.coerce(k, v)
            except ValueError as e:
                log.info("profile field for %s not taken: %s", k, e)
        if not clean:
            return {}
        with self._applying:
            try:
                return self.engine.set(authorise=True, **clean)
            except ValueError as e:
                log.info("profile not applied: %s", e)
                return {}

    def _changed(self, collection, _ids) -> None:
        if collection in (None, "profile"):
            self.pull()

    # ---------------------------------------------------------- controller
    def status(self) -> dict:
        return self.station.sync.status()

    def pairing(self) -> dict | None:
        p = self.station.pairing_info()
        if p is None:
            return None
        return {k: p.get(k, "") for k in ("controllerId", "name", "baseUrl", "deviceId", "user", "maxLevel",
                                           "pairedAt")}

    def discover(self, timeout: float = 3.0) -> list:
        """Controllers on the LAN ([shack_client Controller]); raises
        shack_client.DiscoveryUnavailable without python-zeroconf."""
        return shacklibs.client().discover(timeout=timeout)

    def pair(self, base_url: str, username: str, password: str, totp: str | None = None, device_name: str = ""):
        """Pairing or NeedsDecision; raises PairingError or Offline. Run it
        off the UI thread."""
        if not base_url.endswith("/"):
            base_url += "/"
        return self.station.pair(base_url, username, password, totp=totp or None,
                                 device_name=device_name or self._device_name(), device_kind="desktop")

    def resolve(self, decision, choice: str):
        return self.station.resolve(decision, choice)

    def unpair(self) -> None:
        self.station.unpair()

    def sync_now(self) -> None:
        self.station.sync.now()

    def _device_name(self) -> str:
        import socket
        return f"{socket.gethostname()} ({self.station.app})"

    def close(self) -> None:
        self.station.close()
