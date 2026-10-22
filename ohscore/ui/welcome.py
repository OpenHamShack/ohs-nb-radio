"""First run: who you are, the licence, which radio - three short steps.

The simulator is the default radio, so a new operator lands on a live,
busy band with nothing plugged in. The licence step is a real gate: until
it is accepted (here or in Settings) the window receives only.

The steps and their checks are shared; what they say - the tagline, the
operating rules, what the licence covers, what the simulator simulates -
is the app's, as class attributes of its subclass (ohsnb/ui/welcome.py).

Both apps ask the licence class too (since 18/10/2026; Radio alone did
before), with the classes of the country the callsign puts the station in.
Every step has Skip (Mac test FINDINGS 18: a first run had no way out but
through all three): it closes with nothing saved but the Welcome being
seen, so the simulator stays and the licence stays unacknowledged.
"""
from __future__ import annotations

import re

from PyQt6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QPainter, QPen
from PyQt6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QLineEdit, QStackedWidget, QVBoxLayout,
                             QWidget)

from .. import countries, licences
from . import appicon, icons, theme
from .controls import FocusVisible, Anim, Button, Segmented, check_row, mix

LOCATOR = re.compile(r"^[A-Ra-r]{2}[0-9]{2}([A-Xa-x]{2})?$")

# Said under the class question while there is no callsign to go by. The
# sentence for a country with no licence written is the app's
# (Welcome.NO_LICENCE_YET): what follows from it differs - Radio will not
# transmit, NB transmits with a reminder.
NO_CALL_YET = QT_TRANSLATE_NOOP(
    "Welcome", "Enter your callsign above: the licence classes offered are those of the country it puts you in.")


def _w(text: str) -> str:
    """An apps Welcome sentence in the operators language. The apps keep
    theirs as class attributes (their subclasses say what differs) marked
    with QT_TRANSLATE_NOOP("Welcome", ...), which only puts them in the
    catalog; they are looked up here, where they are shown. Until 18/10/2026
    they were shown as written, so every step but the shared titles stayed
    English whatever the catalog said."""
    return QCoreApplication.translate("Welcome", text) if text else text


def class_choices(call: str, override: str, no_licence: str,
                  no_call: str = NO_CALL_YET) -> tuple[list[tuple[str, str]], str]:
    """The classes Welcome offers for this callsign - those of the licence
    written for the station's country (ohscore/countries.py; `override` is
    Settings' country, stationCountry) - and, when there are none, the
    sentence saying why: `no_licence` with {country} filled, or `no_call`
    while no callsign gives a country. Until 08/10/2026 Radio offered the
    UK's three, whoever was asking; it moved here from ohsradio/ui/welcome.py
    when NB started asking too."""
    s = countries.station(call, override)
    lic = licences.get(s.regime)
    if lic is None:
        # Translated before {country} is filled: the catalog holds the template.
        return [], (_w(no_licence).format(country=s.entity) if s.entity else _w(no_call))
    return [(c, licences.class_name(lic, c)) for c in lic.CLASSES], ""


class Dots(QWidget):
    def __init__(self, n, parent=None):
        super().__init__(parent)
        self.n, self.i = n, 0
        self.k = Anim(self)
        self.setFixedHeight(10)

    def set(self, i):
        self.i = i
        self.k.to(i)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        x = 0.0
        for j in range(self.n):
            w = 8 + 18 * max(0.0, 1 - abs(self.k.value - j))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(mix(theme.c("line2"), theme.c("accent"), max(0.0, 1 - abs(self.k.value - j))))
            p.drawRoundedRect(QRectF(x, 1, w, 8), 4, 4)
            x += w + 6


