"""Frequencies for display in the user's locale (OpenHamShack I18N.md 4.1).

The same rules as ohs-libs' `shack_i18n.fmt.frequency`, and the same
vectors (tests/data/i18n-format.json, copied from ohs-libs
spec/vectors/i18n/format.json) prove it: kHz below 30 MHz and MHz from
30 MHz up unless the field fixes the unit, fixed decimals with trailing
zeros kept so a readout never changes width, the locale's decimal separator,
never any digit grouping ("10,489.750" and "10.489,750" each read as the
other in half the world), and a no-break space before the unit.

The decimal separator comes from QLocale, as the contract asks of a Qt app,
rather than from shack_i18n's own table: the app does not carry ohs-libs at
run time, and QLocale is what the rest of the window already formats with.
Where PyQt6 cannot be imported - the store container, which has no Qt at
all - it comes from `_DECIMAL` below instead, for the language the server's
gettext already speaks. Before that fallback a refusal that named a
frequency (Radio's pinned-span 409) died formatting itself and reached the
client as a 502 (beta.17 on ohs-box, 29/10/2026).
Arithmetic is on integers of Hz, so rounding is exact (half away from zero)
and no float ever shows a stray digit.
"""
from __future__ import annotations

import os

UNITS = {"Hz": 1, "kHz": 1_000, "MHz": 1_000_000, "GHz": 1_000_000_000}
_MAX_DECIMALS = {"Hz": 0, "kHz": 3, "MHz": 6, "GHz": 9}
_DEFAULT_DECIMALS = {"Hz": 0, "kHz": 1, "MHz": 3, "GHz": 6}
_AUTO_MHZ_FROM = 30_000_000
NBSP = " "


class FormatError(ValueError):
    """A value the formatter refuses; `code` matches the shared vectors."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


# The decimal column of shack_i18n's CLDR table (ohs-libs
# python/shack_i18n/src/shack_i18n/_cldr.py, checked there against ICU),
# copied rather than imported because shack-i18n is a build tool here and
# never ships. Only languages and regions whose separator is a comma, plus
# the regions that differ from their language; everything else is ".".
_COMMA_LANGUAGES = {"de", "fr", "es", "it", "nl", "nb", "nn", "no", "sv", "da",
                    "fi", "pl", "pt", "ru", "uk", "cs"}
_REGION_DECIMAL = {"de-CH": ".", "es-MX": "."}


def _table_decimal_point(tag: str | None) -> str:
    """The separator for a BCP 47 or POSIX tag (`de-CH`, `pt_BR.UTF-8`),
    read the way shack_i18n reads one: exact region, then language, then
    English's point."""
    if not tag:
        return "."
    tag = tag.split(".", 1)[0].split("@", 1)[0].replace("_", "-")
    parts = [p for p in tag.split("-") if p]
    if not parts:
        return "."
    lang = parts[0].lower()
    region = next((p.upper() for p in parts[1:] if len(p) == 2 and p.isalpha()), None)
    if region and f"{lang}-{region}" in _REGION_DECIMAL:
        return _REGION_DECIMAL[f"{lang}-{region}"]
    return "," if lang in _COMMA_LANGUAGES else "."


def _process_locale() -> str | None:
    """The tag a process with no Qt formats numbers in: SHACK_LOCALE (the
    override text.py's gettext honours too), else POSIX's order for
    numbers, LC_ALL, LC_NUMERIC, LANG. A container sets none of them, and
    is English."""
    for var in ("SHACK_LOCALE", "LC_ALL", "LC_NUMERIC", "LANG"):
        value = os.environ.get(var, "").strip()
        if value:
            return value
    return None


def _decimal_point(locale) -> str:
    try:
        from PyQt6.QtCore import QLocale
    except ImportError:
        # QLocale objects only come from Qt, so here locale is a tag or None.
        return _table_decimal_point(locale if locale else _process_locale())
    loc = locale if isinstance(locale, QLocale) else QLocale(locale) if locale else QLocale()
    return loc.decimalPoint()


def frequency(hz: int, unit: str = "auto", decimals: int | None = None, locale=None) -> str:
    """`frequency(437_000_000)` is "437.000 MHz" in English, "437,000 MHz"
    in German. `locale` is a tag or a QLocale; None is the app's default
    (which i18n.install() sets)."""
    if isinstance(hz, bool) or not isinstance(hz, int):
        raise FormatError("not-a-number", f"{hz!r} is not a whole number of hertz.")
    if hz < 0:
        raise FormatError("negative-frequency", "A frequency cannot be negative.")
    if unit == "auto":
        unit = "MHz" if hz >= _AUTO_MHZ_FROM else "kHz"
    if unit not in UNITS:
        raise FormatError("bad-unit", f"{unit!r} is not one of {', '.join(UNITS)}.")
    if decimals is None:
        decimals = _DEFAULT_DECIMALS[unit]
    if isinstance(decimals, bool) or not isinstance(decimals, int) or not 0 <= decimals <= _MAX_DECIMALS[unit]:
        raise FormatError("bad-decimals", f"{unit} shows 0 to {_MAX_DECIMALS[unit]} decimals, not {decimals!r}.")
    step = UNITS[unit] // 10 ** decimals          # Hz per last shown digit
    shown = (hz + step // 2) // step              # half away from zero (hz >= 0)
    whole, frac = divmod(shown, 10 ** decimals)
    text = str(whole) + (_decimal_point(locale) + str(frac).zfill(decimals) if decimals else "")
    return text + NBSP + unit
