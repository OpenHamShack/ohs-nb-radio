"""Configuration: load, validate, save atomically.

The file holds an app's persisted state keys (its state registry) plus the
operator's own memories. A key that fails validation on load falls back to
its default with a note rather than stopping the program: a hand-edited
typo should cost one setting, not the radio.

Which app's file it is comes from an `AppId`: QO-100 NB and Radio
are separate programs with separate configs, logs and environment
variables (docs/ham/DESIGN-HAM.md section 1), installable side by side.
"""
from __future__ import annotations

import copy
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from . import host
from .state import Registry

# Not a setting: how the radio in a config came to be what it is, when that
# was not the operator's choice in Settings. Config.load/clean put it in the
# dict they return, an app's command line puts it there for --device, and
# the engine reads it once (Engine.__init__) to explain a simulator nobody
# chose. Never saved - save() writes registry keys only - so it lives
# exactly as long as the run it describes. Users on Windows and macOS took
# the simulator's band for the air (NB/HAM 0.1.9) because nothing on the
# window said which radio it was; the SIMULATOR badge's hover says why from
# this. {"fallback": bool, "why": str}: fallback True means another radio
# was asked for and could not be had; "why" completes "... because <why>".
DEVICE_WHY = "_deviceWhy"


def override_device(cfg: dict, device: str) -> None:
    """--device on the command line: this run's radio, never saved (the
    apps run unpersisted then), and said as such if it is the simulator."""
    cfg["device"] = device
    cfg[DEVICE_WHY] = {"fallback": False,
                       "why": f"for this run on the command line (--device {device}); Settings › Radio is unchanged"}


# Not a setting either: --receive-only on the command line. The engine reads
# it once (Engine.__init__) and takes the transmitter away from every device
# it opens that run, so the one refusal every over already goes through
# (Engine._tx_blocked: "the device cannot transmit") says why. Added
# 17/10/2026 for Brian's Mac running NB on a Pluto shared over the tailnet:
# receive only, by a switch nothing in the window can turn back on. Never
# saved, for the same reason as DEVICE_WHY - a run that forgot the flag
# would otherwise stay deaf to the operator's PTT with no flag to blame.
RECEIVE_ONLY = "_receiveOnly"
RECEIVE_ONLY_REFUSAL = "Started receive-only (--receive-only): restart without it to transmit"


def receive_only(cfg: dict) -> None:
    """--receive-only on the command line: no transmitting this run."""
    cfg[RECEIVE_ONLY] = True


@dataclass(frozen=True)
class AppId:
    name: str      # folder name: ~/.config/<name>, %APPDATA%\<name>; e.g. "openhamshack-nb"
    env: str       # environment-variable prefix: $<env>_CONF, $<env>_DATA; e.g. "OHS_NB"
    # The prefix the variables had before the OpenHamShack rename
    # (17/10/2026; "OHSNB"). Still read, after the new one, so a script, a
    # container or a shortcut that sets $OHSNB_CONF keeps working.
    former_env: str = ""

    def env_var(self, what: str) -> str:
        return f"{self.env}_{what}"

    def env_vars(self, what: str) -> tuple[str, ...]:
        """Every name variable `what` may be set under, the current first."""
        return (self.env_var(what),) + ((f"{self.former_env}_{what}",) if self.former_env else ())

    def getenv(self, what: str) -> str | None:
        """$<env>_<what>, else the former prefix's; None when neither is set
        (an empty value counts as unset, as it always has here)."""
        for name in self.env_vars(what):
            v = os.environ.get(name)
            if v:
                return v
        return None


