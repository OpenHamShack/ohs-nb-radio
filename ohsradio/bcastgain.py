"""The receiver's gain while a broadcast station plays: a DAB session
holding the receiver, or wide FM (Brian, 23/10/2026).

Why: the operator's manual `rxGain` is set for weak amateur signals, and a
broadcast station inherited it. Measured on ohs-box (store Radio
0.1.22-beta.6, an RSPdx under SoapySDRPlay3's gain sense, rxGain 40, so
gRdB 59 at LNA state 1): DAB on block 11B, a local transmitter with 48 dB
of SNR, glitched audibly - `deviceStatus` said `overloaded` true and 4328
overloads, and FIB CRC failures ran at 1.5 % despite the SNR. 12B (17 dB)
was clean at the same gain. A broadcast multiplex is the strongest thing
on the antenna by tens of dB, so it wants less gain, not the same.

What happens instead, while one plays (`Policy`, driven ten times a second
from Radio's supervisor tick):

- **The operator's settings are never touched.** `rxGain`, `rxGainMode`
  and the antenna stay exactly as they were (saved, shown in Settings);
  what changes is only what the engine applies to the device
  (Engine._rx_gain_wanted, the hook NB's dish alignment uses the same
  way). So when the station stops - however it stops - there is nothing to
  put back: the engine applies the operator's own figure again on its
  next reconfigure, exactly, and a radio stopped meanwhile reopens with it
  because it is what the configuration holds.
- **It starts at a broadcast default, never above the operator's gain.**
  The default (`DEFAULT`, per gain model) is a gain a strong local
  multiplex does not overload on the radios measured; where the operator
  already runs less gain than that, theirs is kept - they had a reason.
- **For DAB it steers by the decoder's FIB errors, with overload only
  saying which way.** Every `WINDOW_S` it takes the share of FIBs that
  failed their CRC (the session's `fibsOk`/`fibsBad`). Clean (at most
  `CLEAN_FRAC`): nothing moves, whatever the overload flag says. Errors
  with overload reported in the window: one step less gain. Errors with
  none: the weak-signal side, one step more gain. Any step that leaves
  the errors worse than before it is undone, and the gain it tried is
  barred for the session (`floor` on the weak side, the overload memory
  on the strong side) - so it backs off only until the errors stop, and
  never walks off the weak-signal cliff.

  Why not overload alone (the first version, 046a59f): Brian's sweep on
  ohs-box (24/10/2026; RSPdx, Antenna A, eight Band III blocks, 3 s
  settle and 8 s measure a step) found the SDRplay overload flag
  flickering true at rxGain 45 on 11C, 11D, 12A and 12B while their FIBs
  were 100 % clean. Backing off on it would have walked the gain to 50
  (LNA state 11), where the weak blocks fall apart: 11C to 3.2 dB SNR with
  27 % of FIBs clean, 11D 3.6 dB with 70 %. At 45 (LNA state 6) all eight
  were clean (15-41 dB); at 40 (LNA state 1) the local 11B, 8 km away,
  was 88 % clean and overloaded; at 35 and below (LNA state 0) overload
  grew and blocks lost sync.
- **Wide FM, and DAB before it has FIBs to count,** has only the overload
  report, so it is debounced: one step less after overload in
  `DEBOUNCE` windows running, never into the weak-side `floor`; and one
  step back after `CREEP_S` clear, toward the start, never into a gain
  that overloaded in the last `MEMORY_S` (that step is the margin).
- **A radio that reports no overload** (an RTL-SDR, a Pluto, a SoapySDR
  radio, the simulator) holds the default for wide FM: there is nothing
  to steer by. For DAB its FIB errors still steer it, trying less gain
  first since nothing says which side the errors are on. Estimating clipping from the samples was
  considered and left out - each driver scales its samples differently,
  and a wrong full scale would back a weak station off for nothing.
- **Nothing for** a receiver whose gain control is the device's own AGC
  (that already follows the signal), the Hermes-Lite 2 (its receive gain
  is `hl2Lna`, which rxGain does not reach and which is its operator's),
  or a recording playing (its gain was fixed when it was made). The
  status says which.

Steps per gain model (the device's own word, `deviceStatus.gainModel`,
ohscore/devices/base.py Device.gain_sense; the same split the S-meter's
calibration uses, ohscore/smeter_cal.py `gain_split`):

- `"db"` - a plain gain in dB: 3 dB steps, floor 0; default 30 dB, below
  which a Pluto or RTL-SDR still hears a 17 dB multiplex well and above
  which the strongest local ones start to clip.
- `"sdrplay"` (`device sdrplay`): rxGain is 79 - gRdB, gRdB held to
  20-59, so 3 dB steps over rxGain 20-59; default 30 (gRdB 49). The LNA
  state is its own setting there (`sdrplayLna`) and stays the operator's:
  if gRdB 59 still overloads the policy has done what it may, and says so
  (`atLimit`).
- `"soapysdrplay3"` (`device soapy` with driver=sdrplay, ohs-box): a
  higher rxGain is *less* gain. The first 39 dB are gRdB 20-59, every dB
  above is one LNA state (sdrsource.soapy_gain_split_rf), up to
  `rfgrRange`'s top. Below 39 the steps are 3 dB of gRdB; above, one LNA
  state each (about 3 dB in Band II/III on an RSPdx, more on the older
  models' coarser tables). Default 45: gRdB 59 at LNA state 6, where the
  ohs-box sweep (above) had every Band III block clean - between the
  local multiplex's overload at 40 and the weak blocks' cliff at 50.
"""
from __future__ import annotations

