"""The "What is this?" card: what a right-click on either scope opens in
QO-100 NB (docs/ui-overhaul-2026-10.md section 5.6), in place of the bare
menu it had. Its top says what the signal there is - from the band
skimmer, the band plan and the over-power watch, put together by
ohsnb/whatis.py - with one or two buttons that do the likely thing (Decode
FT8, Decode CW, Listen, Show its text); below a line, the menu's own items
as they were (lock to this as a beacon; auto-tune onto the voice here).

Every button tunes the receiver or shows a page. While anything is on the
air or armed they are all greyed, menu items too, with "Not while
transmitting" saying why; the window checks again when one is pressed,
as an over can start while the card is open (plan section 7, rule 4).

The menu items are QActions added to the card itself, with the likeliest
the default action, so the card answers actions() and defaultAction() as
the QMenu before it did: the beacon-lock and auto-tune tests drive them
unchanged.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QCoreApplication, QPoint, Qt
from PyQt6.QtGui import QAction, QGuiApplication
from PyQt6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QSizePolicy, QVBoxLayout

from ohscore.modegroups import label as mode_label
from ohscore.ui import theme
from ohscore.ui.controls import Button

from .. import whatis
from .skimview import freq_text, heard_text

WIDTH = 400


def title_text(i: whatis.Ident) -> str:
    """The card's first line: what it is."""
    e = i.entry or {}
    w = i.what
    if w == "window":
        return QCoreApplication.translate("WhatIsCard", "{label} calling window · %n signal(s)", "",
                                          int(e.get("count", 1))).format(label=e["label"])
    if w in ("beacon_cw", "beacon_mid", "mmb", "broadcast", "kgstv"):
        return e["label"]
    if w == "known":
        return e["label"]
    return {
        "ssb_measured": QCoreApplication.translate("WhatIsCard", "SSB, dial measured"),
        "ssb_voice": QCoreApplication.translate("WhatIsCard", "SSB: speech heard, dial not measured yet"),
        "ssb_shape": QCoreApplication.translate("WhatIsCard", "SSB? Voice-shaped, no speech heard yet"),
        "cw": QCoreApplication.translate("WhatIsCard", "CW"),
        "data": QCoreApplication.translate("WhatIsCard", "Data, not identified"),
        "carrier": QCoreApplication.translate("WhatIsCard", "Unmodulated carrier"),
        "faint": QCoreApplication.translate("WhatIsCard", "A faint narrow signal"),
        "unlooked": QCoreApplication.translate("WhatIsCard", "Not looked at yet"),
        "signal": QCoreApplication.translate("WhatIsCard", "Signal, not identified"),
    }.get(w, QCoreApplication.translate("WhatIsCard", "Nothing the band skimmer has found here"))


def where_text(i: whatis.Ident, now: float) -> str:
    """Second line: where, in what, when heard, how strong."""
    e = i.entry
    if e is None:
        return freq_text({"kind": "signal", "f": i.f, "dial": None}) + " MHz"
    parts = [freq_text(e) + " " + mode_label(e.get("mode") or "usb")]
    heard = heard_text(e, now)
    parts.append(QCoreApplication.translate("WhatIsCard", "heard now") if heard == "now" else
                 QCoreApplication.translate("WhatIsCard", "heard {ago}").format(ago=heard))
    parts.append(QCoreApplication.translate("WhatIsCard", "SNR {snr:.0f} dB").format(snr=float(e.get("snr") or 0)))
    if i.what in ("data", "faint", "signal", "unlooked", "known", "carrier"):
        parts.append(QCoreApplication.translate("WhatIsCard", "{w:.0f} Hz wide").format(w=e["hi"] - e["lo"]))
    return " · ".join(parts)


def hint_text(key: str) -> str:
    # whatis.HINTS keys: the frequencies are there, the words here, each a
    # literal so the string check and pylupdate6 see it.
    return {
        "slowfsk": QCoreApplication.translate(
            "WhatIsCard", "Seen here on 17/10/2026: a weak, slow FSK about 45 Hz wide. A QRSS or FSK-CW beacon?"),
        "keyedcarrier": QCoreApplication.translate(
            "WhatIsCard", "Seen here on 17/10/2026: a carrier keyed 0.4 s on, 0.4 s off, with a buzzy note. "
                          "Someone testing?"),
        "arqburst": QCoreApplication.translate(
            "WhatIsCard", "Seen here: a 0.45 s tone, then a few seconds of MFSK on a 93.75 Hz grid. An ARQ modem's "
                          "connect or beacon frame (VARA, ARDOP, FreeDATA?)"),
        "arq": QCoreApplication.translate(
            "WhatIsCard", "Connected ARQ data, 4 s blocks and short replies: probably VARA HF, one side of a "
                          "private link"),
        "multicarrier": QCoreApplication.translate(
            "WhatIsCard", "A 1.1 kHz multicarrier that starts on the hour for about 10 minutes. Not FreeDV; not "
                          "identified yet"),
    }.get(key, "")