class Config:
    """One app's config file. `repair` applies the app's cross-key rules to
    a cleaned config, quietly, in the direction that never raises transmit
    power (an app's gain ceiling wins over a stored gain, never the other
    way round).

    `version` and `migrate` are for a change of meaning that the stored
    values alone cannot reveal. Every save writes every persisted key, so a
    file says "foundation" whether the operator chose it or it was merely
    the default of the day; only a version number written beside the keys
    tells a file written after the change from one written before it.
    `migrate(raw, path, notes)` sees the raw file of an older version as
    read from disk - never a dict handed to the engine directly, which is
    the program's own and already current - and returns what to clean. An
    app with no version (NB) writes none and is never migrated.

    `renamed(raw, notes)` is for the other kind of change: a key replaced
    by another, where the old key's presence is itself the evidence (no
    current file has it). It is unambiguous, so it applies to every input
    - a file of any age and a dict handed to the engine alike - and needs
    no version number. It returns the dict to clean, in today's keys."""

    VERSION_KEY = "configVersion"

    def __init__(self, app: AppId, registry: Registry, repair: Callable[[dict], None] | None = None,
                 freq_key: str = "dl", version: int = 0,
                 migrate: Callable[[dict, Path, list], dict] | None = None,
                 renamed: Callable[[dict, list], dict] | None = None):
        self.app = app
        self.renamed = renamed
        self.reg = registry
        self.repair = repair
        self.version = version
        self.migrate = migrate
        # What a stored memory calls its frequency: NB's have always said
        # "dl" (a downlink), HAM's say "rf" (the engine's FREQ_KEY).
        self.freq_key = freq_key

    def conf_path(self) -> Path:
        env = self.app.getenv("CONF")
        if env:
            return Path(env)
        return host.conf_dir(self.app.name) / "config.json"

    def data_dir(self) -> Path:
        env = self.app.getenv("DATA")
        return Path(env) if env else host.data_dir(self.app.name)

    def defaults(self) -> dict:
        # Copies: a list or dict default handed out as itself is shared by
        # every config built from it, and an edit to one changes them all.
        # The converter list is the first default a migration appends to.
        cfg = {k: copy.deepcopy(self.reg.spec[k]["default"]) for k in self.reg.persisted()}
        cfg["memories"] = []
        return cfg

    def clean(self, raw: dict, notes: list[str] | None = None) -> dict:
        """Validated config from an arbitrary dict: unknown keys dropped, bad
        values replaced by defaults (and described in `notes`)."""
        cfg = self.defaults()
        notes = notes if notes is not None else []
        if self.renamed is not None and isinstance(raw, dict) and raw:
            raw = self.renamed(dict(raw), notes)
        for k, v in (raw or {}).items():
            if k == "memories":
                cfg["memories"] = self.clean_memories(v, notes)
                continue
            if k not in self.reg.spec or not self.reg.spec[k]["persist"]:
                continue
            try:
                cfg[k] = self.reg.coerce(k, v)
            except ValueError as e:
                notes.append(f"{e}; using {self.reg.spec[k]['default']!r}")
                if k == "device":
                    cfg[DEVICE_WHY] = {"fallback": True,
                                       "why": f"the saved radio, {v!r}, is not one this program knows"}
        if self.repair is not None:
            self.repair(cfg)
        return cfg

    def clean_memories(self, v, notes: list[str]) -> list[dict]:
        out = []
        if not isinstance(v, list):
            return out
        for m in v[:500]:
            try:
                name = str(m["name"])[:40].strip()
                f = self.reg.coerce("vfo", m[self.freq_key])
                mode = self.reg.coerce("mode", m.get("mode", "usb"))
                if name:
                    out.append({"name": name, self.freq_key: f, "mode": mode})
            except (KeyError, TypeError, ValueError):
                notes.append(f"Dropped an unreadable memory: {m!r}"[:120])
        return out

    def load(self, path: Path | None = None, notes: list[str] | None = None) -> dict:
        path = path or self.conf_path()
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raw = {}
        except (OSError, ValueError) as e:
            if notes is not None:
                notes.append(f"Could not read {path} ({e}); starting from defaults")
            # Whichever radio the file named is unknowable now, and the
            # default (the simulator) stands in for it: say so.
            cfg = self.clean({}, notes)
            cfg[DEVICE_WHY] = {"fallback": True,
                               "why": f"the settings file could not be read ({e}), so every setting, the radio "
                                      f"included, is back to its default"}
            return cfg
        if self.migrate is not None and isinstance(raw, dict) and raw:
            try:
                stored = int(raw.get(self.VERSION_KEY, 0))
            except (TypeError, ValueError):
                stored = 0
            if stored < self.version:
                raw = self.migrate(dict(raw), path, notes if notes is not None else [])
        return self.clean(raw, notes)

    def save(self, cfg: dict, path: Path | None = None) -> None:
        """Write via a temporary file in the same directory, fsync, rename: a
        crash or power cut mid-save leaves the old file or the new one, never a
        truncated one - the Pi this runs on is often switched off at the wall."""
        path = path or self.conf_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        out = {k: cfg[k] for k in self.reg.persisted() if k in cfg}
        out["memories"] = cfg.get("memories", [])
        if self.version:
            out[self.VERSION_KEY] = self.version
        text = json.dumps(out, indent=2, sort_keys=True) + "\n"
        fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
