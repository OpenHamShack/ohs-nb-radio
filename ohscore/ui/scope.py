"""The panadapter + waterfall: one widget, used for the whole transponder
("wide") and for the few kHz around the dial ("zoom").

Layout, top to bottom: the bandplan strip (wide only), the spectrum, a thin
frequency axis, the waterfall. Everything except the waterfall history is
painted fresh each frame from a handful of numbers, which is cheap; the
history is a scopecore.Waterfall ring buffer, which is never re-rendered.

Frequencies are dial Hz throughout, as the engine reports them (on NB, true
downlink Hz with rxCorr already taken out, so beacons stand still while the
LNB drifts); each line is placed by its own start frequency
(docs/ENGINE-API.md "Spectrum items"). What the strip, the markers and the
axis say about the band is the app's: `bridge.face` (ohscore/ui/face.py).

Mouse, on either scope:
  click            tune there (the window decides the snap per mode)
  drag the passband  tune by dragging
  drag elsewhere   pan (wide: the view; zoom: zoomPan)
  wheel            step the dial; ctrl+wheel zooms
  right-click      the app's menu for that frequency, if it has one (NB:
                   "Lock to this as the ... beacon"); right-drag pans
  zoom only: drag a passband edge to set the filter; in FT8/FT4 a click
  inside the audio window sets the RX offset, shift+click the TX offset.
"""
from __future__ import annotations

import math
import time

import numpy as np
from PyQt6.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt6.QtGui import (QBrush, QColor, QFontMetricsF, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                         QPixmap, QPolygonF)
from PyQt6.QtWidgets import QApplication, QToolTip, QWidget

from ..dsp.demod import passband as demod_passband
from ..modegroups import is_slot, js8_slot, slot_spec
from . import layoutrules, palettes, scopelook, theme
from ..i18n import fmt
from .scopecore import HANN_ENBW, FreqMap, PeakMarkers, Waterfall, hang_decay, rbw_line, resample

# The trace's time constant before smoothing was adjustable: 0.32 of the
# way to each new line, at 20 lines/s. The peak ghost (and the default)
# keep it, whatever the operator chooses for the drawn trace.
GHOST_TAU = 0.13

# Peak markers are re-picked this often (seconds of line time), not every
# line: often enough to follow a station that starts or stops, slow enough
# that labels stay put and their text can be read.
MARK_EVERY = 0.5

MARK_BG = QColor(6, 9, 14, 200)

# How the trace and waterfall are drawn (each scope's "Style" pref, the
# adjust panel's Scope tab). Display only: every reading - vs beacon, the
# level guard, beacon lock, the receive SNR - comes from the engine's own
# spectra and IQ, which neither style touches.
#
# "nb" is NB's own look: fine bins (the zoom's are ~12 Hz, RBW 18 Hz) and a
# column takes the highest bin under it (scopecore.resample), so a carrier
# or an FT8 tone stands at its full level and a wide signal reads its power
# per narrow bin - the 400-baud PSK middle beacon ~15 dB under a carrier of
# the same power.
#
# "sdrconsole" approximates SDR Console V3's spectrum, which operators
# compare their downlink with the beacon on (Ray, 12/10/2026: the beacons
# stood relatively higher there than in NB). What SDR-Radio.com documents:
# the default averaging is "Hang & Decay" with the "1 euro filter"
# smoothing (sdr-radio.com/SpectrumAndWaterfall), and FFT bins are
# averaged to one value per display pixel (Simon Brown, forum.sdr-radio.com
# viewtopic.php?p=5894 and p=8062), so its resolution bandwidth is never
# finer than a pixel. Neither its FFT size nor the hang and decay times are
# published. Estimated here: a typical NB view in it is 100-150 kHz across
# 1000-1500 px, so about 100 Hz a pixel, hence SDRC_RBW_HZ; the hang is a
# fifth of a second and the decay 15 dB/s, about what its trace looks like;
# the operator's Smoothing stands in for the 1 euro filter, an adaptive
# low-pass whose steady state is that same exponential average. Its window
# (Hamming suggested for general use) is not copied: after a 100 Hz RBW the
# difference from Hann is under half a dB, and the window belongs to the
# engine's spectra, which the measurements share.
DISPLAY_STYLES = ("nb", "sdrconsole")
SDRC_RBW_HZ = 100.0
SDRC_HOLD_S = 0.2
SDRC_DECAY_DB_S = 15.0
RBW_GAP = 12.0          # px between the axis's unit caption and the RBW after it

NICE_STEPS = [10, 20, 50, 100, 200, 500, 1_000, 2_000, 5_000, 10_000, 20_000, 25_000, 50_000, 100_000]

def labels_shown(prefs) -> bool:
    """Whether the scopes draw what names a signal: decode labels, the band
    marks and alert captions (Adjust › "Show signal labels", L). One
    setting for every scope rather than one per scope, because the reason
    to hide them - a crowded FT8 waterfall that is read as a picture - is
    the same on the wide, the zoom and the second display. The passband,
    cursors, frequency scale, beacon captions and the streaming CW/PSK/RTTY
    tag are not labels in this sense and stay."""
    return bool(prefs.get("scopeLabels", True))


def set_labels_shown(prefs, on: bool) -> None:
    """Set it, save it, and repaint every scope now - the second display's
    included, which is in another top-level window."""
    prefs["scopeLabels"] = bool(on)
    prefs.save()
    for top in QApplication.topLevelWidgets():
        for sc in ([top] if isinstance(top, ScopeView) else []) + top.findChildren(ScopeView):
            sc.update()


