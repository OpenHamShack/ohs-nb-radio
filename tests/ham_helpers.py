"""Shared set-up for OpenHamShack HAM engine tests: a Radio on the band
simulator, faster than real time, with a throw-away data folder and no
sound card. Nothing here touches ~/.config: persist is off and data_dir
is a temporary directory."""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import tempfile
import time

from ohscore.audio import NullAudio
from ohsradio.radio import Radio


def speech(n):
    """Microphone stand-in: noise with a syllabic envelope, so dead air never trips."""
    import numpy as np
    t = np.arange(n) / 12000.0
    return (0.2 * (0.4 + 0.6 * np.abs(np.sin(2 * np.pi * 2.0 * t))) *
            np.random.default_rng().standard_normal(n)).astype("float32")


def make_radio(audio_source=None, **over):
    tmp = tempfile.TemporaryDirectory()
    # The licence class has no default (ohsradio/state.py); a test radio
    # picks Foundation explicitly, the most restrictive, so tests that key
    # exercise the guard rather than skip it. licenceClass="" gives the
    # unset class a fresh install starts with.
    cfg = {"device": "sim", "audioBackend": "null", "simRealtime": False, "simSeed": 7, "simHourUtc": 12.0,
           "callsign": "GM4BRI", "licenceClass": "foundation"}
    cfg.update(over)
    audio = NullAudio(realtime=False, source=audio_source) if audio_source else NullAudio(realtime=False)
    r = Radio(cfg, persist=False, data_dir=tmp.name, audio=audio)
    r._tmp = tmp
    return r


def pump(radio, seconds, until=None, feeds=()):
    """Heartbeat for up to `seconds` (the watchdog wants it), draining
    `feeds` into lists; stop early when until() is true."""
    got = {f.kind: [] for f in feeds}
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        radio.heartbeat()
        for f in feeds:
            got[f.kind] += f.drain()
        if until is not None and until():
            break
        time.sleep(0.02)
    return got


def close(radio):
    radio.stop()
    radio._tmp.cleanup()
