"""Broadcast listening on the desktop: wide FM's RDS beside the frequency,
and the station lists the weekly band scan makes (ohsradio/bandscan.py).

- **RdsStrip**, in the header beside the readout while the mode is wide
  FM: the station's programme service name large, a STEREO badge that
  follows the pilot (the meter's `stereo`, so it shows with or without
  RDS), and its RadioText under it as what is playing now. Empty and
  narrow in every other mode.
- **StationsView**, a view beside Decoders: FM programmes (sorted by name
  or frequency, filtered by programme type) and DAB services by
  ensemble, with Scan now and the scan's progress. A click on an FM
  programme tunes to its strongest frequency in wide FM; a click on a DAB
  service starts (or switches) the DAB session for it. It reads the
  engine's scanner directly, as every desktop view reads the engine, and
  refreshes when `stationsAt` or `bandScan` change. DAB services show
  their logo (from the ensemble's SPI, once heard) and programme type.
- **DabNowPlaying**, under the DAB list while a DAB station plays: its
  logo and name, what is on (DL Plus's title and artist, else the
  programme text, and the guide's programme), and its latest slide. It
  looks once a second (the engine's session and its picture store,
  ohscore/dabpics.py): pictures come a few seconds apart at most, and a
  feed subscription would only add a second path for the same thing.

Nothing here keys: tuning and DAB sessions are receive-side.
"""
from __future__ import annotations

from PyQt6.QtCore import QCoreApplication, Qt, QTimer
from PyQt6.QtGui import QIcon, QPixmap
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QSizePolicy, QTreeWidget, QTreeWidgetItem,
                             QVBoxLayout, QWidget)

from ohscore.decoders import Refused
from ohscore.i18n import fmt
from ohscore.ui import theme
from ohscore.ui.controls import Button

FM, DAB = "fm", "dab"


def mhz(hz: float, places: int = 1) -> str:
    return fmt.frequency(int(round(hz)), "MHz", places)


def ps_text(ps: str | None) -> str:
    """A programme service name as shown: the eight characters without their padding."""
    return (ps or "").strip()


class RdsStrip(QWidget):
    """The header's wide FM line: PS large, STEREO, RadioText (module docstring)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        top = QHBoxLayout()
        top.setSpacing(theme.S2)
        self.ps = QLabel("")
        self.ps.setFont(theme.font(22, theme.QFont.Weight.DemiBold))
        self.ps.setTextFormat(Qt.TextFormat.PlainText)
        # Room for any eight-character name from the start: the header's
        # layout gives a label the width it had when it was last laid out,
        # and an empty one has none.
        self.ps.setMinimumWidth(self.ps.fontMetrics().horizontalAdvance("WWWWWWW"))
        top.addWidget(self.ps)
        self.badge = QLabel(self.tr("STEREO"))
        self.badge.setToolTip(self.tr("The station's stereo pilot is heard"))
        k = theme.t()
        self.badge.setStyleSheet(f"QLabel {{ color: {k['bg0']}; background: {k['ok']}; border-radius: 4px;"
                                 f" padding: 1px 6px; font-weight: 600; }}")
        self.badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top.addWidget(self.badge, 0, Qt.AlignmentFlag.AlignVCenter)
        top.addStretch(1)
        lay.addLayout(top)
        self.rt = QLabel("")
        self.rt.setObjectName("Muted")
        self.rt.setTextFormat(Qt.TextFormat.PlainText)
        self.rt.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.rt)
        self.rt_full = ""
        self.mode = ""
        self.rds: dict | None = None
        self.stereo = False
        self._show()

    def on_state(self, st: dict) -> None:
        self.mode = st.get("mode", "")
        self.rds = st.get("rds")
        if self.mode != "wfm":
            self.stereo = False
        elif self.rds is not None:
            self.stereo = bool(self.rds.get("stereo"))
        self._show()

    def on_meter(self, m: dict) -> None:
        if "stereo" in m and bool(m["stereo"]) != self.stereo:
            self.stereo = bool(m["stereo"])
            self._show()

    def _show(self) -> None:
        on = self.mode == "wfm"
        d = self.rds or {}
        self.ps.setText(ps_text(d.get("ps")) if on else "")
        self.badge.setVisible(on and self.stereo)
        rt = (d.get("rt") or "").strip() if on else ""
        self.rt_full = self.tr("Now: {text}").format(text=rt) if rt else ""
        self._elide()
        tip = []
        if on and d.get("pi"):
            tip.append(self.tr("PI {pi}").format(pi=d["pi"]))
            if d.get("ptyName"):
                tip.append(d["ptyName"])
        if self.rt_full:
            tip.append(self.rt_full)
        self.setToolTip(" · ".join(tip))
        self.setVisible(on)

    def _elide(self) -> None:
        # RadioText is up to 64 characters: shown to the strip's width with
        # an ellipsis, all of it in the tooltip.
        self.rt.setText(self.rt.fontMetrics().elidedText(self.rt_full, Qt.TextElideMode.ElideRight,
                                                         max(10, self.width())))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()


def scan_line(view: dict) -> str:
    """The list's own line: when it was made, or why it was not."""
    tr = QCoreApplication.translate
    if view.get("status") == "scanning":
        return tr("StationsView", "Scanning now…")
    parts = []
    if view.get("scannedAt"):
        parts.append(tr("StationsView", "Scanned {when}").format(when=view["scannedAt"].replace("T", " ")
                                                                 .replace("Z", " UTC")))
    if view.get("statusText"):
        parts.append(view["statusText"])
    if view.get("nextDue"):
        parts.append(tr("StationsView", "next scan {when}").format(when=view["nextDue"].replace("T", " ")
                                                                    .replace("Z", " UTC")))
    return " · ".join(parts)