class Choice(FocusVisible, QWidget):
    """A selectable card: icon, title, one line of explanation."""

    picked = pyqtSignal(str)

    def __init__(self, key, icon, title, text, parent=None):
        super().__init__(parent)
        self.key, self.icon, self.title, self.text = key, icon, title, text
        self.on = False
        self.k = Anim(self)
        self.hover = Anim(self)
        self.setFixedHeight(theme.px(76))
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def set_on(self, on):
        self.on = on
        self.k.to(1.0 if on else 0.0)

    def enterEvent(self, e):
        self.hover.to(1)

    def leaveEvent(self, e):
        self.hover.to(0)

    def mouseReleaseEvent(self, e):
        self.picked.emit(self.key)

    def keyPressEvent(self, e):
        if e.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return):
            self.picked.emit(self.key)
        else:
            super().keyPressEvent(e)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        p.setPen(QPen(mix(theme.c("line"), theme.c("accent"), self.k.value), 1.5))
        p.setBrush(mix(mix(theme.c("bg2"), theme.c("bg3"), self.hover.value), theme.c("accent", 0.12), self.k.value))
        p.drawRoundedRect(r, 10, 10)
        icons.paint(p, self.icon, QRectF(r.x() + 18, r.center().y() - 14, 28, 28),
                    mix(theme.c("text2"), theme.c("accent"), self.k.value), 1.8)
        p.setFont(theme.font(15, theme.QFont.Weight.Bold))
        p.setPen(theme.c("text"))
        px = theme.px
        p.drawText(QRectF(r.x() + 62, r.y() + px(12), r.width() - 100, px(24)), Qt.AlignmentFlag.AlignVCenter,
                   self.title)
        p.setFont(theme.font(12.5))
        p.setPen(theme.c("text2"))
        p.drawText(QRectF(r.x() + 62, r.y() + px(36), r.width() - 100, px(28)), Qt.AlignmentFlag.AlignVCenter,
                   self.text)
        cx, cy = r.right() - 26, r.center().y()
        p.setPen(QPen(mix(theme.c("line2"), theme.c("accent"), self.k.value), 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QRectF(cx - 9, cy - 9, 18, 18))
        if self.k.value > 0.01:
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.c("accent"))
            rr = 5 * self.k.value
            p.drawEllipse(QRectF(cx - rr, cy - rr, 2 * rr, 2 * rr))
        if self.focus_visible():
            p.setPen(QPen(theme.c("accent"), 2))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(r, 10, 10)


