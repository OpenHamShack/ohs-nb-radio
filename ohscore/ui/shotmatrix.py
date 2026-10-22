"""The screenshot matrix both apps' screenshot tools share.

    python3 -m ohsnb.ui.screenshots OUT --matrix modes=usb,ft8,q65,js8,sstv
        sizes=1920x1080,1366x768,1280x720,1024x600 scales=1,1.3 themes=dark,light
        [--workspace watch] [--receive-only] [--locale en-XA]

writes OUT/m-<mode>-<W>x<H>-<scale>-<theme>[-<workspace>].png for every
combination: the real window on the simulator, as the docs' screenshots
are made. It is how each package of the October 2026 UI overhaul checks
its work (docs/ui-overhaul-2026-10.md, "Rules for every package"), so the
pictures one package looked at are the ones the next can make again.
Every list may be shortened; each defaults to the whole of it.

A fresh window for each mode, theme and text size, as the app starts
with them: it waits long enough for the mode's decodes (two periods of a
slot mode, Q65's 60 s ones included) and the waterfall, then shrinks
through the sizes, largest first. The whole default matrix takes about
twenty minutes; shorten the lists to check one thing. A size below the window's minimum is held at the
minimum by Qt; the file keeps the size asked for and the run says so.
Nothing is written to docs/screenshots unless OUT says so.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..config import RECEIVE_ONLY
from ..modegroups import slot_spec

ALL_MODES = ("usb", "ft8", "q65", "js8", "sstv")
ALL_SIZES = ((1920, 1080), (1366, 768), (1280, 720), (1024, 600))
ALL_SCALES = ("1", "1.3")
ALL_THEMES = ("dark", "light")
# Periods of the modes that are not slot modes in ohscore/modegroups.py yet
# (Q65 and JS8 until their panels exist), so the wait is right before then.
PERIODS = {"q65": 60.0, "js8": 15.0}


@dataclass
class Matrix:
    modes: tuple = ALL_MODES
    sizes: tuple = ALL_SIZES
    scales: tuple = ALL_SCALES
    themes: tuple = ALL_THEMES
    workspace: str = ""
    receive_only: bool = False
    locale: str = ""
    skipped: list = field(default_factory=list)


def parse(argv: list[str]) -> tuple[Matrix | None, list[str]]:
    """(the matrix asked for, or None without --matrix; argv without the
    matrix's own words)."""
    if "--matrix" not in argv:
        return None, list(argv)
    m, rest = Matrix(), []
    it = iter(argv)
    for a in it:
        if a == "--matrix":
            continue
        if a == "--receive-only":
            m.receive_only = True
        elif a in ("--workspace", "--locale"):
            v = next(it, "")
            if not v or v.startswith("--"):
                raise SystemExit(f"{a} needs a value")
            setattr(m, a[2:], v)
        elif "=" in a and a.split("=", 1)[0] in ("modes", "sizes", "scales", "themes"):
            k, v = a.split("=", 1)
            items = tuple(x for x in v.split(",") if x)
            if k == "sizes":
                try:
                    items = tuple(tuple(int(n) for n in x.lower().split("x")) for x in items)
                except ValueError:
                    raise SystemExit(f"sizes are WxH, e.g. 1366x768: {v}") from None
            if k == "scales":
                for x in items:
                    float(x)
            if k == "themes" and set(items) - set(ALL_THEMES):
                raise SystemExit(f"themes are dark and light: {v}")
            setattr(m, k, items)
        else:
            rest.append(a)
    return m, rest


def settle_seconds(mode: str) -> float:
    """How long a fresh window needs before its pictures say something: two
    whole periods of a slot mode (the first is usually caught half-way), or
    long enough for the wide waterfall to fill (about 20 s on a busy
    machine; 14 s left the foot of it black)."""
    spec = slot_spec(mode)
    period = spec.period if spec else PERIODS.get(mode)
    return 2 * period + 5.0 if period else 25.0


def filename(mode: str, size: tuple[int, int], scale: str, theme_name: str, workspace: str = "") -> str:
    return f"m-{mode}-{size[0]}x{size[1]}-{scale}-{theme_name}{'-' + workspace if workspace else ''}.png"


def run(m: Matrix, out, app_modes, open_window, wait, close) -> list:
    """Render the matrix into `out`. `open_window(theme_name, scale, **cfg)`
    makes the app's window on the simulator at a voice dial, in that theme
    and text size, and returns (win, bridge, radio, prefs); `wait(s)` runs
    the event loop for s seconds; `close(win, bridge)` ends it. Returns the
    files written."""
    written = []
    extra = {RECEIVE_ONLY: True} if m.receive_only else {}
    # Largest first, so the window only ever shrinks: a waterfall made
    # taller keeps the rows it had and leaves the rest black until new
    # lines fill it, while one made shorter just drops its oldest.
    sizes = sorted(m.sizes, key=lambda wh: wh[0] * wh[1], reverse=True)
    for mode in m.modes:
        if mode not in app_modes:
            print(f"skipped {mode}: not one of this app's modes", flush=True)
            m.skipped.append(mode)
            continue
        for theme_name in m.themes:
            for scale in m.scales:
                # A fresh window for each theme and text size, as the app
                # starts with them, rather than the rebuild Settings makes:
                # that carries the wide waterfall over only partly filled
                # (half of it black at 1920 x 1080 on ohs-dev, 17/10/2026).
                win, bridge, radio, prefs = open_window(theme_name, float(scale), **extra)
                if m.workspace:
                    # Pinned as W or the Workspace menu would pin it (and
                    # kept in ui.json); the file name says which.
                    win.choose_workspace(m.workspace)
                if bridge.st.get("mode") != mode:
                    bridge.set_mode_tuned(mode)
                win.resize(*sizes[0])
                wait(settle_seconds(mode))
                for size in sizes:
                    win.resize(*size)
                    wait(1.0)
                    got = (win.width(), win.height())
                    if got != tuple(size):
                        print(f"note: asked for {size[0]}x{size[1]}, the window is {got[0]}x{got[1]} "
                              "(its minimum)", flush=True)
                    p = out / filename(mode, size, scale, theme_name, m.workspace)
                    win.grab().save(str(p))
                    written.append(p)
                    print("wrote", p, flush=True)
                close(win, bridge)
    return written