def pixmap(data: bytes | None) -> QPixmap | None:
    """A picture's bytes (PNG or JPEG) as a pixmap; None for none or a
    picture Qt cannot read."""
    if not data:
        return None
    pm = QPixmap()
    return pm if pm.loadFromData(data) and not pm.isNull() else None


class DabNowPlaying(QWidget):
    """The playing DAB station (module docstring)."""

    LOGO = 56
    SLIDE = (320, 240)

    def __init__(self, parent=None):
        super().__init__(parent)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S3)
        self.logo = QLabel()
        self.logo.setFixedSize(theme.px(self.LOGO), theme.px(self.LOGO))
        self.logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self.logo, 0, Qt.AlignmentFlag.AlignTop)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.name = QLabel("")
        self.name.setFont(theme.font(18, theme.QFont.Weight.DemiBold))
        self.name.setTextFormat(Qt.TextFormat.PlainText)
        col.addWidget(self.name)
        self.what = QLabel("")
        self.what.setTextFormat(Qt.TextFormat.PlainText)
        self.what.setWordWrap(True)
        col.addWidget(self.what)
        self.on_now = QLabel("")
        self.on_now.setObjectName("Muted")
        self.on_now.setTextFormat(Qt.TextFormat.PlainText)
        self.on_now.setWordWrap(True)
        col.addWidget(self.on_now)
        col.addStretch(1)
        lay.addLayout(col, 1)
        self.slide = QLabel()
        self.slide.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.slide.setFixedSize(theme.px(self.SLIDE[0]), theme.px(self.SLIDE[1]))
        lay.addWidget(self.slide, 0, Qt.AlignmentFlag.AlignTop)
        self._shown: tuple = ()
        self.setVisible(False)

    def show_session(self, sess: dict | None, pics) -> None:
        """A DAB session's view (Decoders.session), or None when none plays."""
        meta = (sess or {}).get("meta") or {}
        sid = meta.get("playing")
        if not sess or not sid:
            self.setVisible(False)
            self._shown = ()
            return
        svc = next((x for x in meta.get("services") or [] if x.get("sid") == sid), {})
        dl = meta.get("dlPlus") or {}
        if dl.get("itemTitle") and dl.get("itemArtist"):
            what = self.tr("{title} by {artist}").format(title=dl["itemTitle"], artist=dl["itemArtist"])
        else:
            what = (dl.get("itemTitle") or meta.get("dls") or "").strip()
        now = svc.get("now") or {}
        on = self.tr("On now: {name}").format(name=now["name"]) if now.get("name") else ""
        if svc.get("ptyName"):
            on = " · ".join(x for x in (on, svc["ptyName"]) if x)
        slide = (meta.get("slide") or {}) if (meta.get("slide") or {}).get("sid") == sid else {}
        key = (sid, svc.get("label"), what, on, slide.get("rev"), pics.has_logo(sid) if pics else False)
        self.setVisible(True)
        if key == self._shown:
            return
        self._shown = key
        self.name.setText((svc.get("label") or sid).strip())
        self.what.setText(what)
        self.on_now.setText(on)
        logo = pixmap(pics.logo(sid, "square")[0]) if pics is not None and pics.has_logo(sid) else None
        self.logo.setPixmap(logo.scaled(self.logo.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.SmoothTransformation) if logo else QPixmap())
        got = pics.slide(sid) if pics is not None else None
        pm = pixmap(got[0]) if got else None
        self.slide.setPixmap(pm.scaled(self.slide.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                       Qt.TransformationMode.SmoothTransformation) if pm else QPixmap())
        self.slide.setToolTip(slide.get("categoryTitle") or "")


