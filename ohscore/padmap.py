"""The operator's own mapping for the AKP03E (Settings › Control pad): which
action each key, button and knob runs in this app, on top of the app's
pad-layout.json.

shack_pad already has the mechanism (shack_pad.mapping, CONTROLLER-PAD.md
§5): the change is one entry in the station profile's
controllerMaps.<kind>.ajazz-akp03e, every stored value is checked again on
read, and one that this version cannot use (an action removed, a hand
edit, a newer version's map synced from a controller) leaves that one
control on its default instead of misfiring. This module is the desktop
editor's side of it, without Qt so it can be tested and reasoned about on
its own:

- **Page 1 only.** The library has up to four pages; the desktop editor
  edits the first and carries any others (from a controller) through
  untouched.
- **PTT only on the six picture keys.** The library allows a transmit
  action on any press; here it may only be a key with a picture, so the
  key that keys the transmitter is the one that shows ON AIR and PTT off.
  A stored map that puts it on a small button or a knob (a hand edit, a
  controller's editor) is cleaned on read: that control falls back to its
  default (clean_maps). One key at most: choosing PTT for another key
  moves it, and "Nothing" on the PTT key means the pad cannot key at all.
  Where it sits changes nothing else: the pad keys only through the
  lease, only once "The pad may transmit" is on (ohscore/ui/padlink.py).
- **Stored as one entry, written as one entry.** The profile splits
  controllerMaps into one field per app and model and never deletes a
  field, so "back to the defaults" is written as an empty entry (None),
  not by leaving the entry out - left out, the old one would come back.
"""
from __future__ import annotations

from pathlib import Path

from . import padactions, shacklibs
from .i18n.text import _

MODEL = "ajazz-akp03e"
# Actions the editor never offers: the platform's app switching (there is
# nothing to switch to on a desktop) and `none-turn`, which is shown as the
# knob's "Nothing".
_HIDDEN_PREFIX = ("app:",)


def _lib():
    shacklibs.pad()
    from shack_pad import actions, mapping
    from shack_pad.drivers import by_model
    return actions, mapping, by_model(MODEL)


def clean_maps(maps: dict | None, kind: str) -> dict:
    """controllerMaps with any transmit action on a control that has no
    picture taken out of this app's AKP03E entry, so that control keeps its
    default. Everything else is passed through as it is: the library checks
    the rest on read."""
    actions_mod, mapping, drv = _lib()
    entry = mapping.entry_of(maps, kind, MODEL)
    pages = entry.get("pages")
    if not isinstance(pages, list):
        return maps or {}
    keys = set(drv.screen_keys())
    changed = False
    new_pages = []
    for page in pages:
        if not isinstance(page, dict):
            new_pages.append(page)
            continue
        out = {}
        for cid, b in page.items():
            if cid not in keys and isinstance(b, dict) and b.get("press") in actions_mod.TX_IDS:
                b = {k: v for k, v in b.items() if k != "press"}
                changed = True
            out[cid] = b
        new_pages.append(out)
    if not changed:
        return maps
    return mapping.with_entry(maps, kind, MODEL, {**entry, "pages": new_pages})


class PadMap:
    """One app's AKP03E mapping being edited. `maps` is the profile's
    controllerMaps as stored; nothing is written from here (entry() and
    maps() say what to store)."""

    def __init__(self, package_dir: Path, maps: dict | None):
        self._actions, self._mapping, self.drv = _lib()
        self.decl, self.layout = padactions.declaration(package_dir)
        self.kind = self.decl["app"]
        self.acts, _notes = self._actions.load(self.decl)
        stored = self._mapping.entry_of(clean_maps(maps, self.kind), self.kind, MODEL)
        self.stored = stored or None
        self._entry = stored or None

    # ---------------------------------------------------------- reading
    def rows(self) -> list[tuple[str, str]]:
        """(control, slot) in the pad's order: the six keys, the three
        buttons, then each knob's turn and press."""
        out = []
        for c in self.drv.controls:
            if c["kind"] == "knob":
                out += [(c["id"], "turn"), (c["id"], "press")]
            else:
                out.append((c["id"], "press"))
        return out

    def page(self) -> dict:
        return self._mapping.resolve(self.drv, self.layout, self._entry, self.acts)[0][0]

    def default_page(self) -> dict:
        return self._mapping.resolve(self.drv, self.layout, None, self.acts)[0][0]

    def current(self, cid: str, slot: str) -> str:
        return self.page().get(cid, {}).get(slot) or ("none" if slot == "press" else "none-turn")

    def choices(self, cid: str, slot: str) -> list[str]:
        """The actions this control may run, Nothing first, then in the
        app's declared order with each knob action's up/down presses after
        the declared presses. PTT is offered only on a picture key."""
        nothing = "none" if slot == "press" else "none-turn"
        keys = set(self.drv.screen_keys())
        out = [nothing]
        for aid, a in self.acts.items():
            if aid == nothing or a.kind != slot or aid.startswith(_HIDDEN_PREFIX) or aid in ("none", "none-turn"):
                continue
            if a.tx and cid not in keys:
                continue
            out.append(aid)
        # The library builds the derived up/down presses after the declared
        # ones; keep "Next page" (a library action) after the app's own.
        if "page" in out:
            out.remove("page")
            out.append("page")
        return out

    def ptt_key(self) -> str | None:
        return self._mapping.find_holder(self.page(), "ptt")

    def is_default(self) -> bool:
        return self.page() == self.default_page()

    def changed(self) -> bool:
        """Anything to store: the edit differs from what is stored."""
        return self.entry() != self.stored

    # ---------------------------------------------------------- editing
    def set(self, cid: str, slot: str, aid: str) -> None:
        """One control's action on page 1. ValueError (a sentence) for
        anything the mapping cannot use; nothing changes then."""
        if aid in self.acts and self.acts[aid].tx and cid not in self.drv.screen_keys():
            raise ValueError(_("PTT can only be on one of the six keys with a picture"))
        self._entry = self._mapping.set_binding(self.drv, self.layout, self._entry, self.acts, 0, cid, slot, aid)

    def reset(self) -> None:
        self._entry = None

    def entry(self) -> dict | None:
        """What to store for this app and model: None for the app's own
        layout."""
        if self._entry is None or self.is_default() and len(self._mapping.stored_pages(self._entry)) == 1:
            return None
        return self._entry


def store(profile, kind: str, entry: dict | None) -> None:
    """Write one app's AKP03E entry to the station profile, and only that
    entry: another app's map, or this app's keypad map, is left alone."""
    profile.update({"controllerMaps": {kind: {MODEL: entry}}})