from ohsradio.i18n import _

# Seconds (module docstring). One window of FIB counts or overload reports:
# DAB sends about 125 FIBs a second (mode I: 12 every 96 ms), so a second
# holds enough to tell 1 % from clean.
WINDOW_S = 1.0
# After a change, this long before counting again: the gain reaches the
# device on the receive thread, and the decoder's FIBs in flight were
# taken at the old gain.
SETTLE_S = 1.0
MIN_FIBS = 50              # fewer in a window (no sync yet): overload only
CLEAN_FRAC = 0.005         # a window this clean is clean
WORSE_FRAC = 0.01          # a step that adds this much to the errors is undone
DEBOUNCE = 3               # overload-only: windows running before a step down
# Clear this long after the last overload or error: settled.
HOLD_S = 5.0
# Overload-only: clear this long since the last change before one step back up.
CREEP_S = 30.0
# A gain that overloaded with errors stays out of reach this long.
MEMORY_S = 300.0

DB_STEP = 3.0
DEFAULT = {"db": 30.0, "sdrplay": 30.0, "soapysdrplay3": 45.0}
SDRPLAY_RANGE = (20.0, 59.0)          # rxGain over which `sdrplay`'s gRdB moves (79 - 59 .. 79 - 20)
SOAPY_IF_TOP = 39.0                   # soapysdrplay3: rxGain at which gRdB reaches 59 and the LNA steps begin


class Ladder:
    """Where rxGain may go for a broadcast station on one gain model, in
    the device's own units: `less(g)` and `more(g)` are one step of less
    or more real gain (None past the end), `gainier(a, b)` whether `a` is
    more real gain than `b`."""

    def __init__(self, model: str, rfgr_range=None):
        self.model = model if model in DEFAULT else "db"
        self.reduction = self.model == "soapysdrplay3"
        if self.model == "soapysdrplay3":
            rf = rfgr_range or (0, 27)
            self.lo, self.hi = 0.0, SOAPY_IF_TOP + float(int(rf[1]) - int(rf[0]))
        elif self.model == "sdrplay":
            self.lo, self.hi = SDRPLAY_RANGE
        else:
            self.lo, self.hi = 0.0, 73.0      # ohscore/state.py rxGain's range
        self.default = self.clamp(DEFAULT[self.model])

    def clamp(self, g: float) -> float:
        return min(max(float(g), self.lo), self.hi)

    def gainier(self, a: float, b: float) -> bool:
        return a < b if self.reduction else a > b

    def less(self, g: float) -> float | None:
        if self.reduction:
            # Up to 39 the gRdB steps; above, every LNA state.
            nxt = min(g + DB_STEP, SOAPY_IF_TOP) if g < SOAPY_IF_TOP else float(int(g) + 1)
            return nxt if nxt <= self.hi else None
        nxt = g - DB_STEP
        if g <= self.lo:
            return None
        return max(nxt, self.lo)

    def more(self, g: float) -> float | None:
        if self.reduction:
            if g <= self.lo:
                return None
            nxt = float(int(g) - 1) if g > SOAPY_IF_TOP else g - DB_STEP
            return max(nxt, self.lo)
        if g >= self.hi:
            return None
        return min(g + DB_STEP, self.hi)

    def start(self, operator: float) -> float:
        """The broadcast default, or the operator's own gain where that is
        already less."""
        op = self.clamp(operator)
        return op if self.gainier(self.default, op) else self.default


