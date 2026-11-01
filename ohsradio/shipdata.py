"""What a ship's own AIS says, made readable from bundled tables (Brian,
01/11/2026; docs/SERVER-API.md "AIS", "Flag and port"). No network:
both tables ship with Radio (ohsradio/data/ships/, each with its
LICENCE.txt), so a box with no route out shows them as well as any.

    flag(mmsi)        -> {"mid", "country", "iso", "emoji"} | None
    destination(text) -> {"text", "code"} | None

**The flag** is the country the MMSI's Maritime Identification Digits are
allocated to (ITU-R M.585), not anything the ship says about itself. Where
the MID sits depends on the station's form:

    MIDxxxxxx   a ship (first digit 2-7)          8MIDxxxxx  a handheld VHF
    0MIDxxxxx   a group of ships                  98MIDxxxx  a craft with a parent ship
    00MIDxxxx   a coast (base) station            99MIDxxxx  an aid to navigation
    111MIDxxx   a SAR aircraft

A SART, MOB or EPIRB (970, 972, 974xxxxxx) carries a maker's number where
the MID would be, and so has no flag; nor has anything whose MID the ITU
has not allocated. `emoji` is the Unicode flag of the ISO 3166 code (two
regional-indicator letters), which every client's text draws (an old
Windows font draws it as the two letters, still readable); None where the
table has no code (306, shared by three Dutch Caribbean islands).

**The destination** an AIS ship types into its voyage data is free text,
but the IMO's guidance asks for a UN/LOCODE, and most merchant ships give
one: "GBARD", "GB ARD", "GB-ARD", sometimes "GBARD>IEDUB" (from and to).
Each code found in the bundled list (every port's, ~17,500) becomes the
port's name; a part that is not one stays as written, so "FOR ORDERS" or
"ARDROSSAN" reads as before. `code` is the raw text when anything was
mapped, for a screen to show muted beside the name, and None otherwise.
A five-letter word written without a space that is itself some port's
name is left alone, so a crew's "FJELL" is not turned into a code that
happens to spell it.
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from functools import lru_cache
from pathlib import Path

log = logging.getLogger("ohsradio.shipdata")

DATA = Path(__file__).resolve().parent / "data" / "ships"

_CODE = re.compile(r"^[A-Z]{2}[A-Z2-9]{3}$")
_SEPARATORS = re.compile(r"[\s\-_.]+")
_PARTS = re.compile(r"\s*(?:=>|->|>)\s*")


@lru_cache(maxsize=1)
def _mids() -> dict[str, tuple[str, str | None]]:
    try:
        raw = json.loads((DATA / "mid.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.warning("no MID table (%s): ships show no flag", e)
        return {}
    return {k: (v[0], v[1]) for k, v in raw.items()}


@lru_cache(maxsize=1)
def _ports() -> tuple[dict[str, str], frozenset[str]]:
    """The code list, and every five-letter port name in it written as a
    code would be (the module docstring's "FJELL")."""
    try:
        ports = json.loads(gzip.decompress((DATA / "locode.json.gz").read_bytes()))
    except (OSError, ValueError) as e:
        log.warning("no port list (%s): destinations show as sent", e)
        return {}, frozenset()
    words = frozenset(n.upper() for n in ports.values() if len(n) == 5 and n.isalpha())
    return ports, words


def mid_of(mmsi) -> str | None:
    """The MID inside an MMSI (module docstring), or None for a form with none."""
    try:
        n = int(mmsi)
    except (TypeError, ValueError):
        return None
    if not 0 < n <= 999_999_999:
        return None
    s = f"{n:09d}"
    if s.startswith("00"):
        return s[2:5]
    if s.startswith("0"):
        return s[1:4]
    if s.startswith("111"):
        return s[3:6]
    if s.startswith(("98", "99")):
        return s[2:5]
    if s.startswith("8"):
        return s[1:4]
    if "2" <= s[0] <= "7":
        return s[:3]
    return None


def emoji_flag(iso: str | None) -> str | None:
    if not iso or len(iso) != 2 or not iso.isalpha():
        return None
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in iso.upper())


def flag(mmsi) -> dict | None:
    mid = mid_of(mmsi)
    got = _mids().get(mid) if mid else None
    if got is None:
        return None
    country, iso = got
    return {"mid": mid, "country": country, "iso": iso, "emoji": emoji_flag(iso)}


def port(part: str) -> str | None:
    """One code's port name, or None for text that is not a known code."""
    ports, words = _ports()
    p = part.strip().upper()
    code = _SEPARATORS.sub("", p)
    if not _CODE.match(code):
        return None
    if code == p and code in words:
        return None
    return ports.get(code)


def destination(text) -> dict | None:
    """An AIS destination as {"text": what to show, "code": the raw text
    when a code was mapped, else None}; None for none."""
    raw = text.strip() if isinstance(text, str) else ""
    if not raw:
        return None
    parts = [x for x in _PARTS.split(raw) if x]
    names = [port(x) for x in parts]
    if not any(names):
        return {"text": raw, "code": None}
    return {"text": " → ".join(n or x for n, x in zip(names, parts)), "code": raw}
