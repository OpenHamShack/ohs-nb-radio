"""The slot panel: FT8, FT4 and Q65's band activity, the slot clock and a
standard QSO sequencer; JS8 in its receive-only form.

Every mode in ohscore/modegroups.py SLOT_MODES comes here (panels.panel_key)
and takes its period, its tone width and whether it transmits from there.
Q65-60A is FT8's QSO over 60 s periods: the same 77-bit messages, so the
same Tx rows and sequencer, with the over queued once the 55 s decode is in
(SlotSpec.queue_at). JS8 joins frames into messages and sends typed text,
not a QSO sequence, so it has a band activity and a send card of its own
(js8.py), shown here in place of the FT8 list and the QSO card: being the
same panel, it has the zoom scope's marks, their clicks, the ARMED
countdown, Escape and the Digital layout the window gives a slot panel,
without the window knowing a second kind.

The sequencer queues each transmission for our next slot 2.5 s into the
other station's, and the engine starts it on the boundary (+0.5 s for FT8).
Their slot is decoded 13.5 s in (ohscore/modes/ft8.py, as WSJT-X's main
pass), so their answer usually lands just before our slot, after that over
was queued: a decode that changes what we say replaces it before it goes
on the air. An operator's own decision - a click on a station, a Tx row
picked, Enable TX switched on - goes in the current slot when it is ours
and still young enough for a late start, cutting an over already on the
air if need be (ft8seq.plan_over, Ft8Panel.tick).
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QRectF, QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QFont, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QScrollArea, QSizePolicy, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget)

from ... import dxcc, pileup
from .. import theme
from ..controls import Anim, Button, Card, Segmented, Toggle, mix
from ...engine import SLOT_LATE, SLOT_LEAD, SLOT_TRUNCATE
from ...ft8seq import Sequencer, plan_over, sender
from ...modegroups import SLOT_MODES, slot_spec
from .common import ModePanel
from .halt import HaltButton
from .js8 import Js8Panel

SLOT = {m: s.period for m, s in SLOT_MODES.items()}
# Rendering an over (ohsdigi, or ft8code as a subprocess on a slow Windows
# laptop) takes up to a few hundred ms between the panel's decision and the
# engine's slot_start(). A late start decided closer than this to the
# engine's limit would be pushed to our next slot - 30 s on - by the time it
# reached the engine, so the panel stops offering one this much earlier.
RENDER_MARGIN = 0.4


def late_until(mode: str) -> float:
    """How far into one of our slots the panel may still queue an over for
    that slot itself (seconds). FT8: the engine's SLOT_TRUNCATE, 6 s - the
    panel sends with late_start, so from 2 s on the engine drops the symbols
    already past rather than shifting the message, and it judges the limit
    by when the over was asked for, so rendering needs no margin. FT4: the
    engine's whole-message shift limit less RENDER_MARGIN, 0.6 s."""
    if mode in SLOT_TRUNCATE:
        return SLOT_TRUNCATE[mode]
    return SLOT_LEAD[mode] + SLOT_LATE[mode] - RENDER_MARGIN


