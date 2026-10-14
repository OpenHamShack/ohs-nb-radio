"""Radio's CW skimmer: every keyed signal in the CW segment of the band the
receive dial is in, decoded at once, whatever the dial is tuned to.

The work is ohs-libs' shack_cw.skim (its README, and openhamshack
docs/CW-SKIMMER-PLAN.md, say how); this is Radio's side of it, and the
contract is docs/ENGINE-API.md `cwskim`/`cwspot` and SERVER-API
`GET api/cwskim`.

- The segment is what the operator sees: the rows of the band plan in force
  (Radio._plan(), the plans the scope's strip draws) whose only mode is CW,
  in the dial's band, joined. A band with none (an R2/R3 plan's rows,
  unchecked) takes the lowest rows that allow CW, up to FALLBACK_HZ from
  the band's edge.
- The receive thread cuts one filter-bank channel over the part of the
  segment inside the receiver's span (`cover`, MARGIN_HZ in from its
  edges), at the smallest output rate that holds it (96 kS/s for 20 m at
  2.4 MS/s), and hands each block to a SkimRunner. put() never blocks: a
  full queue drops the block and counts it (cwSkimDropped).
- The runner's worker is a child process (Brian, 13/10/2026). It imports
  numpy, shack_cw and ohscore.dxcc (for cty.dat), never this app, so its
  Python never holds the receive thread's GIL and it cannot key anything.
- Results come back on the runner's drain thread. cwskim is published once
  a second. cwspot goes at most SPOTS_PER_S items a second, numbered by
  this server's own `rev`, so a client sees a gap only when it really lost
  items. The spots of the last 30 minutes stay here for GET api/cwskim.
- It never retunes the receiver. With the segment outside the span, state
  is "outside" and nothing is skimmed; partly outside, "partial".
- Both CW engines run on every channel, and a call is spotted only when it
  passes the callsign check and has been seen twice (Brian, 14/10/2026;
  shack_cw.skim.calls has the rule and the measurements). The callsign
  list is the RBN week shipped with shack_cw, plus Super Check Partial's
  MASTER.SCP in the data folder if it is there. That is never bundled
  (nothing allows passing it on): with `cwSkimScp` on (off by default) it
  is downloaded when the skimmer starts, at most once a day, as the site's
  developer guide asks (shack_cw.skim.scp.fetch), or the operator puts a
  copy there. A call on no list needs a third decode.

Off by default (`cwSkim`, Brian 13/10/2026): switched on per use.
"""
from __future__ import annotations

import logging
import threading
import time
from pathlib import Path

from ohscore import shacklibs
from ohscore.dsp.bank import Channel

from ohsradio.i18n import _

from . import bands

log = logging.getLogger("ohsradio.cwskim")

MARGIN_HZ = 3_000.0       # skim no closer than this to the edge of the receiver's span
GUARD_HZ = 2_000.0        # channel room either side of the cover, for the filter's skirt
FALLBACK_HZ = 100_000.0   # a band with no CW-only rows: CW-allowed rows this far up from its edge
SPOTS_PER_S = 5.0
ENGINE = "both"           # both CW engines on every channel (shack_cw.skim.pool)
SCP_FILE = "MASTER.SCP"   # the callsign list, in the data folder
KEEP_S = 1800.0
KEEP_N = 500


def segment(plan, dial: float) -> tuple[float, float, str] | None:
    """(lo, hi, band name) of the CW segment of the band `dial` is in, from
    the plan's rows, or None (between bands, or a band with no CW at all)."""
    b = bands.band_at(dial)
    if b is None:
        return None
    rows = sorted((r for r in plan.SEGMENTS if r.lo < b.hi and r.hi > b.lo and r.modes is not None),
                  key=lambda r: r.lo)
    cw = [r for r in rows if set(r.modes) == {"cw"}]
    if not cw:
        cw = [r for r in rows if "cw" in r.modes and r.lo < b.lo + FALLBACK_HZ]
    if not cw:
        return None
    # The run of CW rows that starts lowest, joined while they touch.
    lo, hi = cw[0].lo, cw[0].hi
    for r in cw[1:]:
        if r.lo > hi + 1.0:
            break
        hi = max(hi, r.hi)
    return max(lo, b.lo), min(hi, b.hi), b.name


def off_item() -> dict:
    """GET api/cwskim and the feed while the skimmer is off."""
    return {"state": "off", "band": None, "segment": None, "cover": None, "channels": [], "carriers": [],
            "spotsRev": 0}


