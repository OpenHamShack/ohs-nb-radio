#!/usr/bin/env python3
"""Beacon lock through playback: a cross-check against today's lock
(ohsnb/dsp/lock.py), run through the real headless engine rather than fed
directly.

    tools/playback_lock_report.py <file.sigmf-meta|-data> [--out DIR]

ohsnb/analyse.py's own beacon section (_run_beacon_tracker) feeds
ohsnb.dsp.lock.BeaconTracker the recording directly - a faithful, but
simplified, stand-in for what the radio does: no hardware re-centring
(Radio._rx_done's RECENTRE_HZ), no operator-visible rxLock state, no
supervisor thread. This instead plays the recording through
ohsnb.radio.Radio end to end (Engine.start_playback, realtime=False) -
the production code path, re-centring and all - as a second measurement
of the same recording to check the two agree. Receive-only throughout:
nothing here ever keys, and playback refuses to in any case
(ohscore/devices/filedev.py's own tx_refusal).

Writes report.json, report.txt and (with matplotlib) lock.png to --out
(default: a folder named after the recording, beside it, with
"-playback-lock" appended): locked percentage, every lock/loss
transition (its approximate position in the recording and its rxCorr),
and the rxCorr track over the whole file.

A fresh, throwaway data directory is used (Radio(persist=False,
data_dir=...)), so this never touches the operator's own config or
recordings - the same thing tools/settings-ref.py does for the same
reason, by a different route (that one goes through ohsnb.config.load(),
so it redirects OHSNB_CONF/OHSNB_DATA; this one builds a Radio directly, so
the throwaway folder is just a constructor argument).

Position (where in the recording a lock report happened) is read from the
engine's own playPos (Engine._play_tick, on the supervisor thread, which
ticks every 0.1 *wall-clock* seconds regardless of how fast realtime=False
plays): a three-hour file plays in minutes, so position is necessarily
sampled coarser than the lock reports themselves (BeaconTracker.UPDATE=
0.5 s) - fine for "where in three hours this happened", not a
frame-accurate log. Locked/total percentages are counted from the reports
themselves (BeaconTracker.UPDATE per report, the same convention
ohsnb.analyse._beacon_summary uses), independent of that approximation.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))   # tools/*.py's own convention

from ohscore.audio import NullAudio
from ohscore import sigmf
from ohsnb import state
from ohsnb.dsp.lock import BeaconTracker
from ohsnb.radio import Radio

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAVE_MPL = True
except ImportError:
    HAVE_MPL = False

POLL_S = 0.02        # how often this script itself drains feeds and heartbeats the engine
TIMEOUT_S = 3600.0 * 4   # long enough for a multi-hour file played non-realtime; a stuck run must still end


def _cfg() -> dict:
    cfg = state.defaults(("setting", "control"))
    cfg.update(device="sim", audioBackend="null", persist=False)
    return cfg


def run_playback(path: Path) -> dict:
    """Play `path` through a throwaway headless Radio and return
    {"locked_pct", "total_seconds", "locked_seconds", "transitions":
    [{"pos_s","from","to","rxCorr"}], "track": [{"pos_s","rxCorr","snr",
    "state"}], "final_rx_corr", "dropped"}."""
    with tempfile.TemporaryDirectory(prefix="ohsnb-playback-lock-") as tmp:
        radio = Radio(_cfg(), persist=False, data_dir=tmp, audio=NullAudio(realtime=False))
        feed = radio.subscribe("lock", 20_000)
        radio.start()
        try:
            radio.start_playback(str(path), realtime=False)
            track: list[dict] = []
            transitions: list[dict] = []
            last_state = None
            locked_reports = 0
            total_reports = 0
            t0 = time.monotonic()
            while True:
                radio.heartbeat()
                pos_s = radio.state().get("playPos", 0.0)
                for m in feed.drain():
                    if m.get("kind") != "rx":
                        continue
                    st = m.get("state")
                    corr = m.get("rxCorr")
                    total_reports += 1
                    if st == "locked":
                        locked_reports += 1
                    if st != last_state and st is not None:
                        transitions.append({"pos_s": pos_s, "from": last_state, "to": st,
                                           "rxCorr": round(corr, 1) if corr is not None else None})
                        last_state = st
                    track.append({"pos_s": pos_s, "rxCorr": round(corr, 1) if corr is not None else None,
                                 "snr": m.get("snr"), "state": st})
                if radio.state().get("playEnded"):
                    break
                if time.monotonic() - t0 > TIMEOUT_S:
                    raise TimeoutError(f"playback did not finish within {TIMEOUT_S:.0f} s")
                time.sleep(POLL_S)
            final_corr = next((t_["rxCorr"] for t_ in reversed(track) if t_["rxCorr"] is not None), None)
            return {
                "locked_pct": round(100.0 * locked_reports / total_reports, 1) if total_reports else None,
                "locked_seconds": round(locked_reports * BeaconTracker.UPDATE, 1),
                "total_seconds": round(total_reports * BeaconTracker.UPDATE, 1),
                "transitions": transitions,
                "track": track,
                "final_rx_corr": final_corr,
                "dropped": feed.dropped,
            }
        finally:
            radio.stop()


def _report_text(r: dict, path: Path) -> str:
    lines = [f"Beacon lock through playback: {path.name}",
            f"Locked {r['locked_pct']}% of {r['total_seconds']:.0f} s of lock reports "
            f"({r['locked_seconds']:.0f} s locked)" if r["locked_pct"] is not None else
            "No lock reports were seen at all",
            f"Final rxCorr: {r['final_rx_corr']:+.1f} Hz" if r["final_rx_corr"] is not None else
            "Final rxCorr: unknown",
            f"Transitions: {len(r['transitions'])}"]
    for t in r["transitions"][:40]:
        frm = t["from"] or "(start)"
        lines.append(f"  {t['pos_s']:7.1f} s: {frm} -> {t['to']}" +
                    (f" (rxCorr {t['rxCorr']:+.1f} Hz)" if t["rxCorr"] is not None else ""))
    if len(r["transitions"]) > 40:
        lines.append(f"  ... and {len(r['transitions']) - 40} more (see report.json)")
    if r["dropped"]:
        lines.append(f"! {r['dropped']} lock reports were dropped (this script's own feed overflowed)")
    return "\n".join(lines) + "\n"


def _save_plot(out_dir: Path, r: dict) -> list[str]:
    if not HAVE_MPL or not r["track"]:
        return []
    pos = [t["pos_s"] for t in r["track"]]
    corr = [t["rxCorr"] for t in r["track"]]
    locked = [t["state"] == "locked" for t in r["track"]]
    fig, ax = plt.subplots(figsize=(9, 4))
    lx = [p for p, l in zip(pos, locked) if l]
    ly = [c for c, l in zip(corr, locked) if l]
    ux = [p for p, l in zip(pos, locked) if not l]
    uy = [c for c, l in zip(corr, locked) if not l]
    ax.plot(lx, ly, ".", markersize=2, color="tab:blue", label="locked")
    ax.plot(ux, uy, ".", markersize=2, color="tab:red", label="not locked")
    ax.set_xlabel("seconds into the recording (approximate)"); ax.set_ylabel("rxCorr (Hz)")
    ax.set_title("Beacon lock through playback"); ax.legend()
    fig.tight_layout(); fig.savefig(out_dir / "lock.png", dpi=110); plt.close(fig)
    return ["lock.png"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file", help="a .sigmf-meta or .sigmf-data path (either names the pair)")
    ap.add_argument("--out", type=Path, default=None, help="folder for the report (default: beside the recording)")
    a = ap.parse_args(argv)
    path = Path(a.file)
    data_path, _meta_path = sigmf.paths(path)
    out_dir = a.out or path.parent / f"{data_path.stem}-playback-lock"
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        r = run_playback(path)
    except (ValueError, OSError, TimeoutError) as e:
        print(f"Could not play {path}: {e}", file=sys.stderr)
        return 1
    plots = _save_plot(out_dir, r)
    (out_dir / "report.json").write_text(json.dumps(r, indent=2) + "\n", encoding="utf-8")
    text = _report_text(r, path)
    (out_dir / "report.txt").write_text(text, encoding="utf-8")
    print(text, end="")
    if plots:
        print(f"Plots: {', '.join(plots)}")
    print(f"(full report: {out_dir}/report.txt, report.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
