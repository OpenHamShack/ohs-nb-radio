"""QO-100 NB's answers to the shared widgets (ohscore/ui/face.py): the
QO-100 narrowband transponder as the scope, the readout, the logbook and
the voice panel show it."""
from __future__ import annotations

import re

from ohscore import update
from ohscore.ui.face import Face
from ohsnb.i18n import _

from .. import bandplan

SHORT_SEG = {"lower beacon": "BCN", "CW only": "CW", "narrow digimodes (500 Hz max)": "NARROW DIGI",
             "digimodes (2.7 kHz max)": "DIGI", "SSB only": "SSB", "middle beacon": "BCN",
             "AMSAT-DL broadcast": "BC", "emergency (10489.860)": "EMG", "mixed modes, contests": "MIXED",
             "multimedia beacon": "MM", "upper beacon": "BCN"}
BEACON_SHORT = {"lower": "Lower beacon", "middle": "Middle beacon", "mm": "Multimedia", "upper": "Upper beacon"}


def khz_label(f: float, step: float) -> str:
    """Axis labels: kHz above 10489 MHz, as many decimals as the step needs."""
    k = (f - 10_489_000_000.0) / 1000.0
    if step >= 1000:
        return f"{k:.0f}"
    if step >= 100:
        return f"{k:.1f}"
    if step >= 10:
        return f"{k:.2f}"
    return f"{k:.3f}"


def parse_freq(text: str) -> float:
    """A typed frequency -> downlink Hz.

    Accepted: "10489.540" or "10489540000" (downlink MHz or Hz), "489.540"
    (MHz above 10 GHz), "540" or "540.25" (kHz above 10489 MHz - the band is
    only 500 kHz wide, so this is what operators say aloud), and uplink
    "2400.040" (MHz), which is converted. Spaces and a trailing unit are
    ignored. Raises ValueError with a sentence.
    """
    s = text.strip().lower().replace(" ", "").replace(",", ".")
    s = re.sub(r"(mhz|khz|hz|ghz)$", "", s)
    if s.count(".") > 1:           # 10489.540.000 -> 10489.540000
        head, _sep, tail = s.partition(".")
        s = head + "." + tail.replace(".", "")
    try:
        x = float(s)
    except ValueError:
        raise ValueError(_("{text} is not a frequency").format(text=repr(text))) from None
    if x >= 1e9:
        dl = x
    elif 10_000 <= x < 11_000:
        dl = x * 1e6
    elif 2_399 <= x < 2_401:
        dl = bandplan.dl(x * 1e6)
    elif 2_399e6 <= x < 2_401e6:
        dl = bandplan.dl(x)
    elif 480 <= x < 500:
        dl = 10_000e6 + x * 1e6
    elif 0 <= x < 1000:
        dl = 10_489e6 + x * 1e3
    else:
        raise ValueError(_("{text} is not a QO-100 narrowband frequency").format(text=repr(text)))
    if not (bandplan.DL_LO <= dl <= bandplan.DL_HI):
        raise ValueError(_("{mhz:.4f} MHz is outside the narrowband transponder ({lo}-{hi} MHz)").format(
            mhz=dl / 1e6, lo=bandplan.mhz(bandplan.DL_LO), hi=bandplan.mhz(bandplan.DL_HI)))
    return round(dl)