def _thread_runner(was, on_result):
    """A thread-mode SkimRunner with `was`'s settings, for the fallback."""
    from shack_cw.skim.runner import SkimRunner
    c = was.config
    return SkimRunner(on_result, mode="thread", max_channels=c["max_channels"], squelch_db=c["squelch_db"],
                      pitch=c["pitch"], country=c["country"], history=c["history"], birdies=c["birdies"],
                      engine=c["engine"])


def selftest(out=print, mode: str = "process", seconds: float = 40.0, timeout: float = 120.0) -> int:
    """`python3 -m ohsradio --cw-skim-selftest`: the skimmer decodes shack_cw's
    synthetic band (four stations, a carrier, noise) in a worker *process*,
    with the country lookup this build carries, and every station is
    spotted with its country. 0 on success.

    For the frozen Windows and macOS builds (build-windows.ps1,
    try-dmg.sh), where a spawned child is the frozen program run again and
    works only if the entry point calls multiprocessing.freeze_support()
    and the bundle carries shack_cw.skim and cty.dat (CW-SKIMMER-PLAN §2.4).
    Opens no radio, no window and no audio; transmits nothing."""
    import os
    shacklibs.cw()
    from shack_cw.skim import runner as skim_runner, synth

    rate = 24_000.0
    z, stations = synth.selftest_band(rate, seconds)
    want = {s.call for s in stations}
    got: dict[str, dict] = {}
    errors: list[str] = []
    lock = threading.Lock()

    def on_result(kind, payload):
        with lock:
            if kind == "spots":
                for sp in payload:
                    if sp.get("status") == "valid":
                        got[sp["call"]] = sp
            elif kind == "status" and payload.get("state") == "error":
                errors.append(payload.get("why") or "error")
            elif kind == "warning":
                errors.append(str(payload))

    r = skim_runner.SkimRunner(on_result, mode=mode, max_channels=16, country=("ohscore.dxcc:skim_lookup", [None]))
    t0 = time.monotonic()
    try:
        r.start()
        pid = getattr(r._worker, "pid", None)
        out(f"cw-skim-selftest: worker {mode}" + (f" pid {pid} (this is {os.getpid()})" if pid else ""))
        if mode == "process" and (not pid or pid == os.getpid()):
            out("cw-skim-selftest: FAIL (the worker is not a process of its own)")
            return 1
        blk = int(0.075 * rate)
        lo, hi = -0.42 * rate, 0.42 * rate
        for i in range(0, len(z), blk):
            while not r.put(z[i:i + blk], t=i / rate, centre=0.0, rate=rate, lo=lo, hi=hi, band="20m"):
                if r.state != "running" or time.monotonic() - t0 > timeout:
                    break
                time.sleep(0.01)
        while time.monotonic() - t0 < timeout:
            with lock:
                if want <= set(got) or errors:
                    break
            time.sleep(0.2)
    finally:
        r.stop()
    with lock:
        missing = sorted(want - set(got))
        countries = {c: got[c].get("country") for c in sorted(got)}
    out("cw-skim-selftest: spotted " + (", ".join(f"{c} ({k or 'no country'})" for c, k in countries.items())
                                        or "nothing") + f" in {time.monotonic() - t0:.1f} s")
    if errors:
        out("cw-skim-selftest: " + "; ".join(errors))
    if missing or errors or not all(countries.values()):
        out("cw-skim-selftest: FAIL" + (f" (missing {', '.join(missing)})" if missing else ""))
        return 1
    out("cw-skim-selftest: PASS")
    return 0


