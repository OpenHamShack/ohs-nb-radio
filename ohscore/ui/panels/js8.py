"""JS8: the band activity, one row per message, and sending a message.

JS8 sends a message as a run of frames, one per period, each event
saying whether it is the message's first or last (ohscore/modes/js8.py:
`first`, `last`, `kind`, `call`, `to`). FT8's list shows one row per
decode, which for JS8 would scatter "GM4BRI: HB9XYZ", "HELLO THERE HOW ARE"
and "YOU TODAY" over three rows a quarter of a minute apart among
everyone else's; here they are joined back into the one line JS8Call
shows, the row growing as each frame arrives.

Sending (Brian, 17/10/2026): a message typed or made by a button (CQ,
heartbeat, a reply to the station picked) is queued; with Enable TX on,
its frames go out one per period from the next period on, each its own
over through the engine's send() and so through the same guard as FT8's
(ohscore/modes/js8.py says why one frame per over). Enable TX off or Halt
TX ends it, cutting a frame on the air, as the FT8 panel's do; Escape
reaches it through the slot panel's set_tx_enabled. JS8 has no QSO
sequence to automate, so there are no Tx rows: JS8Call's own operating is
typing to a station.

The panel lives inside the slot panel (Ft8Panel shows it in place of its
band activity and QSO card while the mode is JS8), so the window's
slot-mode wiring - the zoom scope's RX and TX marks and their clicks, the
waterfall labels, the Digital layout, the ARMED countdown - serves JS8 as
it serves FT8.

The UI overhaul of October 2026, section 5.1 (docs/ui-overhaul-2026-10.md).
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QBrush
from PyQt6.QtWidgets import (QAbstractItemView, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                             QTableWidget, QTableWidgetItem, QWidget)

from .. import theme
from ..controls import Button, Card, Segmented, Toggle
from ...modegroups import JS8_DEFAULT_SPEED, JS8_SPEEDS
from .common import ModePanel
from .halt import HaltButton

# Two frames are one message's when their audio offsets are this close.
# A station's frames all go out on one offset (JS8Call keeps it fixed for
# the message), and the decoder reads each to the nearest hertz, so a few
# hertz is drift and rounding; 10 Hz is under two of JS8 Normal's 6.25 Hz
# tones, so two stations would have to overlap to be confused.
SAME_OFFSET_HZ = 10.0
# Rows kept, as the FT8 list keeps 600 lines.
MAX_ROWS = 400


@dataclass
class Js8Message:
    """One message as frames arrive: what its row shows."""
    slot: float                  # the first frame's period start (UTC s)
    last_slot: float             # the latest frame's
    snr: int
    dt: float
    df: float
    call: str = ""
    to: str = ""
    kind: str = ""
    speed: str = JS8_DEFAULT_SPEED
    parts: list = field(default_factory=list)
    started: bool = True         # its first frame was heard
    done: bool = False           # its last frame was heard

    def text(self) -> str:
        """The message as JS8Call shows it, without the sender's "CALL: "
        (the From column has it), one space between words, and an ellipsis
        at either end that was not heard."""
        s = " ".join("".join(self.parts).split())
        if self.call and s.startswith(self.call + ":"):
            s = s[len(self.call) + 1:].lstrip()
        if not self.started:
            s = "… " + s
        if not self.done:
            s += " …"
        return s

    def heartbeat(self) -> bool:
        # A CQ is a heartbeat-kind frame too ("@ALLCALL CQ CQ CQ"); only
        # "@HB" ones are the automatic beacons the filter hides.
        return self.kind == "heartbeat" and "@HB" in "".join(self.parts).upper().split()


def frame_text(ev: dict) -> str:
    """A frame's text as JS8Call joins it. The engine's events carry it
    trimmed (ohscore/modes/js8.py), which loses the space a frame ends with:
    "HELLO FROM BERLIN TNX " and "FOR THE QSO" would join as "TNXFOR". A
    frame can as well end inside a word, so the space cannot be put back by
    rule; the event's raw frame is read again (ohsdigi's js8_unpack, which
    decoded it) for the text untrimmed. Without ohsdigi the event's own text
    is used: then it is js8's raw frame anyway."""
    frame, i3 = ev.get("frame"), ev.get("i3bit")
    if frame and i3 is not None:
        try:
            from ...modes import js8 as js8mode
            lb = js8mode._OHSDIGI_JS8
            if lb is not None:
                return str(lb.js8_unpack(str(frame), int(i3))["text"])
        except Exception:  # noqa: BLE001 - a frame ohsdigi cannot read shows as the engine gave it
            pass
    return str(ev.get("text") or "")


