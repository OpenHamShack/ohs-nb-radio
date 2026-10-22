"""What a callsign is, in one place: both apps, every place one is checked.

Until 08/10/2026 each place had its own idea. PSKReporter wanted 3-13
characters with a letter and a digit; the FT8 decoder's jt9 argument took
anything of A-Z, 0-9 and "/" up to 12; the logbook kept letters, digits and
"/"; QRZ links took the longest part with a digit. Each was right for a UK
call and each disagreed with the others on the forms an operator abroad
signs: EA8/GM4BRI/P (a prefix for where the station is, then a suffix for
how), VE3/W1AW, GM4BRI/MM, W1AW/4 (call area 4). One helper means a call
the Settings page accepts is a call every other part accepts too.

The shape accepted, and why it is lenient: one *home call* - the part that
holds both a letter and a digit and is longest, as QRZ files it - with at
most one part before it and two after, each of letters and digits only. A
home call is 3-10 characters. That admits special-event calls (GB100RSGB,
TM1A) and contest calls the ITU's prefix rules would also admit, and turns
away what is plainly not a call: a word with no digit, a bare prefix
(EA8, which ends in its digit), a four-character locator (IO86). It is a
typing check, not a licence check: a six-character locator (IO86HA) has
a call's shape and passes. Whose call it is, is the operator's business;
this only stops typing mistakes reaching the air, the log or a spotting
network.

Where the station *is* comes from the prefix or a location suffix, not the
home call: EA8/GM4BRI is in the Canary Islands and under Spain's rules
(ohscore/dxcc.py location_part, ohscore/countries.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass

# A home call: 3-10 letters and digits with at least one of each, a digit
# (the call-area digit: G4ABC, 2E0ABC, 9A1AA, 4U1ITU) within the first five,
# and ending in a letter. Ending in a letter is what tells a call from a
# bare prefix (EA8, KH6), which ends in its digit.
_HOME = re.compile(r"^(?=.*[A-Z])[A-Z0-9]{0,4}[0-9][A-Z0-9]{0,5}[A-Z]$")
_PART = re.compile(r"^[A-Z0-9]{1,6}$")

# Suffixes that say how the station operates rather than where. They are
# also what ohscore/dxcc.py drops before looking a call up.
OPERATING_SUFFIXES = frozenset({"P", "M", "MM", "AM", "A", "QRP", "QRPP", "LH", "LGT"})


@dataclass(frozen=True)
class Parts:
    prefix: str          # "EA8" in EA8/GM4BRI/P, "" for none
    home: str            # "GM4BRI"
    suffixes: tuple      # ("P",), ("MM",), ("4",), ("EA8",) ...


def normalise(call) -> str:
    """Upper case, no surrounding spaces or FT8 hash brackets. A space
    inside is left alone, so "W9 XYZ" stays a typo rather than becoming a
    call nobody typed."""
    return str(call or "").strip().upper().strip("<>")


def _is_home(part: str) -> bool:
    return 3 <= len(part) <= 10 and bool(_HOME.match(part))


def parts(call) -> Parts | None:
    """The call split into prefix, home call and suffixes; None when it is
    not a callsign (see the module docstring)."""
    c = normalise(call)
    if not c or len(c) > 20 or c.startswith("/") or c.endswith("/") or "//" in c:
        return None
    bits = c.split("/")
    if len(bits) > 4 or not all(_PART.match(b) or _is_home(b) for b in bits):
        return None
    homes = [i for i, b in enumerate(bits) if _is_home(b)]
    if not homes:
        return None
    # Of several call-shaped parts (VP2E/K1ABC: both end in a letter) the
    # longest is the home call, as QRZ.com files it; a tie goes to the
    # later part, since a prefix comes first. VE3/W1AW and G4ABC/EA8 have
    # only one: a bare prefix ends in its digit.
    i = max(homes, key=lambda j: (len(bits[j]), j))
    if i > 1 or len(bits) - i - 1 > 2:
        return None
    return Parts(bits[0] if i == 1 else "", bits[i], tuple(bits[i + 1:]))


def valid(call) -> bool:
    """A callsign, home or portable: G4ABC, GM4BRI/P, EA8/GM4BRI/P,
    VE3/W1AW, W1AW/4, GM4BRI/MM, 2E0ABC, GB100RSGB."""
    return parts(call) is not None


def home(call) -> str:
    """The operator's own call inside a portable form (EA8/GM4BRI/P ->
    GM4BRI); the normalised input when it is not a callsign."""
    p = parts(call)
    return p.home if p is not None else normalise(call)


def is_portable_abroad(call) -> bool:
    """Whether the call carries a location of its own - a prefix (EA8/...)
    or a location suffix (.../EA8, .../4) - rather than only /P, /M ..."""
    p = parts(call)
    if p is None:
        return False
    return bool(p.prefix) or any(s not in OPERATING_SUFFIXES for s in p.suffixes)