class Qo100Face(Face):
    app_name = "OpenHamShack QO-100 NB"
    former_name = "OpenHamShack NB"
    package = "openhamshack-nb"
    update_feed = "https://openhamshack.com/desktop/nb/update.json"
    update_feeds = update.with_mirrors(update_feed)
    # The app's name in a diagnostics upload (ohscore/diagupload.py), as in its feed's folder.
    diag_app = "nb"
    freq_label = "Downlink"
    freq_hint = "10489.540, 540.2 or 2400.040"
    tx_width_limit = 2700.0
    sim_needs_licence = False
    # On QO-100 the beacon is the level every station is judged by; the
    # S-meter can read against it (ohscore/ui/smeter.py), and by default says
    # so in S-units with the middle beacon at S9 (overhaul decision 10): an
    # operator who never chose a unit gets it, a stored choice is kept.
    smeter_beacon = True
    smeter_default_unit = "sbeacon"

    wide_lo = bandplan.DL_LO - 25_000.0
    wide_hi = bandplan.DL_HI + 25_000.0
    segments = bandplan.SEGMENTS
    axis_unit = "kHz +10489"

    _TEXT = {"txWidth": "QO-100 allows 2.7 kHz at most; OpenHamShack QO-100 NB refuses wider.",
             "am": "AM is receive-only here - for listening to the beacons. Use USB to talk.",
             "licence": "I hold an amateur licence that allows me to transmit to QO-100, I will transmit only "
                        "within its terms, and I will keep my downlink below the beacon."}

    def text(self, topic: str) -> str:
        return self._TEXT.get(topic, "")

    def segment_at(self, f: float) -> dict | None:
        return bandplan.segment_at(f)

    def short_label(self, label: str) -> str:
        return SHORT_SEG.get(label, label.upper())

    def markers(self) -> list[tuple[str, float, str]]:
        # A beacon is marked where beacon lock puts it: the F1A beacons at
        # their nominal (mark) frequency, the BPSK beacon at its carrier.
        return [(key, b["ref"] if b["kind"] != "f1a" else b["dl"], BEACON_SHORT.get(key, key))
                for key, b in bandplan.BEACONS.items()]

    def mhz(self, f: float, places: int = 4) -> str:
        return bandplan.mhz(f, places)

    def axis_label(self, f: float, step: float) -> str:
        return khz_label(f, step)

    def readout_title(self) -> str:
        return "Downlink · MHz"

    def digit_groups(self, hz: int) -> list[tuple[str, int | None, str]]:
        # "10 489.540 000": the "10" never changes and is dimmed; the Hz
        # group is smaller and quieter.
        s = f"{hz:011d}"
        mhz_part, khz_part, hz_part = s[:5], s[5:8], s[8:]
        return [(mhz_part[:2], 10, "dim"), (" ", None, "gap"), (mhz_part[2:], 8, "bright"), (".", None, "dot"),
                (khz_part, 5, "bright"), (" ", None, "gapS"), (hz_part, 2, "small")]

    def tunable_place(self, place: int) -> bool:
        return place <= 5          # 1 MHz steps would leave the 500 kHz band

    secondary_keys = ("rigFreq", "rigLink", "txRadio")

    def secondary(self, st: dict) -> tuple[str, str] | None:
        # With an IC-9700 as the transmitter, what Ray most needs under the
        # downlink is what his radio's own display should read.
        rig_f = float(st.get("rigFreq") or 0.0)
        if st.get("txRadio", "sdr") != "sdr" and rig_f and st.get("rigLink") == "ok":
            s = f"{int(round(rig_f)):010d}"
            return "9700", f"{s[:4].lstrip('0')}.{s[4:7]} {s[7:]}"
        vfo = float(st.get("vfo") or 0.0)
        txd = float(st.get("txDial") or vfo)
        us = f"{int(round(bandplan.ul(txd))):010d}"
        return "UP", f"{us[:4]}.{us[4:7]} {us[7:]}"

    on_air_keys = Face.on_air_keys + ("txRadio", "rigKeyed")

    def on_air(self, st: dict) -> bool:
        # With an IC-9700 transmitting, on the air is what the radio says
        # (rigKeyed, read back from it whoever keyed it) - the same answer
        # the transmit card's "TX (CAT)" / "USB RX" gives, which Ray saw
        # right while the frame and ON AIR said otherwise. The engine's
        # txOnAir is only NB having sent the CAT key, not the radio obeying.
        if st.get("txRadio", "sdr") != "sdr":
            return bool(st.get("rigKeyed"))
        return super().on_air(st)

    def parse_freq(self, text: str) -> float:
        return parse_freq(text)

    def icon(self):
        from .appicon import app_icon
        return app_icon()

    def big_freq(self, hz: int) -> str:
        s = f"{hz:011d}"
        return f"{s[:5]}.{s[5:8]} {s[8:]}"

    def big_status(self, st: dict) -> tuple[str, str] | None:
        # Beacon lock: the one thing worth reading from across the room.
        rl = st.get("rxLock", "off")
        return f"RX {rl.upper()}", {"locked": "ok", "searching": "warn", "lost": "err", "hold": "accent",
                                    "manual": "accent"}.get(rl, "text3")