class CwSkim:
    """See the module. `radio` is ohsradio.radio.Radio; `mode` is "process"
    (the box and the desktop) or "thread" (tests)."""

    def __init__(self, radio, mode: str = "process"):
        shacklibs.cw()
        from shack_cw.skim.runner import SkimRunner
        self.radio = radio
        s = radio.st
        self.lock = threading.Lock()
        data = getattr(radio, "data_dir", None)
        # The callsign list, by name: the worker is a process of its own and
        # re-reads the file when it changes, so a list fetched after the
        # start (fetch_scp) is used within a minute.
        self.scp_path = Path(data) / SCP_FILE if data else None
        self.runner = SkimRunner(self._result, mode=mode, max_channels=int(s["cwSkimMax"]),
                                 squelch_db=float(s["cwSkimSquelch"]), pitch=float(s["cwPitch"]),
                                 country=("ohscore.dxcc:skim_lookup", [str(data) if data else None]),
                                 history=("shack_cw.skim.scp:history", [[str(self.scp_path)]])
                                 if self.scp_path else None,
                                 engine=ENGINE)
        self.ch: Channel | None = None
        self.ch_d = 0
        self.gen = 0
        self.geo_key = None
        self.seg_key = None
        self.seg = None
        self.where: dict = {}               # band, segment, cover: for the items
        self.state, self.why = "off", ""
        self.spots: dict[int, dict] = {}    # id -> the newest of each spot
        self.pending: dict[int, dict] = {}  # spots waiting for their turn on the feed
        self.allow = SPOTS_PER_S
        self.allow_t = time.monotonic()
        self.rev = 0
        self.last_snap: dict = {}
        self.stopped = False
        self.idle_t = 0.0

    # ------------------------------------------------------------ lifecycle
    def start(self) -> None:
        """Start the worker on a thread of its own: a spawned process takes
        a moment to start, and this is called from the receive thread.

        A child process that cannot start at all (a frozen build missing
        its multiprocessing support, a sandbox that forbids it) leaves the
        skimmer in a thread instead (CW-SKIMMER-PLAN §2.4): it then shares
        the GIL with receive, which costs smoothness, not correctness, and
        the log and a toast say so. --cw-skim-selftest is what proves the
        process starts in each frozen build."""
        def go():
            try:
                self.runner.start()
            except Exception as e:  # noqa: BLE001 - whatever spawn raised: fall back, and say why
                log.warning("CW skimmer: no worker process (%s); running it in a thread", e)
                self.runner = _thread_runner(self.runner, self._result)
                self.runner.start()
                self.radio.toast(_("The CW skimmer is running in a thread: its worker process could not "
                                   "start ({why}).").format(why=e), "warn")
            if self.stopped:
                self.runner.stop()
                return
            self.fetch_scp()
        threading.Thread(target=go, name=f"{self.radio.THREAD_PREFIX}-cwskim-start", daemon=True).start()
        self._set_state("running", "")

    def fetch_scp(self) -> str:
        """Bring MASTER.SCP up to date if `cwSkimScp` allows (at most once a
        day; see the module). On the start thread, never the receive one; a
        failure costs only the list, and is logged."""
        if self.scp_path is None or not self.radio.st.get("cwSkimScp", False):
            return "off"
        from shack_cw.skim import scp
        version = self.radio.app_version() or "dev"
        try:
            got = scp.fetch(self.scp_path, f"OpenHamShack-Radio/{version}")
        except (OSError, ValueError) as e:
            log.warning("CW skimmer: MASTER.SCP not fetched (%s); the bundled RBN list stands alone", e)
            return "failed"
        if got == "fetched":
            log.info("CW skimmer: MASTER.SCP fetched into %s", self.scp_path)
        return got

    def stop(self) -> None:
        self.stopped = True
        self.runner.stop()
        self.ch = None
        self.state, self.why = "off", ""
        self.radio._status(cwSkimState="off", cwSkimWhy="", cwSkimSignals=0, cwSkimChannels=0, cwSkimCpu=0.0)
        self.radio._publish("cwskim", dict(off_item(), t=time.time(), spotsRev=self.rev))

    def configure(self, s: dict) -> None:
        self.runner.configure(max_channels=int(s["cwSkimMax"]), squelch_db=float(s["cwSkimSquelch"]),
                              pitch=float(s["cwPitch"]))

    # ------------------------------------------------------- the receive thread
    def feed(self, X, starts) -> None:
        r = self.radio
        if self.runner.state not in ("running",):
            return
        dial = r._rx_dial(r.st)
        b = bands.band_at(dial)
        key = (r.st.get("planInUse"), b.name if b is not None else None)
        if key != self.seg_key:
            self.seg_key = key
            self.seg = segment(r._plan(), dial) if b is not None else None
        span_lo, span_hi = r.wide_span()
        if self.seg is None:
            self._set_state("outside", _("There is no CW segment in the band plan here."))
            self._idle_item()
            return
        lo, hi, band = self.seg
        clo, chi = max(lo, span_lo + MARGIN_HZ), min(hi, span_hi - MARGIN_HZ)
        self.where = {"band": band, "segment": {"lo": lo, "hi": hi, "plan": r.st.get("planInUse", "")},
                      "cover": {"lo": clo, "hi": chi} if chi > clo else None}
        if chi - clo < 1_000.0:
            self._set_state("outside", _("The CW segment, {lo:.3f}-{hi:.3f} MHz, is outside what the receiver "
                                         "covers now, {slo:.3f}-{shi:.3f} MHz.").format(
                lo=lo / 1e6, hi=hi / 1e6, slo=span_lo / 1e6, shi=span_hi / 1e6))
            self._idle_item()
            return
        g = r.geo
        d = g.decimation_for((chi - clo + 2 * GUARD_HZ) / 0.84)
        rate = g.fs / d
        mid = 0.5 * (clo + chi)
        gk = (r.centre, id(r.rx_conv), clo, chi, band, d)
        if gk != self.geo_key:
            # A new centre, converter, band or cover: the worker's tracks
            # start again (its spots are kept).
            self.geo_key = gk
            self.gen += 1
        if self.ch is None or self.ch_d != d:
            self.ch = Channel(g, d, cutoff=0.42 * rate)
            self.ch_d = d
        self.ch.set_freq(r._off(mid))
        y = self.ch.take(X, starts)
        if not len(y):
            return
        partial = clo > lo + 1.0 or chi < hi - 1.0
        self._set_state("partial" if partial else "running", "")
        # The receiver's own DC, if it falls in the segment (10 m, the HL2):
        # a notch round it is never offered a decoder.
        dc = r.centre if lo <= r.centre <= hi else None
        if not self.runner.put(y, t=time.time() - len(y) / rate, centre=mid, rate=rate, lo=clo, hi=chi,
                               band=band, generation=self.gen, dc=dc):
            r._status(cwSkimDropped=self.runner.dropped)

    def _idle_item(self) -> None:
        """Outside, the worker hears nothing and sends nothing, so the item
        that says so is sent from here, once a second like the worker's."""
        now = time.monotonic()
        if now - self.idle_t >= 1.0:
            self.idle_t = now
            self.last_snap = {"channels": [], "carriers": []}
            self.radio._publish("cwskim", self._item(self.last_snap))

    def _set_state(self, state: str, why: str) -> None:
        if (state, why) == (self.state, self.why):
            return
        if self.state == "error" and self.runner.state == "error":
            return              # the worker's own error stands until it is back
        self.state, self.why = state, why
        self.radio._status(cwSkimState=state, cwSkimWhy=why)

    # --------------------------------------------------- results (drain thread)
    def _item(self, snap: dict) -> dict:
        item = dict(off_item(), **self.where, **snap)
        item.update(t=time.time(), state=self.state, spotsRev=self.rev)
        if self.why:
            item["why"] = self.why
        if self.state == "outside":
            item["channels"] = []
        return item

    def _result(self, kind: str, payload) -> None:
        r = self.radio
        if kind == "snapshot":
            snap = {k: payload[k] for k in ("channels", "carriers") if k in payload}
            if self.state == "outside":
                return          # the worker's last picture, of a segment no longer in view
            self.last_snap = snap
            if self.state != "off":
                r._publish("cwskim", self._item(snap))
            self._send_spots()
        elif kind == "spots":
            with self.lock:
                for sp in payload:
                    sp = {k: v for k, v in sp.items() if k != "rev"}
                    self.pending[sp["id"]] = sp
            self._send_spots()
        elif kind == "status":
            state = payload.get("state")
            if state == "error":
                self.state, self.why = "error", payload.get("why") or _("The CW skimmer stopped.")
                r._status(cwSkimState="error", cwSkimWhy=self.why)
            elif state == "running" and self.state == "error":
                self.state, self.why = "running", ""
                r._status(cwSkimState="running", cwSkimWhy="")
            r._status(cwSkimSignals=int(payload.get("signals", 0)),
                      cwSkimChannels=int(payload.get("channels", 0)),
                      cwSkimCpu=float(payload.get("cpu", 0.0)), cwSkimDropped=int(payload.get("dropped", 0)))
        elif kind == "warning":
            log.warning("CW skimmer: %s", payload)

    def _send_spots(self) -> None:
        now = time.monotonic()
        out = []
        with self.lock:
            self.allow = min(SPOTS_PER_S, self.allow + (now - self.allow_t) * SPOTS_PER_S)
            self.allow_t = now
            for sid in list(self.pending):
                if self.allow < 1.0:
                    break
                sp = self.pending.pop(sid)
                self.spots[sid] = sp
                self.allow -= 1.0
                self.rev += 1
                out.append({"t": time.time(), "rev": self.rev, "spot": sp})
            self._prune()
        for item in out:
            self.radio._publish("cwspot", item)

    def _prune(self) -> None:
        t = time.time()
        for sid in [k for k, v in self.spots.items() if t - float(v.get("last") or 0) > KEEP_S]:
            del self.spots[sid]
        if len(self.spots) > KEEP_N:
            old = sorted(self.spots.items(), key=lambda kv: kv[1].get("last") or 0)[:len(self.spots) - KEEP_N]
            for sid, _v in old:
                del self.spots[sid]

    # --------------------------------------------------------------- api/cwskim
    def view(self) -> dict:
        """GET api/cwskim: the cwskim item and every spot of the last 30
        minutes, newest first."""
        with self.lock:
            spots = sorted(self.spots.values(), key=lambda v: -(v.get("last") or 0))[:KEEP_N]
        item = self._item(dict(self.last_snap) if self.state != "off" else {})
        item.pop("t", None)
        item["spots"] = spots
        return item
