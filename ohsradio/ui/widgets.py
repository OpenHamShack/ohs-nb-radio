"""OpenHamShack Radio's own header widgets: the band bar under the readout, and the
licence and sequencer chips where NB has its lock badges
(docs/ham/DESIGN-HAM.md section 7). Hand-painted like the rest; each
says its state in words as well as colour."""
from __future__ import annotations

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFontMetricsF, QPainter, QPen
from PyQt6.QtWidgets import QSizePolicy, QWidget

from ohscore import converters as cv
from ohscore import licences
from ohscore.i18n import fmt
from ohscore.ui import icons, theme
from ohscore.ui.controls import Anim, FocusVisible, mix

from .. import bands, plutofix, xvtr
from ..guard import watts


def class_can_transmit(cls: str, b: bands.Band, regime=licences.ofcom) -> bool:
    """Whether licence class `cls` of `regime` (the licence in force) has
    any allocation inside band `b`."""
    return licences.class_can_transmit(regime, cls, b.lo, b.hi)


class BandBar(FocusVisible, QWidget):
    """160 ... 6 cm, the bands the receiver covers (shown()). Bright: the
    licence class may transmit there; dim: receive only; faint: one Pluto
    setting away (the tooltip says why). Click recalls the band's stack -
    a first visit lands where bands.first_register says - and click again
    steps through its three registers (the dots). On the right: the
    band's FT8 and FT4 dials, and the two VFO buttons."""

    picked = pyqtSignal(str)
    action = pyqtSignal(str)          # "ft8", "ft4", "a=b", "swap"

    def __init__(self, bridge, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.hover: str | None = None
        self.cells: list[tuple[QRectF, str, str]] = []     # (rect, kind "band"/"act", key)
        self.sel = Anim(self)
        self.setFixedHeight(theme.px(36))
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        bridge.changed.connect(self._changed)

    def sizeHint(self):
        return QSize(theme.px(900), self.height())

    def _changed(self, ch):
        if any(k in ch for k in ("band", "bandStacks", "licenceClass", "running", "vfo", "mode", "split",
                                 "device", "converters")):
            self.update()

    def _fixable(self, b: bands.Band) -> bool:
        """Out of reach only because the Pluto is set as an AD9363: one
        setting away, so the band stays on the bar (faint) and a click
        explains and offers the change."""
        radio = self.bridge.radio
        return (radio.converter_for(b.name, rx=True) is None and
                plutofix.needs_ad9364(getattr(radio, "dev", None), b.name) is not None)

    def shown(self) -> list[bands.Band]:
        """The bands on the bar: those the receiver covers, directly or
        through a converter. Until 13/10/2026 every band was drawn and the
        unreachable ones faint; Brian asked for the row filtered to the
        receiver's coverage, so an HL2 shows 160-10 and a Pluto 4 m up,
        and 6 m appears only once a converter reaches it. A band one
        Pluto setting would reach stays, for the fix it offers."""
        return [b for b in bands.BANDS if self._status(b)[0] != "off" or self._fixable(b)]

    def _status(self, b: bands.Band) -> tuple[str, str]:
        """("tx" | "rx" | "off", why). A band worked through a converter
        (ohsradio/xvtr.py) is judged by what the radio tunes for it - its IF -
        and says so; a band with no radio here (6 m) is available through one."""
        radio = self.bridge.radio
        dfr = xvtr.deferred(radio.st, b)
        if dfr:
            return "off", dfr
        conv = radio.converter_for(b.name, rx=True)          # what reaching the band is judged on
        dev = getattr(radio, "dev", None)
        rx_lo, rx_hi = getattr(dev, "rx_range", (0.0, 6e9)) if dev is not None else (0.0, 6e9)
        if not xvtr.reach(b, conv, (rx_lo, rx_hi)):
            kind = getattr(dev, "kind", "radio")
            via = f" through {conv.title}" if conv is not None else ""
            why = f"The {kind} cannot tune {b.name}{via} ({rx_lo / 1e6:g}-{rx_hi / 1e6:g} MHz)"
            if conv is None and plutofix.needs_ad9364(dev, b.name) is not None:
                why += " as an AD9363: click for the AD9364 setting"
            return "off", why
        inf = radio.licence_in_force()
        if inf.regime is None:
            return "rx", inf.why_none
        cls = inf.cls
        if not class_can_transmit(cls, b, inf.regime):
            if not cls:
                return "rx", "No licence class chosen: receive only until you choose yours"
            return "rx", f"{licences.class_name(inf.regime, cls)} licence: receive only on {b.name}"
        note = f"{b.name}: {b.lo / 1e6:g}-{b.hi / 1e6:g} MHz"
        tconv = radio.converter_for(b.name)
        if tconv is not None:
            note += f"\nthrough {tconv.title}" + {cv.RX: " (receive only)", cv.RXTX: "",
                                                   cv.TX: " (transmit only: received directly)"}[tconv.use]
        if b.experimental:
            note += f"\n{b.experimental}"
        return "tx", note

    ACTS = (("ft8", "FT8"), ("ft4", "FT4"), ("a=b", "A=B"), ("swap", "A↔B"))

    def _widths(self, pad: float, least: float) -> tuple[list[float], list[float]]:
        fm = QFontMetricsF(theme.font(12.5, theme.QFont.Weight.Bold))
        return ([max(least, fm.horizontalAdvance(b.label) + pad) for b in self.shown()],
                [fm.horizontalAdvance(t) + pad for _k, t in self.ACTS])

    def _need(self, pad: float, least: float, gap: float) -> float:
        bw, aw = self._widths(pad, least)
        return sum(bw) + sum(aw) + gap * (len(bw) + len(aw)) + theme.px(12)

    def _spacing(self) -> tuple[float, float, float]:
        """(padding, least cell, gap): roomy where the row has the room,
        closer where it has not - every band and both VFO keys stay whole
        on a 1024 px window (overhaul section 3), an HL2's ten HF bands
        and a converter's included."""
        roomy = (float(theme.px(18)), float(theme.px(34)), float(theme.px(4)))
        if self._need(*roomy) <= self.width():
            return roomy
        return float(theme.px(10)), float(theme.px(26)), float(theme.px(2))

    def minimumSizeHint(self):
        pad, least, gap = float(theme.px(10)), float(theme.px(26)), float(theme.px(2))
        return QSize(int(self._need(pad, least, gap)), self.height())

    def _layout(self) -> list[tuple[QRectF, str, str]]:
        pad, least, gap = self._spacing()
        bw, aw = self._widths(pad, least)
        h, y = theme.px(26), theme.px(2)
        cells = []
        x = 0.0
        shown = self.shown()
        self._laid = tuple(b.name for b in shown)
        for b, w in zip(shown, bw):
            cells.append((QRectF(x, y, w, h), "band", b.name))
            x += w + gap
        right = self.width()
        for (key, _text), w in reversed(list(zip(self.ACTS, aw))):
            right -= w
            cells.append((QRectF(right, y, w, h), "act", key))
            right -= gap
        return cells

    def resizeEvent(self, e):
        self.cells = self._layout()
        super().resizeEvent(e)

    def _hit(self, pos) -> tuple[str, str] | None:
        for r, kind, key in self.cells:
            if r.contains(pos):
                return kind, key
        return None

    def _dial_tip(self, key: str) -> str:
        """The FT8 or FT4 key's tooltip, with the dial it goes to: in kHz on
        HF and MHz above, in the locale's decimal form (ohscore/i18n/fmt.py).
        A plain tooltip, so the shared frequency rules apply as they stand,
        not the readout's grouped digits."""
        b = bands.BY_NAME.get(self.bridge.st.get("band", ""))
        dial = getattr(b, key, None) if b is not None else None
        if not dial:
            return self.tr("This band's FT8 dial") if key == "ft8" else self.tr("This band's FT4 dial")
        freq = fmt.frequency(int(round(dial)))
        return (self.tr("This band's FT8 dial, {freq}") if key == "ft8"
                else self.tr("This band's FT4 dial, {freq}")).format(freq=freq)

    def mouseMoveEvent(self, e):
        h = self._hit(e.position())
        key = h[1] if h else None
        if key != self.hover:
            self.hover = key
            tip = ""
            if h and h[0] == "band":
                tip = self._status(bands.BY_NAME[key])[1]
            elif h and key in ("ft8", "ft4"):
                tip = self._dial_tip(key)
            elif h:
                tip = {"a=b": self.tr("VFO B (the split transmit dial) = A"), "swap": self.tr("Swap VFO A and B")}[key]
            self.setToolTip(tip)
            self.setCursor(Qt.CursorShape.PointingHandCursor if h else Qt.CursorShape.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def mouseReleaseEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton:
            return
        h = self._hit(e.position())
        if not h:
            return
        kind, key = h
        if kind == "band":
            st, why = self._status(bands.BY_NAME[key])
            # A band only the AD9363 setting keeps out of reach goes to the
            # window anyway, which explains it and offers the fix: a toast
            # saying "cannot tune" was all a tester saw on 05/10/2026.
            if st == "off" and (self.bridge.radio.converter_for(key, rx=True) is not None or
                                plutofix.needs_ad9364(getattr(self.bridge.radio, "dev", None), key) is None):
                self.bridge.say(why)
                return
            self.picked.emit(key)
        else:
            self.action.emit(key)

    def paintEvent(self, _e):
        # The radio, its converters or the Pluto setting can change what the
        # receiver covers while the window is open: lay the row out again
        # when the set of bands it shows changes.
        if not self.cells or getattr(self, "_laid", None) != tuple(b.name for b in self.shown()):
            self.cells = self._layout()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        st = self.bridge.st
        cur = st.get("band", "")
        stacks = st.get("bandStacks") or {}
        p.setFont(theme.font(12.5, theme.QFont.Weight.Bold))
        cur_band = bands.BY_NAME.get(cur)
        for r, kind, key in self.cells:
            hot = key == self.hover
            if kind == "band":
                b = bands.BY_NAME[key]
                status, _ = self._status(b)
                on = key == cur
                if on:
                    bg, fg, border = theme.c("accent"), theme.c("accentText"), Qt.PenStyle.NoPen
                else:
                    bg = mix(theme.c("bg2"), theme.c("bg3"), 1.0 if hot else 0.0)
                    fg = {"tx": theme.c("text"), "rx": theme.c("text3"), "off": theme.c("text3", 0.45)}[status]
                    border = QPen(theme.c("line"), 1)
                    if status == "off":
                        bg = theme.c("bg1")
                p.setPen(border)
                p.setBrush(bg)
                p.drawRoundedRect(r, 6, 6)
                p.setPen(fg)
                label = b.label
                p.drawText(r.adjusted(0, -1, 0, 0), Qt.AlignmentFlag.AlignCenter, label)
                if status == "rx" and not on:
                    # receive only: a small open ring in the corner
                    p.setPen(QPen(theme.c("text3"), 1.1))
                    p.setBrush(Qt.BrushStyle.NoBrush)
                    p.drawEllipse(QRectF(r.right() - 8, r.y() + 3.5, 4.5, 4.5))
                if b.experimental and status != "off" and not on:
                    p.setPen(Qt.PenStyle.NoPen)
                    p.setBrush(theme.c("warn", 0.8))
                    p.drawEllipse(QRectF(r.right() - 8, r.y() + 3.5, 4.5, 4.5))
                # stack registers: three dots under the band, the one in use filled
                e = stacks.get(key)
                n = len(e["regs"]) if e else 3
                i = e["i"] if e else 0
                if on or e:
                    for j in range(n):
                        cx = r.center().x() + (j - (n - 1) / 2) * 7
                        col = (theme.c("accent") if on else theme.c("text3")) if j == i else theme.c("line2")
                        p.setPen(Qt.PenStyle.NoPen)
                        p.setBrush(col)
                        p.drawEllipse(QPointF(cx, r.bottom() + 4.5), 1.8, 1.8)
            else:
                enabled = True
                if key in ("ft8", "ft4"):
                    enabled = cur_band is not None and bool(getattr(cur_band, key))
                text = {"ft8": "FT8", "ft4": "FT4", "a=b": "A=B", "swap": "A↔B"}[key]
                p.setPen(QPen(theme.c("line"), 1))
                p.setBrush(mix(theme.c("bg2"), theme.c("bg3"), 1.0 if hot and enabled else 0.0))
                p.drawRoundedRect(r, 6, 6)
                p.setPen(theme.c("text2") if enabled else theme.c("text3", 0.5))
                p.drawText(r.adjusted(0, -1, 0, 0), Qt.AlignmentFlag.AlignCenter, text)
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 1.5, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 6, 6)


class Chip(QWidget):
    """A header status chip: small-caps title, a coloured word, a detail.

    In the window's Tight tier (overhaul section 3) it is a pill one line
    high - its icon, the word and the detail - so the header fits one line
    at 1024 x 600; the title goes into the tooltip, the icon tells the two
    chips apart."""

    def __init__(self, title: str, icon: str, parent=None, width: int = 230):
        super().__init__(parent)
        self.title, self.icon = title, icon
        self.word, self.detail, self.colour = "", "", "text3"
        self.tip = ""
        self.k = Anim(self)
        self.prev = theme.c("text3")
        self.w = width
        self.pill = False
        self.setFixedHeight(theme.px(48))
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

    def sizeHint(self):
        return QSize(theme.px(self.w * 0.7 if self.pill else self.w), self.height())

    def minimumSizeHint(self):
        return QSize(theme.px(120 if self.pill else 170), self.height())

    def set_tier(self, tier: str) -> None:
        pill = tier == "tight"
        if pill != self.pill:
            self.pill = pill
            self.setFixedHeight(theme.px(24 if pill else 48))
            self._set_tip()
            self.updateGeometry()
            self.update()

    def _set_tip(self):
        self.setToolTip(f"{self.title}: {self.word}" + (f"\n{self.tip}" if self.tip else "") if self.pill else self.tip)

    def set(self, word: str, detail: str, colour: str, tip: str = "", title: str | None = None):
        if colour != self.colour:
            self.prev = theme.c(self.colour)
            self.k.value = 0.0
            self.k.to(1.0)
        changed = (word, detail, colour, title) != (self.word, self.detail, self.colour, None)
        self.word, self.detail, self.colour = word, detail, colour
        if title is not None:
            self.title = title
        self.tip = tip
        self._set_tip()
        if changed:
            self.update()

    def tick(self, dt):
        pass

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        col = mix(self.prev, theme.c(self.colour), self.k.value)
        bg = QColor(col)
        bg.setAlphaF(0.10)
        p.setPen(QPen(QColor(col.red(), col.green(), col.blue(), 90), 1))
        p.setBrush(bg)
        p.drawRoundedRect(r, r.height() / 2 if self.pill else 10, r.height() / 2 if self.pill else 10)
        if self.pill:
            self._paint_pill(p, r, col)
            return
        icons.paint(p, self.icon, QRectF(12, r.center().y() - 10, 20, 20), col, 1.7)
        p.setFont(theme.caps(10))
        p.setPen(theme.c("text3"))
        fm = QFontMetricsF(p.font())
        tr = QRectF(42, 6, r.width() - 48, 14)
        p.drawText(tr, Qt.AlignmentFlag.AlignVCenter, fm.elidedText(self.title, Qt.TextElideMode.ElideRight, tr.width()))
        p.setFont(theme.font(13.5, theme.QFont.Weight.Bold))
        p.setPen(col)
        fw = QFontMetricsF(p.font())
        p.drawText(QRectF(42, 21, r.width() - 48, 20), Qt.AlignmentFlag.AlignVCenter, self.word)
        if self.detail:
            df = theme.font(12, theme.QFont.Weight.Medium)
            dfm = QFontMetricsF(df)
            x = 42 + fw.horizontalAdvance(self.word) + 8
            room = r.right() - 8 - x
            if room > dfm.horizontalAdvance("…") + 4:
                p.setFont(df)
                p.setPen(theme.c("text2"))
                p.drawText(QRectF(x, 21, room, 20), Qt.AlignmentFlag.AlignVCenter,
                           dfm.elidedText(self.detail, Qt.TextElideMode.ElideRight, room))


    def _paint_pill(self, p, r: QRectF, col) -> None:
        ic = r.height() * 0.62
        icons.paint(p, self.icon, QRectF(r.x() + theme.px(8), r.center().y() - ic / 2, ic, ic), col, 1.6)
        x = r.x() + theme.px(8) + ic + theme.px(6)
        p.setFont(theme.font(11.5, theme.QFont.Weight.Bold))
        p.setPen(col)
        fw = QFontMetricsF(p.font())
        room = r.right() - theme.px(10) - x
        word = fw.elidedText(self.word, Qt.TextElideMode.ElideRight, room)
        p.drawText(QRectF(x, r.y(), room, r.height()), Qt.AlignmentFlag.AlignVCenter, word)
        if self.detail and word == self.word:
            df = theme.font(11, theme.QFont.Weight.Medium)
            dfm = QFontMetricsF(df)
            x += fw.horizontalAdvance(word) + theme.px(6)
            room = r.right() - theme.px(10) - x
            if room > dfm.horizontalAdvance("…") + 4:
                p.setFont(df)
                p.setPen(theme.c("text2"))
                p.drawText(QRectF(x, r.y(), room, r.height()), Qt.AlignmentFlag.AlignVCenter,
                           dfm.elidedText(self.detail, Qt.TextElideMode.ElideRight, room))


SEG_WORD = {"CW": "CW", "CW & MGM": "CW, MGM", "narrow digital": "CW, narrow digital",
            "narrow digital (200 Hz)": "narrow digital", "all modes": "all modes", "SSB & MGM": "SSB, MGM",
            "narrow band": "CW, SSB, MGM", "FM simplex": "FM simplex", "60 m segment": "60 m, all modes"}


def licence_chip_text(st: dict) -> tuple[str, str, str, str, str]:
    """(title, word, detail, colour, tooltip) for the licence chip."""
    info = st.get("licenceInfo") or {}
    cls = info.get("class") or ""
    level = info.get("level", "ok")
    no_regime = "regime" in info and not info["regime"]
    why = info.get("why", "")
    seg = info.get("segment") or ""
    lim = info.get("limitW")
    title = f"Licence · {cls or 'not chosen'}"
    if no_regime:
        # No licence written for the station's country, none entered: the
        # same kind of fact as no class, said the same way.
        title = "Licence · none set up"
        # Amber, not red, for all three: a setting to make or a frequency
        # to move off, not a fault, and red is for the air (overhaul 5.3).
        word, colour, detail = "NO LICENCE", "warn", "set up in Settings"
    elif not cls:
        # No class yet: say what unlocks it rather than "NO TX HERE", which
        # reads as a fact about the frequency.
        word, colour, detail = "NO CLASS", "warn", "choose in Settings"
    elif info.get("deferred"):
        # Not the licence's doing: grey, not red, and the reason is the band's.
        word, colour, detail = "NO RADIO", "text3", "band not covered"
    elif level == "refused":
        word, colour = "NO TX HERE", "warn"
        detail = seg
    else:
        word = f"{lim:g} W {info.get('limitKind', 'PEP')}" if lim else "TX"
        colour = "warn" if level == "warn" else "ok"
        detail = SEG_WORD.get(seg, seg)
    est = float(st.get("estPep") or 0.0)
    tip = (f"<b>{cls + ' licence' if cls else 'Licence class not chosen'}</b><br>{why or 'Transmit is allowed here.'}"
           f"<br><br>Segment: {seg or '(none in the plan)'}"
           f"<br>Estimated PEP at this drive: {watts(est)} (an estimate from the power chain in Settings: over "
           f"the limit it warns; only a measured excess unkeys)")
    return title, word, detail, colour, tip


SEQ = {"rx": ("RX", "text3", "receiving"), "seq": ("SEQ", "warn", "PTT line keyed, waiting"),
       "tx": ("ON AIR", "tx", ""), "hang": ("HANG", "warn", "RF off, line dropping")}
