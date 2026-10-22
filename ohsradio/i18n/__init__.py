"""gettext for ohsradio's sentences no widget says (ohscore/i18n/text.py says
why they are not Qt strings): the engine's refusals and toasts and the
ValueError messages the window shows as they are. OpenHamShack Radio's
own domain, `ohsradio`, with its English template beside the Qt catalog in
this folder (written by `tools/i18n.py pot`).

Imported as `from ohsradio.i18n import _` (or ngettext/pgettext): those are the
names the string check (tools/i18n.py check) and the template writer recognise. Importing it
needs no PyQt, so the engine stays usable headless.
"""
from __future__ import annotations

from pathlib import Path

from ohscore.i18n.text import domain

DOMAIN = domain("ohsradio", Path(__file__).resolve().parent)


def _(msg: str) -> str:
    return DOMAIN.gettext(msg)


def ngettext(singular: str, plural: str, n: int) -> str:
    return DOMAIN.ngettext(singular, plural, n)


def pgettext(context: str, msg: str) -> str:
    return DOMAIN.pgettext(context, msg)
