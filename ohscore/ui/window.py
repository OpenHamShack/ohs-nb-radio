"""The main window: it builds the layout and wires the bridge to the widgets,
and owns the operator-level behaviour that spans widgets - tuning steps,
click-to-tune, PTT, the shortcuts, the panel for the current mode.

Layout (DESIGN.md "User interface"):

  header   brand | frequency readout | app status (NB: RX/TX lock) | PTT | tools
  body     wide panadapter + waterfall
           zoom scope | lower panel (Operate / Logbook / Memories / the app's) | rail
  footer   status strip

How much room each part gets is the workspace's (ohscore/ui/workspace.py):
Digital, Voice or Watch, following the mode or pinned by the operator. A
switch resizes and shows or hides; it never builds a widget, never
changes the mode or the frequency, and never touches transmitting.

How much of each part shows is the tier's (ohscore/ui/layoutrules.py;
overhaul section 3): Full, Compact or Tight, from the window's size over
the text scale. Compact narrows the rail and drops the brand's words;
Tight makes the header one line, puts the rail in a drawer behind the
tab row's Controls button and the mode on a button beside it. Like a
workspace switch, a tier change only resizes, shows, hides and moves
widgets that exist. The window may be as small as 1024 x 600 at 100 %
text (decision 5), scaled with the text and never more than the screen.

Theme changes rebuild the window's content (each widget picks up colours
when built); the radio, the feeds and the second display keep running.

BaseWindow is that window for any app. The app's MainWindow subclasses it
for what is its own (ohsnb/ui/mainwindow.py): the header's status widgets,
the transmit card, its shortcuts and mode keys, the status strip's items,
and its Settings, Welcome and About dialogs. Its name and icon come from
the bridge's Face.
"""
from __future__ import annotations

import time

import numpy as np
from PyQt6.QtCore import QByteArray, QCoreApplication, QEvent, QObject, QPoint, Qt, QTimer
from PyQt6.QtGui import QAction, QActionGroup, QFontMetricsF, QKeySequence, QShortcut
from PyQt6.QtWidgets import (QAbstractSpinBox, QApplication, QComboBox, QHBoxLayout, QLabel, QLayout, QLineEdit, QMainWindow,
                             QMenu, QPlainTextEdit, QScrollArea, QSplitter, QStackedWidget, QTextEdit, QVBoxLayout, QWidget)

from ..modegroups import MODE_LABELS, is_slot, js8_slot, slot_spec
from . import appicon, layoutrules, playback, recording, theme, txstate
from . import workspace as wsm
from .update import UpdateBanner, UpdateController
from .chrome import IconButton, MoreButton, ShortcutOverlay, StatusStrip
from .controls import Button, FocusVisible, Segmented
from .logbook import LogView, MemoriesView
from .panels import make_panel, panel_key
from .panels.common import MacroBar
from .panels.text import mode_offset
from .modegrid import ModeGrid, ModeMenuButton
from .prefs import SPLITTER_NAMES, layout_from_sizes, sizes_from_layout
from .rail import RailDrawer, ReceiveCard
from .smeter import passband_noise_dbfs
from .readout import STEPS, Readout
from .layoutrules import FULL, TIGHT
from .scope import ScopeView
from .status import OnAirGlow, PttButton, SimBadge, ToastHost
from .tuning import DEFAULT_STEP, click_to_dial

# The pixel sizes as ui.json kept them before workspaces, when the window
# had two layouts (FT8/FT4's and everyone else's); still written from the
# workspaces nearest to them, so going back to an older version finds the
# layout the operator left.
LEGACY_PREFS = {"voice": "splitters", "digital": "slotSplitters"}
TEXT_INPUTS = (QLineEdit, QPlainTextEdit, QTextEdit, QAbstractSpinBox, QComboBox)
# PSK's extra stations at most (state.py pskChannels), beside the mode's own.
PSK_MORE_MAX = 15


class PageStack(QStackedWidget):
    """A QStackedWidget as tall as the page showing, not the tallest page
    it holds. The lower panel holds every mode's panel made so far and the
    views; once FT8's tall panel had been made, the stock stack would not
    let Watch give the band two thirds of the window, whichever page was
    on top."""

    def __init__(self):
        super().__init__()
        # The stack's own layout would otherwise set the widget's minimum
        # to its largest page's, whatever minimumSizeHint says.
        self.layout().setSizeConstraint(QLayout.SizeConstraint.SetNoConstraint)
        self.currentChanged.connect(lambda _i: self.updateGeometry())

    def minimumSizeHint(self):
        w = self.currentWidget()
        return w.minimumSizeHint() if w is not None else super().minimumSizeHint()

    def sizeHint(self):
        w = self.currentWidget()
        return w.sizeHint() if w is not None else super().sizeHint()


def workspace_label(ws: str) -> str:
    """A workspace's name on screen."""
    return {wsm.DIGITAL: QCoreApplication.translate("BaseWindow", "Digital"),
            wsm.VOICE: QCoreApplication.translate("BaseWindow", "Voice"),
            wsm.WATCH: QCoreApplication.translate("BaseWindow", "Watch")}.get(ws, ws)


