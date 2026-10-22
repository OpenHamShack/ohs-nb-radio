"""Memories: the app's built-in presets followed by the operator's own.

Moved out of ohsnb/radio.py (docs/ham/DESIGN-HAM.md section 2.5 step 8a).
The presets are the app's (QO-100's beacons and calling frequencies for
NB, a band plan's for HAM); the operator's memories are persisted in the
config under "memories". A memory's frequency is stored under the app's
`freq_key` (NB's have always said "dl") and validated as a `vfo` value,
so a memory can never hold a dial the radio would refuse.

Not thread-safe by itself: the engine holds its own lock around `store`
and `remove`, as it did when this was inline.
"""
from __future__ import annotations

from typing import Callable

from .i18n.text import _


class Memories:
    def __init__(self, presets: list[dict], user: list[dict], coerce: Callable, freq_key: str):
        self.presets = presets
        self.user = list(user)
        self.coerce = coerce
        self.freq_key = freq_key

    def listing(self) -> list[dict]:
        return ([dict(p, builtin=True) for p in self.presets] +
                [dict(m, builtin=False) for m in self.user])

    def make(self, name: str, freq: float, mode: str) -> dict:
        """A validated memory, not yet stored. Raises ValueError."""
        name = str(name).strip()[:40]
        if not name:
            raise ValueError(_("A memory needs a name"))
        return {"name": name, self.freq_key: self.coerce("vfo", freq), "mode": self.coerce("mode", mode)}

    def store(self, m: dict) -> None:
        """Add `m`, replacing any memory of the same name."""
        self.user = [x for x in self.user if x["name"] != m["name"]] + [m]

    def remove(self, name: str) -> None:
        self.user = [x for x in self.user if x["name"] != name]

    def find(self, name: str) -> dict:
        for m in self.listing():
            if m["name"] == name:
                return m
        raise ValueError(_("No memory called {name}").format(name=repr(name)))