class SlotRing(QWidget):
    """The slot clock: a ring filling over the slot, even/odd, and whether
    this slot is ours to transmit in."""

    # Drawn at 96 px and scaled to the size it is given: the QSO card's
    # short form (Ft8Panel._fit_qso) asks for a smaller ring.
    FULL = 96

    def __init__(self, parent=None):
        super().__init__(parent)
        self.mode = "ft8"
        self.our_parity = 1
        self.tx_armed = False
        self.keyed = False
        self.setFixedSize(self.FULL, self.FULL)

    def set_diameter(self, d: int) -> None:
        self.setFixedSize(d, d)

    def sizeHint(self):
        return self.minimumSize()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        k = self.width() / self.FULL
        p.scale(k, k)
        slot = SLOT.get(self.mode, 15.0)
        now = time.time()
        n = int(now // slot)
        frac = (now - n * slot) / slot
        ours = (n % 2) == self.our_parity
        r = QRectF(6, 6, self.FULL - 12, self.FULL - 12)
        p.setPen(QPen(theme.c("bg3"), 7, cap=Qt.PenCapStyle.FlatCap))
        p.drawArc(r, 0, 360 * 16)
        col = theme.c("tx") if (self.keyed or (ours and self.tx_armed)) else theme.c("ok")
        p.setPen(QPen(col, 7, cap=Qt.PenCapStyle.RoundCap))
        p.drawArc(r, 90 * 16, -int(frac * 360 * 16))
        p.setFont(theme.font(23, theme.QFont.Weight.Bold, mono=True))
        p.setPen(theme.c("text"))
        left = slot - (now - n * slot)
        p.drawText(QRectF(r.x(), r.y() + 12, r.width(), 30), Qt.AlignmentFlag.AlignCenter, f"{left:.0f}")
        word = "TX" if self.keyed else (self.tr("TX NEXT") if (not ours and self.tx_armed) else "RX")
        parity = self.tr("EVEN") if n % 2 == 0 else self.tr("ODD")
        # Inside the ring's hole whatever the language and text size: at
        # 130 % in the pseudo-locale "[ÉVÉÑ~~]" ran out across the arc.
        inner = r.width() - 2 * 7 - 4
        p.setFont(self.fitted(theme.caps(10), word, inner))
        p.setPen(col)
        p.drawText(QRectF(r.x(), r.y() + 42, r.width(), 13), Qt.AlignmentFlag.AlignCenter, word)
        p.setFont(self.fitted(theme.caps(10), parity, inner - 8))
        p.setPen(theme.c("text3"))
        p.drawText(QRectF(r.x(), r.y() + 55, r.width(), 13), Qt.AlignmentFlag.AlignCenter, parity)

    @staticmethod
    def fitted(font: QFont, text: str, width: float) -> QFont:
        """`font`, made smaller (to 60 % at most) until `text` fits `width`."""
        f = QFont(font)
        size = f.pixelSize()
        least = max(6, int(size * 0.6))
        while size > least and QFontMetricsF(f).horizontalAdvance(text) > width:
            size -= 1
            f.setPixelSize(size)
        return f


class TxRow(QWidget):
    """One of Tx1..Tx6: click to make it the next transmission."""

    def __init__(self, n: int, panel, parent=None):
        super().__init__(parent)
        self.n, self.panel = n, panel
        self.text = ""
        self.current = False
        self.k = Anim(self)
        self.hover = Anim(self)
        self.setFixedHeight(25)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set(self, text: str, current: bool):
        self.text = text
        if current != self.current:
            self.current = current
            self.k.to(1.0 if current else 0.0)
        self.update()

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def mouseReleaseEvent(self, e):
        if self.text:
            self.panel.choose(self.n)

    def tag(self) -> tuple[str, QFont, float]:
        """The row's "Tx6", its font, and where the message starts: after
        the label as drawn, not at a fixed 44 px, which at 130 % or in a
        longer language ran "Tx6" into "CQ"."""
        tag = self.tr("Tx{n}").format(n=self.n)
        f = theme.font(10.5, theme.QFont.Weight.Bold)
        return tag, f, max(44.0, 8 + QFontMetricsF(f).horizontalAdvance(tag) + 10)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        # The row chosen is accent; red only while that over is armed (Enable
        # TX on) or on the air (the overhaul's section 5.3: an idle "CQ
        # NOCALL" outlined in red read as a transmitter left on).
        hot = self.current and self.panel.tx_hot()
        mark = theme.c("tx") if hot else theme.c("accent")
        bg = mix(theme.c("bg2"), theme.c("bg3"), self.hover.value)
        bg = mix(bg, theme.c("tx", 0.22) if hot else theme.c("accent", 0.16), self.k.value)
        p.setPen(QPen(mix(theme.c("line"), mark, self.k.value), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, 5, 5)
        tag, f, x = self.tag()
        p.setFont(f)
        p.setPen(mark if self.current else theme.c("text3"))
        p.drawText(QRectF(8, 0, x - 8, r.height()), Qt.AlignmentFlag.AlignVCenter, tag)
        p.setFont(theme.font(13, theme.QFont.Weight.Medium, mono=True))
        p.setPen(theme.c("text") if self.text else theme.c("text3"))
        p.drawText(QRectF(x, 0, max(0.0, r.width() - x - 6), r.height()), Qt.AlignmentFlag.AlignVCenter,
                   self.text or "—")


class PileupLine(QLabel):
    """The pile-up summary over the band activity (ohscore/pileup.py): one
    line, elided at the panel's width with the whole of it in the tooltip,
    a click putting the station in the DX call."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.full = ""
        self.setObjectName("Muted")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Ignored: the line never widens the panel; it elides instead.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)

    def set_line(self, text: str):
        if text != self.full:
            self.full = text
            self.setToolTip(text)
            self._fit()
        if self.isHidden() == bool(text):
            self.setVisible(bool(text))

    def _fit(self):
        self.setText(self.fontMetrics().elidedText(self.full, Qt.TextElideMode.ElideRight, max(0, self.width())))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit()

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()


# The band activity's text size in pixels (theme.font): what Ctrl and the
# wheel move between, and the second display's fixed large size. The
# default was 13.5 until 16/10/2026, when the FT8 layout gave the list most
# of the window and Ray asked for it to be easier to read; 16 since the
# overhaul (decision 11), the default itself being prefs.py's ft8FontPx.
FONT_MIN, FONT_MAX, FONT_BIG = 11.0, 24.0, 21.0
# DT and Freq give their room to the message, and move into each row's
# tooltip, when the band activity is too narrow to show every column and
# still this many characters of message (the overhaul's Tight rule,
# section 3). The plan said "below 640 px"; that is what this comes to at
# the default 16 px, and it follows Ctrl + wheel and the text size. Judged
# by the list's own width, not the window's tier: beside the QSO card the
# list is only 514 px wide at 1366 x 768 (Compact), where all seven
# columns left the message 44 px.
NARROW_MESSAGE_CHARS = 18
# Decodes kept for the pile-up line: four slots' worth is all it reads.
PILEUP_KEEP_SLOTS = 4


class Ft8Panel(ModePanel):
    # The modes its own band activity and QSO card show; JS8's frames go to
    # its receive-only view (Js8Panel).
    modes = ("ft8", "ft4", "q65")
    COLS = ["UTC", "dB", "DT", "Freq", "", "Message", "Country"]

    def __init__(self, bridge, prefs, parent=None, big: bool = False):
        super().__init__(bridge, prefs, parent)
        self.seq = Sequencer(self.mycall(), self.st("locator") or "")
        self.tx_enabled = False
        self.sent_slot = None
        self.sent_msg = ""
        # What goes next has just been decided (plan_over's `fresh`):
        # "operator" (a click on a station, a Tx row, Enable TX on) or
        # "heard" (auto seq moved on at a decode); "" otherwise. Either may
        # go in the current slot, late-started, and replace an over queued
        # with the old message before it goes on the air; only the
        # operator's also cuts one already on the air. Cleared once sent.
        self.fresh = ""
        self.replacing = False
        self.last_slot_row = None
        self.worked = self._worked_calls()
        self.on_offsets = None          # callback(rx, tx) so the zoom scope can draw them
        self.js8: Js8Panel | None = None    # JS8's view, made the first time JS8 is shown
        self.shown_mode = None
        self.countries = dxcc.load(getattr(bridge.radio, "data_dir", None))
        self.recent: list[dict] = []        # the last few slots' decodes, for the pile-up line
        self.pile_slot = None               # the slot the line was last worked out in
        self.pile: pileup.Pileup | None = None
        self.narrow = False                 # DT and Freq hidden (narrow_below)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)

        act = Card(self.tr("Band activity"))
        self.pile_line = PileupLine()
        self.pile_line.setToolTip("")
        self.pile_line.clicked.connect(self._pile_clicked)
        self.pile_line.hide()
        act.lay.addWidget(self.pile_line)
        self.table = QTableWidget(0, len(self.COLS))
        # UTC, dB and DT are WSJT-X's own column names and stay; the words
        # are translated here, COLS being read before any catalog is loaded.
        heads = list(self.COLS)
        heads[3], heads[5], heads[6] = self.tr("Freq"), self.tr("Message"), self.tr("Country")
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.big = big
        hh = self.table.horizontalHeader()
        for i in range(5):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        # The country rides at the right end, after the message, so the
        # message keeps its place under the eye and its column index.
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Interactive)
        self.set_text_size(FONT_BIG if big else prefs["ft8FontPx"], save=False)
        self.table.setColumnHidden(6, not self.countries)
        if not big:
            # Ctrl and the wheel (or Ctrl + / -) over the list change its
            # text size, as in a browser; the size is kept in ui.json.
            self.table.viewport().installEventFilter(self)
            self.table.installEventFilter(self)
            self.table.setToolTip(self.tr("Ctrl and the mouse wheel, or Ctrl + and Ctrl -, change the text size."))
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        self.table.cellDoubleClicked.connect(self._row_clicked)
        self.table.cellClicked.connect(self._row_clicked)
        act.lay.addWidget(self.table, 1)
        legend = QLabel(self._legend_text(True))
        legend.setObjectName("Faint")
        # Wraps rather than running off the card's edge: a longer language
        # (the pseudo-locale's 40 % more) did not fit one line at 1280 px.
        legend.setWordWrap(True)
        self.legend = legend
        # Which decoder the lines above come from, at the end of the legend:
        # ohsdigi normally, jt9 where it is not built or after it failed
        # (ohscore/modes/ft8.py), so a difference an operator notices can be
        # put down to the right one.
        self.decoder_label = QLabel()
        self.decoder_label.setObjectName("Faint")
        self.decoder_label.setToolTip(self.tr("Settings › Station › FT8 and FT4 decoder chooses which comes "
                                              "first."))
        # Q65's period and submode, which nothing else on the screen says
        # (an FT8 operator's 15 s habit would read the 60 s ring as stuck).
        self.period_note = QLabel()
        self.period_note.setObjectName("Faint")
        self.period_note.setToolTip(self.tr("Q65 submode A with 60 s periods, decoded once 55 s into each "
                                            "period. Averaging over several periods is not offered."))
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.addWidget(legend, 1)
        foot.addWidget(self.period_note)
        foot.addWidget(self.decoder_label)
        act.lay.addLayout(foot)
        self._show_decoder(self.st("ft8DecoderInUse") or "")
        # The list's narrow form (DT and Freq in the tooltip) holds UTC, dB,
        # a short message and the country in this.
        act.setMinimumWidth(300)
        act.installEventFilter(self)
        self.act_card = act
        lay.addWidget(act, 5)

        q = Card(self.tr("QSO"))
        q.lay.setSpacing(5)
        self.qso_card = q
        top = QHBoxLayout()
        top.setSpacing(theme.S3)
        self.ring = SlotRing()
        top.addWidget(self.ring)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(6)
        self.dx = QLineEdit()
        self.dx.setPlaceholderText(self.tr("DX call"))
        self.dx.setFont(theme.font(15, theme.QFont.Weight.Bold, mono=True))
        self.dx.setMinimumWidth(110)
        self.dx.editingFinished.connect(self._dx_edited)
        self.dxgrid = QLineEdit()
        self.dxgrid.setPlaceholderText(self.tr("Grid"))
        self.dxgrid.setFont(theme.font(13.5, mono=True))
        # A six-character locator, whole at any text size (76 px held it
        # at 100 % with nothing to spare).
        self.dxgrid.setFixedWidth(max(76, int(QFontMetricsF(self.dxgrid.font()).horizontalAdvance("IO75RL")) + 18))
        grid.addWidget(self.dx, 0, 0)
        grid.addWidget(self.dxgrid, 0, 1)
        self.period = Segmented([("0", self.tr("Even")), ("1", self.tr("Odd"))], "1", compact=True)
        self.period.setToolTip(self.tr("Which slots we transmit in. Answering a CQ picks the opposite of theirs."))
        self.period.picked.connect(lambda v: setattr(self.ring, "our_parity", int(v)))
        grid.addWidget(self.period, 1, 0, 1, 2)
        self.offsets = QLabel()
        self.offsets.setObjectName("Muted")
        self.offsets.setFont(theme.font(12, mono=True))
        grid.addWidget(self.offsets, 2, 0, 1, 2)
        top.addLayout(grid, 1)
        self.qso_grid = grid
        q.lay.addLayout(top)
        self.rows = [TxRow(n, self) for n in range(1, 7)]
        # The Tx rows scroll when the card is short (1024 x 600, section 3's
        # Tight rule): the DX call above them and Enable TX and Halt TX
        # around them stay in view, and the six rows give way first. At
        # full height the area is as tall as the rows and never scrolls.
        rows = QWidget()
        rl = QVBoxLayout(rows)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(q.lay.spacing())
        for r in self.rows:
            rl.addWidget(r)
        self.rows_area = QScrollArea()
        self.rows_area.setWidget(rows)
        self.rows_area.setWidgetResizable(True)
        self.rows_area.setFrameShape(QScrollArea.Shape.NoFrame)
        self.rows_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.rows_area.setStyleSheet("QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }")
        self.rows_area.setMinimumHeight(2 * self.rows[0].height() + rl.spacing())
        self.rows_area.setMaximumHeight(rows.sizeHint().height())
        q.lay.addWidget(self.rows_area, 1)
        self.shown_next = None              # the Tx row last scrolled into view
        self.rows_area.installEventFilter(self)
        tg = QGridLayout()
        tg.setHorizontalSpacing(theme.S4)
        tg.setVerticalSpacing(2)
        self.enable = Toggle(self.tr("Enable TX"), False, colour="tx")
        self.enable.toggled.connect(self.toggle_tx)
        self.auto = Toggle(self.tr("Auto seq"), prefs["ft8AutoSeq"])
        self.auto.toggled.connect(lambda on: self._pref("ft8AutoSeq", on))
        self.hold = Toggle(self.tr("Hold TX freq"), prefs["ft8HoldTx"])
        self.hold.toggled.connect(lambda on: self._pref("ft8HoldTx", on))
        # WSJT-X's Tx = Rx and Rx = Tx buttons as one switch that stays on
        # (Ray, 16/10/2026): on, the TX offset jumps to the RX offset and a
        # click on either, in the zoom scope or the band activity, moves
        # both. Hold TX freq then has nothing to hold, so it greys out.
        self.lock = Toggle(self.tr("TX = RX"), prefs["ft8TxEqRx"])
        self.lock.setToolTip(self.tr("Transmit on the receive audio frequency, and keep the two together while "
                                     "this is on."))
        self.lock.toggled.connect(self.set_tx_eq_rx)
        self.hold.setEnabled(not self.lock.on)
        tg.addWidget(self.enable, 0, 0)
        tg.addWidget(self.auto, 0, 1)
        tg.addWidget(self.lock, 1, 0)
        tg.addWidget(self.hold, 1, 1)
        q.lay.addLayout(tg)
        # Halt / Log / Clear ride in the card's header: on a 768-line laptop
        # the card has no height to spare for a row of its own.
        bt = QWidget()
        bl = QHBoxLayout(bt)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(6)
        self.halt = HaltButton(self.tr("Halt TX"))
        self.halt.clicked.connect(self.halt_tx)
        self.log_btn = Button(self.tr("Log QSO"), icon="book", small=True)
        self.log_btn.clicked.connect(self.log_now)
        self.clear_btn = Button(self.tr("Clear"), kind="ghost", small=True)
        self.clear_btn.clicked.connect(self.clear_qso)
        for b in (self.halt, self.log_btn, self.clear_btn):
            b.setMinimumWidth(b.sizeHint().width())
            bl.addWidget(b)
        q.set_header_widget(bt)
        # Below the toggles, what the rows cannot use once all six show. No
        # stretch of its own: with one it took half of every spare pixel,
        # and at 1920 x 1080 and 130 % Tx6 was cut off above an empty band.
        q.lay.addStretch(0)
        # The short form (_fit_qso): the card's least height in the full
        # form, measured while it is in it, and which form it is in.
        self.qso_short = False
        self.qso_full_need = 0
        q.installEventFilter(self)
        # As wide as its header's buttons need beside the title (Card._place
        # keeps 90 px for it): narrower, Halt TX slid under Log QSO.
        q.setMinimumWidth(max(300, bt.sizeHint().width() + 2 * theme.S3 + 90))
        q.setMaximumWidth(460)
        lay.addWidget(q, 3)
        self._show_for(self.st("mode"))
        self._refresh()

    # ------------------------------------------------------------ helpers
    def set_text_size(self, px: float, save: bool = True):
        """The band activity's text size: the font, the row height and the
        fixed columns all scale with it, so a larger size reads larger
        rather than clipping. Rows already in the list follow."""
        px = max(FONT_MIN, min(FONT_MAX, round(float(px) * 2) / 2))
        t = self.table
        t.setFont(theme.font(px, mono=True))
        vh = t.verticalHeader()
        old, row = vh.defaultSectionSize(), int(round(px * 1.75))
        vh.setDefaultSectionSize(row)
        for r in range(t.rowCount()):
            if t.rowHeight(r) == old:      # decodes; the slot separators keep theirs
                t.setRowHeight(r, row)
        # Each fixed column from its widest value in the font as drawn
        # (theme.font has the text size in it): scaled from 13.5 px alone,
        # "22:42:15" was cut to "22:42..." at 130 %. The country holds the
        # short names (dxcc Entity.short, fourteen characters at most); the
        # tooltip has the full one. It was sized for "Fed. Rep. of Germany",
        # which took the message's room.
        fm = t.fontMetrics()
        self.col_px = [fm.horizontalAdvance(w) + 18 for w in ("00:00:00", "-20", "+0.0", "2500", "✓")]
        self.col_px.append(fm.horizontalAdvance("Turks & Caicos") + 18)
        for col, w in zip((0, 1, 2, 3, 4, 6), self.col_px):
            t.setColumnWidth(col, w)
        self._fit_columns(self.act_card.width() if hasattr(self, "act_card") else 0)
        if save:
            self._pref("ft8FontPx", px)

    def eventFilter(self, obj, ev):
        if obj is getattr(self, "act_card", None) and ev.type() == QEvent.Type.Resize:
            self._fit_columns(ev.size().width())
            return False
        if obj is getattr(self, "qso_card", None) and ev.type() == QEvent.Type.Resize:
            self._fit_qso(ev.size().height())
            return False
        if obj is getattr(self, "rows_area", None) and ev.type() == QEvent.Type.Resize:
            # A new height shows a different number of rows: bring the one
            # going next back into view once the area has laid itself out
            # (the first scroll, made before the window was shown, had no
            # height to scroll in, and Tx6's CQ sat out of sight).
            QTimer.singleShot(0, self._rescroll)
            return False
        mods = getattr(ev, "modifiers", lambda: Qt.KeyboardModifier.NoModifier)()
        if mods & Qt.KeyboardModifier.ControlModifier:
            px = self.prefs["ft8FontPx"]
            if ev.type() == QEvent.Type.Wheel and ev.angleDelta().y():
                self.set_text_size(px + (1 if ev.angleDelta().y() > 0 else -1))
                return True
            if ev.type() == QEvent.Type.KeyPress and ev.key() in (Qt.Key.Key_Plus, Qt.Key.Key_Equal,
                                                                  Qt.Key.Key_Minus):
                self.set_text_size(px + (-1 if ev.key() == Qt.Key.Key_Minus else 1))
                return True
        return super().eventFilter(obj, ev)

    def _fit_qso(self, height: int) -> None:
        """The QSO card's short form, for a card shorter than its full form
        needs (Radio at 1024 x 600 under the band buttons, or any panel
        with a line above it saying what the mode is missing): a smaller
        slot ring, the offsets line left to the zoom scope's RX and TX
        flags, which say the same, and the Tx rows down to one, scrolled
        to the one going next. The header's Halt TX, the DX call and Enable
        TX stay in view whatever the height. Judged against the full
        form's own least height, so the form a size gets never depends on
        the form it had before."""
        if not self.qso_short:
            self.qso_full_need = self.qso_card.minimumSizeHint().height()
        short = height < self.qso_full_need
        if short == self.qso_short:
            return
        self.qso_short = short
        row = self.rows[0].height()
        spacing = self.rows_area.widget().layout().spacing()
        self.ring.set_diameter(72 if short else SlotRing.FULL)
        self.offsets.setVisible(not short)
        self.qso_grid.setVerticalSpacing(4 if short else 6)
        self.rows_area.setMinimumHeight(row if short else 2 * row + spacing)

    def _rescroll(self) -> None:
        self.shown_next = None
        self._show_next_row()

    def _show_next_row(self) -> None:
        """Scroll the Tx rows to the one going next when that changes (not
        on every refresh, which would undo the operator's own scrolling)."""
        nxt = self.seq.next
        if nxt == self.shown_next or not 1 <= nxt <= len(self.rows):
            return
        self.shown_next = nxt
        self.rows_area.ensureWidgetVisible(self.rows[nxt - 1], 0, 0)

    def narrow_below(self) -> int:
        """The band activity's width under which DT and Freq hide: every
        column, NARROW_MESSAGE_CHARS of message, the frame and scroll bar."""
        msg = self.table.fontMetrics().horizontalAdvance("0" * NARROW_MESSAGE_CHARS)
        return sum(self.col_px) + msg + 48

    def _fit_columns(self, width: int):
        """The Tight rule (narrow_below): DT and Freq hide, every decode's
        tooltip has them, and the message keeps the room. The ✓ column goes
        with them (a station worked before is dimmed anyway, and its row's
        tooltip says so), and the country shrinks towards eight characters,
        eliding (its tooltip has the full name), before the message is
        squeezed under a scroll bar."""
        narrow = width < self.narrow_below()
        if narrow != self.narrow:
            self.narrow = narrow
            for col in (2, 3, 4):
                self.table.setColumnHidden(col, narrow)
        fm = self.table.fontMetrics()
        rest = self.col_px[5]
        if narrow:
            rest = width - 48 - self.col_px[0] - self.col_px[1] - fm.horizontalAdvance("0" * NARROW_MESSAGE_CHARS)
        # Narrower still (1180 x 700 with the rail showing leaves the list
        # 300 px): the country shrinks to eight characters, then goes (every
        # row's tooltip names it), before the message loses another letter.
        least = fm.horizontalAdvance("0" * 8) + 18
        self.table.setColumnHidden(6, rest < least or not self.countries)
        self.table.setColumnWidth(6, max(least, min(self.col_px[5], rest)))

    def tx_hot(self) -> bool:
        """Whether what this panel sends is armed or on the air: Halt TX and
        the chosen Tx row are red only then."""
        return self.tx_enabled or bool(self.st("keyed")) or bool(self.bridge.face.on_air(self.bridge.st))

    def _legend_text(self, answer: bool) -> str:
        """The colour key under the band activity, with the click hint or
        (a mirror, which cannot answer) without: two whole lines, so a
        translation is never cut at an English phrase."""
        t = theme.t()
        if answer:
            s = self.tr("<span style='color:{cq}'>■</span> CQ &nbsp;&nbsp;<span style='color:{mine}'>■</span> to "
                        "you &nbsp;&nbsp;<span style='color:{worked}'>✓</span> worked before &nbsp;&nbsp;click a "
                        "line to answer it")
        else:
            s = self.tr("<span style='color:{cq}'>■</span> CQ &nbsp;&nbsp;<span style='color:{mine}'>■</span> to "
                        "you &nbsp;&nbsp;<span style='color:{worked}'>✓</span> worked before")
        # The placeholder keeps its name ("mine") so the catalogs' strings
        # stay as they are; the colour is the gold of decision 8.
        return s.format(cq=t["cq"], mine=t["toYou"], worked=t["text3"])

    def _pref(self, k, v):
        self.prefs[k] = v
        self.prefs.save()

    def _worked_calls(self) -> set:
        try:
            return {e.get("call", "").upper() for e in self.bridge.radio.log_entries()}
        except Exception:  # noqa: BLE001
            return set()

    def mode(self):
        m = self.st("mode")
        return m if m in SLOT else "ft8"

    def transmits(self) -> bool:
        """Whether the mode showing is one this app sends."""
        return slot_spec(self.mode()).transmits

    def _sequenced(self) -> bool:
        """Whether this panel's own QSO sequencer sends the mode showing
        (FT8, FT4, Q65); JS8's view sends its own messages."""
        return self.mode() in self.modes and self.transmits()

    def _show_for(self, mode: str):
        """Show FT8's list and QSO card, or JS8's receive-only view, for
        `mode`. Only shows and hides: the views are made once and keep
        their rows, so going back to a mode finds its list as it was."""
        if mode not in SLOT or mode == self.shown_mode:
            return
        changed = self.shown_mode is not None
        self.shown_mode = mode
        js8 = mode in Js8Panel.modes
        if js8:
            self._js8_view()
        if self.js8 is not None:
            self.js8.setVisible(js8)
        self.act_card.setVisible(not js8)
        self.qso_card.setVisible(not js8 and not self.mirror)
        self.period_note.setText(self.tr("Q65-60A · 60 s periods") if mode == "q65" else "")
        if changed and (self.tx_enabled or (self.js8 is not None and self.js8.tx_enabled)):
            # A QSO set going in one mode does not carry on in another: FT8's
            # next over must not go out as a minute of Q65, and JS8 sends
            # nothing. An over of ours already queued is the old mode's
            # audio (the engine re-checks a keyed over on a mode change but
            # does not end it), so it is halted, as Enable TX off does.
            self.set_tx_enabled(False)
            if self.js8 is not None:
                # A JS8 message part sent stays unsent: leaving JS8 drops it.
                self.js8.pending, self.js8.nframes, self.js8.part = "", 0, 0
                self.js8.set_tx_enabled(False)
            self.fresh = ""
            if self.st("keyed") and not self.mirror:
                self.bridge.halt()

    def _js8_view(self) -> Js8Panel:
        if self.js8 is None:
            self.js8 = Js8Panel(self.bridge, self.prefs, self, big=self.big,
                                font_px=FONT_BIG if self.big else self.prefs["ft8FontPx"])
            self.js8.on_pick = lambda df: self.set_offsets(rx=df)
            if self.mirror:
                self.js8.set_mirror()
            self.js8.hide()
            self.layout().addWidget(self.js8, 8)
        return self.js8

    def _refresh(self):
        self.seq.mycall = self.mycall()
        self.seq.mygrid = (self.st("locator") or "")[:4].upper()
        msgs = self.seq.messages()
        for r in self.rows:
            r.set(msgs.get(r.n, ""), r.n == self.seq.next)
        self._show_next_row()
        if self.dx.text().upper() != self.seq.dx and not self.dx.hasFocus():
            self.dx.setText(self.seq.dx)
        if not self.dxgrid.hasFocus():
            self.dxgrid.setText(self.seq.dxgrid)
        if (self.st("dxCall") or "") != self.seq.dx:
            # The decoder steers jt9's a-priori passes by it (ft8._jt9_call).
            self.bridge.set(quiet=True, dxCall=self.seq.dx)
        rx, tx = self.prefs["ft8RxOffset"], self.prefs["ft8TxOffset"]
        self.offsets.setText(self.tr("RX {rx} Hz   TX {tx} Hz").format(rx=f"{rx:.0f}", tx=f"{tx:.0f}"))
        self.ring.tx_armed = self.tx_enabled
        self.ring.mode = self.mode()
        # The DX call or our call may have changed what the line says.
        self._show_pileup()
        if self.on_offsets:
            # No TX mark for a mode that does not transmit (JS8): the zoom
            # scope draws what it is given.
            self.on_offsets(rx, tx if self.transmits() else None)

    def set_offsets(self, rx=None, tx=None):
        if not self.transmits():
            # A mode this app does not send: a TX offset alone (a Shift +
            # click on the zoom scope) means nothing; TX = RX still keeps
            # the two together.
            tx = None
        if self.lock.on and (rx is not None or tx is not None):
            # Locked: whichever moved, both go there (RX when both are given).
            rx = tx = rx if rx is not None else tx
        if rx is not None:
            self.prefs["ft8RxOffset"] = float(rx)
        if tx is not None:
            self.prefs["ft8TxOffset"] = float(tx)
        self.prefs.save()
        self._refresh()

    def set_tx_eq_rx(self, on: bool):
        """TX = RX on or off (the switch, or anything else that wants it)."""
        self.lock.set_on(on)
        self._pref("ft8TxEqRx", bool(on))
        self.hold.setEnabled(not on)
        if on:
            self.set_offsets(rx=self.prefs["ft8RxOffset"])
        else:
            self._refresh()

    def choose(self, n: int):
        self.seq.next = n
        self.fresh = "operator"
        self._refresh()

    def set_tx_enabled(self, on: bool):
        if self.js8 is not None and self.mode() in Js8Panel.modes:
            # JS8 showing: its own Enable TX. Off is Escape's way in
            # (BaseWindow.unkey_all), which stops queued text too, so the
            # rest of the message is dropped; the window halts the air.
            if not on:
                self.js8.pending, self.js8.nframes, self.js8.part = "", 0, 0
            self.js8.set_tx_enabled(on)
        self.tx_enabled = bool(on) and self._sequenced()
        self.enable.set_on(self.tx_enabled)
        self._refresh()

    def toggle_tx(self, on: bool):
        """The operator's Enable TX. Switched off during an over it ends the
        over too, as the store form's Enable TX off does (autotx.py) and as
        Brian asked for CAT PTT on 12/10/2026: off means the radio is not
        keyed. (WSJT-X lets the over finish; so does the panel itself when it
        switches Enable TX off after sending 73 - that goes through
        set_tx_enabled, not here.)"""
        self.set_tx_enabled(on)
        self.fresh = "operator" if on else ""
        # Any over on the air while this panel is showing is, in practice,
        # its own send; and Enable TX off is "stop transmitting" either way.
        if not on and self.st("keyed"):
            self.bridge.halt()

    def halt_tx(self):
        # Halt means now, not after the radio has sent what it holds.
        self.set_tx_enabled(False)
        if self.st("keyed"):
            self.bridge.halt()

    def clear_qso(self):
        self.seq.reset()
        self.dx.clear()
        self.dxgrid.clear()
        self._refresh()

    def _dx_edited(self):
        call = self.dx.text().strip().upper()
        if call and call != self.seq.dx:
            self.seq.answer(call, self.dxgrid.text().strip())
            self.fresh = "operator"
            self._abandon_pending()
            self._refresh()

    def log_now(self):
        if not self.seq.dx:
            self.bridge.say(self.tr("Nothing to log: no DX call"), "info")
            return
        try:
            self.bridge.radio.log_qso(self.seq.dx, mode=self.mode(), rstSent=self.seq.sent,
                                      rstRcvd=self.seq.rcvd, grid=self.seq.dxgrid)
        except ValueError as e:
            self.bridge.say(str(e))
            return
        self.worked.add(self.seq.dx)
        self.bridge.say(self.tr("Logged {call} ({mode}, sent {sent}, rcvd {rcvd})").format(
            call=self.seq.dx, mode=self.mode().upper(), sent=self.seq.sent, rcvd=self.seq.rcvd or '?'), "info")

    # ------------------------------------------------------------ decodes
    def _add_row(self, cells: list[str], fg: QColor | None = None, bg: QColor | None = None, data=None,
                 sep: bool = False):
        t = self.table
        at_bottom = t.verticalScrollBar().value() >= t.verticalScrollBar().maximum() - 2
        r = t.rowCount()
        t.insertRow(r)
        for i, txt in enumerate(cells):
            it = QTableWidgetItem(txt)
            if fg is not None:
                it.setForeground(QBrush(fg))
            if bg is not None:
                it.setBackground(QBrush(bg))
            if data is not None:
                it.setData(Qt.ItemDataRole.UserRole, data)
            if i in (1, 2, 3):
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if sep:
                it.setFlags(Qt.ItemFlag.NoItemFlags)
                it.setBackground(QBrush(theme.c("bg3")))
                it.setFont(theme.font(11, theme.QFont.Weight.DemiBold, mono=True))
            t.setItem(r, i, it)
        if sep:
            t.setRowHeight(r, 18)
        if t.rowCount() > 600:
            t.removeRow(0)
        if at_bottom:
            t.scrollToBottom()

    def on_event(self, ev):
        mode = ev.get("mode")
        if mode in Js8Panel.modes:
            self._js8_view().on_event(ev)
            return
        if mode not in self.modes or "text" not in ev:
            return
        text, mine = self._show_decode(ev)
        if mine and self.auto.on:
            res = self.seq.heard(text, ev.get("snr"))
            if res["next"] is not None:
                if res["new_dx"] and not self.tx_enabled:
                    self.bridge.say(self.tr("{call} is calling you").format(call=res['new_dx']), "info")
                if res["log"]:
                    self.log_now()
                    self.tx_enabled = False
                    self.enable.set_on(False)
                    # Their 73 after our RR73: the RR73 repeat queued for
                    # our next slot has nothing left to say.
                    self._abandon_pending()
                elif self.seq.message() != self.sent_msg:
                    # The decode changed what we say. With the early decode
                    # (13.5 s into their slot, ohscore/modes/ft8.py) it lands
                    # just before our slot, after the over for that slot was
                    # queued (2.5 s into theirs) with the old message: until
                    # 16/10/2026 that stale over went out and the answer
                    # waited a whole cycle more, so every QSO took twice its
                    # time. Now it is replaced if not yet on the air.
                    self.fresh = self.fresh or "heard"
                self._refresh()

    def _show_decode(self, ev) -> tuple[str, bool]:
        """Add a decode's row (and its slot's separator) to the band
        activity; (its text, whether it names us)."""
        slot = float(ev.get("slot") or ev.get("t") or time.time())
        if slot != self.last_slot_row:
            self.last_slot_row = slot
            stamp = time.strftime("%H:%M:%S", time.gmtime(slot))
            self._add_row([stamp, "", "", "", "", "", ""],
                          fg=theme.c("text3"), sep=True)
        text = ev["text"]
        words = text.upper().split()
        mine = bool(self.mycall()) and self.mycall() in words
        cq = words[:1] == ["CQ"]
        call = (ev.get("call") or "").upper()
        worked = call in self.worked
        fg, bg = None, None
        if mine:
            # Gold, not WSJT-X's pink-red: red is for being on the air
            # (decision 8).
            fg, bg = theme.c("text"), theme.c("toYou", 0.28)
        elif cq:
            fg, bg = theme.c("text"), theme.c("cq", 0.16)
        if worked and not mine:
            fg = theme.c("text3")
        ent = self.countries.lookup(call) if call else None
        dt, df = f"{ev.get('dt', 0.0):+.1f}", f"{ev.get('df', 0):d}"
        self._add_row([time.strftime("%H:%M:%S", time.gmtime(slot)), f"{ev.get('snr', 0):+d}", dt, df,
                       "✓" if worked else "", text, ent.short if ent else ""],
                      fg=fg, bg=bg, data=dict(ev))
        # DT and Freq ride in every cell's tooltip, so the narrow list (which
        # hides their columns) still has them under the pointer.
        tip = self.tr("DT {dt} s · {df} Hz").format(dt=dt, df=df)
        if worked:
            tip += "\n" + self.tr("Worked before")
        r = self.table.rowCount() - 1
        for i in range(6):
            # The country too: a narrow list hides its column.
            self.table.item(r, i).setToolTip(ent.name + "\n" + tip if ent else tip)
        if ent:
            self.table.item(r, 6).setToolTip(
                self.tr("{call}: {country} ({continent}, prefix {prefix})").format(
                    call=call, country=ent.name, continent=ent.continent, prefix=ent.prefix) + "\n" + tip)
        self._note_for_pileup(ev, slot)
        return text, mine

    # ------------------------------------------------------------ pile-up
    def _note_for_pileup(self, ev: dict, slot: float):
        period = SLOT.get(ev.get("mode"), 15.0)
        self.recent.append({"slot": slot, "text": ev.get("text", ""), "snr": ev.get("snr", 0),
                            "call": ev.get("call") or "", "mode": ev.get("mode")})
        keep = slot - PILEUP_KEEP_SLOTS * period
        self.recent = [d for d in self.recent if d["slot"] > keep and d["mode"] == ev.get("mode")]
        self._show_pileup()

    def _show_pileup(self, now: float | None = None):
        """The pile-up line for the decodes kept, the DX call and our last
        over; hidden when there is none, and for a mode that is not FT8,
        FT4 or Q65."""
        mode = self.mode()
        p = None
        decodes = [d for d in self.recent if d["mode"] == mode]
        now = self._clock() if now is None else now
        # Our last over counts as calling while it is as recent as the
        # decodes kept; one from an hour ago says nothing about this pile-up.
        sent = self.sent_msg if self.sent_slot is not None and \
            now - self.sent_slot * SLOT[mode] < PILEUP_KEEP_SLOTS * SLOT[mode] else ""
        if mode in self.modes and decodes:
            p = pileup.summarise(decodes, SLOT[mode], self.mycall(), self.seq.dx, sent, now=now)
        self.pile = p
        self.pile_line.set_line(self._pile_text(p) if p is not None else "")

    def _clock(self) -> float:
        """UTC as the decodes count it: a recording being played decodes in
        the time it was recorded (Engine._audio_utc), so its pile-up would
        age out at once against the wall clock."""
        if self.st("playing") and self.st("playUtc"):
            return float(self.st("playUtc"))
        return time.time()

    def _pile_text(self, p: "pileup.Pileup") -> str:
        ent = self.countries.lookup(p.dx)
        who = f"{p.dx} ({ent.short})" if ent else p.dx
        calls = ", ".join(f"{c} {s:+d}" for c, s in p.shown)
        if p.more:
            calls = self.tr("{calls}, +{n} more").format(calls=calls, n=p.more)
        you = {pileup.ANSWERED: self.tr("answered you"), pileup.HEARD: self.tr("you: heard here"),
               pileup.CALLING: self.tr("you: calling"), pileup.NOT: self.tr("you: not calling")}[p.you]
        line = self.tr("Pile-up: {who} · {n} calling: {calls}").format(who=who, n=p.count, calls=calls)
        if p.working:
            line += " · " + self.tr("working {call}").format(call=p.working)
        return line + " · " + you

    def _pile_clicked(self):
        """The station goes in the DX call, as typing it would; nothing is
        sent. Not while Enable TX is on: a stray click on a summary line must
        not turn an over going to one station towards another."""
        p = self.pile
        if p is None or p.dx == self.seq.dx or self.mirror:
            return
        if self.tx_enabled:
            self.bridge.say(self.tr("Enable TX is on: switch it off to pick {call}").format(call=p.dx), "info")
            return
        self.seq.answer(p.dx, "")
        self._refresh()

    def carry_from(self, other: "Ft8Panel"):
        """The window was rebuilt (a theme change): the band activity the
        old panel showed, replayed row by row from the decodes each row
        keeps, so the colours are this theme's (adopt, for a mirror,
        copies the rows as they are). Only the rows: the QSO sequence is
        not handed on, so nothing a decode would set going is replayed."""
        o = other.table
        for r in range(o.rowCount()):
            it = o.item(r, 5)
            ev = it.data(Qt.ItemDataRole.UserRole) if it is not None else None
            if ev:
                self._show_decode(ev)
        self.table.scrollToBottom()
        if other.js8 is not None:
            self._js8_view().carry_from(other.js8)

    def _row_clicked(self, row, _col):
        if self.mirror:
            return
        it = self.table.item(row, 5)
        ev = it.data(Qt.ItemDataRole.UserRole) if it else None
        if not ev:
            return
        # The station, not a CQ's modifier: "CQ DX OH8ZZ KP20" is OH8ZZ.
        call, grid = sender(ev.get("text", ""), ev.get("call") or "")
        if not call or call == self.mycall():
            return
        self.seq.answer(call, ev.get("grid") or grid, ev.get("snr"))
        # Transmit in the other parity from theirs.
        slot_len = SLOT.get(ev.get("mode"), 15.0)
        their = int(round(float(ev.get("slot", time.time())) / slot_len)) % 2
        ours = 1 - their
        self.period.set_value(str(ours))
        self.ring.our_parity = ours
        self.set_offsets(rx=ev.get("df"), tx=None if self.hold.on else ev.get("df"))
        # A new QSO: whatever was queued for the old one (the RR73 or 73 the
        # sequencer repeats until the other station's 73 arrives) is
        # abandoned, as WSJT-X abandons it, and the call goes in the very
        # next slot of ours - this one, if it is ours and young enough.
        self.fresh = "operator"
        self._abandon_pending()
        self.set_tx_enabled(True)

    def on_state(self, ch):
        if "mode" in ch:
            self._show_for(ch["mode"])
        if "callsign" in ch or "locator" in ch or "mode" in ch:
            self._refresh()
        if self.js8 is not None:
            self.js8.on_state(ch)
        if "ft8DecoderInUse" in ch:
            self._show_decoder(ch["ft8DecoderInUse"] or "")

    def _show_decoder(self, name: str) -> None:
        self.decoder_label.setText(self.tr("decoder: {name}").format(name=name) if name else "")

    def set_mirror(self):
        super().set_mirror()
        self.qso_card.hide()
        self.legend.setText(self._legend_text(False))
        if self.js8 is not None:
            self.js8.set_mirror()

    def adopt(self, other: "Ft8Panel"):
        """Start a mirror with the band activity the main panel already has."""
        t, o = self.table, other.table
        for r in range(o.rowCount()):
            t.insertRow(t.rowCount())
            for c in range(o.columnCount()):
                it = o.item(r, c)
                if it is not None:
                    n = it.clone()
                    n.setFont(t.font() if not (it.flags() == Qt.ItemFlag.NoItemFlags) else it.font())
                    t.setItem(t.rowCount() - 1, c, n)
            if o.rowHeight(r) != o.verticalHeader().defaultSectionSize():
                t.setRowHeight(t.rowCount() - 1, int(o.rowHeight(r) * 1.4))
        self.last_slot_row = other.last_slot_row
        t.scrollToBottom()
        if other.js8 is not None:
            self._js8_view().adopt(other.js8)

    def next_over_at(self) -> float | None:
        """While Enable TX is on: when our next over is due (UTC seconds),
        for the window's ARMED countdown; else None."""
        if self.js8 is not None and self.mode() in Js8Panel.modes:
            return self.js8.next_over_at()
        if self.mirror or not self.tx_enabled:
            return None
        mode = self.mode()
        slot = SLOT[mode]
        now = time.time()
        cur = int(now // slot)
        if cur % 2 == int(self.period.value) and self.fresh and now - cur * slot <= late_until(mode):
            return now
        n = cur + 1
        if n % 2 != int(self.period.value):
            n += 1
        return n * slot

    def _tx_idle(self) -> bool:
        idle = getattr(self.bridge.radio, "tx_idle", None)
        return idle() if callable(idle) else not self.st("keyed")

    def _abandon_pending(self):
        """Drop an over that is queued but not yet on the air: the operator
        has moved on to another station, and its message is for the old
        one. One already on the air is left to plan_over: replaced while a
        late start is still possible, else allowed to finish, since cutting
        it then would not bring the new QSO's first over any sooner."""
        if self.mirror or self.sent_slot is None:
            return
        if self.st("keyed") and not self.bridge.st.get("txOnAir"):
            self.replacing = True
            self.bridge.halt()

    def tick(self, dt):
        # TX on the ring when radiating, not when queued: the over is queued
        # 2.5 s into the slot before, which then read TX, not TX NEXT.
        self.ring.keyed = self.bridge.face.on_air(self.bridge.st)
        self.ring.update()
        k = int(self._clock() // SLOT[self.mode()])
        if k != self.pile_slot:
            # A new slot: callers age out of the line even with no decodes.
            self.pile_slot = k
            self._show_pileup()
        if not self.mirror:
            hot = self.halt.hot
            self.halt.show_state(self.tx_enabled, self.bridge)
            if hot != self.halt.hot:
                for r in self.rows:
                    r.update()
        if self.js8 is not None and self.mode() in Js8Panel.modes:
            self.js8.tick(dt)
            return
        if self.mirror or not self.tx_enabled or not self._sequenced():
            return
        mode = self.mode()
        slot = SLOT[mode]
        ours = int(self.period.value)
        now = time.time()
        queue_at = slot_spec(mode).queue_at
        cur = int(now // slot)
        if not self.fresh and cur % 2 != ours and now - cur * slot < queue_at:
            # Their slot, and what we say next may yet change with its
            # decodes: wait for them. plan_over's own wait is capped at a
            # quarter of the slot (FT4's 7.5 s), which for Q65 would queue
            # 45 s before the decode that decides the message.
            return
        k = plan_over(now, slot, ours, self.sent_slot, bool(self.fresh), late_until(mode), decode_wait=queue_at)
        if k is None:
            return
        n = self.seq.next
        msg = self.seq.message()
        if not self._tx_idle():
            if k == self.sent_slot and self.fresh:
                on_air = bool(self.bridge.st.get("txOnAir"))
                if msg == self.sent_msg or (on_air and self.fresh != "operator"):
                    # What is queued says it already; or it is on the air
                    # and nobody asked for it to be cut - a decode alone
                    # does not key the radio down and up again.
                    self.fresh = ""
                elif not self.replacing:
                    # Queued (or, the operator's choice, just on the air)
                    # with the old message, and still early enough to start
                    # the new one in its place.
                    self.replacing = True
                    self.bridge.halt()
            return
        self.sent_slot = k
        self.sent_msg = msg
        self.fresh = ""
        self.replacing = False
        if self.bridge.send(mode, text=msg, freq=self.prefs["ft8TxOffset"], period="even" if ours == 0 else "odd",
                            late_start=True):
            # Our own over in the `own` gold (the colour that already means
            # "our signal"): red is kept for the air itself (section 5.3).
            self._add_row([time.strftime("%H:%M:%S", time.gmtime(k * slot)), "", "",
                           f"{self.prefs['ft8TxOffset']:.0f}", "", "TX  " + msg], fg=theme.c("own"))
            self._show_pileup()
            if self.seq.sent_now(n):
                self.log_now()
            if n == 5:
                self.set_tx_enabled(False)
        else:
            self.set_tx_enabled(False)