class Welcome(QDialog):
    TAGLINE = ""                 # under the app's name
    RULES = ""                   # the licence step's rules, rich text
    ACK_NOTE = QT_TRANSLATE_NOOP("Welcome", "Leave this unticked to listen only - transmit stays locked until you "
                                            "tick it here or in Settings › Station.")
    ACK = ""                     # the box the operator ticks
    RADIO_TEXT = ""              # under "Your radio"
    DEVICES: tuple = ()          # (device key, icon, title, one line), in order
    # The licence class question: on which step (0 the station, beside the
    # callsign it follows; 1 the licence, above a box that names it), what
    # it says, and whether the box may be ticked with no class chosen.
    CLASS_PAGE = 0
    CLASS_CAP = ""
    NO_LICENCE_YET = ""          # {country}
    ACK_NEEDS_CLASS = False

    def __init__(self, bridge, prefs, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs = bridge, prefs
        self.restart_needed = False
        face = bridge.face
        # Welcome's own strings are translate("Welcome", ...), not
        # self.tr(): each app builds its subclass (the subclass trap,
        # docs/I18N.md), as About's are below.
        self.setWindowTitle(QCoreApplication.translate("Welcome", "Welcome to {app}").format(app=face.app_name))
        self.setModal(True)
        # Sized with the text (Settings › Display › Text size), as its
        # fonts are: a fixed 720 x 560 gave 130 % text the room of 100 %,
        # and the station step grew a class question on 18/10/2026.
        # Settings offers a size only where the main window's minimum fits
        # the screen (layoutrules.scale_fits), so this fits too; the cap is
        # for a screen smaller than the one the size was chosen on. The
        # 40 px is the title bar the available height does not count.
        fw, fh = theme.px(720), theme.px(560)
        scr = (parent.screen() if parent is not None else None) or QGuiApplication.primaryScreen()
        if scr is not None:
            room = scr.availableGeometry()
            fw, fh = min(fw, room.width()), min(fh, room.height() - 40)
        self.setFixedSize(fw, fh)
        st = bridge.radio.state()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 26)
        lay.setSpacing(14)
        top = QHBoxLayout()
        ic = QLabel()
        ic.setPixmap(appicon.pixmap(face.icon(), 48, self.devicePixelRatioF() or 1.0))
        top.addWidget(ic)
        t = QVBoxLayout()
        t.setSpacing(0)
        h = QLabel(face.app_name)
        h.setFont(theme.font(22, theme.QFont.Weight.Bold))
        s = QLabel(_w(self.TAGLINE))
        s.setObjectName("Muted")
        t.addWidget(h)
        t.addWidget(s)
        top.addLayout(t)
        top.addStretch(1)
        self.dots = Dots(3)
        self.dots.setFixedWidth(80)
        top.addWidget(self.dots, 0, Qt.AlignmentFlag.AlignVCenter)
        lay.addLayout(top)
        lay.addSpacing(6)
        self.stack = QStackedWidget()
        lay.addWidget(self.stack, 1)

        # 1 - station
        p1 = QWidget()
        l1 = QVBoxLayout(p1)
        l1.setContentsMargins(0, 0, 0, 0)
        l1.setSpacing(8)
        self._title(l1, QCoreApplication.translate("Welcome", "Your station"),
                    QCoreApplication.translate("Welcome", "Used in macros, FT8 and JS8 messages and the log; JS8 "
                                                          "will not send without a callsign. You can change all "
                                                          "of this later in Settings."))
        self.call = QLineEdit(st.get("callsign", ""))
        self.call.setPlaceholderText(QCoreApplication.translate("Welcome", "Callsign, e.g. GM4BRI"))
        self.call.setFont(theme.font(20, theme.QFont.Weight.Bold, mono=True))
        self.call.setMinimumHeight(theme.px(48))
        self.loc = QLineEdit(st.get("locator", ""))
        self.loc.setPlaceholderText(QCoreApplication.translate("Welcome", "Locator, e.g. IO86ha"))
        self.loc.setFont(theme.font(17, mono=True))
        self.loc.setMinimumHeight(theme.px(44))
        for lab, w in ((QCoreApplication.translate("Welcome", "Callsign"), self.call),
                       (QCoreApplication.translate("Welcome", "Locator"), self.loc)):
            c = QLabel(lab)
            c.setObjectName("Muted")
            l1.addWidget(c)
            l1.addWidget(w)
        self.p1_msg = QLabel("")
        self.p1_msg.setStyleSheet(f"color: {theme.t()['warn']};")
        l1.addWidget(self.p1_msg)
        # Where the class question goes on each step that may hold it
        # (CLASS_PAGE): under the callsign it follows, or above the rules
        # and the box that names it.
        self._class_slots = [QVBoxLayout()]
        l1.addLayout(self._class_slots[0])
        l1.addStretch(1)
        self.stack.addWidget(p1)

        # 2 - licence
        p2 = QWidget()
        l2 = QVBoxLayout(p2)
        l2.setContentsMargins(0, 0, 0, 0)
        l2.setSpacing(10)
        self._title(l2, QCoreApplication.translate("Welcome", "Before you transmit"), "")
        self._class_slots.append(QVBoxLayout())
        l2.addLayout(self._class_slots[1])
        rules = QLabel(_w(self.RULES))
        rules.setWordWrap(True)
        rules.setTextFormat(Qt.TextFormat.RichText)
        rules.setStyleSheet(f"font-size: {theme.px(14)}px;")
        l2.addWidget(rules)
        row, self.ack = check_row(_w(self.ACK), bool(prefs["licenceAck"]), bold=True)
        l2.addWidget(row)
        n = QLabel(_w(self.ACK_NOTE))
        n.setObjectName("Faint")
        n.setWordWrap(True)
        l2.addWidget(n)
        l2.addStretch(1)
        self.stack.addWidget(p2)

        # 3 - radio
        p3 = QWidget()
        l3 = QVBoxLayout(p3)
        l3.setContentsMargins(0, 0, 0, 0)
        l3.setSpacing(10)
        self._title(l3, QCoreApplication.translate("Welcome", "Your radio"), _w(self.RADIO_TEXT))
        self.choices = {}
        for key, ic_, title, text in self.DEVICES:
            c = Choice(key, ic_, _w(title), _w(text))
            c.picked.connect(self._pick_device)
            self.choices[key] = c
            l3.addWidget(c)
        self.uri = QLineEdit(st.get("plutoUri", "ip:192.168.2.1"))
        self.uri.setPlaceholderText("ip:192.168.2.1")
        self.uri.setFont(theme.font(14, mono=True))
        l3.addWidget(self.uri)
        l3.addStretch(1)
        self.stack.addWidget(p3)
        self.device = st.get("device", "sim")
        self._pick_device(self.device)
        self._class_question(st)

        nav = QHBoxLayout()
        self.back = Button(QCoreApplication.translate("Welcome", "Back"), kind="ghost")
        self.back.clicked.connect(lambda: self.go(self.stack.currentIndex() - 1))
        # On every step, for whoever wants to look around first. It saves
        # nothing but "seen" - not even what was typed - so it can never
        # vouch for a licence nobody ticked, nor swap the simulator for a
        # radio (the overhaul's safety rule 4, docs/ui-overhaul-2026-10.md).
        self.skip_btn = Button(QCoreApplication.translate("Welcome", "Skip"), kind="ghost")
        self.skip_btn.setToolTip(QCoreApplication.translate(
            "Welcome", "Close this and carry on with the radio already chosen (a new install: the simulator). "
                       "Nothing here is saved, and the licence stays unacknowledged, so a radio will not transmit "
                       "until you accept it in Settings › Station. Welcome… in the menu brings this back."))
        self.skip_btn.clicked.connect(self.skip)
        self.next = Button(QCoreApplication.translate("Welcome", "Next"), kind="primary")
        self.next.setMinimumWidth(120)
        self.next.clicked.connect(self._next)
        nav.addWidget(self.back)
        nav.addWidget(self.skip_btn)
        nav.addStretch(1)
        nav.addWidget(self.next)
        lay.addLayout(nav)
        self.go(0)

    def _class_question(self, st):
        """The licence class: a caption, the classes of the callsign's
        country (none preselected) and why there are none, if there are
        none, on step CLASS_PAGE."""
        lay = self._class_slots[self.CLASS_PAGE]
        lay.setSpacing(self.stack.widget(self.CLASS_PAGE).layout().spacing())
        self.cls_cap = QLabel(_w(self.CLASS_CAP))
        self.cls_cap.setObjectName("Muted")
        self.cls_cap.setWordWrap(True)
        # No class preselected (Brian, 05/10/2026): an unset class shows no
        # segment lit, so the operator has to pick theirs rather than accept
        # whichever happened to be first.
        self.cls = Segmented([], st.get("licenceClass", ""))
        self.cls_why = QLabel("")
        self.cls_why.setWordWrap(True)
        self.cls_why.setObjectName("Faint")
        # Why the class could not be saved, on the page that holds the
        # class. It used to go to the station page's message line, which is
        # hidden while the operator is on the last page pressing Start: the
        # dialog simply did not close, and said nothing.
        self.cls_msg = QLabel("")
        self.cls_msg.setWordWrap(True)
        self.cls_msg.setStyleSheet(f"color: {theme.t()['warn']};")
        self.cls_msg.hide()                        # an empty line's height under the class otherwise
        for w in (self.cls_cap, self.cls, self.cls_why, self.cls_msg):
            lay.addWidget(w)
        self._classes()
        self.call.textChanged.connect(lambda _t: self._classes())

    def _classes(self):
        """The class choice follows the callsign typed on this dialog."""
        opts, why = class_choices(self.call.text().strip().upper(),
                                  self.bridge.radio.state().get("stationCountry", ""), self.NO_LICENCE_YET)
        keep = self.cls.value if any(v == self.cls.value for v, _ in opts) else ""
        self.cls.options = opts
        self.cls.set_value(keep, animate=False)
        self.cls.setVisible(bool(opts))
        self.cls.updateGeometry()
        self.cls.update()
        self.cls_why.setText(why)
        self.cls_why.setVisible(bool(why))

    def _class_msg(self, text):
        self.cls_msg.setText(text)
        self.cls_msg.setVisible(bool(text))

    def _title(self, lay, title, sub):
        h = QLabel(title)
        h.setFont(theme.font(19, theme.QFont.Weight.Bold))
        lay.addWidget(h)
        if sub:
            s = QLabel(sub)
            s.setObjectName("Muted")
            s.setWordWrap(True)
            lay.addWidget(s)
        lay.addSpacing(6)

    def _pick_device(self, key):
        self.device = key
        for k, c in self.choices.items():
            c.set_on(k == key)
        self.uri.setVisible(key == "pluto")

    def go(self, i):
        i = max(0, min(2, i))
        self.stack.setCurrentIndex(i)
        self.dots.set(i)
        self.back.setVisible(i > 0)
        self.next.set_text(QCoreApplication.translate("Welcome", "Start listening") if i == 2
                           else QCoreApplication.translate("Welcome", "Next"))

    def _next(self):
        i = self.stack.currentIndex()
        if i == 0:
            loc = self.loc.text().strip()
            if loc and not LOCATOR.match(loc):
                self.p1_msg.setText(QCoreApplication.translate(
                    "Welcome", "That does not look like a Maidenhead locator (e.g. IO86 or IO86ha)."))
                return
            self.p1_msg.setText("")
        if i < 2:
            self.go(i + 1)
            return
        self.finish()

    def skip(self):
        """Close, marking the Welcome seen and nothing else: whatever was
        typed or ticked is dropped, the radio stays as it was, and the
        licence acknowledgement is left as it stood (on a first run,
        unacknowledged - so a radio stays locked to receive)."""
        self.prefs["welcomed"] = True
        self.prefs.save()
        self.reject()

    def finish(self):
        if self.ack.isChecked() and not self.cls.value and self.cls.options and self.ACK_NEEDS_CLASS:
            # The box says "the class I have chosen": with none chosen it
            # would vouch for nothing. Listening needs neither.
            self._class_msg(QCoreApplication.translate(
                "Welcome", "Choose your licence class above, or leave the box unticked to listen only."))
            self.go(self.CLASS_PAGE)
            return
        changes = {"callsign": self.call.text().strip().upper(), "locator": self.loc.text().strip(),
                   "device": self.device}
        if self.device == "pluto":
            changes["plutoUri"] = self.uri.text().strip() or "ip:192.168.2.1"
        st = self.bridge.radio.state()
        changes = {k: v for k, v in changes.items() if st.get(k) != v}
        try:
            if changes:
                self.bridge.radio.set(authorise=True, **changes)
        except ValueError as e:
            self.p1_msg.setText(str(e))
            self.go(0)
            return
        # Kept across a second Start after a refusal below: these changes
        # are saved by then, and the second pass would find none.
        self.restart_needed = self.restart_needed or "device" in changes or "plutoUri" in changes
        # The class after the callsign: which classes exist follows the
        # country the callsign is in. An empty choice leaves the class as it
        # was - Welcome never clears one Settings set.
        if self.cls.value and self.cls.value != self.bridge.radio.state().get("licenceClass"):
            try:
                self.bridge.radio.set(authorise=True, licenceClass=self.cls.value)
            except ValueError as e:
                self._class_msg(str(e))
                self.go(self.CLASS_PAGE)
                return
        self._class_msg("")
        self.prefs["welcomed"] = True
        self.prefs["licenceAck"] = bool(self.ack.isChecked())
        self.prefs.save()
        self.bridge.st.update(self.bridge.radio.state())
        self.accept()