def detail_lines(i: whatis.Ident, st: dict) -> list[str]:
    """The lines under the title: the calls heard, what NB does with it,
    what the surveys learnt, the segment, the skimmer's state."""
    e = i.entry or {}
    w = i.what
    out = []
    if w == "window" and e.get("calls"):
        out.append(" ".join(e["calls"][:8]) + (" …" if len(e["calls"]) > 8 else ""))
    elif w == "beacon_cw":
        out.append(QCoreApplication.translate(
            "WhatIsCard", "Keyed by shifting between two tones (F1A): Decode CW puts the key-down tone on the CW "
                          "pitch"))
    elif w == "beacon_mid":
        out.append(QCoreApplication.translate(
            "WhatIsCard", "Its text is decoded in the background, whatever the mode"))
    elif w == "mmb":
        out.append(QCoreApplication.translate(
            "WhatIsCard", "Bulletins, pictures and the DX cluster, received in the background"))
    elif w == "kgstv":
        if e.get("sender"):
            out.append(QCoreApplication.translate("WhatIsCard", "Last sent by {call}").format(call=e["sender"]))
        out.append(QCoreApplication.translate(
            "WhatIsCard", "Pictures are received in the background, whatever the mode"))
    elif w == "broadcast":
        out.append(QCoreApplication.translate("WhatIsCard", "AMSAT-DL's own bulletins, in USB"))
    elif w == "known":
        out.append(QCoreApplication.translate("WhatIsCard", "Not decoded by OpenHamShack QO-100 NB"))
    elif w == "carrier" and i.segment and i.segment.get("modes") == ["ssb"]:
        out.append(QCoreApplication.translate("WhatIsCard", "In an SSB segment this is usually a station tuning up"))
    elif w == "faint":
        out.append(QCoreApplication.translate(
            "WhatIsCard", "Too weak to tell CW, a carrier or data apart; the skimmer looks again in a few minutes"))
    elif w == "unlooked":
        out.append(QCoreApplication.translate(
            "WhatIsCard", "The skimmer listens to each signal in turn ({looks:.0f} looks a minute)").format(
                looks=float(st.get("skimLooks") or 0)))
    elif w == "signal" and e.get("why"):
        out.append(e["why"])
    if i.hint:
        out.append(hint_text(i.hint))
    if i.segment:
        seg = i.segment
        name = seg["label"][:1].upper() + seg["label"][1:]
        out.append(name if seg["tx"] else
                   QCoreApplication.translate("WhatIsCard", "{segment}: no transmitting").format(segment=name))
    if i.skimmer == "off":
        out.append(QCoreApplication.translate("WhatIsCard", "Band skimmer off: Settings › LNB & locks"))
    elif i.skimmer == "error":
        out.append(QCoreApplication.translate("WhatIsCard", "Band skimmer stopped after an error (see the log)"))
    return out


def over_lines(ev: dict) -> list[str]:
    """Why a column is amber or red: the over-power watch's event."""
    if ev["kind"] == "leila" or (ev.get("leila") and not ev.get("excessDb")):
        return [QCoreApplication.translate("WhatIsCard", "LEILA? siren-like"),
                QCoreApplication.translate(
                    "WhatIsCard", "Two tones taking turns every 200 ms, the pattern of AMSAT-DL's LEILA siren on real "
                                  "recordings. Not confirmed as LEILA.")]
    head = QCoreApplication.translate("WhatIsCard", "+{db:.0f} dB over the beacon").format(db=ev["excessDb"])
    if ev.get("leila"):
        head += " · " + QCoreApplication.translate("WhatIsCard", "LEILA?")
    out = [head, QCoreApplication.translate(
        "WhatIsCard", "Power in a 1 kHz slice against the middle beacon's. In a pile-up the slice adds several "
                      "callers together: on 17/10/2026 a slice reading +9 to +19 dB held a strongest single "
                      "station 8 to 12 dB over.")]
    if ev.get("call"):
        out.append(QCoreApplication.translate("WhatIsCard", "Heard here by your decoder: {call}").format(
            call=ev["call"]))
    return out


def action_text(a: whatis.Action) -> str:
    if a.key == "decode":
        return QCoreApplication.translate("WhatIsCard", "Decode {mode}").format(mode=mode_label(a.mode))
    if a.key == "autotune":
        return QCoreApplication.translate("WhatIsCard", "Listen and auto-tune")
    if a.key == "try":
        return QCoreApplication.translate("WhatIsCard", "Try as {mode}").format(mode=mode_label(a.mode))
    if a.key == "view":
        return {"midtext": QCoreApplication.translate("WhatIsCard", "Show its text"),
                "bulletins": QCoreApplication.translate("WhatIsCard", "Show the beacon"),
                "kgstv": QCoreApplication.translate("WhatIsCard", "Show pictures")}.get(a.page, a.page)
    return QCoreApplication.translate("WhatIsCard", "Listen")


