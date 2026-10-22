"""Pieces shared by the mode panels: the panel base, a receive/transmit
terminal, a macro bar, and the type-ahead transmit queue."""
from __future__ import annotations

import time

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QTextCharFormat, QTextCursor
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
                             QTextEdit, QVBoxLayout, QWidget)

from .. import theme
from ..controls import Button, Toggle
from ..prefs import expand_macro


class ModePanel(QWidget):
    """Base: holds the bridge and prefs, receives decoder events and state."""

    modes: tuple[str, ...] = ()

    def __init__(self, bridge, prefs, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs = bridge, prefs
        # A mirror (the second display's copy) shows everything but never
        # transmits: one panel per mode owns the transmit queue/sequencer.
        self.mirror = False

    def set_mirror(self):
        self.mirror = True

    def on_event(self, ev: dict):
        pass

    def on_state(self, ch: dict):
        pass

    def tick(self, dt: float):
        pass

    def st(self, k, d=None):
        return self.bridge.st.get(k, d)

    def mycall(self) -> str:
        return (self.st("callsign") or "").upper()


class Terminal(QTextEdit):
    """Received text in the text colour, sent text in our own gold, a
    faint timestamp when a new over starts after a pause."""

    def __init__(self, parent=None, big: bool = False):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(theme.font(22 if big else 14.5, mono=True))
        self.document().setMaximumBlockCount(3000)
        self.last_kind = None
        self.last_t = 0.0
        self.history: list[tuple[str, str, float]] = []     # for a mirror to replay
        self.setMinimumHeight(80)
        self.setStyleSheet(f"QTextEdit {{ background: {theme.t()['bg2']}; border: 1px solid {theme.t()['line']};"
                           f" border-radius: 6px; padding: 8px; }}")

    def put(self, text: str, kind: str = "rx", now: float | None = None):
        if not text:
            return
        now = time.time() if now is None else now
        self.history.append((text, kind, now))
        if len(self.history) > 4000:
            del self.history[:1000]
        cur = self.textCursor()
        cur.movePosition(QTextCursor.MoveOperation.End)
        fmt = QTextCharFormat()
        if kind == "dim":
            kind_for_stamp = self.last_kind or "rx"
        else:
            kind_for_stamp = kind
        if (kind_for_stamp != self.last_kind or now - self.last_t > 20) and not self.document().isEmpty():
            stamp = QTextCharFormat()
            stamp.setForeground(theme.c("text3"))
            stamp.setFont(theme.font(11, mono=True))
            cur.insertText("\n", fmt)
            cur.insertText(time.strftime("%H:%M:%S  ", time.gmtime(now)) + ("TX  " if kind == "tx" else ""), stamp)
        # What we sent in the `own` gold - the colour that already means our
        # own signal - not red, which by the time anyone reads it is no
        # longer on the air (overhaul section 5.3).
        fmt.setForeground(theme.c("own") if kind == "tx" else theme.c("text3") if kind == "dim" else theme.c("text"))
        cur.insertText(text, fmt)
        self.last_kind, self.last_t = kind_for_stamp, now
        self.setTextCursor(cur)
        self.ensureCursorVisible()


class MacroBar(QWidget):
    """A row of macro buttons. Right-click (or the pencil) edits them."""

    fire = pyqtSignal(str)
    MAX = 8                 # macros kept, and function keys bound to them (F1 ... F8)

    def __init__(self, prefs, key: str, parent=None, mycall_fn=lambda: "", loc_fn=lambda: ""):
        super().__init__(parent)
        self.prefs, self.key, self.mycall_fn, self.loc_fn = prefs, key, mycall_fn, loc_fn
        # A grid that re-flows with the width: six macros on one line on a
        # wide screen, two rows of three on a laptop, never elided to "F1 ...".
        self.lay = QGridLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setHorizontalSpacing(6)
        self.lay.setVerticalSpacing(6)
        self.buttons: list = []
        self.cols = 0
        self.rebuild()

    def rebuild(self):
        for b in self.buttons:
            b.hide()
            b.deleteLater()
        self.buttons = []
        for i, m in enumerate(self.prefs[self.key]):
            # Label by what it will actually send, short: "CQ CQ DE GM4BRI…".
            text = expand_macro(m, self.mycall_fn(), "", "599", self.loc_fn()).replace("  ", " ").strip()
            label = f"F{i + 1}  " + (text if len(text) <= 16 else text[:15].rstrip() + "\u2026")
            b = Button(label, small=True)
            b.setToolTip(m)
            b.clicked.connect(lambda m=m: self.fire.emit(m))
            b.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            b.customContextMenuRequested.connect(lambda _p: self.edit())
            self.buttons.append(b)
        ed = Button(self.tr("Edit"), small=True, kind="ghost")
        ed.clicked.connect(self.edit)
        self.buttons.append(ed)
        self.cols = 0
        self._flow()

    def trigger(self, i: int) -> bool:
        """Send macro i (the F-key's way in). False if there is none."""
        macros = self.prefs[self.key]
        if not 0 <= i < len(macros) or not self.isVisible():
            return False
        self.fire.emit(macros[i])
        return True

    def _flow(self):
        w = max(1, self.width())
        cols = max(1, min(len(self.buttons), int(w // 130)))
        if cols == self.cols:
            return
        self.cols = cols
        while self.lay.count():
            self.lay.takeAt(0)
        for i, b in enumerate(self.buttons):
            self.lay.addWidget(b, i // cols, i % cols)
            b.show()

    def resizeEvent(self, e):
        self._flow()
        super().resizeEvent(e)

    def edit(self):
        d = QDialog(self)
        d.setWindowTitle(self.tr("Macros"))
        lay = QVBoxLayout(d)
        lay.setContentsMargins(20, 18, 20, 16)
        lay.setSpacing(10)
        # The macro fields are doubled braces: format() fills {max} and
        # leaves them as the operator types them.
        hint = QLabel(self.tr("One macro per line (up to {max}, sent by F1 to F{max}). {{MYCALL}}, "
                              "{{CALL}} (or {{DXCALL}}: the QSO box's call), {{RST}} and {{LOC}} (your locator) are "
                              "filled in when sent; a macro whose field is empty is not sent.").format(max=self.MAX))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        ed = QPlainTextEdit("\n".join(self.prefs[self.key]))
        ed.setFont(theme.font(13, mono=True))
        ed.setMinimumSize(560, 220)
        lay.addWidget(ed)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        lay.addWidget(bb)
        if d.exec():
            lines = [x.strip() for x in ed.toPlainText().splitlines() if x.strip()][:self.MAX]
            self.prefs[self.key] = lines
            self.prefs.save()
            self.rebuild()


class TxQueue:
    """Type-ahead for text modes. The engine sends one rendered message at a
    time and refuses another while keyed, so text queues here and goes out
    in chunks whenever the transmitter is free."""

    def __init__(self, bridge, mode_fn, on_sent):
        self.bridge = bridge
        self.mode_fn = mode_fn            # -> (mode, extra send options)
        self.on_sent = on_sent            # callback(text) when a chunk is handed to the engine
        self.pending = ""
        self.last_try = 0.0

    def add(self, text: str):
        self.pending += text

    def clear(self):
        self.pending = ""

    def pump(self):
        if not self.pending.strip() or self.bridge.st.get("keyed"):
            if not self.pending.strip():
                self.pending = ""
            return
        now = time.monotonic()
        if now - self.last_try < 0.4:
            return
        self.last_try = now
        mode, opts = self.mode_fn()
        chunk, self.pending = self.pending, ""
        if self.bridge.send(mode, text=chunk, **opts):
            self.on_sent(chunk)
        else:
            # Refused (licence, bandplan...): the reason was toasted; drop the
            # text rather than retrying it forever.
            pass


class TxEntry(QWidget):
    """The line you type to transmit, with send-as-you-type and a queue count."""

    submit = pyqtSignal(str)

    def __init__(self, placeholder: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        self.edit.setFont(theme.font(14.5, mono=True))
        self.edit.setMinimumHeight(34)
        self.edit.returnPressed.connect(self._enter)
        self.edit.textEdited.connect(self._typed)
        self.live = Toggle(self.tr("As you type"), False)
        self.live.setToolTip(self.tr("Send each word as soon as you finish it (space), instead of the whole line "
                                     "on Enter."))
        self.send_btn = Button(self.tr("Send"), icon="send", kind="primary")
        self.send_btn.clicked.connect(self._enter)
        self.stop_btn = Button(self.tr("Stop"), kind="ghost")
        lay.addWidget(self.edit, 1)
        lay.addWidget(self.live)
        lay.addWidget(self.send_btn)
        lay.addWidget(self.stop_btn)

    def _enter(self):
        t = self.edit.text()
        if t:
            self.submit.emit(t + " ")
            self.edit.clear()

    def _typed(self, t: str):
        if self.live.on and t.endswith(" "):
            self.submit.emit(t)
            self.edit.clear()


def why_label(text: str) -> QLabel:
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {theme.t()['warn']}; padding: 10px; background: {theme.t()['bg2']};"
                      f" border-radius: 6px;")
    return lab
