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
- **It backs off while the device reports overload** (`deviceStatus`
  `overloaded`, or its `overloads` count rising: the SDRplay API's power
  overload events, shack_sdr's SdrplaySource), one step every `STEP_S`
  until it has been clear for `HOLD_S` - then it is settled.
- **It creeps back up, slowly,** one step after `CREEP_S` clear since the
  last change, toward the start gain, never into a gain that overloaded
  in the last `MEMORY_S` (that one step is the margin: a gain that
  overloaded once stays one step out of reach while the memory lasts).
  Without the creep a fading or briefly keyed neighbour would leave a
  weak multiplex at the floor for the rest of the session.
- **A radio that reports no overload** (an RTL-SDR, a Pluto, a SoapySDR
  radio, the simulator) gets the default and stays there: there is
  nothing to steer by. Estimating clipping from the samples was
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
  models' coarser tables). Default 43: gRdB 59 at LNA state 4 - the
  state ohs-box's own `rfgain_sel=4` chose for 2 m, and three states
  (about 9 dB) below the rxGain 40 that overloaded on 11B.
"""
from __future__ import annotations

from ohsradio.i18n import _

# Seconds (module docstring): a step down at most this often while the
# device reports overload - long enough for the change to reach the
# device on the receive thread and the device to report again (the
# SDRplay API acknowledges and re-detects within a few blocks), short
# enough that a badly overloaded start clears in a couple of seconds.
STEP_S = 0.5
# Clear this long after the last overload: settled.
HOLD_S = 5.0
# Clear this long since the last change before one step back up.
CREEP_S = 30.0
# A gain that overloaded stays out of reach this long.
MEMORY_S = 300.0

DB_STEP = 3.0
DEFAULT = {"db": 30.0, "sdrplay": 30.0, "soapysdrplay3": 43.0}
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

    def begin(self, key, now: float, model: str, rfgr_range, operator_db: float, adaptive: bool) -> None:
        """A broadcast station starts (`key` names it: a new key is a new
        station). `adaptive`: the device reports overload."""
        self.key = key
        self.rfgr_range = rfgr_range
        self.ladder = Ladder(model, rfgr_range)
        self.operator = float(operator_db)
        self.cap = self.ladder.start(operator_db)
        self.gain = self.cap
        self.adaptive = bool(adaptive)
        self.changed_at = self.began_at = now
        self.over_at: float | None = None
        self.bad: dict[float, float] = {}       # gain -> when it last overloaded
        self.backoffs = 0
        self.overloaded = False
        self.at_limit = False
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
        (their change is a deliberate act; the memory of what overloaded
        stays)."""
        bad = self.bad
        self.begin(self.key, now, self.ladder.model, self.rfgr_range, operator_db, self.adaptive)
        self.bad = bad

    def tick(self, now: float, overloaded: bool) -> bool:
        """One look at the device; True when the gain to apply changed."""
        if self.wanted is None:
            return False
        self.overloaded = bool(overloaded) and self.adaptive
        changed = False
        if self.overloaded:
            self.over_at = now
            self.bad[self.gain] = now
            if now - self.changed_at >= STEP_S:
                nxt = self.ladder.less(self.gain)
                if nxt is None:
                    self.at_limit = True
                else:
                    self.gain, self.changed_at, changed = nxt, now, True
                    self.backoffs += 1
        elif self.adaptive and now - self.changed_at >= CREEP_S and \
                (self.over_at is None or now - self.over_at >= CREEP_S):
            nxt = self.ladder.more(self.gain)
            if nxt is not None and not self.ladder.gainier(nxt, self.cap) and not self._recently_bad(nxt, now):
                self.gain, self.changed_at, changed = nxt, now, True
                self.at_limit = False
        if changed:
            self.wanted = ("manual", self.gain)
        self._publish(now)
        return changed

    def _recently_bad(self, g: float, now: float) -> bool:
        """`g`, or anything with more gain than it, overloaded within
        MEMORY_S."""
        return any(now - t < MEMORY_S and (b == g or self.ladder.gainier(g, b)) for b, t in self.bad.items())

    def _publish(self, now: float) -> None:
        if not self.adaptive:
            state, text = "fixed", _(
                "Broadcast gain {db:g} (this radio does not report overload, so it stays there). Your own "
                "gain, {op:g}, is back when the station stops.")
        elif now - (self.over_at if self.over_at is not None else self.began_at) < HOLD_S:
            state = "limit" if self.at_limit else "backing_off"
            if self.over_at is None:
                state, text = "settling", _("Broadcast gain {db:g}: watching for overload")
            elif self.at_limit:
                text = _("Broadcast gain {db:g}: the radio is still overloaded at the least gain this policy may set")
            else:
                text = _("Broadcast gain {db:g}: the radio reports overload, so the gain is coming down")
        else:
            state, text = "settled", _(
                "Broadcast gain {db:g}, chosen for this station. Your own gain, {op:g}, is back when it stops.")
        self._view = {"auto": True, "db": self.gain, "operatorDb": self.operator, "gainModel": self.ladder.model,
                      "adaptive": self.adaptive, "state": state, "overloaded": self.overloaded,
                      "backoffs": self.backoffs, "atLimit": self.at_limit,
                      "text": text.format(db=self.gain, op=self.operator)}