# Where the About box says the source is. The program is GPL and the Windows
# build carries only bytecode and compiled ohsdigi, so the one place a
# Windows user is sure to look must say where the source of the very
# version they run is (Brian, 06/10/2026): its section on the source site,
# which lists every release's own tarball and the third-party source.
SOURCE_SITE = "https://openhamshack.com/source/"


class About(QDialog):
    """The About box both apps show, with their own one-line `text`.

    Its strings are under the "About" context by QCoreApplication.translate
    rather than self.tr(): each app builds its own subclass, and self.tr()
    would look them up under that subclass instead. (Spelt out in full each
    time: pylupdate6 recognises no shorter alias.)"""

    def __init__(self, face, version: str, text: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle(QCoreApplication.translate("About", "About {app}").format(app=face.app_name))
        self.setFixedSize(460, 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(36, 30, 36, 24)
        lay.setSpacing(8)
        ic = QLabel()
        ic.setPixmap(appicon.pixmap(face.icon(), 72, self.devicePixelRatioF() or 1.0))
        lay.addWidget(ic, 0, Qt.AlignmentFlag.AlignHCenter)
        h = QLabel(f"{face.app_name} {version}")
        h.setFont(theme.font(20, theme.QFont.Weight.Bold))
        lay.addWidget(h, 0, Qt.AlignmentFlag.AlignHCenter)
        self.former = None
        if face.former_name:
            self.former = QLabel(QCoreApplication.translate("About", "Formerly {name}").format(name=face.former_name))
            self.former.setObjectName("Muted")
            lay.addWidget(self.former, 0, Qt.AlignmentFlag.AlignHCenter)
        t = QLabel(text)
        t.setWordWrap(True)
        t.setAlignment(Qt.AlignmentFlag.AlignCenter)
        t.setObjectName("Muted")
        lay.addWidget(t)
        if face.package:
            url = f"{SOURCE_SITE}#{face.package}"
            self.source = QLabel(QCoreApplication.translate(
                "About", "Free software under the GNU GPL, version 3 or later. The source of {app} {version}, ohsdigi "
                         "included, and of the third-party parts it carries: {link}").format(
                app=face.app_name, version=version, link=f'<a href="{url}">openhamshack.com/source</a>'))
            self.source.setTextFormat(Qt.TextFormat.RichText)
            self.source.setOpenExternalLinks(True)
            self.source.setWordWrap(True)
            self.source.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self.source.setObjectName("Muted")
            lay.addWidget(self.source)
        lay.addStretch(1)
        ok = Button(QCoreApplication.translate("About", "Close"), kind="primary")
        ok.clicked.connect(self.accept)
        lay.addWidget(ok, 0, Qt.AlignmentFlag.AlignHCenter)