class StationsView(QWidget):
    """The station lists (module docstring). `radio` is the engine; `say`
    shows a sentence the way the window shows a toast."""

    def __init__(self, bridge, prefs, say, parent=None):
        super().__init__(parent)
        self.bridge, self.prefs, self.say = bridge, prefs, say
        self.radio = bridge.radio
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(theme.S2)
        row = QHBoxLayout()
        row.setSpacing(theme.S2)
        self.band = QComboBox()
        self.band.addItem(self.tr("FM"), FM)
        self.band.addItem(self.tr("DAB"), DAB)
        self.band.setToolTip(self.tr("Which list"))
        row.addWidget(self.band)
        self.sort = QComboBox()
        self.sort.addItem(self.tr("By name"), "name")
        self.sort.addItem(self.tr("By frequency"), "freq")
        self.sort.setToolTip(self.tr("How the FM list is ordered"))
        row.addWidget(self.sort)
        self.genre = QComboBox()
        self.genre.setToolTip(self.tr("Only stations of this programme type (from their RDS)"))
        self.genre.setMinimumWidth(theme.px(170))
        row.addWidget(self.genre)
        row.addStretch(1)
        self.scan_btn = Button(self.tr("Scan now"), small=True)
        self.scan_btn.setToolTip(self.tr("Make this list again now (about a minute; the radio is yours again the "
                                         "moment you use it)"))
        self.scan_btn.clicked.connect(self.scan_now)
        row.addWidget(self.scan_btn)
        lay.addLayout(row)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setWordWrap(True)
        self.status.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        lay.addWidget(self.status)
        self.tree = QTreeWidget()
        self.tree.setRootIsDecorated(False)
        self.tree.setUniformRowHeights(True)
        self.tree.itemActivated.connect(self._activated)
        self.tree.itemClicked.connect(self._activated)
        lay.addWidget(self.tree, 1)
        self.playing = DabNowPlaying()
        lay.addWidget(self.playing)
        self._pics_rev = None
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._look)
        self._tick.start()
        self.band.setCurrentIndex(max(0, self.band.findData(prefs.get("stationsBand", FM))))
        self.sort.setCurrentIndex(max(0, self.sort.findData(prefs.get("stationsSort", "name"))))
        for w in (self.band, self.sort, self.genre):
            w.currentIndexChanged.connect(self._chosen)
        bridge.changed.connect(self._state)
        self.refresh()

    def detach(self):
        # A theme change rebuilds the window, and by then Qt may have
        # deleted the old view's timer with its children.
        try:
            self._tick.stop()
        except RuntimeError:
            pass
        try:
            self.bridge.changed.disconnect(self._state)
        except (TypeError, RuntimeError):
            pass

    @property
    def pictures(self):
        return getattr(self.radio, "dab_pictures", None)

    def _look(self) -> None:
        """Once a second (DabNowPlaying's docstring): the playing station,
        and the DAB list again when a logo has come since it was filled."""
        if not self.isVisible():
            return
        held = self._dab_session()
        full = self.radio.decoders.session(held["id"]) if held is not None else None
        self.playing.show_session(full if self.band.currentData() == DAB else None, self.pictures)
        pics = self.pictures
        if pics is not None and self.band.currentData() == DAB and pics.rev != self._pics_rev:
            self._pics_rev = pics.rev
            self.refresh()

    @property
    def scanner(self):
        return getattr(self.radio, "bandscan", None)

    def _state(self, ch: dict) -> None:
        # radioDnsLogos: its fetched logos shown or hidden (dabpics.py).
        if any(k in ch for k in ("stationsAt", "bandScan", "radioDnsLogos")):
            self.refresh()

    def _chosen(self, _i: int = 0) -> None:
        self.prefs["stationsBand"] = self.band.currentData()
        self.prefs["stationsSort"] = self.sort.currentData()
        self.refresh(keep_genre=True)

    # ------------------------------------------------------------ the list
    def refresh(self, keep_genre: bool = True) -> None:
        sc = self.scanner
        band = self.band.currentData()
        fm = band == FM
        self.sort.setVisible(fm)
        self.genre.setVisible(fm)
        self.tree.clear()
        if sc is None:
            self.status.setText(self.tr("This radio has no station lists."))
            return
        view = sc.view(band)
        # The engine's own state, not the window's copy: right after Scan
        # now, the copy has not heard of the scan yet.
        progress = self.radio.state().get("bandScan") or {}
        line = scan_line(view)
        if progress:
            line = self.tr("Scanning: {text} ({percent} %)").format(text=progress.get("text") or "",
                                                                   percent=progress.get("percent", 0))
        self.scan_btn.setEnabled(not progress)
        if fm:
            self._fill_fm(view["stations"], keep_genre)
            if not view["stations"] and not progress:
                line = " · ".join(x for x in (line, self.tr("No FM stations listed yet: Scan now makes the list"))
                                  if x)
        else:
            self._fill_dab(view["ensembles"])
            if not view["ensembles"] and not progress:
                line = " · ".join(x for x in (line, self.tr("No DAB ensembles listed yet: Scan now makes the list"))
                                  if x)
        self.status.setText(line)

    def _fill_fm(self, stations: list[dict], keep_genre: bool) -> None:
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels([self.tr("Station"), self.tr("Frequency"), self.tr("Type"), self.tr("Also on")])
        genres = sorted({p["ptyName"] for p in stations if p.get("ptyName")})
        want = self.genre.currentData() if keep_genre else None
        self.genre.blockSignals(True)
        self.genre.clear()
        self.genre.addItem(self.tr("Every type"), None)
        for g in genres:
            self.genre.addItem(g, g)
        self.genre.setCurrentIndex(max(0, self.genre.findData(want)) if want else 0)
        self.genre.blockSignals(False)
        want = self.genre.currentData()
        shown = [p for p in stations if want is None or p.get("ptyName") == want]
        if self.sort.currentData() == "name":
            # Named ones first, alphabetically; one without RDS by its frequency after them.
            shown.sort(key=lambda p: (not ps_text(p.get("ps")), ps_text(p.get("ps")).casefold(), p["best"]["hz"]))
        else:
            shown.sort(key=lambda p: p["best"]["hz"])
        for p in shown:
            best = p["best"]
            name = ps_text(p.get("ps")) or self.tr("(no RDS)")
            also = ", ".join(mhz(a["hz"]) for a in p.get("alts") or [])
            it = QTreeWidgetItem([name, mhz(best["hz"]), p.get("ptyName") or "", also])
            tip = [self.tr("{level} dBFS").format(level=f"{best['level']:.0f}")]
            if best.get("stereo"):
                tip.append(self.tr("stereo"))
            if p.get("pi"):
                tip.append(self.tr("PI {pi}").format(pi=p["pi"]))
            if p.get("rt"):
                tip.append(p["rt"])
            it.setToolTip(0, " · ".join(tip))
            it.setData(0, Qt.ItemDataRole.UserRole, {"band": FM, "hz": best["hz"]})
            self.tree.addTopLevelItem(it)
        for c in range(4):
            self.tree.resizeColumnToContents(c)

    def _fill_dab(self, ensembles: list[dict]) -> None:
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels([self.tr("Station"), self.tr("Ensemble"), self.tr("Block"), self.tr("Kind"),
                                   self.tr("Type")])
        pics = self.pictures
        rows = [(s, e) for e in ensembles for s in e.get("services") or []]
        rows.sort(key=lambda r: ((r[0].get("label") or "").casefold(), r[1]["freqHz"]))
        for s, e in rows:
            kind = {"dab": "DAB", "dab+": "DAB+"}.get(s.get("kind"), s.get("kind") or "")
            if s.get("bitrate"):
                kind += " " + self.tr("{kbps} kbit/s").format(kbps=s["bitrate"])
            it = QTreeWidgetItem([(s.get("label") or "").strip(), (e.get("label") or "").strip(),
                                  f"{e['block']}  {mhz(e['freqHz'], 3)}", kind, s.get("ptyName") or ""])
            it.setData(0, Qt.ItemDataRole.UserRole, {"band": DAB, "block": e["block"], "freqHz": e["freqHz"],
                                                     "sid": s.get("sid")})
            if pics is not None and pics.has_logo(s.get("sid")):
                pm = pixmap(pics.logo(s["sid"], "square")[0])
                if pm is not None:
                    it.setIcon(0, QIcon(pm))
            self.tree.addTopLevelItem(it)
        for c in range(5):
            self.tree.resizeColumnToContents(c)

    # ------------------------------------------------------------ actions
    def _activated(self, item, _col: int = 0) -> None:
        d = item.data(0, Qt.ItemDataRole.UserRole) or {}
        if d.get("band") == FM:
            self.tune_fm(float(d["hz"]))
        elif d.get("band") == DAB:
            self.play_dab(d["block"], float(d["freqHz"]), d["sid"])

    def _dab_session(self) -> dict | None:
        decs = getattr(self.radio, "decoders", None)
        if decs is None:
            return None
        return next((s for s in decs.sessions() if s.get("holdsReceiver")), None)

    def tune_fm(self, hz: float) -> bool:
        """Wide FM on `hz`; a DAB station playing is stopped first (it holds
        the receiver, and a click on an FM station means listen to that)."""
        held = self._dab_session()
        if held is not None:
            self.radio.decoders.stop(held["id"])
        return self.bridge.set(mode="wfm", vfo=float(hz))

    def play_dab(self, block: str, freq: float, sid: str) -> None:
        """The DAB session for service `sid`: the playing one switched if it
        is on that block, else stopped and one started there."""
        decs = self.radio.decoders
        held = self._dab_session()
        try:
            if held is not None and held.get("block") == block:
                decs.configure(held["id"], {"service": sid})
                return
            if held is not None:
                decs.stop(held["id"])
            try:
                decs.start("dab", freq, {"block": block, "service": sid})
            except Refused as e:
                # Background decoders pin the span: DAB would take it to
                # Band III, so the operator says whether to stop them.
                if e.code != "span_pinned":
                    raise
                if self.bridge.ask_stop(e.sessions or [], None, str(e)):
                    decs.start("dab", freq, {"block": block, "service": sid}, drop_sessions=True)
        except ValueError as e:
            self.say(str(e))

    def scan_now(self) -> None:
        sc = self.scanner
        if sc is None:
            return
        try:
            sc.scan_now(self.band.currentData())
        except ValueError as e:
            self.say(str(e))
            return
        self.refresh()