def join_frame(open_msgs: list[Js8Message], ev: dict, period: float | None = None) -> tuple[Js8Message, bool]:
    """Add one decoded frame to the messages still open (those whose last
    frame has not come), as JS8Call joins them: the message at the same
    speed and offset whose latest frame was in the period before this one
    (or this one), unless this frame starts a new message. `period` is the
    frame's speed's unless given. Returns (the message, whether it is new);
    `open_msgs` is updated in place."""
    speed = ev.get("speed") if ev.get("speed") in JS8_SPEEDS else JS8_DEFAULT_SPEED
    period = JS8_SPEEDS[speed].period if period is None else period
    slot = float(ev.get("slot") or ev.get("t") or time.time())
    df = float(ev.get("df") or 0)
    first, last = bool(ev.get("first", True)), bool(ev.get("last", True))
    match = None
    for m in open_msgs:
        if m.speed == speed and abs(m.df - df) <= SAME_OFFSET_HZ and 0.0 <= slot - m.last_slot <= period * 1.5:
            match = m
            break
    if match is not None and first:
        # A new message where an unfinished one stood: that one's end was
        # never heard, and stays open-ended on its row.
        open_msgs.remove(match)
        match = None
    new = match is None
    if new:
        match = Js8Message(slot=slot, last_slot=slot, snr=int(ev.get("snr") or 0), dt=float(ev.get("dt") or 0.0),
                           df=df, speed=speed, started=first)
        open_msgs.append(match)
    match.last_slot = slot
    match.parts.append(frame_text(ev))
    match.call = match.call or (ev.get("call") or "").upper()
    match.to = match.to or (ev.get("to") or "").upper()
    match.kind = match.kind or str(ev.get("kind") or "")
    if last:
        match.done = True
        open_msgs.remove(match)
    # A message whose next frame is overdue is over, heard or not.
    for m in list(open_msgs):
        if slot - m.last_slot > JS8_SPEEDS[m.speed].period * 1.5:
            open_msgs.remove(m)
    return match, new


