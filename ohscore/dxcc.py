"""Which DXCC entity (country) a callsign belongs to, from cty.dat.

cty.dat is AD1C's country file, the one every logging and FT8 program uses.
Three places, first found wins:

1. cty.dat in the app's data folder - the operator's own. The file is
   reissued every few weeks as DXpeditions come and go, and an operator who
   cares can update it without a new release of ours.
2. ohscore/data/cty.dat - our own copy, a pinned Big CTY edition vendored
   into the source and so into every package (ohscore/data/cty-source.txt,
   tools/cty-refresh.py). Until 0.1.10 there was none: FT8 needed WSJT-X,
   which installs a copy, so the column came with it. Since ohsdigi decodes
   without WSJT-X, a machine without it would have had no column at all.
3. Wherever WSJT-X (or Debian's hamradio-files) installed one -
   host.wsjtx_cty_files(). Only reached by a run from a tree without
   ohscore/data.

Ours beats an installed WSJT-X's on purpose. Ours is refreshed at each
release; WSJT-X's is whatever its package carried when it was built (the
copy Debian 13's wsjtx installs is June 2025's), and the file holds no date
to compare by - only an "=VERSION" call filed under whichever entity that
edition chose - so "the newer of the two" could only be guessed from file
times, which a package manager sets to anything. WSJT-X's own updater
writes into WSJT-X's log folder, which was never read here; an operator
who wants that copy puts it in the data folder.

Format (https://www.country-files.com/cty-dat-format/): an entity line of
eight colon-separated fields (name, CQ zone, ITU zone, continent, lat, lon,
UTC offset, primary prefix, a leading * marking a WAE-only entity), then its
prefixes, comma-separated, ending in ';'. A prefix starting with '=' is an
exact callsign. Each may carry overrides in (), [], <>, {} and ~~, which
this module does not need and strips.

cty.dat's names are long ("Fed. Rep. of Germany", "European Russia") and
the decode lists' Country column has room for about fourteen characters,
so the lists show `Entity.short`, from ohscore/data/dxcc-short.json, with
the full name in the tooltip. A table rather than a rule: no truncation or
abbreviation scheme turns "Fed. Rep. of Germany" into "Germany" or "Dem.
Rep. of the Congo" into "DR Congo". An operator's newer cty.dat may bring
a long name the table has not heard of; it then shows whole and elides.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import host


@dataclass(frozen=True)
class Entity:
    name: str
    continent: str
    prefix: str        # the primary prefix, e.g. "G", "EA8"
    wae: bool = False  # a WAE-only entity (Shetland, Vienna Intl Ctr): DXCC counts it under its parent
    # Kept since 08/10/2026 for ohscore/countries.py: where the entity is,
    # roughly (its centre; cty.dat's longitude is west-positive and is
    # turned round here), for the IARU region and QO-100's footprint.
    lat: float | None = None
    lon: float | None = None     # degrees east
    itu: int | None = None       # ITU zone
    cq: int | None = None        # CQ zone

    @property
    def short(self) -> str:
        """The name to show where room is short: the table's, else the name."""
        return short_names().get(self.name, self.name)


_OVERRIDES = re.compile(r"\(.*?\)|\[.*?\]|<.*?>|\{.*?\}|~.*?~")

# Suffixes that say how the station is operating, not where: dropped
# before looking the call up. /MM and /AM are at sea or in the air, in no
# country at all.
_NOT_A_PLACE = {"P", "M", "QRP", "QRPP", "A", "LH", "LGT"}
_NOWHERE = {"MM", "AM"}


def _num(s: str, sign: float = 1.0) -> float | None:
    try:
        return sign * float(s)
    except ValueError:
        return None


def _int(s: str) -> int | None:
    try:
        return int(s)
    except ValueError:
        return None


def parse(text: str) -> tuple[dict[str, Entity], dict[str, Entity]]:
    """(exact calls, prefixes) -> Entity, from the text of a cty.dat."""
    exact: dict[str, Entity] = {}
    prefixes: dict[str, Entity] = {}
    for record in text.split(";"):
        record = record.strip()
        if not record:
            continue
        head, sep, body = record.partition("\n")
        f = [x.strip() for x in head.split(":")]
        if len(f) < 8:
            continue
        primary = f[7]
        ent = Entity(f[0], f[3], primary.lstrip("*"), primary.startswith("*"), _num(f[4]), _num(f[5], -1.0),
                     _int(f[2]), _int(f[1]))
        for alias in body.replace("\n", "").split(","):
            alias = _OVERRIDES.sub("", alias).strip().upper()
            if not alias:
                continue
            if alias.startswith("="):
                exact[alias[1:]] = ent
            else:
                prefixes[alias] = ent
    return exact, prefixes