class Policy:
    """One broadcast station's gain, from `begin` to `end` (module
    docstring). Driven by `tick` on Radio's supervisor thread; `wanted` is
    read on the receive thread (one tuple, assigned whole)."""

    def __init__(self):
        self.key = None
        self.wanted: tuple | None = None       # ("manual", rxGain) while applying, else None
        self._view: dict = {}

    def view(self) -> dict:
        return dict(self._view)

    def active(self) -> bool:
        return self.key is not None

    def begin(self, key, now: float, model: str, rfgr_range, operator_db: float, adaptive: bool,
              from_operator: bool = False) -> None:
        """A broadcast station starts (`key` names it: a new key is a new
        station). `adaptive`: the device reports overload. `from_operator`:
        start at the operator's own gain rather than the broadcast default
        (AIS, ohsradio/ais.py: weak signals, so only overload moves it)."""
        self.key = key
        self.rfgr_range = rfgr_range
        self.from_operator = bool(from_operator)
        self.ladder = Ladder(model, rfgr_range)
        self.operator = float(operator_db)
        self.cap = self.ladder.clamp(operator_db) if from_operator else self.ladder.start(operator_db)
        # The weak side may climb back as far as the operator's own gain
        # where that is more than the start: they chose it.
        op = self.ladder.clamp(operator_db)
        self.top = op if self.ladder.gainier(op, self.cap) else self.cap
        self.gain = self.cap
        self.adaptive = bool(adaptive)
        self.changed_at = self.began_at = now
        self.trouble_at: float | None = None    # the last overload or FIB error that counted
        self.bad: dict[float, float] = {}       # gain -> when it last overloaded with errors
        self.floor: float | None = None         # a gain whose errors were the weak signal's: never this far
        self.last_step = None                   # (direction, gain stepped from, errors before) awaiting its verdict
        self.backoffs = 0
        self.overloaded = False
        self.at_limit = False
        self.fib_bad: float | None = None
        self.signal = "overload"
        self.streak = 0
        self._win = None
        self.wanted = ("manual", self.gain)
        self._publish(now)

    def idle(self, key, why: str, text: str) -> None:
        """A broadcast station plays but this policy may not touch the gain
        (`why` a code, `text` the sentence): the operator's gain stands."""
        self.key = key
        self.wanted = None
        self._view = {"auto": False, "db": None, "why": why, "text": text}

    def end(self) -> None:
        self.key = None
        self.wanted = None
        self._view = {}

    def operator_changed(self, now: float, operator_db: float) -> None:
        """The operator moved rxGain while the station plays: the new
        figure is the new start and ceiling, as if the station began now
        (their change is a deliberate act; what was learned stays)."""
        bad, floor = self.bad, self.floor
        self.begin(self.key, now, self.ladder.model, self.rfgr_range, operator_db, self.adaptive,
                   from_operator=self.from_operator)
        self.bad, self.floor = bad, floor

    # -- the steps ------------------------------------------------------------
    def _allowed(self, g: float, now: float) -> bool:
        lad = self.ladder
        if self.floor is not None and not lad.gainier(g, self.floor):
            return False            # as little gain as the weak side's cliff, or less
        if lad.gainier(g, self.top):
            return False
        return not any(now - t < MEMORY_S and (b == g or lad.gainier(g, b)) for b, t in self.bad.items())

    def _step(self, now: float, direction: str, errors: float | None) -> bool:
        nxt = (self.ladder.less if direction == "less" else self.ladder.more)(self.gain)
        if nxt is None or not self._allowed(nxt, now):
            self.at_limit = True
            return False
        self.last_step = (direction, self.gain, errors) if errors is not None else None
        self.gain, self.changed_at = nxt, now
        self.at_limit = False
        if direction == "less":
            self.backoffs += 1
        return True

    def tick(self, now: float, overloaded: bool, fibs: tuple | None = None) -> bool:
        """One look at the device (`overloaded`: a new overload since the
        last look) and, for DAB, the session's FIB counts so far (`fibs`,
        (ok, bad), or None). True when the gain to apply changed."""
        if self.wanted is None:
            return False
        if now - self.changed_at < SETTLE_S:
            self._win = None
            self._publish(now)
            return False
        if self._win is None:
            self._win = {"t": now, "fibs": fibs, "over": False}
        w = self._win
        w["over"] = w["over"] or (bool(overloaded) and self.adaptive)
        if now - w["t"] < WINDOW_S:
            return False
        self._win = None
        self.overloaded = w["over"]
        changed = False
        n = bad = 0
        if fibs is not None and w["fibs"] is not None:
            ok, bad = fibs[0] - w["fibs"][0], fibs[1] - w["fibs"][1]
            n = ok + bad
        if n >= MIN_FIBS and bad >= 0:
            changed = self._fib_window(now, bad / n, w["over"])
        else:
            self.signal, self.fib_bad = "overload", None
            changed = self._overload_window(now, w["over"])
        if changed:
            self.wanted = ("manual", self.gain)
        self._publish(now)
        return changed

    def _fib_window(self, now: float, frac: float, over: bool) -> bool:
        self.signal, self.fib_bad, self.streak = "fibs", round(frac, 4), 0
        last, self.last_step = self.last_step, None
        if last is not None and last[2] is not None and frac > last[2] + WORSE_FRAC:
            # The step made it worse: back, and never there again.
            direction, before, _errors = last
            if direction == "less":
                self.floor = self.gain
            else:
                self.bad[self.gain] = now
            self.gain, self.changed_at, self.trouble_at = before, now, now
            return True
        if frac <= CLEAN_FRAC:
            self.at_limit = False
            return False
        self.trouble_at = now
        if over:
            self.bad[self.gain] = now
            return self._step(now, "less", frac)
        if not self.adaptive and self.floor is None:
            # No overload report to say which side the errors are on: try
            # less gain first (a broadcast station is more often too strong
            # than too weak); if that is worse it is undone and becomes the
            # floor, and from then on the errors mean more gain.
            return self._step(now, "less", frac)
        return self._step(now, "more", frac)

    def _overload_window(self, now: float, over: bool) -> bool:
        if not self.adaptive:
            return False
        if over:
            self.trouble_at = now
            self.streak += 1
            if self.streak < DEBOUNCE:
                return False
            self.streak = 0
            self.bad[self.gain] = now
            return self._step(now, "less", None)
        self.streak = 0
        quiet = self.trouble_at is None or now - self.trouble_at >= CREEP_S
        if quiet and now - self.changed_at >= CREEP_S and self.ladder.gainier(self.cap, self.gain):
            return self._step(now, "more", None)
        return False

    def _publish(self, now: float) -> None:
        recent = self.trouble_at is not None and now - self.trouble_at < HOLD_S
        if not self.adaptive and self.signal != "fibs":
            state, text = "fixed", _(
                "Broadcast gain {db:g} (this radio does not report overload, so it stays there). Your own "
                "gain, {op:g}, is back when the station stops.")
        elif self.at_limit and recent:
            state, text = "limit", _(
                "Broadcast gain {db:g}: reception still has errors, and no gain this policy may set is better")
        elif recent:
            state, text = "adjusting", _("Broadcast gain {db:g}: adjusting to this station")
        elif now - self.began_at < HOLD_S:
            state, text = "settling", _("Broadcast gain {db:g}: watching reception")
        else:
            state, text = "settled", _(
                "Broadcast gain {db:g}, chosen for this station. Your own gain, {op:g}, is back when it stops.")
        self._view = {"auto": True, "db": self.gain, "operatorDb": self.operator, "gainModel": self.ladder.model,
                      "adaptive": self.adaptive, "state": state, "signal": self.signal, "fibBad": self.fib_bad,
                      "overloaded": self.overloaded, "backoffs": self.backoffs, "atLimit": self.at_limit,
                      "floorDb": self.floor, "text": text.format(db=self.gain, op=self.operator)}
