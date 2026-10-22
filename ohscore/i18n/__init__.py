"""Which language the windows speak (docs/I18N.md, OpenHamShack I18N.md).

English is the source language: every user-visible string is written in
English inside `self.tr()` or `QCoreApplication.translate()`, and the
catalogs carry the translations. `install()` chooses one language and puts
its catalogs in front of Qt.

Two apps share this core, so a running window draws on two catalogs: the
shared one beside this file (`ohscore`, the strings of the widgets both apps
build) and the app's own (`ohsnb` or `ohsradio`, beside its package). Each app's
`make_app()` passes both, as (directory, domain) pairs; the core never names
an app (tests/test_core_isolation.py), so the list comes from the app.

The choice: `SHACK_LOCALE` if set (a tag such as `de`, `pt_BR` or `en-XA`,
for trying a language or the pseudo-locale without changing the desktop's),
otherwise the desktop's own list of preferred languages, first match wins.
A language is taken if any of the catalogs has it (a half-translated app
still shows what it has); one with no catalog falls through to the next,
and English is always the last word.

Every domain's English catalog is installed even when English was chosen,
and under any other language too: it holds the English plural forms,
without which `tr("%n station(s)", "", n)` would show the source text, and
with it a catalog that lacks a string falls back to proper English rather
than to the source. Qt asks the most recently installed translator first,
so all the English goes in before any of the chosen language. Contexts do
not collide between domains: a context is a class name, and ohscore's
classes are ohscore's alone.
"""
from __future__ import annotations

import os
from pathlib import Path

CATALOG_DIR = Path(__file__).resolve().parent
DOMAIN = "ohscore"
# The shared catalog alone, for a caller that names no app (a tool, a test
# of an ohscore widget).
CORE = [(CATALOG_DIR, DOMAIN)]

# Kept here, not just installed: Qt holds a pointer, Python the object, and
# a translator Python collects is a translator Qt reads freed memory from.
_installed: list = []


def candidates(tag: str) -> list[str]:
    """Catalog suffixes for a locale tag, most specific first:
    `pt-BR.UTF-8` -> `["pt_BR", "pt"]`."""
    tag = tag.split(".")[0].split("@")[0].replace("-", "_").strip()
    if not tag or tag in ("C", "POSIX"):
        return []
    parts = tag.split("_")
    return ["_".join(parts[:i]) for i in range(len(parts), 0, -1)]


def preferred() -> list[str]:
    """The locale tags to try, in order."""
    from PyQt6.QtCore import QLocale
    override = os.environ.get("SHACK_LOCALE", "").strip()
    if override:
        return [override]
    return list(QLocale.system().uiLanguages())


def choose(tags: list[str], catalogs=CORE) -> str:
    """The first catalog suffix in `tags` that any of `catalogs` (a list of
    (directory, domain)) has compiled, else "en"."""
    for tag in tags:
        for cand in candidates(tag):
            if any((Path(d) / f"{dom}_{cand}.qm").is_file() for d, dom in catalogs):
                return cand
    return "en"


def install(app=None, locale: str | None = None, catalogs=CORE) -> str:
    """Put the chosen language's catalogs in front of Qt and return its suffix.

    Safe to call again, and called again: each app's make_app() calls it,
    and the test suite builds both apps' windows in one process, so the
    second app's catalogs must replace the first's rather than sit behind
    them. Whatever this module installed before is removed first.
    """
    from PyQt6.QtCore import QCoreApplication, QLibraryInfo, QLocale, QTranslator
    for t in _installed:
        QCoreApplication.removeTranslator(t)
    _installed.clear()
    chosen = choose([locale] if locale else preferred(), catalogs)
    files = [Path(d) / f"{dom}_en.qm" for d, dom in catalogs]
    if chosen != "en":
        files += [Path(d) / f"{dom}_{chosen}.qm" for d, dom in catalogs]
    for f in files:
        t = QTranslator()
        if f.is_file() and t.load(str(f)):
            QCoreApplication.installTranslator(t)
            _installed.append(t)
    if chosen != "en":
        # Qt's own words (the file dialog, Yes/No buttons) from Qt's catalogs,
        # where the installation has them.
        qt = QTranslator()
        if qt.load(f"qtbase_{chosen}", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
            QCoreApplication.installTranslator(qt)
            _installed.append(qt)
    # Numbers follow the locale that was asked for (fmt reads QLocale()):
    # the tag itself, not the catalog it landed on, so de_CH keeps its
    # decimal point while speaking the de catalog.
    asked = locale or os.environ.get("SHACK_LOCALE", "").strip()
    QLocale.setDefault(QLocale(asked) if asked else QLocale.system())
    return chosen


def app_catalogs(package_dir) -> list:
    """The shared catalog and an app's own, the app's from the `i18n`
    folder of `package_dir` with the folder's name as its domain
    (ohsnb/i18n/ohsnb_*.qm)."""
    pkg = Path(package_dir).resolve()
    return CORE + [(pkg / "i18n", pkg.name)]