def _call_area(call: str, digit: str) -> str:
    """EA1ABC with /8 is signing from call area 8: EA8. The digit of the
    home prefix is replaced; a call with no digit gets it appended."""
    m = re.match(r"^([A-Z0-9]*?[A-Z])(\d)", call)
    if m:
        return m.group(1) + digit
    return call + digit


def location_part(call: str) -> str | None:
    """The part of a (possibly portable) call that says where the station
    is, or None for maritime/aeronautical mobile. EA8/G4ABC -> EA8,
    G4ABC/P -> G4ABC, G4ABC/EA8 -> EA8, EA1ABC/8 -> EA8."""
    parts = [p for p in call.strip().upper().split("/") if p]
    if not parts:
        return ""
    if any(p in _NOWHERE for p in parts[1:]):
        return None
    parts = [parts[0]] + [p for p in parts[1:] if p not in _NOT_A_PLACE]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) == 1:
        return _call_area(parts[0], parts[1])
    # A prefix added to a home call is the shorter part: EA8/G4ABC, G4ABC/EA8.
    return min(parts[:2], key=len)


class Countries:
    def __init__(self, text: str = ""):
        self.exact, self.prefixes = parse(text) if text else ({}, {})
        self.longest = max((len(p) for p in self.prefixes), default=0)

    def __bool__(self):
        return bool(self.prefixes)

    def lookup(self, call: str) -> Entity | None:
        call = (call or "").strip().upper().strip("<>")
        if not call or call.startswith("..."):
            return None
        if call in self.exact:
            return self.exact[call]
        where = location_part(call)
        if not where:
            return None
        if where in self.exact:
            return self.exact[where]
        for n in range(min(len(where), self.longest), 0, -1):
            ent = self.prefixes.get(where[:n])
            if ent is not None:
                return ent
        return None


# Beside this module in every build: the .deb copies ohscore whole, and the
# Windows and macOS specs name ohscore/data as data.
BUNDLED = Path(__file__).absolute().parent / "data" / "cty.dat"
SHORT_NAMES = BUNDLED.with_name("dxcc-short.json")

_short: dict[str, str] | None = None


def short_names() -> dict[str, str]:
    """cty.dat name -> short name, read once. Empty if the file is missing
    (a build that left it out shows the full names, as before)."""
    global _short
    if _short is None:
        try:
            raw = json.loads(SHORT_NAMES.read_text(encoding="utf-8"))
            _short = {k: v for k, v in raw.items() if not k.startswith("_") and isinstance(v, str)}
        except (OSError, ValueError):
            _short = {}
    return _short


def candidates(data_dir: Path | None = None) -> list[Path]:
    """Where a cty.dat may be, in the order the module docstring gives."""
    out = []
    if data_dir is not None:
        out.append(Path(data_dir) / "cty.dat")
    return out + [BUNDLED] + host.wsjtx_cty_files()


_cache: dict[str, Countries] = {}


def load(data_dir: Path | None = None) -> Countries:
    """The first readable cty.dat, parsed once per process; an empty
    Countries (lookups return None) when there is none."""
    for p in candidates(data_dir):
        key = str(p)
        if key in _cache:
            return _cache[key]
        try:
            text = p.read_text(encoding="latin-1")
        except OSError:
            continue
        _cache[key] = Countries(text)
        return _cache[key]
    return Countries()


def skim_lookup(data_dir: str | None = None):
    """The CW skimmer's country lookup (shack_cw.skim.calls): call ->
    {"country", "dxcc", "continent"}, or None for a call in no entity,
    which the skimmer then never spots. It is the same file and the same
    answer as the decodes' country column (Engine._with_country), so a spot
    and a decode never disagree. It is named "ohscore.dxcc:skim_lookup"
    because the skimmer's worker is a separate process, which can be handed
    only a name. This module imports nothing of either app and nothing
    that can key (tests/test_ham_cwskim.py)."""
    countries = load(Path(data_dir) if data_dir else None)

    def lookup(call: str) -> dict | None:
        ent = countries.lookup(call)
        return None if ent is None else {"country": ent.name, "dxcc": ent.prefix, "continent": ent.continent}
    return lookup
