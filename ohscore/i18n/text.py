"""gettext for sentences no widget says: the engines' refusals and
toasts, ValueError messages the windows show as they are, and the
`--server` API's JSON errors (OpenHamShack I18N.md section 2: Qt's tr()
for widgets, gettext for the rest, one domain per package).

Why not QCoreApplication.translate everywhere: the engine runs without
Qt in `--headless` and `--server`, and in a store container with no Qt
platform plugin at all; an engine import must not need PyQt.

Each package has its own domain - `ohscore`, `ohsnb`, `ohsradio` - with the
English template beside its Qt catalog (`<package>/i18n/<domain>.pot`) and
compiled translations under `<package>/i18n/locale/<lang>/LC_MESSAGES/
<domain>.mo`. A module takes its package's function:

    from ohscore.i18n.text import _            # ohscore
    _ = text.domain("ohsnb", OHSNB_I18N_DIR)    # an app package

shack-i18n-check recognises calls spelt `_`, `ngettext` and `pgettext`
(and checks their msgids against the .pot once one exists), so keep those
names.

The language: SHACK_LOCALE if set, else the process locale (LANGUAGE,
LC_ALL, LC_MESSAGES, LANG, as gettext reads them). English, the source
language, needs no catalog.
"""
from __future__ import annotations

import gettext
import os
from pathlib import Path

CORE_DIR = Path(__file__).resolve().parent


def languages() -> list[str] | None:
    """gettext's language list: SHACK_LOCALE alone when set (the same
    override ohscore/i18n/__init__.py gives the windows), else None for
    gettext's own environment lookup."""
    tag = os.environ.get("SHACK_LOCALE", "").strip()
    if not tag:
        return None
    from . import candidates
    return candidates(tag) or None


class Domain:
    def __init__(self, name: str, directory: Path):
        self.name = name
        self.localedir = Path(directory) / "locale"
        self._t = None

    def _tr(self):
        if self._t is None:
            self._t = gettext.translation(self.name, str(self.localedir), languages=languages(), fallback=True)
        return self._t

    def gettext(self, msg: str) -> str:
        return self._tr().gettext(msg)

    def ngettext(self, singular: str, plural: str, n: int) -> str:
        return self._tr().ngettext(singular, plural, n)

    def pgettext(self, context: str, msg: str) -> str:
        return self._tr().pgettext(context, msg)


def domain(name: str, directory: Path) -> Domain:
    return Domain(name, directory)


OHSCORE = Domain("ohscore", CORE_DIR)


def _(msg: str) -> str:
    return OHSCORE.gettext(msg)


def ngettext(singular: str, plural: str, n: int) -> str:
    return OHSCORE.ngettext(singular, plural, n)


def pgettext(context: str, msg: str) -> str:
    return OHSCORE.pgettext(context, msg)