class WhatIsCard(QFrame):
    """The card. `items` are the menu's (text, callable, likeliest);
    `do(action)` is the window's, called with a whatis.Action; `busy` greys
    everything."""

    def __init__(self, ident: whatis.Ident, items, do, busy: bool, st: dict, parent=None):
        super().__init__(parent, Qt.WindowType.Popup)
        self.ident, self.do, self.busy = ident, do, busy
        self.setObjectName("WhatIs")
        t = theme.t()
        self.setStyleSheet(
            f"#WhatIs {{ background: {t['bg1']}; border: 1px solid {t['line2']}; border-radius: 12px; }}"
            f"#WhatIsItem {{ text-align: left; padding: 6px 10px; border: none; border-radius: 5px; "
            f"background: transparent; color: {t['text']}; }}"
            f"#WhatIsItem:hover {{ background: {t['bg3']}; }}"
            f"#WhatIsItem:disabled {{ color: {t['text3']}; }}")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(theme.S4, theme.S3, theme.S4, theme.S3)
        lay.setSpacing(theme.S1)
        head = QLabel(self.tr("What is this?"))
        head.setFont(theme.caps(10.5))
        head.setStyleSheet(f"color: {t['text3']};")
        lay.addWidget(head)
        self.lines: list[QLabel] = []
        if ident.over is not None:
            red = ident.over["kind"] == "leila" or ident.over.get("leila")
            for n, text in enumerate(over_lines(ident.over)):
                lab = self._line(lay, text, 13 if n == 0 else 12, bold=n == 0)
                if n == 0:
                    lab.setStyleSheet(f"color: {t['err'] if red else t['warn']};")
            lay.addSpacing(theme.S2)
        self.title = self._line(lay, title_text(ident), 14, bold=True)
        self._line(lay, where_text(ident, time.time()), 12, mono=True, muted=True)
        for text in detail_lines(ident, st):
            self._line(lay, text, 12)
        self.buttons: list[tuple[whatis.Action, Button]] = []
        acts = list(ident.actions) + list(ident.tries)
        if acts:
            row = QHBoxLayout()
            row.setSpacing(theme.S2)
            for n, a in enumerate(acts):
                b = Button(action_text(a), kind="primary" if n == 0 else "plain", small=True)
                if a.key == "try":
                    b.setToolTip(self.tr("A guess: nothing has identified this signal"))
                b.setEnabled(not busy)
                b.clicked.connect(lambda a=a: self._do(a))
                row.addWidget(b)
                self.buttons.append((a, b))
            row.addStretch(1)
            lay.addSpacing(theme.S1)
            lay.addLayout(row)
        self.busy_note = None
        if busy:
            self.busy_note = self._line(lay, self.tr("Not while transmitting"), 12, bold=True)
            self.busy_note.setStyleSheet(f"color: {t['warn']};")
        self._default = None
        self.items: list[QPushButton] = []
        if items:
            line = QFrame()
            line.setFixedHeight(1)
            line.setStyleSheet(f"background: {t['line']};")
            lay.addSpacing(theme.S2)
            lay.addWidget(line)
            for text, fn, likeliest in items:
                act = QAction(text, self)
                act.setEnabled(not busy)
                act.triggered.connect(lambda _=False, fn=fn: self._item(fn))
                self.addAction(act)
                if likeliest:
                    self._default = act
                b = QPushButton(text)
                b.setObjectName("WhatIsItem")
                b.setFont(theme.font(12.5, theme.QFont.Weight.DemiBold if likeliest else theme.QFont.Weight.Normal))
                b.setEnabled(not busy)
                b.setCursor(Qt.CursorShape.PointingHandCursor)
                b.clicked.connect(act.trigger)
                lay.addWidget(b)
                self.items.append(b)
        self.setFixedWidth(theme.px(WIDTH))

    def _line(self, lay, text: str, size: float, bold=False, mono=False, muted=False) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setFont(theme.font(size, theme.QFont.Weight.DemiBold if bold else theme.QFont.Weight.Normal, mono=mono))
        lab.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)
        if muted:
            lab.setObjectName("Muted")
        lay.addWidget(lab)
        self.lines.append(lab)
        return lab

    def texts(self) -> list[str]:
        """Every line, as shown (for the tests and the diagnostics)."""
        return [lab.text() for lab in self.lines]

    def defaultAction(self) -> QAction | None:
        return self._default

    def button(self, text: str) -> Button | None:
        return next((b for _a, b in self.buttons if b.text == text), None)

    def _do(self, a: whatis.Action) -> None:
        self.close()
        self.do(a, self.ident)

    def _item(self, fn) -> None:
        self.close()
        fn()

    def popup(self, where: QPoint) -> None:
        """Open at `where` (global), kept on the screen."""
        self.adjustSize()
        x, y = where.x(), where.y()
        scr = QGuiApplication.screenAt(where) or QGuiApplication.primaryScreen()
        if scr is not None:
            g = scr.availableGeometry()
            x = max(g.left(), min(x, g.right() - self.width()))
            y = max(g.top(), min(y, g.bottom() - self.height()))
        self.move(x, y)
        self.show()


__all__ = ["WhatIsCard", "title_text", "detail_lines", "over_lines", "action_text"]
