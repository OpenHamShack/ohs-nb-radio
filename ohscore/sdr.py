"""shack_sdr, as both apps reach it: the decoder host and the Rust decoders
(RADIO-SDR-PLAN §4), the runtime codec loader (§5) and the receive-only
RTL-SDR and SDRplay sources (§6), from ohs-libs' shack-sdr wheel.

One place imports it, so one place says what happens without it. The wheel
is native - one per platform, pinned in tools/vendor/shack-sdr.lock - and a
package built for no platform in particular (the .deb's "all") carries none.
Everything that needs it asks `load()` and, given None, offers the feature
greyed with `why()`, as every optional piece of this program does: RTTY in
the mode list, the Decoders view, the two receivers in Settings › Radio.

**The codec loader is configured here, before anything asks it a
question.** Its search starts in the app's codecs folder, and its first
look at a new file runs a probe in a child process (codecs.py in
shack_sdr). In a frozen build `python -m shack_sdr.codecs` is not a
command - sys.executable is the app itself - so the probe is the app run
with `--codec-probe <id> <path>` (main_probe(), wired into each app's
__main__), and the loader must know that before FreeDV's import-time look
for codec2, or it would start the app's own window as its "probe".
"""
from __future__ import annotations

import logging
import sys
import threading
from pathlib import Path

from . import host
from .i18n.text import _

log = logging.getLogger("ohscore.sdr")

# PSK31/63/125 receive through shack_sdr's Rust `psk` decoder (Radio's SDR
# milestone 2): the PSK modes' decoder (modes/sdrmode.py PskDecoder, with
# several stations at once through pskChannels), `psk` sessions in the
# Decoders view and on api/decoders, and the zoom's click-to-add-a-station.
# On since the wheels with ohs-libs' fix (the over's last character when
# no idle follows it, and a carrier step mid-over when TX lock steps our
# own echo: test_tx_drain and test_playback's own-echo check) were
# vendored for beta.7. Off puts the PSK modes back on psk.py's Python
# decoder, as before milestone 2 (store beta.6 shipped that way, Brian,
# 23/10/2026): kept as the one switch should the Rust decoder need
# parking again, and the "as shipped" tests still check that path then.
PSK_ON_SHACK_SDR = True

_lock = threading.Lock()
_mod = None
_why = ""
_tried = False
_configured = False


def load():
    """The shack_sdr package, or None when this installation has none."""
    global _mod, _why, _tried
    with _lock:
        if _tried:
            return _mod
        _tried = True
        try:
            from . import shacklibs
            _mod = shacklibs.sdr()
        except ImportError as e:
            _mod = None
            _why = str(e)
            log.warning("shack_sdr is not available: %s", e)
        return _mod


def available() -> bool:
    return load() is not None


def why() -> str:
    """The sentence for anything that needs shack_sdr and cannot have it."""
    if load() is not None:
        return ""
    return _("this installation has no decoder library for this computer (shack-sdr); install the package "
             "built for your computer's processor")


def probe_argv() -> list[str] | None:
    """How the codec loader starts its probe child: None (its own
    `python -m shack_sdr.codecs`) from source and in the .deb; the app
    itself with --codec-probe when frozen."""
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable)
        # A Windows GUI program has no stdout to answer on, so the probe is
        # the console twin every Windows build has beside it.
        console = exe.with_name(exe.stem + "-console" + exe.suffix)
        if sys.platform == "win32" and console.is_file():
            exe = console
        return [str(exe), "--codec-probe"]
    return None


def configure(app: str, data_dir: Path | None, data_from_env: bool) -> None:
    """Point the codec loader at this app's folders. `data_dir` is the
    app's data folder; its codecs/ is the codecs folder only when the
    operator chose the data folder ($<APP>_DATA, a test's scratch home):
    otherwise the folder is the one RADIO-SDR-PLAN §5.2 names for each OS,
    which shack_sdr knows. Safe to call again (each engine does)."""
    global _configured
    m = load()
    if m is None:
        return
    folder = Path(data_dir) / "codecs" if (data_from_env and data_dir) else None
    cache = (Path(data_dir) / "codecs-probed.json") if data_dir else None
    m.codecs.configure(folder, app=app, bundle_dirs=[str(d) for d in host._bundle_dirs()], cache_path=cache,
                       probe_argv=probe_argv())
    _configured = True


def codecs():
    """shack_sdr.codecs, configured (with defaults if no engine has yet),
    or None."""
    m = load()
    if m is None:
        return None
    global _configured
    with _lock:
        if not _configured:
            m.codecs.configure(app="openhamshack-radio", bundle_dirs=[str(d) for d in host._bundle_dirs()],
                               probe_argv=probe_argv())
            _configured = True
    return m.codecs


def codec_path(codec: str) -> str | None:
    """A library for `codec` that passed the loader's probe, or None."""
    c = codecs()
    if c is None:
        return None
    try:
        return c.path(codec)
    except Exception:  # noqa: BLE001 - a loader that fails costs that codec, never the program
        log.warning("the codec loader failed looking for %s", codec, exc_info=True)
        return None


def main_probe(argv: list[str]) -> int:
    """`<app> --codec-probe <id> <path>`: the codec loader's child, in a
    frozen build (see the module docstring)."""
    m = load()
    if m is None:
        print('{"ok": false, "why": "crashed", "detail": "no shack_sdr"}', flush=True)
        return 1
    return int(m.codecs.main(["probe", *argv]) or 0)