class Brand(QWidget):
    """The app's icon and name, the tagline under it, and SIMULATOR when
    the radio is the simulator. Compact keeps the icon; Tight neither
    (its header is one line): SIMULATOR stays in every tier."""

    def __init__(self, face, tagline: str, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(10)
        ic = QLabel()
        ic.setPixmap(appicon.pixmap(face.icon(), 40, self.devicePixelRatioF() or 1.0))
        self.icon = ic
        lay.addWidget(ic)
        col = QVBoxLayout()
        col.setSpacing(0)
        name = QLabel(face.app_name)
        name.setFont(theme.font(15, theme.QFont.Weight.Bold))
        sub = QLabel(tagline)
        sub.setFont(theme.font(11))
        sub.setObjectName("Faint")
        # Beside the app's name, the first thing read on the window: the
        # status strip said "Simulator" for months and nobody saw it.
        top = QHBoxLayout()
        top.setSpacing(8)
        top.addWidget(name)
        self.sim = SimBadge()
        top.addWidget(self.sim, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        col.addStretch(1)
        col.addLayout(top)
        col.addWidget(sub)
        col.addStretch(1)
        lay.addLayout(col)
        self.words = (name, sub)

    def set_tier(self, tier: str) -> None:
        for w in self.words:
            w.setVisible(tier == layoutrules.FULL)
        self.icon.setVisible(tier != TIGHT)


class BaseWindow(QMainWindow):
    TAGLINE = ""                 # under the app's name in the header
    MODE_KEYS: dict = {}         # Ctrl+<key> -> mode
    SHORTCUTS: list = []         # the "?" overlay's sections
    STEPS = STEPS                # the tuning steps [ and ] cycle through
    # An app's own views beside Mode / Logbook / Memories in the lower panel:
    # (key, label, shortcut); make_extra_view(key) builds each (NB: its
    # multimedia beacon).
    EXTRA_VIEWS: list = []
    # Extra views the tab row leaves out in the Tight tier (View menu only).
    TIGHT_MENU_VIEWS: tuple = ()
    # Views that leave the tab row in Compact as well (still on the View
    # menu and their shortcut): a seventh tab is wider than a 1280 px
    # window has room for (Radio's Local view, 23/10/2026).
    COMPACT_MENU_VIEWS: tuple = ()
    # The least rail that shows the full mode grid's labels whole.
    GRID_RAIL = 320
    # The screen's available (width, height) when a test says what screen
    # it means; None asks the screen the window is on.
    SCREEN_ROOM: tuple[int, int] | None = None

    def __init__(self, bridge, prefs, start_error: str = ""):
        super().__init__()
        self.bridge, self.prefs = bridge, prefs
        self.face = bridge.face
        self.setWindowTitle(self.window_title())
        self.setWindowIcon(self.face.icon())
        self.tier: str | None = None
        self.tier_switch_ms = 0.0
        self._drawer_cause = (False, False)
        self._screen_hooked = False
        self.apply_minimum()
        self.step = DEFAULT_STEP.get(bridge.st.get("mode", "usb"), 100)
        self.panels: dict[str, QWidget] = {}
        self.panel = None
        self.second = None
        self.ptt_latched = False
        self.space_down = False
        self.built = False
        self.last_mode = None
        # The workspace: which is chosen (Auto or pinned, kept in ui.json)
        # and which is showing. FT8 had a layout of its own from 16/10/2026
        # (Ray: "the FT8 needs larger real-estate"); the workspaces made
        # that three, each with its own defaults and the operator's own
        # changes, so dragging the FT8 layout about does not undo the one
        # set up for SSB.
        self.ws = wsm.Workspaces(prefs["workspace"])
        self.workspace: str | None = None
        self.ws_switch_ms = 0.0
        self._relayout_due = False
        self._tx_form = None
        # False until restore_state has sized the window: the first build
        # picks its panel (and so its workspace) before then, when the
        # splitters' sizes are a placeholder that must not be saved over
        # the operator's.
        self.split_ready = False
        # Before the menu and the build: Help › Check for updates… and the
        # banner both talk to it. It checks nothing until the app's run()
        # calls start(), so a window built by a test or a tool stays offline.
        self.updates = UpdateController(self)
        # Help › Send diagnostics… and the opt-in automatic upload; like the
        # updates, it sends nothing until run() calls start().
        from .diagsend import DiagSendController
        self.diagsend = DiagSendController(self)
        self._menu()
        self.build()
        bridge.changed.connect(self.on_state)
        bridge.meter.connect(self.on_meter)
        bridge.decoded.connect(self.on_event)
        bridge.toast.connect(self.on_toast)
        bridge.tick.connect(self.on_tick)
        bridge.zoom.connect(self.on_zoom_lines)
        QApplication.instance().installEventFilter(self)
        self._shortcuts()
        self.restore_state()
        if start_error:
            QTimer.singleShot(400, lambda: self.on_toast({"level": "error", "text": start_error}))
        self.on_state(dict(bridge.st))

    # ================================================================ building
    def _menu(self):
        # QCoreApplication.translate under BaseWindow's own context, not
        # self.tr(): PyQt looks self.tr() up under the class of the object
        # (each app's MainWindow), so a string written here would never be
        # found in the ohscore catalog. Spelt out each time because that is
        # the form pylupdate6 and the check both recognise.
        mb = self.menuBar()
        f = mb.addMenu(QCoreApplication.translate("BaseWindow", "&File"))
        self.act_rec = QAction(QCoreApplication.translate("BaseWindow", "Record receive IQ…"), self, checkable=True)
        self.act_rec.setShortcut(QKeySequence("Ctrl+Shift+R"))
        self.act_rec.triggered.connect(lambda _=False: recording.toggle(self))
        f.addAction(self.act_rec)
        a = QAction(QCoreApplication.translate("BaseWindow", "Open recordings folder"), self)
        a.triggered.connect(lambda: recording.open_folder(self))
        f.addAction(a)
        self.act_play = QAction(QCoreApplication.translate("BaseWindow", "Play IQ recording…"), self, checkable=True)
        self.act_play.setShortcut(QKeySequence("Ctrl+Shift+P"))
        self.act_play.triggered.connect(lambda _=False: playback.toggle(self))
        f.addAction(self.act_play)
        self.act_loop = QAction(QCoreApplication.translate("BaseWindow", "Loop playback"), self, checkable=True)
        self.act_loop.triggered.connect(lambda on: self.bridge.set(playLoop=bool(on)))
        f.addAction(self.act_loop)
        f.addSeparator()
        a = QAction(QCoreApplication.translate("BaseWindow", "Export log as ADIF…"), self)
        a.triggered.connect(lambda: (self.show_view("log"), self.logview.export()))
        f.addAction(a)
        f.addSeparator()
        a = QAction(QCoreApplication.translate("BaseWindow", "Quit"), self)
        a.setShortcut(QKeySequence("Ctrl+Q"))
        a.triggered.connect(self.close)
        f.addAction(a)
        v = mb.addMenu(QCoreApplication.translate("BaseWindow", "&View"))
        self.act_second = QAction(QCoreApplication.translate("BaseWindow", "Second display"), self, checkable=True)
        self.act_second.setShortcut(QKeySequence("Ctrl+D"))
        self.act_second.triggered.connect(self.toggle_second)
        v.addAction(self.act_second)
        a = QAction(QCoreApplication.translate("BaseWindow", "Light theme"), self, checkable=True)
        a.setShortcut(QKeySequence("Ctrl+T"))
        a.setChecked(self.prefs["theme"] == "light")
        a.triggered.connect(lambda on: self.set_theme("light" if on else "dark"))
        self.act_theme = a
        v.addAction(a)
        a = QAction(QCoreApplication.translate("BaseWindow", "Full screen"), self)
        a.setShortcut(QKeySequence("F11"))
        a.triggered.connect(lambda: self.showNormal() if self.isFullScreen() else self.showFullScreen())
        v.addAction(a)
        # View › Workspace and the tab row's Workspace button are one menu.
        # No shortcuts on its actions: W and Shift+W are single keys the
        # window's key filter handles (not while typing), as f, z and r are.
        self.ws_menu = v.addMenu(QCoreApplication.translate("BaseWindow", "Workspace"))
        self.ws_actions: dict[str, QAction] = {}
        group = QActionGroup(self)
        for key, name in ((wsm.AUTO, QCoreApplication.translate("BaseWindow", "Auto - follows the mode\tShift+W")),
                          (wsm.DIGITAL, workspace_label(wsm.DIGITAL)), (wsm.VOICE, workspace_label(wsm.VOICE)),
                          (wsm.WATCH, workspace_label(wsm.WATCH))):
            a = QAction(name, self, checkable=True)
            a.triggered.connect(lambda _=False, k=key: self.choose_workspace(k))
            group.addAction(a)
            self.ws_menu.addAction(a)
            self.ws_actions[key] = a
        self.ws_menu.addSeparator()
        a = QAction(QCoreApplication.translate("BaseWindow", "Reset this workspace's layout"), self)
        a.triggered.connect(self.reset_workspace)
        self.ws_menu.addAction(a)
        v.addSeparator()
        for name, key, view in ((QCoreApplication.translate("BaseWindow", "Operate"), "Ctrl+J", "mode"),
                                (QCoreApplication.translate("BaseWindow", "Logbook"), "Ctrl+L", "log"),
                                (QCoreApplication.translate("BaseWindow", "Memories"), "Ctrl+B", "mem"),
                                *((QCoreApplication.translate("MainWindow", label), sc, k)
                                  for k, label, sc in self.EXTRA_VIEWS)):
            a = QAction(name, self)
            a.setShortcut(QKeySequence(key))
            a.triggered.connect(lambda _=False, vv=view: self.show_view(vv))
            v.addAction(a)
        v.addSeparator()
        a = QAction(QCoreApplication.translate("BaseWindow", "Keyboard shortcuts"), self)
        a.triggered.connect(lambda: self.overlay.open())
        v.addAction(a)
        r = mb.addMenu(QCoreApplication.translate("BaseWindow", "&Radio"))
        a = QAction(QCoreApplication.translate("BaseWindow", "Settings…"), self)
        a.setShortcut(QKeySequence("Ctrl+,"))
        a.triggered.connect(self.open_settings)
        r.addAction(a)
        a = QAction(QCoreApplication.translate("BaseWindow", "Restart the radio"), self)
        a.triggered.connect(self.restart_radio)
        r.addAction(a)
        a = QAction(QCoreApplication.translate("BaseWindow", "Voice memories…"), self)
        a.triggered.connect(self.open_voice_memories)
        r.addAction(a)
        self.radio_menu_extra(r)
        h = mb.addMenu(QCoreApplication.translate("BaseWindow", "&Help"))
        # Kept, so an app adds its own items by reference: finding the menu
        # by its title stops working the moment the title is translated.
        self.help_menu = h
        a = QAction(QCoreApplication.translate("BaseWindow", "Welcome…"), self)
        a.triggered.connect(self.open_welcome)
        h.addAction(a)
        a = QAction(QCoreApplication.translate("BaseWindow", "Check for updates…"), self)
        a.triggered.connect(lambda: self.updates.open_dialog())
        h.addAction(a)
        h.addSeparator()
        a = QAction(QCoreApplication.translate("BaseWindow", "Save diagnostics…"), self)
        a.triggered.connect(self.save_diagnostics)
        h.addAction(a)
        a = QAction(QCoreApplication.translate("BaseWindow", "Send diagnostics…"), self)
        a.triggered.connect(lambda: self.diagsend.open_dialog())
        h.addAction(a)
        a = QAction(QCoreApplication.translate("BaseWindow", "Open log folder"), self)
        a.triggered.connect(self.open_log_folder)
        h.addAction(a)
        h.addSeparator()
        a = QAction(QCoreApplication.translate("BaseWindow", "About {app}").format(app=self.face.app_name), self)
        a.triggered.connect(self.open_about)
        h.addAction(a)

    def window_title(self) -> str:
        """The title bar's text. The app's MainWindow says it through its
        own catalog (its name is user text like any other: some scripts
        write it differently); the face's app_name is the fallback and stays
        the name diagnostics and logs record."""
        return self.face.app_name

    def radio_menu_extra(self, menu) -> None:
        """An app's own items at the end of the Radio menu (NB: Dish alignment…)."""

    def build(self):
        """(Re)build the window's content from the current theme."""
        old = self.centralWidget()
        b = self.bridge
        root = QWidget()
        root.setObjectName("Root")
        outer = QVBoxLayout(root)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        # A new version, when there is one: above everything, full width.
        self.update_banner = UpdateBanner()
        outer.addWidget(self.update_banner)
        self.updates.attach(self.update_banner)
        body = QWidget()
        bl = QVBoxLayout(body)
        bl.setContentsMargins(theme.S3, theme.S2, theme.S3, theme.S2)
        bl.setSpacing(theme.S2)
        self.body_layout = bl

        # Header -----------------------------------------------------------
        head = QHBoxLayout()
        head.setSpacing(theme.S5)
        brand = Brand(self.face, self.TAGLINE)
        self.brand = brand
        self.head = head
        self.sim_badge = brand.sim
        self.sim_badge.set_state(b.st)
        head.addWidget(brand)
        self.readout = Readout(b)
        self.readout.set_step(self.step)
        self.readout.tune.connect(self.tune_to)
        self.readout.step_clicked.connect(lambda: self.cycle_step(+1))
        self.readout.step_wheel.connect(self.cycle_step)
        self.readout.chip_clicked.connect(self.chip)
        head.addWidget(self.readout, 1)
        self.tickers: list = []
        self._header_status(head)
        self.ptt = PttButton()
        self.ptt.pressed.connect(lambda: self.ptt_input(True))
        self.ptt.released.connect(lambda: self.ptt_input(False))
        head.addWidget(self.ptt)
        tools = QVBoxLayout()
        tools.setSpacing(4)
        row1, row2 = QHBoxLayout(), QHBoxLayout()
        row1.setSpacing(4)
        row2.setSpacing(4)
        self.btn_second = IconButton("screen", QCoreApplication.translate("BaseWindow", "Second display (Ctrl+D)"))
        self.btn_second.clicked.connect(self.toggle_second)
        bset = IconButton("gear", QCoreApplication.translate("BaseWindow", "Settings (Ctrl+,)"))
        bset.clicked.connect(self.open_settings)
        bhelp = IconButton("help", QCoreApplication.translate("BaseWindow", "Keyboard shortcuts (?)"))
        bhelp.clicked.connect(lambda: self.overlay.open())
        blog = IconButton("book", QCoreApplication.translate("BaseWindow", "Logbook (Ctrl+L)"))
        blog.clicked.connect(lambda: self.show_view("log"))
        row1.addWidget(self.btn_second)
        row1.addWidget(bset)
        row2.addWidget(blog)
        row2.addWidget(bhelp)
        tools.addLayout(row1)
        tools.addLayout(row2)
        self.tool_buttons = (self.btn_second, bset, blog, bhelp)
        # Tight's header is one line: the four become one button with
        # them on a menu (the same actions, the same shortcuts). Made
        # now and hidden, so a tier change builds nothing.
        self.more_btn = MoreButton(QCoreApplication.translate(
            "BaseWindow", "Second display, Settings, Logbook, Keyboard shortcuts"))
        self.more_menu = QMenu(self)
        for text, fn in ((QCoreApplication.translate("BaseWindow", "Second display\tCtrl+D"), self.toggle_second),
                         (QCoreApplication.translate("BaseWindow", "Settings…\tCtrl+,"), self.open_settings),
                         (QCoreApplication.translate("BaseWindow", "Logbook\tCtrl+L"), lambda: self.show_view("log")),
                         (QCoreApplication.translate("BaseWindow", "Keyboard shortcuts\t?"),
                          lambda: self.overlay.open())):
            a = self.more_menu.addAction(text)
            a.triggered.connect(lambda _=False, fn=fn: fn())
        self.more_btn.clicked.connect(
            lambda: self.more_menu.popup(self.more_btn.mapToGlobal(QPoint(0, self.more_btn.height()))))
        self.more_btn.hide()
        tools.addWidget(self.more_btn, 0, Qt.AlignmentFlag.AlignVCenter)
        head.addLayout(tools)
        bl.addLayout(head)
        self._under_header(bl)

        # Scopes, panel, rail ------------------------------------------------
        self.wide = ScopeView(b, self.prefs, "wide")
        self.wide.clicked.connect(self.scope_click)
        self.wide.wheel_step.connect(lambda d: self.step_tune(d))
        self.zoom = ScopeView(b, self.prefs, "zoom")
        self.zoom.clicked.connect(self.scope_click)
        self.zoom.wheel_step.connect(lambda d: self.step_tune(d))
        self.zoom.offset_clicked.connect(self.offset_click)
        self.zoom.channel_clicked.connect(self.psk_channel_click)
        for sc in (self.wide, self.zoom):
            sc.palette_changed.connect(self.set_palette)
            sc.colours_requested.connect(self.open_scope_colours)
            sc.context_requested.connect(self.scope_menu)
        self.zoom.setMinimumWidth(260)

        lower = QWidget()
        ll = QVBoxLayout(lower)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(theme.S2)
        # The tab row (plan section 5.2): the same tabs in every mode, in
        # the order Ctrl+J / L / B / M / K keep. "Operate", not "Mode": the
        # rail's card is called Mode (decision 6). The mode's name used to
        # follow the tabs as a label that read like a last tab ("q65"); it
        # is the Operate page's first line now. The Workspace button sits
        # at the right end.
        tabs = QHBoxLayout()
        self.views = Segmented([("mode", QCoreApplication.translate("BaseWindow", "Operate")),
                                ("log", QCoreApplication.translate("BaseWindow", "Logbook")),
                                ("mem", QCoreApplication.translate("BaseWindow", "Memories")),
                                *((k, QCoreApplication.translate("MainWindow", label))
                                  for k, label, _ in self.EXTRA_VIEWS)], "mode", compact=True)
        self.view_options = list(self.views.options)
        self.views.picked.connect(self.show_view)
        tabs.addWidget(self.views)
        tabs.addStretch(1)
        # Tight's tab row also carries what the rail would: the mode (a
        # button with its menu) and Controls, which opens the rail as a
        # drawer. Hidden in the other tiers.
        self.mode_btn = ModeMenuButton(b.radio.STATE.modes)
        k = theme.t()
        # Drawn like the row's other buttons; its own "▾" is the indicator.
        self.mode_btn.setStyleSheet(
            f"QToolButton {{ background: {k['bg2']}; color: {k['text']}; border: 1px solid {k['line2']};"
            f" border-radius: 6px; padding: 2px 10px; font-weight: 600; }}"
            f" QToolButton:hover {{ border-color: {k['accent']}; }}"
            " QToolButton::menu-indicator { image: none; width: 0px; }")
        self.mode_btn.setFixedHeight(theme.px(26))
        self.mode_btn.picked.connect(self.set_mode)
        # An over button on its menu (NB's KG-STV) is the Mode card's: the
        # card notes it as recent and the app's over_picked handler acts.
        self.mode_btn.over_picked.connect(lambda m: self.modegrid._pick(m))
        self.mode_btn.hide()
        tabs.addWidget(self.mode_btn)
        self.controls_btn = Button(QCoreApplication.translate("BaseWindow", "Controls"), kind="ghost", small=True,
                                   checkable=True)
        self.controls_btn.setToolTip(QCoreApplication.translate(
            "BaseWindow", "The mode, transmit and receive controls, over the right of the panel. Esc closes "
                          "them when nothing is on the air."))
        self.controls_btn.setMinimumWidth(self.controls_btn.sizeHint().width())     # never "Co…"
        self.controls_btn.clicked.connect(self.toggle_drawer)
        self.controls_btn.hide()
        tabs.addWidget(self.controls_btn)
        self.ws_button = Button("", kind="ghost", small=True)
        self.ws_button.setToolTip(QCoreApplication.translate(
            "BaseWindow", "How the window is laid out: follows the mode (Auto), or the one you chose. "
                          "W steps through them, Shift+W goes back to Auto."))
        self.ws_button.clicked.connect(self._open_ws_menu)
        tabs.addWidget(self.ws_button)
        ll.addLayout(tabs)
        self.stack = PageStack()
        self.panel_stack = PageStack()
        self.logview = LogView(b)
        self.memview = MemoriesView(b)
        operate = QWidget()
        ol = QVBoxLayout(operate)
        ol.setContentsMargins(0, 0, 0, 0)
        ol.setSpacing(theme.S1)
        self.panel_title = QLabel("")
        self.panel_title.setFont(theme.font(13, theme.QFont.Weight.DemiBold))
        self.panel_title.setObjectName("Muted")
        self.panel_title.setTextFormat(Qt.TextFormat.PlainText)
        # Wrapped: what a mode is missing is a sentence ("FT8 - ohsdigi ...
        # did not load: reinstall ..."), and one line of it set the lower
        # panel's least width to 1038 px, wider than a 1024 px window.
        self.panel_title.setWordWrap(True)
        ol.addWidget(self.panel_title)
        ol.addWidget(self.panel_stack, 1)
        self.stack.addWidget(operate)
        self.stack.addWidget(self.logview)
        self.stack.addWidget(self.memview)
        self.extra_views = {}
        for k, _label, _sc in self.EXTRA_VIEWS:
            self.extra_views[k] = self.make_extra_view(k)
            self.stack.addWidget(self.extra_views[k])
        ll.addWidget(self.stack, 1)
        self.panels = {}
        self.panel = None

        self.split_low = QSplitter(Qt.Orientation.Horizontal)
        self.split_low.addWidget(self.zoom)
        self.split_low.addWidget(lower)
        self.split_low.setStretchFactor(0, 4)
        self.split_low.setStretchFactor(1, 6)
        self.split_low.setHandleWidth(theme.S2)
        self.split_main = QSplitter(Qt.Orientation.Vertical)
        self.split_main.addWidget(self.wide)
        self.split_main.addWidget(self.split_low)
        self.split_main.setStretchFactor(0, 11)
        self.split_main.setStretchFactor(1, 9)
        self.split_main.setHandleWidth(theme.S2)

        rail = QWidget()
        rl = QVBoxLayout(rail)
        rl.setContentsMargins(0, 0, 4, 0)
        rl.setSpacing(theme.S2)
        self.modegrid = ModeGrid(b.radio.STATE.modes)
        self.modegrid.picked.connect(self.set_mode)
        self.rxcard = ReceiveCard(b, prefs=self.prefs)
        self.rxcard.expand_toggled.connect(lambda on: self._card_expanded("receive", on))
        self.txcard = self._transmit_card()
        if self.txcard is not None and hasattr(self.txcard, "expand_toggled"):
            self.txcard.expand_toggled.connect(lambda on: self._card_expanded("transmit", on))
        rl.addWidget(self.modegrid)
        if self.txcard is not None:
            rl.addWidget(self.txcard)
        rl.addWidget(self.rxcard)
        rl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(rail)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._rail_style = ("QScrollArea { background: transparent; } QScrollArea > QWidget > QWidget "
                            "{ background: transparent; }")
        scroll.setStyleSheet(self._rail_style)
        # Its least width is what its cards need in the workspace's forms
        # (_fit_rail), so Watch's slim rail is as slim as they allow.
        scroll.setMaximumWidth(400)
        self.rail = rail
        self.rail_scroll = scroll

        self.split_side = QSplitter(Qt.Orientation.Horizontal)
        self.split_side.addWidget(self.split_main)
        self.split_side.addWidget(scroll)
        self.split_side.setStretchFactor(0, 1)
        self.split_side.setStretchFactor(1, 0)
        self.split_side.setHandleWidth(theme.S2)
        self.split_side.setCollapsible(0, False)
        for sp in (self.split_main, self.split_low, self.split_side):
            sp.splitterMoved.connect(self._split_moved)
        bl.addWidget(self.split_side, 1)
        outer.addWidget(body, 1)
        self.status = StatusStrip(b, items=self.status_items)
        outer.addWidget(self.status)
        # setCentralWidget hides and deletes the previous one itself.
        self.setCentralWidget(root)
        self.root = root
        # Tight's drawer: empty and hidden until the tier gives it the rail.
        self.drawer = RailDrawer(root, self._rail_style)
        self.drawer.follow(self._place_drawer)

        # Overlays ----------------------------------------------------------------
        self.glow = OnAirGlow(root)
        self.toasts = ToastHost(root)
        self.overlay = ShortcutOverlay(root, self.SHORTCUTS)
        self.built = True
        # New widgets: the workspace and the tier are applied to them afresh.
        self.workspace = None
        self._tx_form = None
        self.tier = None
        self.modegrid.set_caps(b.st.get("modes") or {})
        self.mode_btn.set_caps(b.st.get("modes") or {})
        self.mode_btn.set_mode(b.st.get("mode", "usb"))
        if self.split_ready:
            # A rebuild (theme, text size): restore_state does this the
            # first time, once the window has its size.
            self.sync_tier()
        self.switch_panel(b.st.get("mode", "usb"))
        self._sync_ptt()
        self._sync_header(None)

    # ================================================================ the app's parts
    def _header_status(self, head) -> None:
        """Add the app's status widgets to the header, between the readout
        and the PTT button; animated ones go in self.tickers."""

    def _under_header(self, body) -> None:
        """Add the app's own row(s) between the header and the scopes (HAM:
        the band bar) to the body's vertical layout."""

    def _transmit_card(self):
        """The app's transmit card for the rail, or None."""
        return None

    def _sync_header(self, ch: dict | None) -> None:
        """Bring the header's status widgets up to date (ch None: all of it)."""

    def status_items(self, st: dict) -> list[tuple[str, str]]:
        """The app's items in the status strip."""
        return []

    def settings_dialog(self):
        raise NotImplementedError

    def welcome_dialog(self):
        raise NotImplementedError

    def about_dialog(self):
        raise NotImplementedError

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.built:
            if self.split_ready:
                self.sync_tier()
            # The workspace's fractions, applied to the new size: a layout
            # dragged at 1920 x 1080 is the same layout full screen or on a
            # laptop (Qt's own stretch factors would let the rail and the
            # zoom drift from it).
            if self.split_ready and self.workspace is not None:
                self._apply_sizes(self._ws_layout(self.workspace))
            if self.workspace is not None:
                self._sync_ws_ui()
            self.glow.setGeometry(self.centralWidget().rect())
            self._place_drawer()
            self.toasts.reposition()
            if self.overlay.isVisible():
                self.overlay.setGeometry(self.centralWidget().rect())

    # ================================================================ panels
    def switch_panel(self, mode: str):
        key = panel_key(mode)
        info = (self.bridge.st.get("modes") or {}).get(mode, {})
        p = self._ensure_panel(key)
        if p is not self.panel:
            self._relayout_soon()
        self.panel = p
        self.panel_stack.setCurrentWidget(p)
        title, missing = self.mode_line(mode, info if isinstance(info, dict) else {})
        self.panel_title.setText(title)
        self.panel_title.setStyleSheet(f"color: {theme.t()['warn' if missing else 'text2']};")
        self._title_missing = missing
        self._sync_title()
        if key == "slot":
            p._refresh()
        elif key == "text":
            self._set_zoom_offsets(rx=mode_offset(mode))
        else:
            self.zoom.audio_offsets = {}
        if hasattr(p, "on_state"):
            p.on_state({"mode": mode})
        # After the mode change it follows, never before (plan 2.2).
        self._follow_mode(mode)

    def _sync_title(self) -> None:
        """The Operate page's first line, except in Tight when it says no
        more than the mode button beside the tabs: there the height is the
        panel's (a 1024 x 600 window has 22 px fewer to spare than the
        voice panel needs with it). What a mode is missing always shows."""
        self.panel_title.setVisible(self.tier != TIGHT or getattr(self, "_title_missing", False))

    def mode_line(self, mode: str, info: dict) -> tuple[str, bool]:
        """The Operate page's first line for `mode`, and whether it says
        what the mode is missing here (shown in the warning colour): "FT8 ·
        15 s periods", "JS8 · receive only", "FreeDV — needs codec2"."""
        name = MODE_LABELS.get(mode, mode.upper())
        if info.get("missing"):
            return f"{name}  —  {info['missing']}", True
        parts = [name]
        spec = slot_spec(mode)
        if spec is not None:
            parts.append(QCoreApplication.translate("BaseWindow", "{secs} s periods").format(secs=f"{spec.period:g}"))
        if info.get("decode") and not info.get("encode"):
            parts.append(QCoreApplication.translate("BaseWindow", "receive only"))
        return "  ·  ".join(parts), False

    def _ensure_panel(self, key: str):
        """The mode panel `key`, made the first time it is wanted."""
        if key not in self.panels:
            p = make_panel(key, self.bridge, self.prefs)
            self.panels[key] = p
            self.panel_stack.addWidget(p)
            if key == "slot":
                p.on_offsets = lambda rx, tx: self._set_zoom_offsets(rx=rx, tx=tx)
        return self.panels[key]

    def _set_zoom_offsets(self, rx=None, tx=None):
        d = {}
        if rx is not None:
            d["rx"] = float(rx)
        if tx is not None:
            d["tx"] = float(tx)
        self.zoom.audio_offsets = d
        self.zoom.update()

    def make_extra_view(self, key: str) -> QWidget:
        """Build the app's own view `key` (one of EXTRA_VIEWS)."""
        raise NotImplementedError

    def view_keys(self) -> list[str]:
        return ["mode", "log", "mem", *(k for k, _l, _s in self.EXTRA_VIEWS)]

    def show_view(self, v: str, remember: bool = True):
        """Show lower view `v`. `remember`: the operator chose it, so the
        workspace showing opens on it next time (a switch or a rebuild
        showing a view is not a choice)."""
        self.views.set_value(v)
        keys = self.view_keys()
        idx = keys.index(v)
        if remember and self.workspace is not None and v != self._ws_layout(self.workspace)["view"]:
            self.prefs["workspaces"] = wsm.remember(self.prefs["workspaces"], self.workspace, view=v)
        if idx != self.stack.currentIndex():
            self._relayout_soon()
        if v == "log":
            self.logview.reload()
        elif v == "mem":
            self.memview.reload()
        self.stack.setCurrentIndex(idx)

    # ================================================================ bridge
    def on_state(self, ch: dict):
        if not self.built:
            return
        b = self.bridge
        if "mode" in ch:
            self.modegrid.set_mode(ch["mode"])
            self.mode_btn.set_mode(ch["mode"])
            self._sync_mode_btn()
            self.switch_panel(ch["mode"])
            if ch["mode"] != self.last_mode:
                for sc in (self.wide, self.zoom):
                    sc.tags.clear()          # last mode's streaming text means nothing now
                # Each mode has its natural step (10 Hz CW, 500 Hz FT8 channels...).
                if self.last_mode is not None:
                    self.step = DEFAULT_STEP.get(ch["mode"], 100)
                    self.readout.set_step(self.step)
                self.last_mode = ch["mode"]
        if "modes" in ch:
            self.modegrid.set_caps(ch["modes"] or {})
            self.modegrid.set_mode(b.st.get("mode"))
            self.mode_btn.set_caps(ch["modes"] or {})
        for w in (self.rxcard, self.txcard):
            if w is not None:
                w.on_state(ch)
        for p in self.panels.values():
            p.on_state(ch)
        if self.second is not None:
            self.second.on_state(ch)
        if any(k in ch for k in ("keyed", "txBlocked", "txSeconds", "canTx", "running", "txTimeoutSec", "txSource",
                                 "error", "mode", "txStartAt", "txWarning") + b.face.on_air_keys):
            self._sync_ptt()
        self._sync_header(ch)
        if "simWhy" in ch or "simFallback" in ch:
            self.sim_badge.set_state(b.st)
        if "recording" in ch:
            recording.sync(self)
        if "playing" in ch or "playLoop" in ch:
            playback.sync(self)
        self.status.update()

    def _sync_ptt(self):
        st = self.bridge.st
        keyed = bool(st.get("keyed"))
        # FT8/FT4, PSK/RTTY, SSTV and HSmodem send from their own panel
        # (queued text, scheduled slots, a file) rather than this button;
        # panel_key() is the same lookup that picks which panel is shown, so
        # the two can never disagree.
        panel = panel_key(st.get("mode", "usb")) in ("slot", "text", "image", "data")
        # ON AIR follows the transmitter radiating (Face.on_air), not keyed:
        # an FT8 over is keyed from 2.5 s into the slot before it, and with
        # an IC-9700 only the radio knows when it is really transmitting.
        # The button also wants our own over (keyed), so a 9700 keyed by
        # hand at its microphone lights the frame but shows no session
        # timer that is not counting it.
        on_air = self.bridge.face.on_air(st)
        self.ptt.set_status(on_air and keyed, "" if keyed else self.bridge.can_key(),
                            float(st.get("txSeconds") or 0), float(st.get("txTimeoutSec") or 300),
                            st.get("txSource", ""), panel=panel, armed_at=self._armed_at(),
                            mode=st.get("mode", "usb"), tx=txstate.of_bridge(self.bridge))
        self.glow.set_on(on_air)
        if not keyed:
            self.ptt_latched = False
        self._sync_txcard()

    def _armed_at(self) -> float | None:
        """While transmit is armed but nothing is on the air: when the next
        over's audio is due (UTC seconds; 0.0 when not known yet), else
        None. Armed is an over queued and waiting for its slot or its
        key-up, or a panel's Enable TX on between overs - the state Ray
        read as "transmitting before the RX slot is done"."""
        st = self.bridge.st
        if self.bridge.face.on_air(st):
            return None
        if st.get("keyed"):
            return float(st.get("txStartAt") or 0.0)
        nxt = getattr(self.panel, "next_over_at", None)
        return nxt() if nxt is not None else None

    def on_meter(self, m: dict):
        self.rxcard.on_meter(m)
        if self.txcard is not None:
            self.txcard.on_meter(m)
        if self.panel is not None and hasattr(self.panel, "on_meter"):
            self.panel.on_meter(m)
        if self.second is not None:
            self.second.on_meter(m)

    def on_zoom_lines(self, lines):
        p = self.panels.get("text")
        if p is not None and p is self.panel:
            p.scan(lines)
        # SNR in the receive passband, from the zoom spectrum: the strongest
        # tenth of the passband's bins against the median of the whole span.
        _t, start, bin_hz, db = lines[-1]
        dial, plo, phi = self.zoom._passband_abs()
        i0 = int(max(0, (min(plo, phi) - start) / bin_hz))
        i1 = int(min(len(db), (max(plo, phi) - start) / bin_hz + 1))
        if i1 - i0 >= 3:
            med = float(np.median(db))
            snr = float(np.percentile(db[i0:i1], 90) - med)
            # The same median, as the noise a passband this wide holds: the
            # S-meter's "dB over noise" reference.
            noise = passband_noise_dbfs(med, bin_hz, abs(phi - plo), int(self.bridge.st.get("zoomAvg", 2)))
            self.rxcard.set_snr(max(0.0, snr), noise)

    def on_event(self, ev: dict):
        for p in self.panels.values():
            p.on_event(ev)
        if self.second is not None:
            self.second.on_event(ev)
        self.label_event(ev, (self.wide, self.zoom))

    def label_event(self, ev: dict, scopes):
        mode = ev.get("mode")
        dial = float(ev.get("dial") or self.bridge.st.get("rxDial") or 0)
        if is_slot(mode) and ev.get("text"):
            slot = float(ev.get("slot") or ev.get("t") or time.time())
            f = dial + float(ev.get("df", 1500))
            words = ev["text"].upper().split()
            my = (self.bridge.st.get("callsign") or "").upper()
            kind = "mine" if my and my in words else "cq" if words[:1] == ["CQ"] else ""
            ft8 = self.panels.get("slot")
            if ft8 is not None and (ev.get("call") or "").upper() in ft8.worked and kind != "mine":
                kind = "worked"
            # JS8 at the speed it was decoded at (each event says): a Slow
            # frame is 25 s long and an Ultra one 2.5 s, so Normal's timing
            # pinned their labels well off their traces (WP3's note).
            spec = js8_slot(ev.get("speed") or "") if mode == "js8" else slot_spec(mode)
            anchor = slot + spec.label_at
            for s in scopes:
                text = ev["text"] if not s.wide else (ev.get("call") or ev["text"])
                s.add_label(f, text, anchor, kind, call=ev.get("call") or "")
        elif mode in ("cw", "psk31", "psk63", "psk125", "rtty") and ev.get("text"):
            off = ev.get("freq") or ev.get("center") or ev.get("df") or mode_offset(mode)
            text = ev["text"]
            if text.startswith("[") and text.endswith("]"):
                text = "\u00b7"         # an unreadable CW pattern: a dot on the tag, not the dashes
            for s in scopes:
                s.add_tag(dial + float(off), text, time.time())

    def on_toast(self, it: dict):
        if self.built:
            self.toasts.show_toast(it.get("level", "info"), it.get("text", ""))
            self.toasts.reposition()

    def on_tick(self, dt: float):
        for w in (*self.tickers, self.ptt, self.glow):
            w.tick(dt)
        self.rxcard.tick(dt)
        if self.txcard is not None:
            self.txcard.tick(dt)
        for p in self.panels.values():
            p.tick(dt)
        if self.second is not None:
            self.second.tick(dt)
        self._t_status = getattr(self, "_t_status", 0.0) + dt
        if self._t_status > 1.0:
            self._t_status = 0.0
            self.status.timings = self.timings_text()
            self.status.update()
            # Armed counts down to the next over, so it repaints too.
            if self.bridge.st.get("keyed") or self.ptt.armed_at is not None or self._armed_at() is not None:
                self._sync_ptt()

    # ================================================================ tuning
    def tune_to(self, f: float):
        sp = self.bridge.spec("vfo")
        f = max(sp["min"], min(sp["max"], float(f)))
        self.bridge.set(vfo=f)

    def step_tune(self, n: int, step: float | None = None):
        step = step or self.step
        vfo = float(self.bridge.st.get("vfo", 0))
        # Steps land on the step's grid, as a dial's detents would: from an odd
        # frequency the first step goes to the next grid line, not past it.
        nv = vfo + n * step
        if step >= 10:
            nv = round(nv / step) * step if abs(n) > 1 else (
                (vfo // step + 1) * step if n > 0 else -((-vfo) // step + 1) * step)
        self.tune_to(nv)

    def cycle_step(self, d: int):
        steps = self.STEPS
        i = steps.index(self.step) if self.step in steps else 3
        self.step = steps[max(0, min(len(steps) - 1, i + d))]
        self.readout.set_step(self.step)

    def scope_click(self, f: float, mods):
        st = self.bridge.st
        mode = st.get("mode", "usb")
        target = click_to_dial(mode, f, st, mode_offset(mode))
        if st.get("ritOn"):
            target -= float(st.get("rit") or 0)
        self.tune_to(target)

    def scope_menu_items(self, f: float) -> list[tuple[str, object, bool]]:
        """The right-click menu on a scope at dial frequency `f`: (text,
        callable, is the likeliest) per entry. Both apps offer auto-tune
        there in USB and LSB; an app adds its own (NB: lock to a beacon)."""
        if self.bridge.st.get("mode") not in ("usb", "lsb"):
            return []
        return [("Auto-tune onto the voice here", lambda: self.auto_tune_at(f), False)]

    def auto_tune_at(self, f: float):
        """Auto-tune onto the voice at `f`: the engine first puts the dial
        on that voice's carrier as the recent spectrum places it (where the
        mouse was, rounded as a click would round it, if nothing there looks
        like a voice), then lands it exactly (Engine.auto_tune)."""
        st = self.bridge.st
        mode = st.get("mode", "usb")
        dial = click_to_dial(mode, f, st, mode_offset(mode))
        if not self.bridge.tune_with(lambda: self.bridge.radio.auto_tune(dial)):
            return
        self.bridge.st["autoBusy"] = "tune"
        self.rxcard._sync_auto()

    def scope_menu(self, f: float, where) -> None:
        items = self.scope_menu_items(f)
        if not items:
            return
        # popup(), not exec(): exec() would run a nested event loop inside
        # the scope's mouse handler. Kept on self so it is not collected
        # while open (and so a test can find it). An entry whose second
        # field is a list of (text, callable) is a submenu (Radio's "Decode
        # here as").
        self.scope_menu_open = menu = QMenu(self)
        for text, fn, likeliest in items:
            if isinstance(fn, list):
                sub = menu.addMenu(text)
                for sub_text, sub_fn in fn:
                    a = sub.addAction(sub_text)
                    a.triggered.connect(lambda _=False, fn=sub_fn: fn())
                continue
            act = menu.addAction(text)
            act.triggered.connect(lambda _=False, fn=fn: fn())
            if likeliest:
                menu.setDefaultAction(act)
        menu.popup(where)

    def offset_click(self, off: float, is_tx: bool):
        p = self.panels.get("slot")
        if p is None:
            return
        if is_tx:
            p.set_offsets(tx=off)
        else:
            p.set_offsets(rx=off, tx=None if p.hold.on else off)

    def psk_channel_click(self, off: float):
        """A click on a station on the zoom in PSK: decode it too (one more
        of pskChannels), or stop decoding it when it already is. The mode's
        own channel, at its offset, is always decoded. Within a signal's
        width of a channel counts as that channel."""
        st = self.bridge.st
        mode = st.get("mode", "psk31")
        near = max(20.0, 1.5 * {"psk63": 62.5, "psk125": 125.0}.get(mode, 31.25))
        chans = [float(c) for c in st.get("pskChannels") or []]
        hit = next((c for c in chans if abs(c - off) <= near), None)
        if hit is not None:
            chans.remove(hit)
        elif abs(off - mode_offset(mode)) <= near:
            self.bridge.say(self.tr("That station is the one on the decoder's own channel"), "info")
            return
        elif len(chans) >= PSK_MORE_MAX:
            self.bridge.say(self.tr("PSK decodes at most {n} stations at once: click one to stop it first").format(
                n=PSK_MORE_MAX + 1), "info")
            return
        else:
            chans.append(float(round(off)))
        self.bridge.set(quiet=True, pskChannels=chans)

    def set_mode(self, mode: str):
        """A mode button or mode key: a request to operate in `mode`."""
        # set_mode_tuned (Engine), not plain set(): a mode with a usual
        # operating frequency tunes there too, unless the dial is already
        # in it, Settings turned that off, or the radio is keyed.
        if self.bridge.set_mode_tuned(mode):
            self.operate_requested()

    def operate_requested(self) -> None:
        """The operator asked for a mode (a mode button, a mode key, the
        pad's MODE key): its workspace comes back, even from one pinned by
        hand (decision 2), and the Operate page shows. Tuning from the Band
        list, a memory or a scope does not come here, so browsing the band
        from Watch stays in Watch."""
        was = self.ws.choice
        self.ws.mode_requested()
        if self.ws.choice != was:
            self.prefs["workspace"] = self.ws.choice
            self.prefs.save()
        self._follow_mode(self.bridge.st.get("mode", "usb"))
        self.show_view("mode")

    def chip(self, which: str):
        st = self.bridge.st
        if which == "rit":
            self.bridge.set(ritOn=not st.get("ritOn"))
        elif which == "xit":
            self.bridge.set(xitOn=not st.get("xitOn"))
        elif which == "split":
            on = not st.get("split")
            kw = {"split": on}
            if on and abs(float(st.get("txVfo", 0)) - float(st.get("vfo", 0))) > 50_000:
                kw["txVfo"] = st.get("vfo")
            self.bridge.set(**kw)

    def filter_step(self, wider: bool):
        st = self.bridge.st
        mode = st.get("mode")
        if mode == "cw":
            w = float(st.get("cwWidth", 500)) * (1.25 if wider else 0.8)
            sp = self.bridge.spec("cwWidth")
            self.bridge.set(cwWidth=round(max(sp["min"], min(sp["max"], w)) / 10) * 10)
        elif mode == "am":
            sp = self.bridge.spec("amWidth")
            self.bridge.set(amWidth=max(sp["min"], min(sp["max"], float(st.get("amWidth", 3000)) + (500 if wider else -500))))
        else:
            sp = self.bridge.spec("filterHi")
            self.bridge.set(filterHi=max(sp["min"], min(sp["max"], float(st.get("filterHi", 2700)) + (100 if wider else -100))))

    # ================================================================ PTT
    def ptt_input(self, down: bool):
        """Button or space bar. Hold: key while held. Toggle: each press flips."""
        hold = self.bridge.st.get("pttMode", "hold") == "hold"
        keyed = self._keyed()
        if down and self.ptt.armed_at is not None:
            # The button reads ARMED: pressing it is Halt, as Escape is -
            # Enable TX off and any queued over dropped - not a key-up.
            self.unkey_all()
            self._sync_ptt()
            return
        if hold:
            if down and not keyed:
                self.bridge.ptt(True)
            elif not down:
                # Always: unkeying is idempotent, and a release must never be
                # lost to a state snapshot that has not caught up yet.
                self.bridge.ptt(False)
        elif down:
            self.bridge.ptt(not keyed)
        self.bridge.st.update({"keyed": bool(self.bridge.radio.state().get("keyed"))})
        self._sync_ptt()
        self.readout.update()

    def _keyed(self) -> bool:
        """Keyed right now, from the engine - not the state feed's snapshot,
        which can trail a key-up by a tenth of a second."""
        return bool(self.bridge.radio.state().get("keyed"))

    def unkey_all(self):
        """Escape: everything stops now - queued text, FT8's auto-sequence,
        and what the radio still holds of the over (Bridge.halt), which a
        released PTT would have let go out."""
        for p in self.panels.values():
            if hasattr(p, "txq"):
                p.txq.clear()
            if hasattr(p, "set_tx_enabled"):
                p.set_tx_enabled(False)
        # A voice keyer's CQ loop waiting for its next call is not keyed,
        # but Escape means it too.
        if self._keyed() or self.bridge.radio.keyer.looping():
            self.bridge.halt()

    # ================================================================ keys
    def _shortcuts(self):
        def sc(seq, fn):
            s = QShortcut(QKeySequence(seq), self)
            s.setContext(Qt.ShortcutContext.WindowShortcut)
            s.activated.connect(fn)
        for k, m in self.MODE_KEYS.items():
            sc(QKeySequence(Qt.KeyboardModifier.ControlModifier.value | k.value), lambda m=m: self.set_mode(m))
        for i in range(9):
            sc(f"Alt+{i + 1}", lambda i=i: self.memview.recall_index(i))
        # The macro buttons were labelled F1, F2 ... from the start, but no
        # key was bound to them. Window-wide shortcuts, so they work while
        # typing in the transmit line - which is where an operator's hands
        # are when they want "F2: their call de mine". F11 (full screen) is
        # the only other function key in use, and there are at most eight.
        for i in range(MacroBar.MAX):
            sc(f"F{i + 1}", lambda i=i: self.fire_macro(i))

    def fire_macro(self, i: int) -> bool:
        """F1 ... F8: the current mode's macro button i, as if clicked - the
        CW and keyboard modes' macros, or in the voice modes the voice
        keyer's memories (F1 ... F6; ohscore/ui/keyer.py). One row of keys
        for "send memory n", whichever kind the mode has, as a contest
        logger has it. Does nothing in a mode without either, past the last
        one, or while the Logbook or Memories is showing instead: a key that
        transmits should only do so with the button saying what it sends in
        view."""
        bar = getattr(self.panel, "macros", None) or getattr(self.panel, "keyer", None)
        return bar is not None and bar.trigger(i)

    def _typing(self) -> bool:
        w = QApplication.focusWidget()
        return isinstance(w, TEXT_INPUTS)

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        t = ev.type()
        if t not in (QEvent.Type.KeyPress, QEvent.Type.KeyRelease):
            return False
        # Each key event passes this filter twice - addressed to the QWindow,
        # then to the focused widget. Only the widget delivery counts (or
        # toggle-mode PTT would flip twice), and only for our own windows
        # (dialogs keep their keys).
        if not isinstance(obj, QWidget):
            return False
        top = obj.window()
        if top is not self and (self.second is None or top is not self.second):
            return False
        if self.overlay.isVisible():
            return False
        k = ev.key()
        mods = ev.modifiers()
        if t == QEvent.Type.KeyPress and k == Qt.Key.Key_Escape:
            # Armed between overs (Enable TX on, nothing keyed) counts: the
            # button reads ARMED, and Escape must stop what it promises.
            if self._keyed() or self.bridge.radio.keyer.looping() or self._armed_at() is not None or any(
                    getattr(p, "txq", None) and p.txq.pending for p in self.panels.values()):
                self.unkey_all()
                return True
            # Nothing to stop: Esc closes Tight's drawer (and only then).
            if self.drawer.isVisible():
                self.close_drawer()
                return True
            return False
        if self._typing():
            return False
        fw = QApplication.focusWidget()
        if k == Qt.Key.Key_Space and isinstance(fw, FocusVisible) and fw.focus_visible() and fw is not self.ptt:
            # Someone tabbed to a control: Space works it, as everywhere else.
            return False
        if k == Qt.Key.Key_Space and not (mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier)):
            if ev.isAutoRepeat():
                return True
            if t == QEvent.Type.KeyPress:
                self.space_down = True
                self.ptt_input(True)
            else:
                self.space_down = False
                self.ptt_input(False)
            return True
        if t != QEvent.Type.KeyPress:
            return False
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        if k in (Qt.Key.Key_Left, Qt.Key.Key_Right) and not isinstance(QApplication.focusWidget(),
                                                                        (Segmented,)) and not getattr(
                QApplication.focusWidget(), "set_value", None):
            d = 1 if k == Qt.Key.Key_Right else -1
            if ctrl:
                self.step_tune(d, 1)
            else:
                self.step_tune(d * (10 if shift else 1))
            return True
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.AltModifier):
            return False
        if k == Qt.Key.Key_W:
            # By the key, not its text: Shift+W reads "w" or "W" depending
            # on the platform and Caps Lock, and both must mean Auto.
            if shift:
                self.choose_workspace(wsm.AUTO)
            else:
                self.cycle_workspace()
            return True
        text = ev.text()
        st = self.bridge.st
        actions = {
            "[": lambda: self.cycle_step(-1), "]": lambda: self.cycle_step(+1),
            "f": self.readout.open_editor, "F": self.readout.open_editor,
            "z": lambda: self.zoom.zoom_by(0.8), "Z": lambda: self.zoom.zoom_by(1.25),
            ",": lambda: self.filter_step(False), ".": lambda: self.filter_step(True),
            "r": lambda: self.chip("rit"), "x": lambda: self.chip("xit"), "s": lambda: self.chip("split"),
            "n": lambda: self.bridge.set(nb=not st.get("nb")), "N": lambda: self.bridge.set(nr=not st.get("nr")),
            "m": lambda: self.bridge.set(mute=not st.get("mute")),
            "a": lambda: self.rxcard.request("tune"), "A": lambda: self.rxcard.request("audio"),
            "l": self.toggle_scope_labels, "L": self.toggle_scope_labels,
            "?": self.overlay.open,
        }
        fn = actions.get(text)
        if fn is not None:
            fn()
            return True
        return False

    def toggle_scope_labels(self):
        """L: every scope's signal labels off or on (scope.labels_shown) -
        the Adjust panel's "Show signal labels", without opening it. L
        was free in both apps' sheets; "l" and "L" both, so Caps Lock does
        not take it away."""
        from .scope import labels_shown, set_labels_shown
        set_labels_shown(self.prefs, not labels_shown(self.prefs))

    # ================================================================ windows
    def toggle_second(self):
        from .second import SecondDisplay
        if self.second is None:
            self.second = SecondDisplay(self.bridge, self.prefs, self)
            self.second.closed.connect(self._second_closed)
            self.second.open_on_screen()
            self.prefs["secondDisplay"] = True
        else:
            self.second.close()
            return
        self.act_second.setChecked(True)
        self.btn_second.set_checked(True)
        self.prefs.save()

    def _second_closed(self):
        self.second = None
        self.act_second.setChecked(False)
        self.btn_second.set_checked(False)
        if not self.closing:
            self.prefs["secondDisplay"] = False
            self.prefs.save()

    closing = False

    def open_settings(self, page: str = "", anchor: str = ""):
        d = self.settings_dialog()
        if page:
            d.show_page(page, anchor)
        if d.exec():
            self.apply_prefs(d.restart_needed)

    def open_voice_memories(self):
        from .keyer import open_editor
        open_editor(self.bridge, self)
        for p in self.panels.values():
            if getattr(p, "keyer", None) is not None:
                p.keyer.rebuild()

    def open_scope_colours(self):
        """A scope's adjust panel asked for the colours, which are shared
        by every scope and so live in Settings › Display. Queued: the
        request comes from a popup that is still closing."""
        QTimer.singleShot(0, lambda: self.open_settings("page_display", "look_anchor"))

    def open_welcome(self):
        w = self.welcome_dialog()
        if w.exec():
            self.apply_prefs(w.restart_needed)

    def open_about(self):
        self.about_dialog().exec()

    def save_diagnostics(self):
        from . import diagnostics
        diagnostics.save_diagnostics(self).exec()

    def open_log_folder(self):
        from . import diagnostics
        diagnostics.open_folder(diagnostics.log_folder(self.bridge.radio))

    def apply_prefs(self, restart: bool):
        self.bridge.licence_ok = bool(self.prefs["licenceAck"])
        # A new text size takes the same rebuild as a new theme: every
        # widget sizes its fonts when it is made.
        if self.prefs["theme"] != theme.t()["name"] or theme.nearest_scale(self.prefs["textScale"]) != theme.scale():
            self.set_theme(self.prefs["theme"])
        for s in (self.wide, self.zoom):
            s.set_palette(self.prefs["palette"])     # repaints, and with it the scope colours
        self.rxcard.s.apply_prefs()
        if self.second is not None:
            self.second.apply_prefs()
        if restart:
            self.restart_radio()
        self._sync_ptt()

    def set_palette(self, name: str):
        self.prefs["palette"] = name
        self.prefs.save()
        for sc in (self.wide, self.zoom):
            sc.set_palette(name)
        if self.second is not None and self.second.scope is not None:
            self.second.scope.set_palette(name)

    def restart_radio(self):
        err = self.bridge.restart()
        self.on_toast({"level": "error" if err else "info",
                       "text": err or "The radio restarted with the new settings (receiving, not transmitting)."})

    def set_theme(self, name: str):
        """Rebuild the window in theme `name`, keeping what the operator was
        watching. Two things changed on 17/10/2026, after NB's Mac test:

        - The waterfalls, the band activity and the text received are
          carried over (_carry_over). The rebuild used to start them empty:
          a theme toggle cleared half a minute of waterfall and every decode
          on screen. Colours are baked into a decode row and a terminal's
          text as they are added, so those are replayed into the new
          widgets, not copied; a waterfall's rows are palette colours,
          which a theme does not change. An FT8 QSO's sequence and Enable
          TX are not: a theme change leaves transmit disarmed, as a fresh
          window does.
        - The old window is gone before the new stylesheet is set. Setting
          it restyled every widget about to be thrown away - 0.6-1.2 s of
          the GUI thread on ohs-dev, during which receive starved
          (tools/rx_storm.py: a toggle took 1.4-2.4 s and cost receive
          blocks and audio underruns).

        The text size (prefs "textScale") is applied here too, so a change
        of size is the same rebuild with the same carry-over."""
        self.save_state()
        self.prefs["theme"] = name
        self.prefs.save()
        theme.set_theme(name)
        was = theme.scale()
        rescaled = theme.set_scale(self.prefs["textScale"]) != was
        mode_view = self.views.value if self.built else None
        keep = self._detach_for_rebuild() if self.built else None
        if rescaled:
            # After the detach, as the stylesheet: a new application font
            # restyles every widget there is.
            QApplication.instance().setFont(theme.app_font())
            # The least window is scaled with the text (layoutrules).
            self.apply_minimum()
        QApplication.instance().setStyleSheet(theme.stylesheet())
        self.act_theme.setChecked(name == "light")
        self.build()
        self.restore_splitters()
        if mode_view is not None:
            self.show_view(mode_view, remember=False)
        self.on_state(dict(self.bridge.st))
        if keep is not None:
            self._carry_over(keep)
        if self.second is not None:
            self.second.rebuild()

    def _detach_for_rebuild(self) -> dict:
        """Take the scopes and the mode panels out of the window and delete
        the rest of it now, rather than when the event loop next runs: the
        new stylesheet then restyles only what is kept. The kept widgets are
        hidden orphans until _carry_over has read them."""
        from PyQt6 import sip
        keep = {"scopes": (self.wide, self.zoom), "panels": dict(self.panels)}
        for w in (*keep["scopes"], *keep["panels"].values()):
            w.hide()
            w.setParent(None)
        root = self.takeCentralWidget()
        if root is not None:
            sip.delete(root)
        self.built = False
        return keep

    def _carry_over(self, keep: dict, tries: int = 50):
        """Give the new widgets the old ones' history, then delete the old.
        The scopes wait until the new ones have their size (a widget added
        to a shown window is shown, and laid out, from the event loop), as
        the second display's do before they adopt the main one's."""
        from PyQt6 import sip
        for key, old in keep.pop("panels", {}).items():
            if hasattr(old, "carry_from"):
                self._ensure_panel(key).carry_from(old)
            sip.delete(old)
        if self.wide.height() < 50 and tries > 0:
            QTimer.singleShot(20, lambda: self._carry_over(keep, tries - 1))
            return
        for new, old in zip((self.wide, self.zoom), keep["scopes"]):
            new.adopt(old)
            sip.delete(old)

    # ================================================================ workspaces
    def watch_view(self) -> str:
        """The view Watch opens on: the app's band view, its last own view
        (NB's Band list, Radio's CW Activity), or Operate without one."""
        return self.EXTRA_VIEWS[-1][0] if self.EXTRA_VIEWS else "mode"

    def _ws_layout(self, ws: str) -> dict:
        return wsm.layout(ws, self.prefs["workspaces"].get(ws), self.watch_view())

    def _follow_mode(self, mode: str) -> None:
        ws = self.ws.effective(mode)
        if ws != self.workspace:
            self._apply_workspace(ws)

    def _apply_workspace(self, ws: str) -> None:
        """Show workspace `ws`: its card forms, the scopes' least sizes, its
        proportions and its view. Only resizes and shows or hides what
        exists (plan section 7, rule 6); nothing here changes the mode, the
        frequency or anything about transmitting."""
        t0 = time.perf_counter()
        self.workspace = ws
        lay = self._ws_layout(ws)
        self._apply_forms()
        self.rxcard.set_expanded("receive" in lay["expanded"])
        if self.txcard is not None and hasattr(self.txcard, "set_expanded"):
            self.txcard.set_expanded("transmit" in lay["expanded"])
        self._sync_txcard(fit=False)
        view = lay["view"] if lay["view"] in self.view_keys() else "mode"
        self.show_view(view, remember=False)
        self._fit_rail()
        if self.split_ready:
            # The new page's and forms' least sizes, measured now rather
            # than on the next pass of the event loop, so the splitters are
            # set once, to what fits; the pass _relayout_soon asked for is
            # then not needed.
            QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
            self._apply_sizes(lay)
            self._relayout_due = False
        self._sync_ws_ui()
        self.ws_switch_ms = (time.perf_counter() - t0) * 1000.0

    def _relayout_soon(self) -> None:
        """The workspace's proportions again once Qt has measured a new
        page. A panel or view needs its own least height, and a splitter
        held at one page's minimum (FT8's band activity, the Band list)
        would otherwise stay there after a smaller page replaced it. Next
        time round the event loop, because the new page's minimum is only
        known once its layout has run."""
        if not self._relayout_due:
            self._relayout_due = True
            QTimer.singleShot(0, self._relayout)

    def _relayout(self) -> None:
        # Not due any more when a switch has set the sizes meanwhile.
        if self._relayout_due and self.built and self.split_ready:
            self.restore_splitters()
        self._relayout_due = False

    def _apply_forms(self) -> None:
        """The scopes' least sizes and the rail cards' forms for the
        workspace showing in the tier the window is in (wsm.forms)."""
        tier = self.tier or layoutrules.FULL
        mode, receive, _transmit = wsm.forms(self.workspace, tier)
        self.wide.setMinimumHeight(theme.px(wsm.wide_min(self.workspace, tier)))
        self.zoom.setMinimumWidth(theme.px(wsm.zoom_min(self.workspace, tier)))
        self.modegrid.set_form(mode)
        self.rxcard.set_form(receive)

    def _sync_txcard(self, fit: bool = True) -> None:
        """The Transmit card's form now: hidden in Watch, but back in full
        whenever anything is on the air, armed, or warned about. A card
        with forms (ohscore/ui/txcard.py) is told and shows or hides itself,
        and restores itself while on the air or warned about between our
        calls; one without is shown or hidden here."""
        if self.txcard is None or self.workspace is None:
            return
        st = self.bridge.st
        on_air = bool(self.bridge.face.on_air(st) or st.get("keyed"))
        warning = bool(st.get("txWarning"))
        form = wsm.transmit_form(self.workspace, on_air=on_air, armed=self._armed_at() is not None, warning=warning,
                                 tier=self.tier or layoutrules.FULL)
        self._drawer_for_transmit(on_air, warning)
        was = self.txcard.isVisibleTo(self.rail)
        if hasattr(self.txcard, "set_form"):
            if form != self._tx_form:
                self._tx_form = form
                self.txcard.set_form(form)
        elif (form != wsm.HIDDEN) != was:
            self.txcard.setVisible(form != wsm.HIDDEN)
        if fit and self.txcard.isVisibleTo(self.rail) != was:
            self._fit_rail()

    def _fit_rail(self) -> None:
        """The rail's least width: what its cards need in their forms, and
        the scroll bar it may grow."""
        need = self.rail.minimumSizeHint().width() + self.rail_scroll.verticalScrollBar().sizeHint().width()
        if self.modegrid.form == "compact" and not getattr(self.modegrid, "HAS_COMPACT", False):
            # Watch's slim rail is for the compact Mode card (one button
            # per group, WP2). Until that exists the card is still the grid
            # of four, whose cells' minimum is less than "HSmodem" needs:
            # at 270 px the label was clipped. The grid's own width until
            # then; WP2 sets HAS_COMPACT on ModeGrid when the form is real.
            need = max(need, self.GRID_RAIL)
        self.rail_scroll.setMinimumWidth(min(need, self.rail_scroll.maximumWidth()))
        self.drawer.set_least_width(min(need, self.rail_scroll.maximumWidth()))
        if self.tier == TIGHT:
            self._place_drawer()

    def _sync_ws_ui(self) -> None:
        """The Workspace button's words, as many as the tab row has room
        for: "Workspace: Watch · chosen", "Watch · chosen", then "Watch".
        Never cut off: at 130 % text on a laptop the tab row is short of
        room, and an elided "Wo..." says nothing; the menu it opens names
        every workspace in full."""
        name = workspace_label(self.workspace or wsm.VOICE)
        how = (QCoreApplication.translate("BaseWindow", "chosen") if self.ws.pinned
               else QCoreApplication.translate("BaseWindow", "auto"))
        forms = [QCoreApplication.translate("BaseWindow", "Workspace: {name} · {how}").format(name=name, how=how),
                 f"{name} · {how}", name]
        b = self.ws_button
        fm = QFontMetricsF(b._font())
        lower = self.split_low.widget(1)
        b.setMinimumWidth(int(fm.horizontalAdvance(forms[-1] + "  ▾") + 24))
        if self.tier == TIGHT and lower.width() > 100:
            # Tight's tabs are as wide as their longest label with room to
            # spare; in a longer language that, the mode and Controls
            # buttons and the workspace's name came to 3 px more than a
            # 1024 x 600 window has (en-XA, Digital, WP9), and the whole
            # row was squeezed. The tabs give up their spare room first,
            # down to the least their labels need; they get it back when
            # the row has it again (a shorter workspace name, a wider window).
            self._fit_views()
            lower.layout().invalidate()
            over = lower.minimumSizeHint().width() - lower.width()
            if over > 0:
                self.views.setFixedWidth(max(self.views.minimumSizeHint().width(), self.views.minimumWidth() - over))
        others = sum(w.width() + theme.S2 for w in (self.mode_btn, self.controls_btn) if w.isVisibleTo(lower))
        room = lower.width() - self.views.minimumWidth() - others - 3 * theme.S3 if lower.width() > 100 else 10_000
        pick = next((f for f in forms if fm.horizontalAdvance(f + "  ▾") + 24 <= room), forms[-1])
        b.set_text(pick + "  ▾")
        self.ws_actions[self.ws.choice].setChecked(True)

    def _open_ws_menu(self) -> None:
        # popup(), not exec(): no nested event loop inside a click.
        self.ws_menu.popup(self.ws_button.mapToGlobal(QPoint(0, self.ws_button.height())))

    def choose_workspace(self, choice: str) -> None:
        """Auto, or pin a workspace (the menu, Shift+W for Auto)."""
        if choice == wsm.AUTO:
            self.ws.auto()
        else:
            self.ws.pin(choice)
        self._workspace_chosen()

    def cycle_workspace(self) -> None:
        """W: the next workspace, pinned."""
        self.ws.cycle(self.bridge.st.get("mode", "usb"))
        self._workspace_chosen()

    def _workspace_chosen(self) -> None:
        self.prefs["workspace"] = self.ws.choice
        self.prefs.save()
        self._follow_mode(self.bridge.st.get("mode", "usb"))
        self._sync_ws_ui()

    def reset_workspace(self) -> None:
        """Put the showing workspace's defaults back: proportions, rail,
        view, and its cards' expanded state."""
        if self.workspace is None:
            return
        ws = dict(self.prefs["workspaces"])
        ws.pop(self.workspace, None)
        self.prefs["workspaces"] = ws
        self.prefs.save()
        self._apply_workspace(self.workspace)

    def _card_expanded(self, card: str, on: bool) -> None:
        if self.workspace is None:
            return
        lay = self._ws_layout(self.workspace)
        self.prefs["workspaces"] = wsm.remember(self.prefs["workspaces"], self.workspace,
                                                expanded=wsm.expanded_with(lay["expanded"], card, on))
        self._fit_rail()

    def timings_text(self) -> str:
        """What the GUI thread costs, for the CPU item's tooltip and the
        diagnostics report."""
        return (f"frame {self.bridge.frame_ms:.1f} ms · wide paint {self.wide.cost_paint:.1f} ms"
                f" · line {self.wide.cost_ingest:.2f} ms · workspace switch {self.ws_switch_ms:.1f} ms")

    # ================================================================ tiers
    def screen_room(self) -> tuple[int, int]:
        """The available (width, height) of the screen the window is on:
        the least window is never more than that."""
        if self.SCREEN_ROOM is not None:
            return self.SCREEN_ROOM
        scr = self.screen() or QApplication.primaryScreen()
        if scr is None:
            return (1 << 15, 1 << 15)
        g = scr.availableGeometry()
        return g.width(), g.height()

    def apply_minimum(self) -> None:
        """1024 x 600 at 100 % text, scaled with it, capped to the screen
        (decision 5; it was 1180 x 700, which still broke)."""
        self.setMinimumSize(*layoutrules.minimum_size(theme.scale(), self.screen_room()))

    def showEvent(self, e):
        super().showEvent(e)
        if not self._screen_hooked and self.windowHandle() is not None:
            # Moved to another screen: that screen's room is the cap now.
            self.windowHandle().screenChanged.connect(lambda _s: self.apply_minimum())
            self._screen_hooked = True

    def sync_tier(self) -> None:
        """The tier for the window's size now, applied if it changed."""
        t = layoutrules.tier(self.width(), self.height(), theme.scale())
        if t != self.tier:
            self._apply_tier(t)

    def _apply_tier(self, t: str) -> None:
        """Lay the window out for tier `t`. Like a workspace switch it
        resizes, shows, hides and moves what exists, and touches nothing
        about the radio or transmitting (plan section 7, rules 4 and 6)."""
        t0 = time.perf_counter()
        self.tier = t
        tight = t == TIGHT
        self.brand.set_tier(t)
        self.readout.set_form(t)
        self.ptt.set_form(t)
        for w in self.tickers:
            if hasattr(w, "set_tier"):
                w.set_tier(t)
        for b in self.tool_buttons:
            b.setVisible(not tight)
        self.more_btn.setVisible(tight)
        self.head.setSpacing(theme.px(10) if tight else theme.S5)
        # Tight's height is the panels': the body's margins and gaps halve.
        m = theme.S1 if tight else theme.S2
        self.body_layout.setContentsMargins(theme.S3, m, theme.S3, m)
        self.body_layout.setSpacing(m)
        self._sync_title()
        self.status.set_tier(t)
        self.mode_btn.setVisible(tight)
        self._sync_mode_btn()
        self.controls_btn.setVisible(tight)
        # Views the tab row drops in Tight (TIGHT_MENU_VIEWS): still on the
        # View menu and their shortcut there. Each tab is as wide as the
        # longest label, so a sixth tab cost Radio's 1024 x 600 window its
        # last few pixels in a longer language (en-XA).
        self.views.options = [o for o in self.view_options
                              if not ((tight and o[0] in self.TIGHT_MENU_VIEWS)
                                      or (t != FULL and o[0] in self.COMPACT_MENU_VIEWS))]
        self.views.update()
        self._fit_views()
        if tight:
            self._rail_to_drawer()
        else:
            self._rail_to_side()
        if self.workspace is not None:
            self._apply_forms()
            self._tx_form = None
            self._sync_txcard(fit=False)
            self._fit_rail()
            if self.split_ready:
                QCoreApplication.sendPostedEvents(None, QEvent.Type.LayoutRequest)
                self._apply_sizes(self._ws_layout(self.workspace))
            self._sync_ws_ui()
        self.tier_switch_ms = (time.perf_counter() - t0) * 1000.0

    def _sync_mode_btn(self) -> None:
        """The tab row's mode button lists what the Mode card does: the
        app's over buttons (attached by the app after the window's build)
        and the recent modes first."""
        self.mode_btn.buttons = tuple(getattr(self.modegrid, "buttons", ()))
        self.mode_btn.set_recent(getattr(self.modegrid, "recent", []))

    def _fit_views(self) -> None:
        """The tab row's tabs: a fixed width where there is room for it,
        in Tight only what their labels need (at the text scale, in the
        operator's language)."""
        fm = QFontMetricsF(theme.font(12.5, theme.QFont.Weight.DemiBold))
        n = len(self.views.options)
        need = int(n * (max(fm.horizontalAdvance(lab) for _v, lab in self.views.options) + theme.px(22)) + 6)
        extra = sum(1 for v, _l in self.views.options if v in {k for k, _lab, _sc in self.EXTRA_VIEWS})
        self.views.setFixedWidth(need if self.tier == TIGHT else max(need, theme.px(300 + 110 * extra)))

    # The drawer ------------------------------------------------------------
    def _rail_to_drawer(self) -> None:
        if not self.drawer.isAncestorOf(self.rail):
            self.rail_scroll.takeWidget()
            self.drawer.hold(self.rail)
            # Hidden, the side splitter gives it no room and hides its handle.
            self.rail_scroll.hide()
            self._drawer_cause = (False, False)

    def _rail_to_side(self) -> None:
        if self.drawer.isAncestorOf(self.rail):
            self.close_drawer()
            self.drawer.release()
            self.rail_scroll.setWidget(self.rail)
            self.rail.show()
            self.rail_scroll.show()

    def toggle_drawer(self) -> None:
        if self.drawer.isVisible():
            self.close_drawer()
        else:
            self.open_drawer()

    def open_drawer(self) -> None:
        """Show the rail over the right of the lower panel. Never takes the
        keyboard focus (Space stays PTT, a typed line keeps its caret)."""
        if self.tier != TIGHT:
            return
        self._place_drawer()
        self.drawer.show()
        self.drawer.raise_()
        self.controls_btn.set_checked(True)

    def close_drawer(self) -> None:
        self.drawer.hide()
        self.controls_btn.set_checked(False)

    def _place_drawer(self) -> None:
        """Over the right edge, from under the tab row (never over the
        wide scope, where the band is tuned, nor over Controls, which
        closes it) to the status strip."""
        if not self.built or self.tier != TIGHT:
            return
        root = self.centralWidget()
        top = self.stack.mapTo(root, QPoint(0, 0)).y()
        bottom = self.status.mapTo(root, QPoint(0, 0)).y()
        w = min(max(self.drawer.minimumSizeHint().width(), theme.px(300)), root.width() // 2)
        self.drawer.setGeometry(root.width() - w, top, w, max(100, bottom - top))

    def _drawer_for_transmit(self, on_air: bool, warning: bool) -> None:
        """Plan section 7, rule 3 in Tight, where the Transmit card is in
        the closed drawer: a transmit warning opens it as the warning
        comes up, and so does going on the air from the TX tile or Space
        (the modes that send from their own panel show their over there,
        and opening over that panel every over would hide it). Once: the
        operator may close it again. Controls reads red while either holds."""
        if self.tier != TIGHT:
            self._drawer_cause = (False, False)
            return
        ptt_mode = panel_key(self.bridge.st.get("mode", "usb")) not in ("slot", "text", "image", "data")
        cause = (warning, on_air and ptt_mode)
        if any(now and not was for now, was in zip(cause, self._drawer_cause)):
            self.open_drawer()
        self._drawer_cause = cause
        kind = "danger" if (on_air or warning) else "ghost"
        if self.controls_btn.kind != kind:
            self.controls_btn.kind = kind
            self.controls_btn.update()

    # ================================================================ state
    def save_state(self):
        self.prefs["geometry"] = bytes(self.saveGeometry().toBase64()).decode()
        self._save_legacy_splitters()

    def _dragged(self, ws: str) -> bool:
        lay = self.prefs["workspaces"].get(ws) or {}
        return any(k in lay for k in ("wide", "zoom", "rail"))

    def _save_legacy_splitters(self):
        """The pixel sizes for a downgrade, from the workspace showing, if
        it is one an older version had and the operator changed it."""
        if self.built and self.workspace in LEGACY_PREFS and self._dragged(self.workspace):
            self.prefs[LEGACY_PREFS[self.workspace]] = {n: getattr(self, n).sizes() for n in SPLITTER_NAMES}

    def _split_moved(self, *_):
        """The operator dragged a splitter: the showing workspace keeps the
        new layout as fractions (and the rail in px)."""
        if not self.split_ready or self.workspace is None:
            return
        sizes = {n: getattr(self, n).sizes() for n in SPLITTER_NAMES}
        lay = layout_from_sizes(sizes)
        if self.tier == TIGHT:
            lay.pop("rail", None)               # no rail beside the panels: nothing dragged
        elif self.tier != layoutrules.FULL and "rail" in lay:
            # A rail dragged in Compact is Compact's (wsm.rail_width): kept
            # apart, so the wide rail of a big screen is not narrowed by a
            # drag on a laptop, or the other way round. Tight has none.
            lay["railCompact"] = lay.pop("rail")
        self.prefs["workspaces"] = wsm.remember(self.prefs["workspaces"], self.workspace, **lay)
        self._sync_ws_ui()

    def restore_splitters(self):
        """The showing workspace's proportions: the operator's, or its
        defaults. (Before October 2026 a rebuild, Ctrl+T, left the default
        out, so the new splitters fell back on their stretch factors and a
        theme change widened the rail and narrowed the zoom scope.)"""
        if self.workspace is not None:
            self._apply_sizes(self._ws_layout(self.workspace))

    def _apply_sizes(self, lay: dict) -> None:
        tier = self.tier or layoutrules.FULL
        rail = max(wsm.rail_width(lay, tier, theme.scale()), self.rail_scroll.minimumWidth()) if tier != TIGHT else 0
        sizes = sizes_from_layout({**lay, "rail": rail}, self._split_totals(rail))
        if tier == TIGHT:
            sizes.pop("split_side", None)       # the rail is in the drawer: the splitter holds one widget
        # Outermost first, so each splitter shares out the length it will
        # keep: inner first resized every scope and panel twice, and each
        # resize of a scope reshapes its waterfall image. A splitter already
        # at its sizes is left alone (setSizes lays it out regardless).
        for n in ("split_side", "split_main", "split_low"):
            sp = getattr(self, n)
            if n in sizes and sp.sizes() != sizes[n]:
                sp.setSizes(sizes[n])

    def _split_totals(self, rail: int) -> dict:
        """Each splitter's length to share out: what it has, once it is laid
        out; before that (restore_state runs before the window is shown,
        and a rebuild's splitters are new) what it will have, worked out
        from the window. Qt shares any difference out in proportion when it
        lays them out."""
        w, h = max(1000, self.width()), max(600, self.height())
        nominal = {"split_side": w, "split_main": h - 190, "split_low": w - rail}
        out = {}
        for n in SPLITTER_NAMES:
            sp = getattr(self, n)
            have = sum(sp.sizes())
            out[n] = have if sp.isVisible() and have > 100 else nominal[n]
        # The lower width once the rail has its width: the splitter's own
        # length is the old rail's leftover until Qt lays it out again.
        if self.split_side.isVisible() and sum(self.split_side.sizes()) > 100:
            out["split_low"] = max(100, sum(self.split_side.sizes()) - rail - (self.split_side.handleWidth() if rail else 0))
        return out

    def restore_state(self):
        g = self.prefs["geometry"]
        if g:
            self.restoreGeometry(QByteArray.fromBase64(g.encode()))
        else:
            self.resize(1600, 960)
        self.split_ready = True
        self.sync_tier()
        self.restore_splitters()

    def closeEvent(self, e):
        self.closing = True
        self.unkey_all()
        self.save_state()
        self.bridge.radio.flush_spots()
        self.diagsend.stop()
        if self.second is not None:
            self.second.close()
        self.prefs.save()
        # The key filter is on the whole application (__init__), so it would
        # outlive the window: a closed window went on being asked about
        # every event of every window after it. In one process with one
        # window that was harmless; the test suite opens dozens, and by the
        # end of test_ui_extrig each event passed through every one of them
        # (190,000 Python calls in a single processEvents, a 14 s stall).
        QApplication.instance().removeEventFilter(self)
        super().closeEvent(e)