def fmt_dl(f: float) -> str:
    """10489.541 250 - the readout's grouping, for hover labels."""
    mhz = int(f // 1_000_000)
    rest = int(round(f - mhz * 1_000_000))
    if rest >= 1_000_000:
        mhz, rest = mhz + 1, rest - 1_000_000
    return f"{mhz}.{rest // 1000:03d} {rest % 1000:03d}"


def _poly(n: int) -> tuple[QPolygonF, np.ndarray]:
    """A QPolygonF of n points and a numpy (n, 2) view writing straight into it,
    so a 2000-point trace costs one array assignment rather than 2000 QPointFs."""
    poly = QPolygonF([QPointF(0, 0)] * n)
    ptr = poly.data()
    ptr.setsize(n * 16)
    return poly, np.frombuffer(ptr, np.float64).reshape(n, 2)


class ScopeView(QWidget):
    clicked = pyqtSignal(float, object)      # dial Hz, Qt.KeyboardModifier
    wheel_step = pyqtSignal(int)             # +1 / -1 steps
    offset_clicked = pyqtSignal(float, bool)  # zoom, slot modes: audio offset Hz, is_tx
    palette_changed = pyqtSignal(str)
    colours_requested = pyqtSignal()          # the adjust panel's "Colours..." (Settings › Display)
    context_requested = pyqtSignal(float, object)  # right-click: dial Hz, global QPoint
    mark_clicked = pyqtSignal(dict)           # wide: a click on one of the band marks (set_band_marks)
    alert_clicked = pyqtSignal(dict)          # wide: a click on an alert's caption (set_alerts)

    def __init__(self, bridge, prefs, kind: str = "wide", parent=None, big: bool = False):
        super().__init__(parent)
        self.bridge, self.prefs, self.kind, self.big = bridge, prefs, kind, big
        self.face = bridge.face
        self.wide = kind == "wide"
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        self.setMinimumHeight(160)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.view_lo, self.view_hi = (self.face.wide_lo, self.face.wide_hi) if self.wide else (0.0, 1.0)
        self.fmap = FreqMap(self.view_lo, self.view_hi, 100)
        self.wf = Waterfall(100, 100)
        self.set_palette(prefs["palette"])
        self.look = scopelook.look(prefs)  # colours and widths, Settings › Display (scopelook.py)
        self.avg: np.ndarray | None = None          # the drawn trace, averaged as the operator chose
        self.ref: np.ndarray | None = None          # the ghost's own average, when that differs (else None)
        self.peak: np.ndarray | None = None
        self.peak_t: np.ndarray | None = None      # line time each column's peak was last raised
        self.held: np.ndarray | None = None        # "sdrconsole" style: the hang-and-decay trace
        self.held_t: np.ndarray | None = None
        self.rbw_hz: float | None = None           # the drawn resolution bandwidth (the RBW caption)
        self._peak_on = True
        self._prev_t: float | None = None          # the previous line's time, for per-second rates
        self.floor = None
        self.spread = 2.0                  # noise roughness, dB (see _levels)
        self.range = 50.0
        self.db_lo, self.db_hi = -130.0, -40.0        # the drawn scale: automatic or the operator's
        self._auto_lo, self._auto_hi = -130.0, -40.0  # what automatic would draw
        self.poly_n = 0
        self.last_line_t = time.time()
        self.rps = 20.0                    # waterfall rows per second (measured)
        self._acc = 0.0
        self._sum: np.ndarray | None = None
        self._sum_n = 0
        self.labels: list[dict] = []       # FT8-style decodes: {f, text, t, kind}
        self.peak_marks = PeakMarkers()    # labelled strongest signals (adjust panel, Peaks)
        self._marks_t = -math.inf
        self.tags: dict[int, dict] = {}    # streaming text decodes: {f, text, t}
        self.band_marks: list[dict] = []   # wide: the app's signal marks (set_band_marks)
        self.alerts: list[dict] = []       # wide: the app's alerts (set_alerts)
        self.hover: QPointF | None = None
        self.press = None
        self.audio_offsets: dict[str, float] = {}    # zoom: {"rx": Hz, "tx": Hz} for slot modes
        self.own_seen_t = 0.0
        self.cost_ingest = 0.0             # ms per line batch (EMA)
        self.cost_paint = 0.0              # ms per paint (EMA)
        self.levels_override: tuple[float, float] | None = None
        self._layout()
        self._feed = getattr(bridge, "zoom" if not self.wide else "wide")
        self._feed.connect(self.on_lines)
        bridge.changed.connect(self._on_state)

    def detach(self):
        """Stop listening to the bridge. A scope that goes away before the
        bridge does (the second display's) must call this: a connection to
        a bound method keeps the scope - and the window around it - alive
        and repainting every spectrum line after it was closed, one hidden
        window more for each time the second display was opened."""
        for sig, slot in ((self._feed, self.on_lines), (self.bridge.changed, self._on_state)):
            try:
                sig.disconnect(slot)
            except (TypeError, RuntimeError):
                pass                       # already gone

    # ----------------------------------------------------------- configuration
    def set_palette(self, name: str):
        self.wf.set_lut(palettes.lut(name))
        self.update()

    def speed(self) -> float:
        """Waterfall rows per spectrum line. FT8/FT4 run at a third: a 15 s
        slot should be a readable block with its decode labels on it, not a
        streak that scrolls off before jt9 has finished."""
        k = float(self.prefs.get("wfSpeed", 1.0))
        if is_slot(self._st("mode")):
            k /= 3.0
        return k

    def _st(self, k, d=None):
        return self.bridge.st.get(k, d)

    def slot(self, mode: str):
        """`mode`'s slot spec, JS8's at the speed it sends at (ui.json
        js8Speed, which the JS8 panel keeps): its TX mark is that speed's
        eight tones wide, 25 Hz at Slow to 250 Hz at Ultra, where using the
        mode's own spec drew Normal's 50 Hz at every speed (WP3's note)."""
        if mode == "js8":
            return js8_slot(str(self.prefs.get("js8Speed", "normal")))
        return slot_spec(mode)

    def _target_view(self) -> tuple[float, float]:
        if self.wide:
            return self.view_lo, self.view_hi
        span = float(self._st("zoomSpanHz", 12000.0))
        c = float(self._st("rxDial", 0.0) or self._st("vfo")) + float(self._st("zoomPan", 0.0))
        return c - span / 2, c + span / 2

    def _on_state(self, ch: dict):
        if not self.wide and any(k in ch for k in ("rxDial", "vfo", "zoomSpanHz", "zoomPan")):
            self._apply_view()
        if "ownDl" in ch or any(k in ch for k in self.face.on_air_keys):
            if self.face.on_air(self.bridge.st):
                self.own_seen_t = time.time()
        self.update()

    def _apply_view(self):
        lo, hi = self._target_view()
        if (lo, hi) != (self.fmap.lo, self.fmap.hi):
            old_lo, old_hi = self.fmap.lo, self.fmap.hi
            if old_hi > old_lo + 1:
                self.wf.remap(old_lo, old_hi, lo, hi, self.quiet_colour())
                self._remap_trace(old_lo, old_hi, lo, hi)
            self.fmap.set(lo, hi, self.r_spec.width(), self.r_spec.x())
            self.update()

    def quiet_colour(self) -> int | None:
        """The colour the waterfall draws the middle of the noise in, at the
        levels it is drawing with now; None before there is a noise floor.

        For the columns a retune leaves with no history. They used to take
        the palette's floor colour, which every palette makes near black,
        while the automatic levels draw noise as a dim texture well above
        it: a retune further than the zoom's span (any change of mode
        between the screenshots' sub-bands) left a black block under the
        new rows until it scrolled away - six seconds at 1x, eighteen in
        FT8. The history is still shifted, never invented; what has none is
        shown as quiet band, flat so it does not pass for a recording."""
        if self.floor is None:
            return None
        fl, rg = self._wf_levels()
        mid = self.floor + self.spread              # the noise's median: the floor tracks its lower quartile
        idx = int(np.clip((mid - fl) * (255.0 / max(1.0, rg)), 0, 255))
        return int(self.wf.lut[idx])

    def _remap_trace(self, old_lo, old_hi, lo, hi):
        for name in ("avg", "ref", "peak"):
            a = getattr(self, name)
            if a is None:
                continue
            n = len(a)
            fc = lo + (np.arange(n) + 0.5) * (hi - lo) / n
            src = np.floor((fc - old_lo) / (old_hi - old_lo) * n).astype(np.int64)
            ok = (src >= 0) & (src < n)
            b = np.full(n, self.floor if self.floor is not None else -150.0, np.float32)
            b[ok] = a[src[ok]]
            setattr(self, name, b)
        self.held = None                   # restarts from the next line

    # ----------------------------------------------------------- geometry
    def _layout(self):
        w, h = self.width(), self.height()
        strip = (22 if not self.big else 26) if self.wide else 0
        axis = 20
        frac = 0.40 if self.wide else 0.46
        if self.big:
            frac = 0.30
        spec_h = max(50, int((h - strip - axis) * frac))
        # A short scope (the window's Tight tier gives the wide one 120 px)
        # keeps 40 px of waterfall: the spectrum gives way first, down to
        # 24 px, as the waterfall is what shows who has been on (overhaul
        # section 3). At 120 px it was 28 px of waterfall under 50 of trace.
        spec_h = max(24, min(spec_h, h - strip - axis - 40))
        self.r_strip = QRectF(0, 0, w, strip)
        self.r_spec = QRectF(0, strip, w, spec_h)
        self.r_axis = QRectF(0, strip + spec_h, w, axis)
        self.r_wf = QRectF(0, strip + spec_h + axis, w, max(1, h - strip - spec_h - axis))
        dpr = self.devicePixelRatioF()
        self.wf.resize(max(1, int(w * dpr)), max(1, int(self.r_wf.height() * dpr)))
        lo, hi = self._target_view() if not self.wide else (self.view_lo, self.view_hi)
        if self.wide or hi > lo + 1:
            self.fmap.set(lo, hi, w, 0)
        n = max(2, int(w))
        if self.avg is not None and len(self.avg) != n:
            x_old = np.linspace(0, 1, len(self.avg))
            x_new = np.linspace(0, 1, n)
            self.avg = np.interp(x_new, x_old, self.avg).astype(np.float32)
            self.peak = np.interp(x_new, x_old, self.peak).astype(np.float32)
            self.peak_t = np.full(n, self.last_line_t)
            self.ref = None
        if n != self.poly_n:
            self.poly_n = n
            self.trace_poly, self.trace_xy = _poly(n)
            self.peak_poly, self.peak_xy = _poly(n)

    def resizeEvent(self, e):
        self._layout()
        super().resizeEvent(e)

    # ----------------------------------------------------------- data
    def on_lines(self, lines: list):
        t0 = time.perf_counter()
        if not self.wide:
            self._apply_view()
        lo, hi = self.fmap.lo, self.fmap.hi
        if hi <= lo + 1:
            return
        n_wf = self.wf.w
        n_tr = self.poly_n
        speed = self.speed()
        peak_on, hold, fall = self.peak_settings()
        tau = self.smoothing()
        sdrc = self.display_style() == "sdrconsole"
        if not sdrc:
            self.held = None
        # The widest column either array has: an RBW finer than a column
        # would be pooled away again by resample's maximum.
        col_hz = (hi - lo) / max(1, min(n_wf, n_tr))
        for (t, start, bin_hz, db) in lines:
            # Rates are per second, not per line: the line rate is the
            # engine's scopeFps, and the waterfall speed does not change it.
            # Never zero: two lines stamped alike must still both count.
            dt = 0.05 if self._prev_t is None else min(0.5, max(0.005, t - self._prev_t))
            self._prev_t = t
            # The style's frequency resolution, for the trace and the
            # waterfall alike so the two show the same signals the same
            # size. A new array: `db` is the engine's line, which the
            # window's SNR reading is handed too.
            if sdrc:
                db, self.rbw_hz = rbw_line(db, bin_hz, max(SDRC_RBW_HZ, col_hz))
            else:
                self.rbw_hz = HANN_ENBW * bin_hz
            fill = float(np.min(db)) if len(db) else -150.0
            cols = resample(start, bin_hz, db, lo, hi, n_wf, fill)
            tr = cols if n_wf == n_tr else resample(start, bin_hz, db, lo, hi, n_tr, fill)
            self._levels(cols)
            if sdrc:
                # Hang and decay before the operator's smoothing, as SDR
                # Console smooths after its averaging. The trace only: the
                # waterfall, like SDR Console's, shows each line's levels.
                if self.held is None or len(self.held) != n_tr:
                    self.held, self.held_t = tr.copy(), np.full(n_tr, t)
                else:
                    hang_decay(tr, self.held, self.held_t, t, dt, SDRC_HOLD_S, SDRC_DECAY_DB_S)
                tr = self.held
            if self.avg is None or len(self.avg) != n_tr:
                self.avg = tr.copy()
                self.ref = None
                self.peak = tr.copy()
                self.peak_t = np.full(n_tr, t)
            else:
                self.avg += (tr - self.avg) * self._alpha(tau, dt)
                # The ghost keeps today's averaging whatever the trace's: a
                # raw trace would make it a ceiling of noise spikes, a heavy
                # one would shave the peaks it exists to hold. A second
                # array only while the two differ.
                if abs(tau - GHOST_TAU) < 1e-6:
                    self.ref = None
                elif self.ref is None or len(self.ref) != n_tr:
                    self.ref = self.avg.copy()
                else:
                    self.ref += (tr - self.ref) * self._alpha(GHOST_TAU, dt)
                if peak_on:
                    ref = self.ghost_ref()
                    if not self._peak_on:          # back on: start from now, not a stale ghost
                        self.peak[:] = ref
                        self.peak_t[:] = t
                    self._update_peak(ref, t, dt, hold, fall)
            self._peak_on = peak_on
            # The first lines after a start come before the levels settle;
            # writing them would leave a bright band at the foot of the history.
            if self.n_lines <= 3:
                continue
            # Waterfall speed: accumulate lines, push rows at `speed` rows per
            # line. Lines merge by *mean* in time (a slow waterfall should be a
            # calmer one), unlike columns, which merge by maximum (resample).
            if self._sum is None or len(self._sum) != n_wf:
                self._sum = np.zeros(n_wf, np.float32)
                self._sum_n = 0
            if self._sum_n:
                self._sum += cols
            else:
                self._sum[:] = cols
            self._sum_n += 1
            self._acc += speed
            fl, rg = self._wf_levels()
            if self._acc >= 1.0:
                row = self._sum / self._sum_n
                while self._acc >= 1.0:
                    self.wf.push_db(row, fl, rg)
                    self._acc -= 1.0
                self._sum_n = 0
            if t > self.last_line_t:
                dt = t - self.last_line_t
                if 0.005 < dt < 1.0:
                    self.rps += (speed / dt - self.rps) * 0.05
                self.last_line_t = t
        self._update_marks()
        self.update()
        ms = (time.perf_counter() - t0) * 1000.0 / max(1, len(lines))
        self.cost_ingest += (ms - self.cost_ingest) * 0.1

    def smoothing(self) -> float:
        """The drawn trace's averaging as a time constant in seconds (0:
        raw, each line as it comes). Seconds rather than a per-line factor
        so it means the same at any line rate."""
        return max(0.0, float(self.prefs.get(self.spec_key() + "Smooth", GHOST_TAU)))

    def display_style(self) -> str:
        """This scope's display style (DISPLAY_STYLES); anything else in
        ui.json - a hand edit, a style a later version adds - is "nb"."""
        s = self.prefs.get(self.spec_key() + "Style", "nb")
        return s if s in DISPLAY_STYLES else "nb"

    def rbw_text(self) -> str:
        """"RBW 18 Hz": the resolution bandwidth the trace is drawn at, so
        two scopes - or NB and another program - are compared knowing it.
        Empty before the first line."""
        if not self.rbw_hz:
            return ""
        hz = int(round(self.rbw_hz))
        val = fmt.frequency(hz, "Hz") if hz < 1000 else fmt.frequency(hz, "kHz", 1)
        return self.tr("RBW {rbw}").format(rbw=val)

    def rbw_box(self) -> QRectF | None:
        """Where the RBW caption sits: in the frequency axis, after the unit
        caption ("kHz +10489   RBW 18 Hz"), the one place on a scope that
        nothing else is drawn over. Its first place, the spectrum's
        bottom-left corner, sat on the wide scope's band marks ("Lower
        beacon", "CW") on the simulator's first screenshot."""
        text = self.rbw_text()
        if not text:
            return None
        fm = QFontMetricsF(self._axis_caption_font())
        x = 6 + fm.horizontalAdvance(self.face.axis_unit) + RBW_GAP
        return QRectF(x, self.r_axis.y(), math.ceil(fm.horizontalAdvance(text)) + 2, self.r_axis.height())

    @staticmethod
    def _alpha(tau: float, dt: float) -> float:
        return 1.0 if tau <= 0 else 1.0 - math.exp(-dt / tau)

    def ghost_ref(self) -> np.ndarray:
        """What the peak ghost follows: the trace at the default averaging."""
        return self.ref if self.ref is not None else self.avg

    def peak_settings(self) -> tuple[bool, float, float]:
        """(on, hold seconds, fall dB/s) for the peak ghost from this
        scope's prefs; a hold below zero holds until cleared."""
        k = self.spec_key()
        return (bool(self.prefs.get(k + "Peak", True)), float(self.prefs.get(k + "PeakHold", 1.5)),
                max(0.1, float(self.prefs.get(k + "PeakFall", 10.0))))

    def _update_peak(self, ref: np.ndarray, t: float, dt: float, hold: float, fall: float):
        """The peak ghost: each column rises at once to anything higher,
        holds for `hold` seconds after it last rose, then sinks at `fall`
        dB/s, never below the trace. Before 05/10 this counted lines - hold
        30, fall 0.5 dB a line - which is the 1.5 s and 10 dB/s of the
        defaults at the usual 20 lines/s, but meant something else at any
        other scopeFps. Three whole-array numpy passes; no per-column work."""
        up = ref >= self.peak
        np.copyto(self.peak, ref, where=up)
        self.peak_t[up] = t
        if hold < 0:
            return                                  # until cleared: it only ever rises
        sink = (t - self.peak_t) >= hold
        np.copyto(self.peak, np.maximum(ref, self.peak - fall * dt), where=sink)

    def mark_settings(self) -> tuple[bool, float, int]:
        """(on, dB above the noise floor, most markers) from this scope's prefs."""
        k = self.spec_key()
        return (bool(self.prefs.get(k + "Marks", False)), float(self.prefs.get(k + "MarkAbove", 10.0)),
                max(1, min(10, int(self.prefs.get(k + "MarkMax", 5)))))

    def _update_marks(self, now: bool = False):
        on, above, most = self.mark_settings()
        if not on or self.avg is None or self.floor is None or len(self.avg) < 3:
            self.peak_marks.clear()
            return
        t = self._prev_t if self._prev_t is not None else 0.0
        if not now and t - self._marks_t < MARK_EVERY:
            return
        self._marks_t = t
        n = len(self.avg)
        fm = self.fmap
        col_hz = fm.lo + (np.arange(n) + 0.5) * (fm.span / n)
        # On the trace as drawn, so a label sits on the peak it names; a
        # marker follows its signal within 24 columns between re-picks.
        self.peak_marks.update(self.avg, col_hz, self.floor, above, most, 24 * fm.span / n)

    def refresh_marks(self):
        """A marker setting changed: re-pick now rather than at the next turn."""
        self._update_marks(now=True)
        self.update()

    def clear_peaks(self):
        """The Clear button: the ghost restarts from the trace as it is now."""
        if self.avg is not None and self.peak is not None and len(self.peak) == len(self.avg):
            self.peak[:] = self.ghost_ref()
            self.peak_t[:] = self.last_line_t if self._prev_t is None else self._prev_t
            self.update()

    def _levels(self, cols: np.ndarray):
        lo_est, mid, hi_est = (float(v) for v in np.percentile(cols, (25, 50, 99.7)))
        # How rough the noise is: median minus lower quartile, which on
        # noise alone is 0.67 of its standard deviation in dB and depends on
        # how many FFTs a line averages. Clamped, because on a busy band the
        # median sits on signals rather than noise.
        spread = max(0.5, min(4.0, mid - lo_est))
        self.n_lines = getattr(self, "n_lines", 0) + 1
        if self.floor is None:
            self.floor = lo_est
            self.spread = spread
            self.range = max(30.0, min(70.0, hi_est - lo_est + 6))
            self._dbl, self._dbh = self.floor - 12, self.floor + self.range + 14
        else:
            # Fast while the first few seconds settle, then slow and steady.
            k = max(0.03, 1.0 / self.n_lines)
            self.floor += (lo_est - self.floor) * k
            self.spread += (spread - self.spread) * k
            self.range += (max(30.0, min(70.0, hi_est - self.floor + 6)) - self.range) * 0.01
            want_lo, want_hi = self.floor - 12, self.floor + max(self.range, 40) + 14
            # The scale settles as the floor does, fast for the first lines;
            # at a steady 0.02 from the start, one odd first line (a start-up
            # transient, or before 05/10 the engine's line of zeros) left the
            # trace off the top of the scope for the first ten seconds.
            k = max(0.02, 1.0 / self.n_lines)
            self._dbl += (want_lo - self._dbl) * k
            self._dbh += (want_hi - self._dbh) * k
        # The drawn scale moves in whole dB, so the cached grid layer (see
        # _static) stays valid for seconds at a time instead of one frame.
        self._auto_lo, self._auto_hi = float(round(self._dbl)), float(round(self._dbh))
        self._apply_scale()

    def spec_key(self) -> str:
        """The prefs prefix of this scope's trace settings ("specAuto", ...);
        "spec" for the wide scope (and the second display's, which is a wide
        one), "zoomSpec" for the zoom - as the waterfall's are "wf" and
        "zoomWf"."""
        return "spec" if self.wide else "zoomSpec"

    def auto_scale(self) -> tuple[float, float]:
        """(top, range) dB that the automatic scale has reached."""
        return self._auto_hi, self._auto_hi - self._auto_lo

    def _apply_scale(self):
        """The trace's scale from prefs: automatic (following the noise
        floor, _levels) or the operator's Top and Range. Called per line and
        per paint, so a change in the adjust panel shows at once - the grid
        and its labels follow through _static's cache key."""
        k = self.spec_key()
        if self.prefs.get(k + "Auto", True):
            self.db_lo, self.db_hi = self._auto_lo, self._auto_hi
        else:
            top = float(self.prefs.get(k + "Top", self._auto_hi))
            rg = max(10.0, float(self.prefs.get(k + "Range", self._auto_hi - self._auto_lo)))
            self.db_lo, self.db_hi = top - rg, top

    def _wf_levels(self) -> tuple[float, float]:
        key = "wf" if self.wide else "zoomWf"
        if self.prefs.get(key + "Auto", True) or self.floor is None:
            return self.auto_levels()
        return float(self.prefs.get(key + "Floor", self.prefs["wfFloor"])), float(
            self.prefs.get(key + "Range", self.prefs["wfRange"]))

    def auto_levels(self) -> tuple[float, float]:
        """The waterfall's automatic floor and contrast range.

        The floor sits half a noise spread below the lower quartile - about
        one standard deviation under the median of the noise - so noise is a
        dim texture with some black in it (about a sixth of a flat spectrum)
        and anything above it, even a few dB, shows. A whole spread below
        lit nearly all of it and made the wide view a field of colour. Until 05/10 it sat 5 dB *above* the lower quartile,
        above roughly 85 % of the noise samples of a flat spectrum (the
        engine averages two FFTs a line, so noise spans only a few dB): on a
        busy wide view the transponder's signals carried the picture, but
        a zoom view of nothing but noise and one weak signal was almost
        entirely the palette's floor colour. Ray saw exactly that on the
        real downlink, with a signal about 3 dB over the noise."""
        if self.floor is None:
            return -125.0, self.range
        return self.floor - 0.5 * self.spread, self.range

    def adopt(self, other: "ScopeView"):
        """Start from another scope's history (the second display opening
        beside the main wide scope): its waterfall, levels and labels, so the
        new window is full at once instead of filling for half a minute."""
        self._layout()
        old = other.wf.ordered()
        if old.size:
            rows = min(self.wf.h, old.shape[0])
            cols = np.minimum((np.arange(self.wf.w) * old.shape[1] / self.wf.w).astype(np.int64),
                              old.shape[1] - 1)
            # Same span (both wide scopes): a column stretch is the whole remap.
            self.wf.buf[:rows] = old[:rows][:, cols]
            self.wf.buf[rows:] = self.wf.blank()
            self.wf.head = 0
            self.wf.rows_total = other.wf.rows_total
        self.view_lo, self.view_hi = other.view_lo, other.view_hi
        self.fmap.set(self.view_lo, self.view_hi, self.width(), 0)
        self.floor, self.range = other.floor, other.range
        self.spread = getattr(other, "spread", 2.0)
        self._auto_lo, self._auto_hi = other._auto_lo, other._auto_hi
        self._apply_scale()
        self._dbl, self._dbh = getattr(other, "_dbl", other.db_lo), getattr(other, "_dbh", other.db_hi)
        self.n_lines = getattr(other, "n_lines", 0)
        self.rps, self.last_line_t = other.rps, other.last_line_t       # rows copied 1:1, not stretched
        self.labels = [dict(x) for x in other.labels]
        self.update()

    # decodes ------------------------------------------------------------------
    def add_label(self, f: float, text: str, t: float, kind: str = "", call: str = ""):
        """A decode's label at `f` (dial Hz), pinned to its slot time `t`.
        `call`, the sender, is what the label shrinks to when the full text
        has no room (decode_layout)."""
        self.labels.append({"f": f, "text": text, "t": t, "kind": kind, "call": call})
        if len(self.labels) > 400:
            del self.labels[:100]
        self.update()

    def add_tag(self, f: float, text: str, t: float):
        key = int(round(f / 60.0))
        tag = self.tags.get(key) or self.tags.get(key - 1) or self.tags.get(key + 1)
        if tag is None:
            tag = self.tags.setdefault(key, {"f": f, "text": "", "t": t})
        # One line, printable characters only: decoders emit CR/LF and the odd
        # control character, and a tag is a ticker, not a terminal.
        clean = "".join(ch if ch.isprintable() else " " for ch in text)
        tag["text"] = " ".join((tag["text"] + clean).split(" "))[-28:]
        tag["t"] = t
        tag["f"] = f
        self.update()

    # ----------------------------------------------------------- mouse
    def _passband_abs(self) -> tuple[float, float, float]:
        s = self.bridge.st
        mode = s.get("mode", "usb")
        dial = float(s.get("rxDial") or s.get("vfo") or 0.0)
        lo, hi = demod_passband(mode, s.get("filterLo", 300.0), s.get("filterHi", 2700.0), s.get("cwPitch", 700.0),
                                s.get("cwWidth", 500.0), s.get("amWidth", 3000.0))
        return dial, dial + lo, dial + hi

    def _edges_active(self) -> bool:
        return not self.wide and self._st("mode") in ("usb", "lsb", "cw", "am")

    def _hit(self, pos: QPointF) -> str:
        x = pos.x()
        dial, plo, phi = self._passband_abs()
        xl, xh = self.fmap.x(plo), self.fmap.x(phi)
        if self._edges_active() and pos.y() > self.r_spec.y():
            if abs(x - xl) <= 6:
                return "edge_lo"
            if abs(x - xh) <= 6:
                return "edge_hi"
        if min(xl, xh) - 2 <= x <= max(xl, xh) + 2 and pos.y() > self.r_spec.y():
            return "band"
        return "free"

    # The Adjust pill (overhaul section 5.5): it was a 28 px button of
    # three slider glyphs that operators did not know was a button. Now the
    # glyph and the word, except in the window's Tight tier, where the
    # scopes are short of width and the glyph alone is kept.
    PILL_GLYPH = 28.0

    def _pill_font(self):
        return theme.font(11.5, theme.QFont.Weight.DemiBold)

    def pill_text(self) -> str:
        """"Adjust", or "" for the glyph alone (Tight tier)."""
        return "" if getattr(self.window(), "tier", None) == layoutrules.TIGHT else self.tr("Adjust")

    def pill_tip(self) -> str:
        return (self.tr("Adjust the wide scope: scale, peaks, waterfall levels and palette") if self.wide else
                self.tr("Adjust the zoom scope: scale, peaks, waterfall levels and palette"))

    def _levels_button(self) -> QRectF:
        text = self.pill_text()
        w = self.PILL_GLYPH + (QFontMetricsF(self._pill_font()).horizontalAdvance(text) + 10 if text else 0)
        return QRectF(self.width() - 8 - w, self.r_wf.y() + 6, w, 24)

    def open_levels(self):
        from .wfpanel import AdjustPopover
        pop = AdjustPopover(self, self)
        pop.palette_changed.connect(self.palette_changed)
        pop.adjustSize()
        b = self._levels_button()
        g = self.mapToGlobal(b.bottomRight().toPoint())
        pop.move(g.x() - pop.width(), g.y() + 6)
        pop.show()

    def mousePressEvent(self, e):
        if e.button() not in (Qt.MouseButton.LeftButton, Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton):
            return
        pos = e.position()
        if e.button() == Qt.MouseButton.LeftButton and self._levels_button().contains(pos):
            self.open_levels()
            return
        what = self._hit(pos) if e.button() == Qt.MouseButton.LeftButton else "free"
        self.press = {"pos": pos, "what": what, "moved": False, "button": e.button(),
                      "vfo": float(self._st("vfo", 0.0)), "pan": float(self._st("zoomPan", 0.0)),
                      "view": (self.view_lo, self.view_hi), "mods": e.modifiers(),
                      "filter": (self._st("filterLo"), self._st("filterHi"), self._st("cwWidth"),
                                 self._st("amWidth"))}
        if what == "band":
            self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        pos = e.position()
        self.hover = pos
        pr = self.press
        if pr is None and self._levels_button().contains(pos):
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.hover = None
            self.setToolTip(self.pill_tip())
            self.update()
            return
        self.setToolTip("")
        if pr is None:
            what = self._hit(pos)
            self.setCursor({"edge_lo": Qt.CursorShape.SizeHorCursor, "edge_hi": Qt.CursorShape.SizeHorCursor,
                            "band": Qt.CursorShape.OpenHandCursor}.get(what, Qt.CursorShape.CrossCursor))
            mark = self._mark_at(pos) or self._alert_at(pos)
            if mark is not None and mark.get("tip"):
                QToolTip.showText(e.globalPosition().toPoint(), mark["tip"], self)
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            elif self.wide and self.r_strip.contains(pos):
                seg = self.face.segment_at(self.fmap.f(pos.x()))
                if seg:
                    tip = (f"<b>{seg['label']}</b><br>{self.face.mhz(seg['lo'], 3)} – "
                           f"{self.face.mhz(seg['hi'], 3)} MHz<br>")
                    tip += ("Transmit: " + ", ".join(m.upper() if m != "digital" else "digital" for m in seg["modes"])
                            + (f", {seg['maxBw']:.0f} Hz max" if seg["maxBw"] and seg["maxBw"] < 2700 else "")
                            if seg["tx"] else "No transmitting here")
                    QToolTip.showText(e.globalPosition().toPoint(), tip, self)
            else:
                QToolTip.hideText()
            self.update()
            return
        dx = pos.x() - pr["pos"].x()
        if abs(dx) > 3 or abs(pos.y() - pr["pos"].y()) > 3:
            pr["moved"] = True
        if not pr["moved"]:
            return
        hzpp = self.fmap.hz_per_px
        what = pr["what"]
        if what == "band":
            nv = round((pr["vfo"] + dx * hzpp) / 10.0) * 10.0
            self.bridge.set(quiet=True, vfo=nv)
        elif what in ("edge_lo", "edge_hi"):
            self._drag_edge(what, pos.x())
        else:
            if self.wide:
                lo, hi = pr["view"]
                span = hi - lo
                shift = -dx * span / max(1.0, self.width())
                nlo = max(self.face.wide_lo - span * 0.5, min(self.face.wide_hi - span * 0.5, lo + shift))
                self._set_wide_view(nlo, nlo + span)
            else:
                spec = self.bridge.spec("zoomPan")
                np_ = max(spec["min"], min(spec["max"], pr["pan"] - dx * hzpp))
                self.bridge.set(quiet=True, zoomPan=round(np_ / 10.0) * 10.0)
        self.update()

    def _drag_edge(self, what: str, x: float):
        s = self.bridge.st
        mode = s.get("mode")
        dial = float(s.get("rxDial") or s.get("vfo"))
        f = self.fmap.f(x) - dial
        f = round(f / 10.0) * 10.0
        if mode == "usb":
            if what == "edge_lo":
                self.bridge.set(quiet=True, filterLo=max(0.0, min(1000.0, f, s["filterHi"] - 100)))
            else:
                self.bridge.set(quiet=True, filterHi=max(1000.0, min(4000.0, f)))
        elif mode == "lsb":
            if what == "edge_hi":
                self.bridge.set(quiet=True, filterLo=max(0.0, min(1000.0, -f, s["filterHi"] - 100)))
            else:
                self.bridge.set(quiet=True, filterHi=max(1000.0, min(4000.0, -f)))
        elif mode == "cw":
            w = abs(f - s["cwPitch"]) * 2
            sp = self.bridge.spec("cwWidth")
            self.bridge.set(quiet=True, cwWidth=max(sp["min"], min(sp["max"], round(w / 10) * 10)))
        elif mode == "am":
            sp = self.bridge.spec("amWidth")
            self.bridge.set(quiet=True, amWidth=max(sp["min"], min(sp["max"], round(abs(f) / 100) * 100)))

    def mouseReleaseEvent(self, e):
        pr, self.press = self.press, None
        self.setCursor(Qt.CursorShape.CrossCursor)
        if pr is not None and not pr["moved"] and pr["button"] == Qt.MouseButton.RightButton:
            self.context_requested.emit(self.fmap.f(e.position().x()), e.globalPosition().toPoint())
            return
        if pr is None or pr["moved"] or pr["button"] != Qt.MouseButton.LeftButton:
            return
        x = e.position().x()
        f = self.fmap.f(x)
        mark = self._mark_at(e.position())
        if mark is not None:
            self.mark_clicked.emit(mark)
            return
        alert = self._alert_at(e.position())
        if alert is not None:
            self.alert_clicked.emit(alert)
            return
        if not self.wide and is_slot(self._st("mode")):
            dial = float(self._st("rxDial") or self._st("vfo"))
            off = f - dial
            if 100.0 <= off <= 3200.0:
                self.offset_clicked.emit(round(off), bool(e.modifiers() & Qt.KeyboardModifier.ShiftModifier))
                return
        self.clicked.emit(f, e.modifiers())

    def leaveEvent(self, e):
        self.hover = None
        self.update()

    def wheelEvent(self, e):
        d = e.angleDelta().y()
        if not d:
            return
        if e.modifiers() & Qt.KeyboardModifier.ControlModifier:
            self.zoom_by(0.8 if d > 0 else 1.25, e.position().x())
        else:
            self.wheel_step.emit(1 if d > 0 else -1)
        e.accept()

    def zoom_by(self, k: float, x: float | None = None):
        if self.wide:
            f0 = self.fmap.f(x if x is not None else self.width() / 2)
            span = max(10_000.0, min(self.face.wide_hi - self.face.wide_lo, (self.view_hi - self.view_lo) * k))
            lo = f0 - (f0 - self.view_lo) * span / (self.view_hi - self.view_lo)
            lo = max(self.face.wide_lo, min(self.face.wide_hi - span, lo))
            self._set_wide_view(lo, lo + span)
        else:
            sp = self.bridge.spec("zoomSpanHz")
            span = max(sp["min"], min(sp["max"], float(self._st("zoomSpanHz")) * k))
            self.bridge.set(quiet=True, zoomSpanHz=round(span / 100) * 100)

    def _set_wide_view(self, lo, hi):
        old = (self.fmap.lo, self.fmap.hi)
        self.view_lo, self.view_hi = lo, hi
        self.wf.remap(old[0], old[1], lo, hi)
        self._remap_trace(old[0], old[1], lo, hi)
        self.fmap.set(lo, hi, self.width(), 0)
        self.update()

    def reset_view(self):
        if self.wide:
            self._set_wide_view(self.face.wide_lo, self.face.wide_hi)
        else:
            self.bridge.set(quiet=True, zoomPan=0.0)

    def mouseDoubleClickEvent(self, e):
        if e.button() == Qt.MouseButton.MiddleButton:
            self.reset_view()

    # ----------------------------------------------------------- painting
    def y_db(self, db):
        r = self.r_spec
        return r.bottom() - (db - self.db_lo) / max(1.0, self.db_hi - self.db_lo) * (r.height() - 6)

    def paintEvent(self, _e):
        t0 = time.perf_counter()
        self._apply_scale()
        self.look = scopelook.look(self.prefs)      # cached; rebuilt only when Settings changed it
        p = QPainter(self)
        p.drawPixmap(0, 0, self._static())
        self._paint_bands(p)
        self._paint_trace(p)
        self._paint_marks(p)
        self.wf.draw(p, self.r_wf)
        self._paint_overlays(p)
        self._paint_decodes(p)
        self._paint_hover(p)
        self._paint_levels_button(p)
        p.setPen(QPen(theme.c("line"), 1))
        p.drawLine(QPointF(0, self.r_wf.y()), QPointF(self.width(), self.r_wf.y()))
        p.end()
        ms = (time.perf_counter() - t0) * 1000.0
        self.cost_paint += (ms - self.cost_paint) * 0.1

    def _hover_segment(self):
        if self.wide and self.hover is not None and self.r_strip.contains(self.hover):
            f = self.fmap.f(self.hover.x())
            return next((i for i, sg in enumerate(self.face.segments) if sg[0] <= f < sg[1]), None)
        return None

    def _static(self) -> QPixmap:
        """Background, grid, dB labels, frequency axis and bandplan strip: the
        parts that change only when the view, the scale or the hovered
        segment does. Cached as one pixmap and blitted, rather than ~60
        lines and labels redrawn for every spectrum line."""
        dpr = self.devicePixelRatioF()
        look = scopelook.look(self.prefs)
        key = (self.width(), self.height(), dpr, self.fmap.lo, self.fmap.hi, self.db_lo, self.db_hi,
               self._hover_segment(), theme.t()["name"], self.big, look.static_key, self.rbw_text())
        if getattr(self, "_static_key", None) != key:
            pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(look.background)
            q = QPainter(pm)
            self._paint_grid(q)
            self._paint_axis(q)
            if self.wide:
                self._paint_strip(q)
            q.end()
            self._static_pm, self._static_key = pm, key
        return self._static_pm

    def _ticks(self, min_px: float = 90.0):
        span = self.fmap.span
        step = next((s for s in NICE_STEPS if s / span * self.width() >= min_px), NICE_STEPS[-1])
        f = math.ceil(self.fmap.lo / step) * step
        out = []
        while f <= self.fmap.hi:
            out.append(f)
            f += step
        return step, out

    def db_grid(self) -> list[tuple[float, float, bool]]:
        """(dB, y, labelled) for each horizontal grid line of the current
        scale: every 10 dB, or 20 when 10 would crowd."""
        r = self.r_spec
        span = max(1.0, self.db_hi - self.db_lo)
        dstep = 10 if r.height() / (span / 10) >= 18 else 20 if r.height() / (span / 20) >= 18 else 50
        db = math.floor(self.db_hi / dstep) * dstep
        out = []
        while db > self.db_lo:
            y = round(self.y_db(db)) + 0.5
            out.append((float(db), y, r.y() + 12 < y < r.bottom() - 4))
            db -= dstep
        return out

    def _paint_grid(self, p: QPainter):
        r = self.r_spec
        grid = scopelook.look(self.prefs).grid_pen
        p.setPen(grid)
        _, ticks = self._ticks()
        for f in ticks:
            x = round(self.fmap.x(f)) + 0.5
            p.drawLine(QPointF(x, r.y()), QPointF(x, r.bottom()))
        p.setFont(theme.font(10.5, mono=True))
        for db, y, labelled in self.db_grid():
            p.setPen(grid)
            p.drawLine(QPointF(0, y), QPointF(r.right(), y))
            if labelled:
                p.setPen(QColor(255, 255, 255, 70))
                p.drawText(QRectF(r.right() - 46, y - 13, 42, 12), Qt.AlignmentFlag.AlignRight, f"{db:.0f}")

    def _paint_bands(self, p: QPainter):
        """Under the trace: our receive passband, the TX bracket and its landing."""
        s = self.bridge.st
        r = QRectF(self.r_spec.x(), self.r_spec.y(), self.r_spec.width(), self.r_spec.height() + self.r_axis.height())
        dial, plo, phi = self._passband_abs()
        xl, xh = sorted((self.fmap.x(plo), self.fmap.x(phi)))
        if xh - xl < 3:
            xl, xh = (xl + xh) / 2 - 1.5, (xl + xh) / 2 + 1.5
        g = QLinearGradient(0, r.y(), 0, r.bottom())
        g.setColorAt(0, theme.sc("rx", 0.04))
        g.setColorAt(1, theme.sc("rx", 0.20))
        p.fillRect(QRectF(xl, r.y(), xh - xl, r.height()), QBrush(g))

    def _fill_image(self, ys: np.ndarray) -> QImage:
        """The gradient under the trace, built in numpy: a per-row colour column
        masked by "below the trace". QPainter's antialiased polygon fill of a
        2000-point noisy trace cost 12-15 ms a frame on a desktop CPU; this
        costs well under one."""
        w, h = self.poly_n, max(1, int(self.r_spec.height()))
        look = self.look
        if getattr(self, "_fill_wh", None) != (w, h, look.fill_key):
            self._fill_wh = (w, h, look.fill_key)
            self._fill_buf = np.zeros((h, w), np.uint32)
            self._fill_img = QImage(self._fill_buf.data, w, h, w * 4, QImage.Format.Format_ARGB32_Premultiplied)
            k = np.linspace(0.0, 1.0, h)
            # The fill colour at the top fading to a darker one (Classic:
            # cyan to deep blue), alpha falling with depth from the chosen
            # opacity (Classic: 0.54); premultiplied, as the image format
            # requires.
            a = np.minimum(1.0, (0.50 * (1 - k) ** 1.4 + 0.04) * (look.fill_opacity / 0.54))
            (r0, g0, b0), (r1, g1, b1) = look.fill_top, look.fill_foot
            r = (r0 * (1 - k) + r1 * k) * a
            g = (g0 * (1 - k) + g1 * k) * a
            b_ = (b0 * (1 - k) + b1 * k) * a
            self._grad = ((np.round(a * 255).astype(np.uint32) << 24) | (np.round(r).astype(np.uint32) << 16) |
                          (np.round(g).astype(np.uint32) << 8) | np.round(b_).astype(np.uint32))
            self._rows = np.arange(h, dtype=np.float64)[:, None]
        top = self.r_spec.y()
        mask = self._rows >= (ys[None, :w] - top)
        np.copyto(self._fill_buf, np.where(mask, self._grad[:, None], np.uint32(0)))
        return self._fill_img

    def _paint_trace(self, p: QPainter):
        if self.avg is None or self.poly_n < 2 or len(self.avg) != self.poly_n:
            p.setFont(theme.font(12))
            p.setPen(QColor(255, 255, 255, 90))
            msg = "Waiting for the radio\u2026" if not self._st("running") else "Waiting for spectrum\u2026"
            if self._st("error"):
                msg = "Receiver stopped"
            p.drawText(self.r_spec, Qt.AlignmentFlag.AlignCenter, msg)
            return
        n = self.poly_n
        xs = np.arange(n, dtype=np.float64) * (self.width() / max(1, n - 1))
        a = self.avg.astype(np.float64)
        # A light [1 2 1]/4 smoothing across columns for the drawn trace only:
        # the waterfall and the peak ghost keep the raw maxima. Smoothing
        # set to raw drops this too - raw means each line as it came.
        if self.smoothing() > 0:
            a[1:-1] = 0.25 * a[:-2] + 0.5 * a[1:-1] + 0.25 * a[2:]
        ys = self.y_db(a)
        ys = np.clip(ys, self.r_spec.y() + 1, self.r_spec.bottom())
        look = self.look
        if look.fill:
            p.drawImage(QRectF(0, self.r_spec.y(), self.width(), self.r_spec.height()), self._fill_image(ys))
        self.trace_xy[:, 0] = xs
        self.trace_xy[:, 1] = ys
        # Pens one device pixel wide take Qt's fast antialiased-line path;
        # anything wider falls back to the general stroker and cost ~50 ms
        # here. So the pens are cosmetic hairlines and a wider trace is the
        # hairline drawn again, a device pixel across and a device pixel down
        # (and up and back, for 3): 0.8 / 1.2 / 2 ms on a 1920 px noisy trace,
        # against 57 ms for one 2 px pen. "Wider" includes a 1 px pen on a
        # scaled screen - scopelook._hairline has what that cost.
        dpr = self.devicePixelRatioF()
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.peak is not None and len(self.peak) == n and self.peak_settings()[0]:
            self.peak_xy[:, 0] = xs
            self.peak_xy[:, 1] = np.clip(self.y_db(self.peak.astype(np.float64)), self.r_spec.y() + 1,
                                         self.r_spec.bottom())
            p.setPen(look.peak_pen)
            p.setBrush(Qt.BrushStyle.NoBrush)
            for dx, dy in scopelook.trace_passes(1, dpr):
                p.translate(dx, dy)
                p.drawPolyline(self.peak_poly)
                p.translate(-dx, -dy)
        p.setPen(look.trace_pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        for dx, dy in scopelook.trace_passes(look.width, dpr):
            p.translate(dx, dy)
            p.drawPolyline(self.trace_poly)
            p.translate(-dx, -dy)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _axis_caption_font(self):
        return theme.font(9.5, theme.QFont.Weight.DemiBold, spacing=0.6)

    def _axis_caption_rect(self) -> QRectF:
        """Where the unit caption ("kHz +10489", "MHz") sits at the axis's
        left end, sized from the text. It was a fixed 64 px, which fitted
        the Linux fonts it was drawn with; on Windows 11 at its default DPI
        Segoe UI is wider and NB's caption came out as "kHz +1048" (Ray's
        first on-air test). The font is pixel-sized, so measuring it here
        is the whole fix wherever it runs."""
        w = QFontMetricsF(self._axis_caption_font()).horizontalAdvance(self.face.axis_unit)
        rbw = self.rbw_box()
        if rbw is not None:                 # the tick labels keep clear of both
            w = rbw.right() - 6
        return QRectF(6, self.r_axis.y(), math.ceil(w) + 2, self.r_axis.height())

    def _axis_labels(self) -> list[tuple[float, QRectF, str]]:
        """(tick x, label box, text) for each tick label that fits: none over
        the caption (with a small gap) and none past the right edge."""
        r = self.r_axis
        step, ticks = self._ticks()
        fm = QFontMetricsF(theme.font(10.5, mono=True))
        clear = self._axis_caption_rect().right() + 6
        out = []
        for f in ticks:
            x = self.fmap.x(f)
            lab = self.face.axis_label(f, step)
            w = fm.horizontalAdvance(lab)
            box = QRectF(x - w / 2 - 2, r.y() + 3, w + 4, r.height() - 3)
            if box.left() < clear or box.right() > self.width():
                continue
            out.append((x, box, lab))
        return out

    def mark_label(self, f: float, db: float) -> str:
        """A peak marker's text: the frequency as the axis writes it (NB:
        kHz above 10489 MHz, HAM: MHz - the face's axis_label), to about a
        column's resolution, and the level in dBFS."""
        hzpp = self.fmap.hz_per_px
        step = 10 if hzpp < 20 else 100 if hzpp < 2000 else 1000
        return f"{self.face.axis_label(f, step)}  {db:.0f}"

    def mark_boxes(self, fm: QFontMetricsF | None = None) -> list[tuple[float, float, QRectF, str]]:
        """(x, y of the peak, label box, text) for each marker that can be
        drawn without covering another or a fixed caption (a beacon's
        name, a mode flag, TX): above its peak if there is room, else
        stepped up a row, else beside it, else below it (a peak over the
        top of the scale); one that fits nowhere is left out rather than
        drawn over another. Placed strongest first, and the markers change
        at most twice a second while the captions move only with a retune
        or a zoom, so the layout is as steady as they are."""
        if fm is None:
            fm = QFontMetricsF(theme.font(10.5, theme.QFont.Weight.DemiBold, mono=True))
        r = self.r_spec
        out = []
        # The captions are obstacles from the start but never in the output:
        # a label that would cover one moves on to its next place.
        placed = [c.adjusted(-2, -1, 2, 1) for c in self.caption_boxes()]
        for f, db in self.peak_marks.marks:
            x = self.fmap.x(f)
            if x < 0 or x > self.width():
                continue
            y = float(min(r.bottom(), max(r.y() + 1, self.y_db(db))))
            text = self.mark_label(f, db)
            w, h = fm.horizontalAdvance(text) + 10, 16.0
            tries = [QRectF(x - w / 2, y - 8 - h - k * (h + 2), w, h) for k in range(3)]
            tries += [QRectF(x + 6, y - h / 2, w, h), QRectF(x - 6 - w, y - h / 2, w, h)]
            # A peak off the top of a manual scale: hang it below instead.
            tries += [QRectF(x - w / 2, y + 4 + k * (h + 2), w, h) for k in range(2)]
            for box in tries:
                if box.left() < 2:
                    box.moveLeft(2)
                if box.right() > self.width() - 50:        # clear of the dB labels
                    box.moveRight(self.width() - 50)
                if box.top() < r.y() + 2 or box.bottom() > r.bottom():
                    continue
                if any(box.intersects(q) for q in placed):
                    continue
                placed.append(box)
                out.append((x, y, box, text))
                break
        return out

    def _paint_marks(self, p: QPainter):
        if not self.peak_marks.marks:
            return
        p.setFont(theme.font(10.5, theme.QFont.Weight.DemiBold, mono=True))
        fm = QFontMetricsF(p.font())
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        col = self.look.marker
        for x, y, box, text in self.mark_boxes(fm):
            tri = QPainterPath()
            tri.moveTo(x - 4, y - 7)
            tri.lineTo(x + 4, y - 7)
            tri.lineTo(x, y - 2)
            tri.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPath(tri)
            p.setBrush(MARK_BG)
            p.setPen(self.look.marker_edge)
            p.drawRoundedRect(box, 3, 3)
            p.setPen(col)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)

    def _paint_axis(self, p: QPainter):
        r = self.r_axis
        p.fillRect(r, QColor(10, 13, 19))
        p.setPen(QPen(QColor(255, 255, 255, 18), 1))
        p.drawLine(QPointF(0, r.y() + 0.5), QPointF(self.width(), r.y() + 0.5))
        _, ticks = self._ticks()
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        for f in ticks:
            x = round(self.fmap.x(f)) + 0.5
            p.drawLine(QPointF(x, r.y()), QPointF(x, r.y() + 4))
        p.setFont(theme.font(10.5, mono=True))
        p.setPen(QColor(200, 210, 225, 170))
        for _x, box, lab in self._axis_labels():
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, lab)
        cap = self._axis_caption_rect()
        p.setFont(self._axis_caption_font())
        p.setPen(QColor(200, 210, 225, 110))
        p.fillRect(QRectF(0, r.y() + 1, cap.right() + 2, r.height() - 1), QColor(10, 13, 19))
        p.drawText(cap, Qt.AlignmentFlag.AlignVCenter, self.face.axis_unit)
        rbw = self.rbw_box()
        if rbw is not None:
            p.setPen(QColor(200, 210, 225, 150))
            p.drawText(rbw, Qt.AlignmentFlag.AlignVCenter, self.rbw_text())

    def _paint_strip(self, p: QPainter):
        r = self.r_strip
        p.fillRect(r, QColor(12, 15, 21))
        f_hover = self.fmap.f(self.hover.x()) if self.hover is not None and r.contains(self.hover) else None
        p.setFont(theme.font(10 if not self.big else 11.5, theme.QFont.Weight.Bold, spacing=0.8))
        fm = QFontMetricsF(p.font())
        for lo, hi, label, classes, _bw in self.face.segments:
            x0, x1 = self.fmap.x(lo), self.fmap.x(hi)
            if x1 < 0 or x0 > self.width():
                continue
            key = theme.segment_colour_key(label, classes)
            col = theme.sc(key)
            hot = f_hover is not None and lo <= f_hover < hi
            box = QRectF(x0 + 0.5, r.y() + 3, max(1.0, x1 - x0 - 1), r.height() - 6)
            fillc = QColor(col)
            fillc.setAlphaF(0.42 if hot else 0.24)
            p.fillRect(box, fillc)
            p.fillRect(QRectF(box.x(), box.bottom() - 2, box.width(), 2), col)
            short = self.face.short_label(label)
            text = label.upper() if fm.horizontalAdvance(label.upper()) + 10 < box.width() else short
            if fm.horizontalAdvance(text) + 6 < box.width():
                c2 = QColor(col).lighter(150)
                p.setPen(c2)
                p.drawText(box.adjusted(0, -1, 0, -1), Qt.AlignmentFlag.AlignCenter, text)

    def _paint_overlays(self, p: QPainter):
        s = self.bridge.st
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        full = QRectF(0, self.r_spec.y(), self.width(), self.height() - self.r_spec.y())
        dial, plo, phi = self._passband_abs()
        xl, xh = sorted((self.fmap.x(plo), self.fmap.x(phi)))
        rx = theme.sc("rx")
        # Receive passband edges continue faintly down the waterfall.
        p.setPen(QPen(theme.sc("rx", 0.55), 1))
        for x in (xl, xh):
            p.drawLine(QPointF(x, self.r_spec.y()), QPointF(x, self.r_spec.bottom()))
        p.setPen(QPen(theme.sc("rx", 0.28), 1, Qt.PenStyle.DashLine))
        for x in (xl, xh):
            p.drawLine(QPointF(x, self.r_wf.y()), QPointF(x, self.r_wf.bottom()))
        # Edge handles on the zoom scope.
        if self._edges_active():
            for x, which in ((xl, "lo"), (xh, "hi")):
                hr = QRectF(x - 3, self.r_spec.y() + self.r_spec.height() * 0.35, 6, 26)
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(rx)
                p.drawRoundedRect(hr, 3, 3)
                p.setBrush(QColor(4, 16, 22))
                for k in (-5, 0, 5):
                    p.drawRect(QRectF(x - 1.5, hr.center().y() + k - 0.5, 3, 1))
        # The dial: a solid accent line with a notch on top.
        xd = self.fmap.x(dial)
        p.setPen(QPen(rx, 1.4))
        p.drawLine(QPointF(xd, self.r_spec.y()), QPointF(xd, self.r_spec.bottom()))
        tri = QPainterPath()
        tri.moveTo(xd - 6, self.r_spec.y())
        tri.lineTo(xd + 6, self.r_spec.y())
        tri.lineTo(xd, self.r_spec.y() + 7)
        tri.closeSubpath()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(rx)
        p.drawPath(tri)
        if self.wide:
            self._paint_span(p)
            self._paint_alerts(p)
            self._paint_beacons(p)
            self._paint_band_marks(p)
        self._paint_mode_marks(p, dial)
        self._paint_tx(p)

    def _beacon_font(self):
        return theme.font(10.5, theme.QFont.Weight.DemiBold)

    def beacon_layout(self, fm: QFontMetricsF | None = None) -> list[tuple[float, float, QRectF | None, str]]:
        """(x, y of the diamond, caption box or None, caption) for each fixed
        marker in view. A caption that would run into its neighbour's is
        left off; the diamond and its line still say where it is."""
        if fm is None:
            fm = QFontMetricsF(self._beacon_font())
        out, placed = [], []
        for _key, f, lab in self.face.markers():
            x = self.fmap.x(f)
            if x < -10 or x > self.width() + 10:
                continue
            y = self.r_spec.y() + 6
            w = fm.horizontalAdvance(lab)
            lx = x + 8 if x + 8 + w < self.width() - 50 else x - 8 - w
            box = QRectF(lx, y - 2, w + 2, 14)
            if any(box.adjusted(-6, 0, 6, 0).intersects(q) for q in placed):
                box = None
            else:
                placed.append(box)
            out.append((x, y, box, lab))
        return out

    # ------------------------------------------------------------ band marks
    # The app's list of signals on the band (NB: the band skimmer), as a
    # layer along the bottom of the wide spectrum: a bar under each signal's
    # occupied band, a tick where its dial is, a short caption where there
    # is room. Along the bottom rather than the top, where the beacon
    # captions and peak markers already are; under the trace's noise, so
    # it hides no signal. A click on a mark is the app's (mark_clicked),
    # not a plain tune: it knows the signal's mode and dial.
    MARK_H = 15.0

    def set_band_marks(self, marks: list[dict]) -> None:
        """Each mark: {"lo", "hi", "text", "colour" (a theme scope key),
        "dial" (Hz or None), "tip" (tooltip text), "active"}, plus whatever
        the app wants back in mark_clicked."""
        self.band_marks = list(marks)
        self.update()

    def band_mark_layout(self, fm: QFontMetricsF | None = None) -> list[tuple[dict, QRectF, QRectF | None]]:
        """(mark, its bar, its caption box or None) for each mark in view."""
        if not self.wide or not self.band_marks or not labels_shown(self.prefs):
            return []
        if fm is None:
            fm = QFontMetricsF(self._mark_font())
        y = self.r_spec.bottom() - self.MARK_H
        out, placed = [], []
        for m in sorted(self.band_marks, key=lambda m: (not m.get("active", True), m["lo"])):
            x0, x1 = self.fmap.x(m["lo"]), self.fmap.x(m["hi"])
            if x1 < -5 or x0 > self.width() + 5:
                continue
            bar = QRectF(x0, y + self.MARK_H - 4, max(2.0, x1 - x0), 3)
            text = m.get("text") or ""
            box = None
            if text:
                w = fm.horizontalAdvance(text) + 6
                cand = QRectF(max(0.0, min(self.width() - w, x0)), y, w, self.MARK_H - 4)
                if not any(cand.intersects(q) for q in placed):
                    box = cand
                    placed.append(cand)
            out.append((m, bar, box))
        return out

    def _mark_font(self):
        return theme.font(9.5, theme.QFont.Weight.DemiBold)

    def _mark_at(self, pos) -> dict | None:
        if not self.wide or not self.band_marks:
            return None
        y = self.r_spec.bottom() - self.MARK_H
        if not (y - 2 <= pos.y() <= self.r_spec.bottom() + 1):
            return None
        best = None
        for m, bar, box in self.band_mark_layout():
            hit = (box is not None and box.adjusted(-2, -2, 2, 2).contains(pos)) or \
                (bar.x() - 3 <= pos.x() <= bar.right() + 3)
            if hit and (best is None or (m["hi"] - m["lo"]) < (best["hi"] - best["lo"])):
                best = m
        return best

    def _paint_band_marks(self, p: QPainter):
        lay = self.band_mark_layout()
        if not lay:
            return
        p.setFont(self._mark_font())
        for m, bar, box in lay:
            col = theme.sc(m.get("colour") or "peak", 0.95 if m.get("active", True) else 0.4)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawRect(bar)
            d = m.get("dial")
            if d is not None:
                xd = self.fmap.x(d)
                p.drawRect(QRectF(xd - 0.75, bar.y() - 4, 1.5, 7))
            if box is not None:
                bg = QColor(MARK_BG)
                bg.setAlphaF(0.75 if m.get("active", True) else 0.45)
                p.setBrush(bg)
                p.drawRoundedRect(box, 2.5, 2.5)
                p.setPen(col)
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, m["text"])

    # ------------------------------------------------------------ alerts
    # Something on the band the operator should look at now (NB: a signal
    # over the beacon, LEILA's siren): a tinted column over its frequencies,
    # down through the spectrum and the waterfall, so it is seen whichever
    # half the eye is on, and a caption under the beacon captions. Drawn
    # under the beacons and band marks; translucent, so the signal it is
    # about stays visible. A click on the caption is the app's
    # (alert_clicked).
    ALERT_Y = 24.0

    def set_alerts(self, alerts: list[dict]) -> None:
        """Each alert: {"lo", "hi" (Hz), "text" (the caption), "colour" (a
        theme scope key), "strong" (False draws it faded: over, but recent),
        "tip"}, plus whatever the app wants back in alert_clicked."""
        self.alerts = list(alerts)
        self.update()

    def alert_layout(self, fm: QFontMetricsF | None = None) -> list[tuple[dict, QRectF, QRectF | None]]:
        """(alert, its column, its caption box or None) for each alert in
        view; strong ones first, so they win a caption's place."""
        if not self.wide or not self.alerts:
            return []
        if fm is None:
            fm = QFontMetricsF(self._mark_font())
        top, bottom = self.r_spec.y(), self.r_wf.bottom()
        out, placed = [], []
        # Hidden labels keep the alert's tinted column - a signal over the
        # beacon, or LEILA, is still something to look at - and lose only
        # its caption.
        captions = labels_shown(self.prefs)
        for a in sorted(self.alerts, key=lambda a: not a.get("strong", True)):
            x0, x1 = sorted((self.fmap.x(a["lo"]), self.fmap.x(a["hi"])))
            if x1 < -5 or x0 > self.width() + 5:
                continue
            if x1 - x0 < 4.0:
                x0, x1 = (x0 + x1) / 2 - 2.0, (x0 + x1) / 2 + 2.0
            col = QRectF(x0, top, x1 - x0, bottom - top)
            box = None
            text = (a.get("text") or "") if captions else ""
            if text:
                w = fm.horizontalAdvance(text) + 8
                cand = QRectF(max(0.0, min(self.width() - w, (x0 + x1) / 2 - w / 2)), top + self.ALERT_Y, w, 15)
                for _ in range(3):
                    if not any(cand.intersects(q) for q in placed):
                        box = cand
                        placed.append(cand)
                        break
                    cand = cand.translated(0, 17)
            out.append((a, col, box))
        return out

    def _alert_at(self, pos) -> dict | None:
        for a, _col, box in self.alert_layout():
            if box is not None and box.adjusted(-2, -2, 2, 2).contains(pos):
                return a
        return None

    # ------------------------------------------------------------ the pinned span
    # While background decoder sessions pin Radio's span (state `span`,
    # SERVER-API "The pinned span"), the wide scope says so: a caption,
    # each session's frequency as a dashed line with its decoder's name,
    # and anything the view shows beyond the span greyed, since the dial
    # cannot go there without stopping them (Bridge.ask_stop asks).
    def span_layout(self) -> tuple[list[tuple[float, str]], tuple[float, float] | None]:
        """([(x, caption)] for each session holding the span, in view;
        (x_lo, x_hi) of the span), or ([], None) while nothing pins it."""
        sp = self.bridge.st.get("span") or {}
        if not self.wide or not sp.get("pinned"):
            return [], None
        marks = []
        for sess in sp.get("sessions") or []:
            x = self.fmap.x(float(sess["freqHz"]))
            if -5 <= x <= self.width() + 5:
                marks.append((x, str(sess.get("decoder", "")).upper()))
        return marks, (self.fmap.x(float(sp["loHz"])), self.fmap.x(float(sp["hiHz"])))

    def _paint_span(self, p: QPainter):
        marks, edges = self.span_layout()
        if edges is None:
            return
        top, bottom = self.r_spec.y(), self.r_wf.bottom()
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 110))
        if edges[0] > 0:
            p.drawRect(QRectF(0, top, edges[0], bottom - top))
        if edges[1] < self.width():
            p.drawRect(QRectF(edges[1], top, self.width() - edges[1], bottom - top))
        col = theme.sc("peak", 0.85)
        p.setFont(self._mark_font())
        fm = QFontMetricsF(p.font())
        y = self.r_spec.y() + self.ALERT_Y + 16
        for x, cap in marks:
            p.setPen(QPen(col, 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, self.r_spec.y()), QPointF(x, self.r_spec.bottom()))
            w = fm.horizontalAdvance(cap) + 6
            box = QRectF(min(max(0.0, x + 3), self.width() - w), y, w, 13)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(MARK_BG))
            p.drawRoundedRect(box, 2.5, 2.5)
            p.setPen(col)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, cap)
        text = self.tr("Span held for decoders")
        w = fm.horizontalAdvance(text) + 10
        box = QRectF(self.width() - w - 8, self.r_spec.y() + 4, w, 15)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(MARK_BG))
        p.drawRoundedRect(box, 3, 3)
        p.setPen(col)
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def _paint_alerts(self, p: QPainter):
        lay = self.alert_layout()
        if not lay:
            return
        p.setFont(self._mark_font())
        for a, col, box in lay:
            strong = a.get("strong", True)
            key = a.get("colour") or "warn"
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(theme.sc(key, 0.22 if strong else 0.10))
            p.drawRect(col)
            p.setPen(QPen(theme.sc(key, 0.9 if strong else 0.4), 1))
            for x in (col.left(), col.right()):
                p.drawLine(QPointF(x, col.top()), QPointF(x, col.bottom()))
            if box is not None:
                p.setPen(Qt.PenStyle.NoPen)
                p.setBrush(theme.sc(key, 0.92 if strong else 0.45))
                p.drawRoundedRect(box, 3, 3)
                p.setPen(QColor(10, 10, 12))
                p.drawText(box, Qt.AlignmentFlag.AlignCenter, a["text"])

    def _paint_beacons(self, p: QPainter):
        p.setFont(self._beacon_font())
        col = theme.sc("beacon")
        for x, y, box, lab in self.beacon_layout(QFontMetricsF(p.font())):
            dia = QPainterPath()
            dia.moveTo(x, y)
            dia.lineTo(x + 4.5, y + 4.5)
            dia.lineTo(x, y + 9)
            dia.lineTo(x - 4.5, y + 4.5)
            dia.closeSubpath()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(col)
            p.drawPath(dia)
            p.setPen(QPen(theme.sc("beacon", 0.35), 1, Qt.PenStyle.DotLine))
            p.drawLine(QPointF(x, y + 10), QPointF(x, self.r_spec.bottom()))
            if box is not None:
                p.setPen(col)
                p.drawText(box, Qt.AlignmentFlag.AlignVCenter, lab)

    def caption_boxes(self) -> list[QRectF]:
        """Everything fixed that is written on the spectrum: the beacon
        captions and diamonds (wide), the mode's flags (zoom: PITCH, the
        RX/TX offsets) and the TX flag. Peak labels are placed around these;
        before, a "995.4  -49" could sit on "Multimedia" (0.1.3 screenshots)."""
        out = []
        if self.wide:
            for x, y, box, _lab in self.beacon_layout():
                out.append(QRectF(x - 5, y, 10, 10))
                if box is not None:
                    out.append(box)
        else:
            fm = QFontMetricsF(self._flag_font())
            dial, _plo, _phi = self._passband_abs()
            for x, y, text, _col in self.mode_flags(dial):
                out.append(self._flag_rect(fm, x, y, text))
        tx = self._tx_flag_at()
        if tx is not None:
            out.append(self._flag_rect(QFontMetricsF(theme.font(10, theme.QFont.Weight.Bold)), tx[0], tx[1], "TX"))
        return out

    def _flag_font(self):
        return theme.font(10.5, theme.QFont.Weight.Bold)

    def mode_flags(self, dial: float) -> list[tuple[float, float, str, QColor]]:
        """(x, y, text, colour) of the mode's flags on the zoom scope."""
        if self.wide:
            return []
        mode = self._st("mode")
        y0 = self.r_spec.y() + 4
        if mode == "cw":
            x = self.fmap.x(dial + float(self._st("cwPitch", 700.0)))
            return [(x, y0, f"PITCH {self._st('cwPitch', 700):.0f}", theme.sc("rx"))]
        if is_slot(mode):
            out = []
            for key, col in (("rx", theme.sc("ok")), ("tx", self.tx_colour())):
                off = self.audio_offsets.get(key)
                if off is not None:
                    out.append((self.fmap.x(dial + off), y0 + (0 if key == "rx" else 18), f"{key.upper()} {off:.0f}",
                                col))
            return out
        if mode in ("psk31", "psk63", "psk125", "rtty"):
            off = self.audio_offsets.get("rx")
            if off is not None:
                return [(self.fmap.x(dial + off), y0, f"RX {off:.0f}", theme.sc("ok"))]
        return []

    def _paint_mode_marks(self, p: QPainter, dial: float):
        if self.wide:
            return
        mode = self._st("mode")
        y0, y1 = self.r_spec.y() + 4, self.r_spec.bottom()
        if mode == "cw":
            x = self.fmap.x(dial + float(self._st("cwPitch", 700.0)))
            p.setPen(QPen(theme.sc("rx", 0.85), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(x, y0 + 14), QPointF(x, y1))
        elif is_slot(mode):
            # The decoder's whole audio window, then our RX and TX offsets.
            xl, xh = self.fmap.x(dial + 200), self.fmap.x(dial + 3000)
            p.setPen(QPen(QColor(255, 255, 255, 40), 1, Qt.PenStyle.DotLine))
            for x in (xl, xh):
                p.drawLine(QPointF(x, y0), QPointF(x, self.r_wf.bottom()))
            bw = self.slot(mode).tone_width
            for key, col in (("rx", theme.sc("ok")), ("tx", self.tx_colour())):
                off = self.audio_offsets.get(key)
                if off is None:
                    continue
                xa, xb = self.fmap.x(dial + off), self.fmap.x(dial + off + bw)
                band = QColor(col)
                band.setAlphaF(0.22)
                p.fillRect(QRectF(xa, self.r_spec.y(), max(2.0, xb - xa), self.r_spec.height()), band)
                p.setPen(QPen(col, 1.5))
                p.drawLine(QPointF(xa, self.r_spec.y()), QPointF(xa, self.r_wf.bottom()))
        elif mode in ("psk31", "psk63", "psk125", "rtty"):
            off = self.audio_offsets.get("rx")
            if off is not None:
                x = self.fmap.x(dial + off)
                p.setPen(QPen(theme.sc("ok", 0.9), 1, Qt.PenStyle.DashLine))
                p.drawLine(QPointF(x, y0 + 14), QPointF(x, self.r_wf.bottom()))
        p.setFont(self._flag_font())
        for x, y, text, col in self.mode_flags(dial):
            self._flag(p, x, y, text, col)

    def tx_colour(self) -> QColor:
        """The TX marks' colour: red only while on the air, whichever radio
        (Face.on_air); otherwise our own signal's gold, as the "where it
        landed" box already is. They were red at all times, and red means
        transmitting (overhaul section 5.3)."""
        return theme.sc("tx") if self.face.on_air(self.bridge.st) else theme.sc("own")

    def _flag_rect(self, fm: QFontMetricsF, x: float, y: float, text: str) -> QRectF:
        w = fm.horizontalAdvance(text) + 10
        r = QRectF(x + 3, y, w, 15)
        if r.right() > self.width() - 2:
            r.moveRight(x - 3)
        return r

    def _flag(self, p: QPainter, x: float, y: float, text: str, col: QColor):
        r = self._flag_rect(QFontMetricsF(p.font()), x, y, text)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, 3, 3)
        p.setPen(QColor(6, 8, 12))
        p.drawText(r, Qt.AlignmentFlag.AlignCenter, text)

    def _tx_flag_at(self) -> tuple[float, float] | None:
        """Where the "TX" flag goes, or None when TX is on the RX dial and
        unkeyed (the flag would only repeat the dial line)."""
        s = self.bridge.st
        txd = float(s.get("txDial") or 0.0)
        if not txd:
            return None
        keyed = self.face.on_air(s)
        top = self.r_spec.y() + (22 if not self.wide else 18)
        xt = self.fmap.x(txd)
        if s.get("split") or keyed or abs(xt - self.fmap.x(float(s.get("rxDial") or 0))) > 3:
            return xt, top - 16 if keyed else top
        return None

    def _paint_tx(self, p: QPainter):
        s = self.bridge.st
        txd = float(s.get("txDial") or 0.0)
        if not txd:
            return
        mode = s.get("mode", "usb")
        if mode == "cw":
            lo, hi = txd + s.get("cwPitch", 700) - 50, txd + s.get("cwPitch", 700) + 50
        elif mode == "lsb":
            lo, hi = txd - s.get("txFilterHi", 2700), txd - s.get("txFilterLo", 300)
        elif is_slot(mode):
            off = self.audio_offsets.get("tx", 1500.0)
            lo, hi = txd + off, txd + off + self.slot(mode).tone_width
        else:
            lo, hi = txd + s.get("txFilterLo", 300), txd + s.get("txFilterHi", 2700)
        keyed = self.face.on_air(s)   # radiating, whichever radio (Face.on_air)
        red = theme.sc("tx")
        xl, xh = self.fmap.x(lo), self.fmap.x(hi)
        if xh - xl < 4:
            c = (xl + xh) / 2
            xl, xh = c - 2, c + 2
        top = self.r_spec.y() + (22 if not self.wide else 18)
        xt = self.fmap.x(txd)
        if keyed:
            band = QColor(red)
            band.setAlphaF(0.18)
            p.fillRect(QRectF(xl, top, xh - xl, self.r_spec.bottom() - top), band)
            p.setPen(QPen(red, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(QRectF(xl, top, xh - xl, self.r_spec.bottom() - top))
        else:
            p.setPen(QPen(theme.sc("own", 0.75), 1, Qt.PenStyle.DashLine))
            p.drawLine(QPointF(xt, top), QPointF(xt, self.r_spec.bottom()))
        p.setFont(theme.font(10, theme.QFont.Weight.Bold))
        flag = self._tx_flag_at()
        if flag is not None:
            self._flag(p, flag[0], flag[1], "TX", red if keyed else theme.sc("own"))
        # Where our own signal actually came down (TX lock), and how far that is
        # from where it should be. This is the picture that makes TX lock legible.
        own = float(s.get("ownDl") or 0.0)
        recent = keyed or (time.time() - self.own_seen_t < 8.0)
        if own and recent and s.get("txLockState") in ("searching", "landed", "locked"):
            err = own - txd
            ol, oh = lo + err, hi + err
            xo, xo2 = self.fmap.x(ol), self.fmap.x(oh)
            if xo2 - xo < 4:
                c = (xo + xo2) / 2
                xo, xo2 = c - 2, c + 2
            gold = theme.sc("own")
            good = abs(err) < 25.0
            col = theme.sc("ok") if good else gold
            p.setPen(QPen(col, 1.6, Qt.PenStyle.DashLine))
            p.setBrush(QColor(col.red(), col.green(), col.blue(), 40))
            p.drawRect(QRectF(xo, top + 8, xo2 - xo, self.r_spec.bottom() - top - 8))
            # Arrow from expected to actual centre, with the error spelled out.
            y = top + 4
            xa, xb = (xl + xh) / 2, (xo + xo2) / 2
            p.setPen(QPen(col, 1.6))
            if abs(xb - xa) > 8:
                p.drawLine(QPointF(xa, y), QPointF(xb, y))
                d = 1 if xb > xa else -1
                head = QPainterPath()
                head.moveTo(xb, y)
                head.lineTo(xb - d * 7, y - 4)
                head.lineTo(xb - d * 7, y + 4)
                head.closeSubpath()
                p.setBrush(col)
                p.drawPath(head)
            e0 = "\u00b10" if abs(err) < 0.5 else f"{err:+.0f}"
            txt = (f"TX LOCKED  {e0} Hz" if good else
                   f"LANDED {err / 1000:+.2f} kHz" if abs(err) >= 1000 else f"LANDED {err:+.0f} Hz")
            p.setFont(theme.font(10.5, theme.QFont.Weight.Bold))
            self._flag(p, max(xa, xb) + 4, y - 7, txt, col)

    def _decode_font(self):
        return theme.font(11.5 if not self.big else 18, theme.QFont.Weight.DemiBold)

    def decode_layout(self, fm: QFontMetricsF | None = None) -> list[tuple[dict, QRectF, str, float]]:
        """(label, its box, the text shown, its age in seconds) for every
        decode label with a place on the waterfall now, newest first.
        Labels older than the waterfall is tall are dropped from
        self.labels here.

        Placement, newest first so the newest win a place: at its signal
        and its slot's time; stepped down a row at a time, up to eight,
        past any label already placed. A box that would run past the right
        edge goes to the left of its signal instead. One that finds no free
        place, or would run off the bottom, is tried again as its call alone
        (zoom: a full "CQ DL5XL JO31" is three times a call's width), then
        given up: before, a label that still overlapped after eight steps
        was drawn on top of the others (overhaul section 5.10). Nothing is
        put under the Adjust pill."""
        r = self.r_wf
        if fm is None:
            fm = QFontMetricsF(self._decode_font())
        now_t = self.last_line_t
        dpr = self.devicePixelRatioF()
        px_per_s = self.rps / dpr * (r.height() / max(1.0, self.wf.h / dpr))
        life = r.height() / max(1e-3, px_per_s)
        self._decode_life = life
        placed: list[QRectF] = [self._levels_button().adjusted(-4, -4, 4, 4)]
        out, keep = [], []
        right = self.width() - 2.0
        for lab in reversed(self.labels):
            age = now_t - lab["t"]
            if age > life + 2:
                continue
            keep.append(lab)
            x = self.fmap.x(lab["f"])
            if x < -40 or x > self.width() + 40:
                continue
            y = r.y() + max(0.0, age) * px_per_s
            texts = [lab["text"]]
            call = lab.get("call") or ""
            if call and call != lab["text"]:
                texts.append(call)
            for text in texts:
                w = fm.horizontalAdvance(text) + 12
                box = QRectF(x - 2, y - 9, w, 18)
                if box.right() > right:
                    box.moveRight(x - 4)
                if box.left() < 0:
                    box.moveLeft(0)
                if box.right() > right:
                    continue                    # wider than the scope: try the call
                for _ in range(8):
                    if any(box.intersects(q) for q in placed):
                        box.translate(0, 19)
                    else:
                        break
                if box.bottom() > r.bottom() or any(box.intersects(q) for q in placed):
                    continue
                placed.append(box)
                out.append((lab, box, text, age))
                break
        self.labels = list(reversed(keep))
        # Hidden: still walked above, so old labels are pruned and the
        # rest come back in their right places when shown again.
        return out if labels_shown(self.prefs) else []

    def _paint_decodes(self, p: QPainter):
        r = self.r_wf
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(self._decode_font())
        fm = QFontMetricsF(p.font())
        # A label to us is gold like its row in the band activity (decision
        # 8), whichever name the window gives its kind ("mine" today).
        cols = {"cq": theme.sc("cq"), "mine": theme.sc("toYou"), "toYou": theme.sc("toYou"),
                "worked": QColor(150, 160, 175)}
        lay = self.decode_layout(fm)
        life = self._decode_life
        for lab, box, text, age in lay:
            alpha = max(0.15, 1.0 - max(0.0, age) / life)
            col = cols.get(lab["kind"], QColor(225, 232, 242))
            bg = QColor(6, 9, 14)
            bg.setAlphaF(0.72 * alpha)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(bg)
            p.drawRoundedRect(box, 4, 4)
            stripe = QColor(col)
            stripe.setAlphaF(alpha)
            p.setBrush(stripe)
            p.drawRoundedRect(QRectF(box.x(), box.y(), 3, box.height()), 1.5, 1.5)
            tc = QColor(col)
            tc.setAlphaF(alpha)
            p.setPen(tc)
            p.drawText(box.adjusted(7, 0, 0, 0), Qt.AlignmentFlag.AlignVCenter, text)
        # Streaming text tags (CW, PSK, RTTY): pinned at the top, fading when idle.
        for tag, box, text, age in self.tag_layout(fm):
            alpha = max(0.2, 1.0 - age / 20)
            bg = QColor(6, 9, 14)
            bg.setAlphaF(0.8 * alpha)
            p.setPen(QPen(theme.sc("rx", 0.6 * alpha), 1))
            p.setBrush(bg)
            p.drawRoundedRect(box, 5, 5)
            tc = QColor(230, 240, 250)
            tc.setAlphaF(alpha)
            p.setPen(tc)
            p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)

    def tag_layout(self, fm: QFontMetricsF | None = None) -> list[tuple[dict, QRectF, str, float]]:
        """(tag, its box, the text shown, its age in seconds) for every
        streaming text tag still alive; tags idle for 20 s are dropped from
        self.tags here.

        A tag is centred on its signal at the top of the waterfall, which is
        the Adjust pill's row too. Before, it was drawn wherever its signal
        put it, and an RTTY ticker on the 270 px zoom ran straight under the
        pill (overhaul section 5.10 says nothing goes there). Now a tag that
        would touch the pill moves to end left of it, and if that runs it off
        the left edge it keeps its newest characters and loses the oldest
        behind an ellipsis - a ticker is read from its right-hand end. The
        same clamp keeps every tag inside the scope's edges."""
        if fm is None:
            fm = QFontMetricsF(self._decode_font())
        r = self.r_wf
        pill = self._levels_button().adjusted(-4, -4, 4, 4)
        now = time.time()
        out = []
        for key in list(self.tags):
            tag = self.tags[key]
            age = now - tag["t"]
            if age > 20:
                del self.tags[key]
                continue
            x = self.fmap.x(tag["f"])
            text = tag["text"].strip() or "\u2026"
            w = fm.horizontalAdvance(text) + 14
            box = QRectF(x - w / 2, r.y() + 6, w, 20)
            # The pill sits at the right end of the tags' row, so anything
            # reaching past its left side would be under it or beyond it.
            limit = pill.left() if box.right() > pill.left() and box.top() < pill.bottom() else self.width() - 2.0
            if box.right() > limit:
                box.moveRight(limit)
            if box.left() < 0:
                box.moveLeft(0)
            if box.right() > limit:
                # Wider than the room left of the pill: keep the newest text.
                text = fm.elidedText(text, Qt.TextElideMode.ElideLeft, max(0.0, limit - 14))
                if not text:
                    continue
                box = QRectF(0, box.y(), limit, box.height())
            out.append((tag, box, text, age))
        return out

    def _paint_levels_button(self, p: QPainter):
        b = self._levels_button()
        hot = self.underMouse() and self.hover is None
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 50 if not hot else 110), 1))
        p.setBrush(QColor(10, 13, 19, 200))
        p.drawRoundedRect(b, 12 if b.width() > self.PILL_GLYPH else 6, 12 if b.width() > self.PILL_GLYPH else 6)
        text = self.pill_text()
        if text:
            p.setFont(self._pill_font())
            p.setPen(QColor(220, 230, 240, 235))
            p.drawText(QRectF(b.x() + self.PILL_GLYPH - 2, b.y(), b.width() - self.PILL_GLYPH, b.height()),
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, text)
        # Three level bars - "adjust".
        p.setPen(QPen(QColor(220, 230, 240, 200), 1.6, cap=Qt.PenCapStyle.RoundCap))
        cx, cy = b.x() + self.PILL_GLYPH / 2, b.center().y()
        for dx, knob in ((-6, -2), (0, 3), (6, -4)):
            p.drawLine(QPointF(cx + dx, cy - 6), QPointF(cx + dx, cy + 6))
            p.setBrush(QColor(79, 209, 232))
            p.drawEllipse(QPointF(cx + dx, cy + knob), 2.2, 2.2)

    def _paint_hover(self, p: QPainter):
        if self.hover is None or self.press is not None:
            return
        x = self.hover.x()
        if self.wide and self.r_strip.contains(self.hover):
            return
        f = self.fmap.f(x)
        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        p.setPen(QPen(QColor(255, 255, 255, 60), 1))
        p.drawLine(QPointF(round(x) + 0.5, self.r_spec.y()), QPointF(round(x) + 0.5, self.height()))
        p.setFont(theme.font(11, theme.QFont.Weight.DemiBold, mono=True))
        text = fmt_dl(f)
        seg = self.face.segment_at(f)
        fm = QFontMetricsF(p.font())
        w = fm.horizontalAdvance(text) + 14
        box = QRectF(x + 8, self.r_spec.y() + 20, w, 20)
        if box.right() > self.width() - 50:
            box.moveRight(x - 8)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(255, 255, 255, 40), 1))
        p.setBrush(QColor(14, 18, 26, 230))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor(235, 242, 250))
        p.drawText(box, Qt.AlignmentFlag.AlignCenter, text)
        if seg and self.wide:
            p.setFont(theme.font(10.5))
            p.setPen(QColor(200, 210, 225, 170))
            p.drawText(QRectF(box.x(), box.bottom() + 2, 260, 16), Qt.AlignmentFlag.AlignLeft, seg["label"])