class Js8Panel(ModePanel):
    modes = ("js8",)
    COLS = ["UTC", "dB", "DT", "Freq", "Speed", "From", "Text"]
    FROM, TEXT = 5, 6

    def __init__(self, bridge, prefs, parent=None, big: bool = False, font_px: float = 16.0):
        super().__init__(bridge, prefs, parent)
        self.big = big
        # What we send at, as last chosen (ui.json js8Speed); a speed this
        # version does not know falls back to Normal.
        saved = prefs.get("js8Speed", JS8_DEFAULT_SPEED)
        self.speed = saved if saved in JS8_SPEEDS else JS8_DEFAULT_SPEED
        self.open_msgs: list[Js8Message] = []
        self.msgs: list[Js8Message] = []        # one per row, in row order
        self.events: list[dict] = []            # every frame shown, for a rebuild or a mirror to replay
        self.on_pick = None                     # callback(df): a row was clicked, move the RX offset there
        # Sending: the message queued, its frame count, the next frame to
        # send and the period the last one was queued for.
        self.tx_enabled = False
        self.pending = ""
        self.nframes = 0
        self.part = 0
        self.sent_period = None
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        act = Card(self.tr("JS8 band activity"))
        self.card = act
        self.table = QTableWidget(0, len(self.COLS))
        heads = list(self.COLS)
        # UTC, dB and DT are the column names JS8Call and WSJT-X use.
        heads[3], heads[4], heads[5], heads[6] = self.tr("Freq"), self.tr("Speed"), self.tr("From"), self.tr("Text")
        self.table.setHorizontalHeaderLabels(heads)
        self.table.verticalHeader().hide()
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.table.horizontalHeader()
        hh.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        for i in range(6):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
        hh.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        self.set_text_size(font_px)
        self.table.cellClicked.connect(self._row_clicked)
        act.lay.addWidget(self.table, 1)
        foot = QHBoxLayout()
        foot.setContentsMargins(0, 0, 0, 0)
        foot.setSpacing(theme.S4)
        self.only_me = Toggle(self.tr("Only to me"), False)
        self.only_me.setToolTip(self.tr("Show only messages addressed to your callsign."))
        self.only_me.toggled.connect(lambda _on: self._apply_filter())
        self.show_hb = Toggle(self.tr("Heartbeats"), True)
        self.show_hb.setToolTip(self.tr("Show the automatic @HB heartbeats stations send while they listen."))
        self.show_hb.toggled.connect(lambda _on: self._apply_filter())
        foot.addWidget(self.only_me)
        foot.addWidget(self.show_hb)
        foot.addStretch(1)
        act.lay.addLayout(foot)
        act.setMinimumWidth(360)
        lay.addWidget(act, 5)
        # The message text wants the width: the send card takes the least
        # that holds its buttons (1366 x 768 cut the text to its first word).
        lay.addWidget(self._send_card(), 2)

    def _send_card(self) -> Card:
        c = Card(self.tr("Send"))
        self.send_card = c
        c.lay.setSpacing(6)
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(self.tr("A callsign and text, or CQ"))
        self.entry.setFont(theme.font(14, mono=True))
        self.entry.returnPressed.connect(lambda: self.queue(self.entry.text()))
        top = QHBoxLayout()
        top.setSpacing(6)
        top.addWidget(self.entry, 1)
        c.lay.addLayout(top)
        g = QGridLayout()
        g.setHorizontalSpacing(6)
        g.setVerticalSpacing(6)
        self.cq_btn = Button(self.tr("CQ"), small=True)
        self.cq_btn.setToolTip(self.tr("Call CQ: @ALLCALL CQ CQ CQ"))
        self.cq_btn.clicked.connect(lambda: self.queue("CQ CQ CQ"))
        self.hb_btn = Button(self.tr("Heartbeat"), small=True)
        self.hb_btn.setToolTip(self.tr("Send a heartbeat (@HB HEARTBEAT and your grid): you are listening"))
        self.hb_btn.clicked.connect(lambda: self.queue(f"@HB HEARTBEAT {(self.st('locator') or '')[:4]}".strip()))
        self.reply_btn = Button(self.tr("Reply"), small=True)
        self.reply_btn.setToolTip(self.tr("Start a message to the station picked in the list"))
        self.reply_btn.clicked.connect(self.reply)
        self.send_btn = Button(self.tr("Send"), icon="send", small=True)
        self.send_btn.setToolTip(self.tr("Queue the message; it goes from the next period with Enable TX on"))
        self.send_btn.clicked.connect(lambda: self.queue(self.entry.text()))
        # Send beside the message, the three that make one under it: four in
        # a row were cut to "Heartb…" at 130 %.
        top.addWidget(self.send_btn)
        for i, b in enumerate((self.cq_btn, self.hb_btn, self.reply_btn)):
            g.addWidget(b, 0, i)
        c.lay.addLayout(g)
        # The speed we send at; every speed is decoded whatever this says.
        self.speed_pick = Segmented([(k, self.speed_name(k)) for k in JS8_SPEEDS], self.speed, compact=True)
        self.speed_pick.setToolTip(self.tr("The speed messages are sent at: Slow 30 s, Normal 15 s, Fast 10 s, "
                                           "Turbo 6 s, Ultra 4 s periods. All five are received."))
        self.speed_pick.picked.connect(self.set_speed)
        c.lay.addWidget(self.speed_pick)
        self.tx_status = QLabel()
        self.tx_status.setObjectName("Muted")
        self.tx_status.setWordWrap(True)
        c.lay.addWidget(self.tx_status)
        self.enable = Toggle(self.tr("Enable TX"), False, colour="tx")
        self.enable.toggled.connect(self.toggle_tx)
        c.lay.addWidget(self.enable)
        bt = QWidget()
        bl = QHBoxLayout(bt)
        bl.setContentsMargins(0, 0, 0, 0)
        # Neutral until something is armed or on the air (halt.py).
        self.halt = HaltButton(self.tr("Halt TX"))
        self.halt.setMinimumWidth(self.halt.sizeHint().width())
        self.halt.clicked.connect(self.halt_tx)
        bl.addWidget(self.halt)
        c.set_header_widget(bt)
        c.lay.addStretch(1)
        c.setMinimumWidth(280)
        c.setMaximumWidth(380)
        self._show_tx()
        return c

    # ------------------------------------------------------------ helpers
    def set_text_size(self, px: float):
        """The list's text size, with the row height and fixed columns
        scaled to it, as the FT8 list does (Ft8Panel.set_text_size)."""
        t = self.table
        t.setFont(theme.font(px, mono=True))
        row = int(round(px * 1.75))
        t.verticalHeader().setDefaultSectionSize(row)
        for r in range(t.rowCount()):
            t.setRowHeight(r, row)
        # From the font as drawn (theme.font has the text size in it), so
        # the columns hold their widest value at 130 % too.
        fm = t.fontMetrics()
        widest = ("00:00:00", "-20", "+0.0", "2500", max((self.speed_name(k) for k in JS8_SPEEDS),
                                                         key=fm.horizontalAdvance), "WA1ABC/P")
        for i, w in enumerate(widest):
            t.setColumnWidth(i, fm.horizontalAdvance(w) + 18)

    def _to_me(self, m: Js8Message) -> bool:
        me = self.mycall()
        return bool(me) and (m.to == me or me in "".join(m.parts).upper().replace(":", " ").split())

    def _hidden(self, m: Js8Message) -> bool:
        return (self.only_me.on and not self._to_me(m)) or (not self.show_hb.on and m.heartbeat())

    def _apply_filter(self):
        for r, m in enumerate(self.msgs):
            self.table.setRowHidden(r, self._hidden(m))

    def _paint_row(self, r: int, m: Js8Message):
        cells = [time.strftime("%H:%M:%S", time.gmtime(m.slot)), f"{m.snr:+d}", f"{m.dt:+.1f}", f"{m.df:.0f}",
                 self.speed_name(m.speed), m.call, m.text()]
        fg = bg = None
        words = "".join(m.parts).upper().split()
        if self._to_me(m):
            # Gold for a message to us (the overhaul's decision 8): red is
            # kept for being on the air.
            fg, bg = theme.c("text"), theme.c("toYou", 0.24)
        elif "CQ" in words:
            fg, bg = theme.c("text"), theme.c("cq", 0.16)
        elif m.heartbeat():
            fg = theme.c("text3")
        for i, txt in enumerate(cells):
            it = self.table.item(r, i)
            if it is None:
                it = QTableWidgetItem()
                if i in (1, 2, 3):
                    it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                self.table.setItem(r, i, it)
            it.setText(txt)
            # None clears a colour a frame before gave the row (an empty
            # QBrush would paint the text in no colour at all).
            it.setData(Qt.ItemDataRole.ForegroundRole, QBrush(fg) if fg is not None else None)
            it.setData(Qt.ItemDataRole.BackgroundRole, QBrush(bg) if bg is not None else None)
        self.table.item(r, self.TEXT).setToolTip(m.text())
        self.table.setRowHidden(r, self._hidden(m))

    # ------------------------------------------------------------ decodes
    def on_event(self, ev: dict):
        if ev.get("mode") not in self.modes or not ev.get("text"):
            return
        self.events.append(dict(ev))
        if len(self.events) > 4 * MAX_ROWS:
            del self.events[:MAX_ROWS]
        m, new = join_frame(self.open_msgs, ev)
        t = self.table
        at_bottom = t.verticalScrollBar().value() >= t.verticalScrollBar().maximum() - 2
        if new:
            t.insertRow(t.rowCount())
            self.msgs.append(m)
            if t.rowCount() > MAX_ROWS:
                t.removeRow(0)
                del self.msgs[0]
        self._paint_row(self.msgs.index(m), m)
        if at_bottom:
            t.scrollToBottom()

    def _replay(self, events: list[dict]):
        for ev in events:
            self.on_event(ev)
        self.table.scrollToBottom()

    def carry_from(self, other: "Js8Panel"):
        """The window was rebuilt (a theme change): the old panel's messages,
        replayed frame by frame so the colours are this theme's."""
        self._replay(other.events)

    def adopt(self, other: "Js8Panel"):
        """Start a mirror with the messages the main panel already has."""
        self._replay(other.events)

    def on_state(self, ch: dict):
        if "callsign" in ch:
            for r, m in enumerate(self.msgs):
                self._paint_row(r, m)

    def _row_clicked(self, row: int, _col: int):
        if self.mirror or not (0 <= row < len(self.msgs)):
            return
        if self.on_pick is not None:
            self.on_pick(self.msgs[row].df)

    def set_mirror(self):
        super().set_mirror()
        self.send_card.hide()

    # ------------------------------------------------------------ sending
    def speed_name(self, speed: str) -> str:
        # JS8Call's names for its speeds.
        return {"slow": self.tr("Slow"), "normal": self.tr("Normal"), "fast": self.tr("Fast"),
                "turbo": self.tr("Turbo"), "ultra": self.tr("Ultra")}.get(speed, speed)

    def set_speed(self, speed: str):
        """Send at `speed`. Not while a message is going: its frames were
        counted, and are being timed, at the speed it started at."""
        if speed not in JS8_SPEEDS or (self.tx_enabled and speed != self.speed):
            self.speed_pick.set_value(self.speed)
            return
        self.speed = speed
        self.speed_pick.set_value(speed)
        if self.prefs.get("js8Speed") != speed:
            self.prefs["js8Speed"] = speed
            self.prefs.save()
        self._show_tx()

    def reply(self):
        row = self.table.currentRow()
        call = self.msgs[row].call if 0 <= row < len(self.msgs) else ""
        if call:
            self.entry.setText(call + " ")
        self.entry.setFocus()

    def queue(self, text: str) -> bool:
        """Queue `text` as the message to send and switch Enable TX on: it
        goes from the next period (or this one, if it has only just begun).
        A message already going out is replaced from its next frame."""
        from ...modes import js8 as js8mode
        try:
            n = len(js8mode.frames(text, self.mycall(), self.st("locator") or "", speed=self.speed))
        except ValueError as e:
            self.bridge.say(str(e))
            return False
        self.pending = " ".join(text.upper().split())
        self.nframes, self.part = n, 0
        self.entry.setText(self.pending)
        self.set_tx_enabled(True)
        return True

    def set_tx_enabled(self, on: bool):
        self.tx_enabled = bool(on) and bool(self.pending) and not self.mirror
        self.enable.set_on(self.tx_enabled)
        self.speed_pick.setEnabled(not self.tx_enabled)
        self._show_tx()

    def toggle_tx(self, on: bool):
        """The operator's Enable TX: on sends what is queued (or typed); off
        stops, ending a frame on the air, as the FT8 panel's does."""
        if on and not self.pending and self.entry.text().strip():
            self.queue(self.entry.text())
            return
        self.set_tx_enabled(on)
        if not on and self.st("keyed"):
            self.bridge.halt()

    def halt_tx(self):
        """Halt: nothing more of the message goes, and nothing on the air
        stays on it."""
        self.pending, self.nframes, self.part = "", 0, 0
        self.set_tx_enabled(False)
        if self.st("keyed"):
            self.bridge.halt()

    def _show_tx(self):
        if not self.pending:
            self.tx_status.setText(self.tr("Nothing queued. Messages go out one frame per {s:g} s "
                                           "period.").format(s=JS8_SPEEDS[self.speed].period))
        elif self.part >= self.nframes:
            self.tx_status.setText(self.tr("Sent: {text}").format(text=self.pending))
        else:
            self.tx_status.setText(self.tr("Frame {i} of {n} next: {text}").format(
                i=self.part + 1, n=self.nframes, text=self.pending))

    def _tx_idle(self) -> bool:
        idle = getattr(self.bridge.radio, "tx_idle", None)
        return idle() if callable(idle) else not self.st("keyed")

    def _due(self, now: float) -> int | None:
        """The period the next frame should be queued for at `now`, or None
        to wait: this period if it has only just begun and nothing of ours
        went in it, else the next one once the frame before has ended
        (SlotSpec.queue_at), so frames go in consecutive periods. At the
        speed picked: its period, start and late limit (JS8_SPEEDS)."""
        sp = JS8_SPEEDS[self.speed]
        k = int(now // sp.period)
        into = now - k * sp.period
        # Less a margin for rendering, as the FT8 panel's RENDER_MARGIN.
        if self.sent_period != k and into <= sp.start + sp.late - min(0.4, sp.late / 2):
            return k
        if into >= sp.slot().queue_at and self.sent_period != k + 1:
            return k + 1
        return None

    def next_over_at(self) -> float | None:
        if self.mirror or not self.tx_enabled:
            return None
        now = time.time()
        p = JS8_SPEEDS[self.speed].period
        return now if self._due(now) == int(now // p) else (int(now // p) + 1) * p

    def tick(self, dt: float):
        if not self.mirror:
            self.halt.show_state(self.tx_enabled, self.bridge)
        if self.mirror or not self.tx_enabled or self.part >= self.nframes:
            return
        if not self._tx_idle():
            return
        now = time.time()
        k = self._due(now)
        if k is None:
            return
        self.sent_period = k
        part = self.part
        if self.bridge.send("js8", text=self.pending, part=part, freq=self.prefs["ft8TxOffset"], speed=self.speed):
            self.part += 1
            if self.part >= self.nframes:
                # The last frame is queued: nothing more to send. Enable TX
                # goes off as FT8's does after its 73; the frame still goes.
                self.tx_enabled = False
                self.enable.set_on(False)
                self.speed_pick.setEnabled(True)
        else:
            self.set_tx_enabled(False)
        self._show_tx()
