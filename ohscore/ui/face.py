"""What the shared widgets ask the app: its "face".

The scope, the frequency readout, the logbook and memories views and the
voice panel are the same widgets in QO-100 NB and OpenHamShack Radio, but what
they say about frequencies is not: NB shows a QO-100 downlink with the
transponder's bandplan strip, its beacons and the uplink beneath the
readout; HAM will show an on-air frequency with a terrestrial band plan,
the TX frequency or a transverter IF beneath it. Each app gives its Bridge
one Face (Bridge(radio, face=...)), and every widget that needs one of
these answers asks `bridge.face` - one object rather than a provider per
widget, because the answers belong together: the band the scope draws is
the band the readout parses and the logbook labels.

A method here with no sensible app-neutral answer raises
NotImplementedError rather than guessing one.
"""
from __future__ import annotations


class Face:
    # ------------------------------------------------------------- identity
    app_name = ""                     # window titles: "OpenHamShack QO-100 NB"
    # The name the app had before the family became OpenHamShack (09/10/2026),
    # said once, in the About box only, so an operator who installed it as
    # "OpenHamShack NB" can tell this is the same program. Nowhere else: the rest
    # of the UI uses the new name alone.
    former_name = ""
    package = ""                      # "openhamshack-nb": the .deb, the launcher, its source-site section
    # Its signed update feed (ohscore/update.py, docs/update-feed.md); "" for none.
    update_feed = ""

    def icon(self):
        """The app's QIcon."""
        raise NotImplementedError

    # ---------------------------------------------------------------- words
    freq_label = "Frequency"          # log and memory column heading

    def text(self, topic: str) -> str:
        """An app's sentence about one of its rules, for the panel that
        shows it ('' to show nothing). Topics: "txWidth" (the transmit
        audio width rule), "am" (what AM is for), "licence" (what the
        operator acknowledges before anything will key)."""
        return ""

    # Whether the licence acknowledgement gates keying the simulator too.
    # OpenHamShack Radio's does (its guide says so); QO-100 NB's does not, because
    # its own Settings › Simulator promises it can be tried with no licence,
    # and the simulator never radiates (Device.radiates).
    sim_needs_licence = True

    # Whether the S-meter offers "dB vs beacon": a reference only a
    # satellite with a beacon has (NB's meter feed carries its level).
    smeter_beacon = False
    # The S-meter's unit until the operator picks one. NB overrides: on
    # QO-100 the beacon is the one reference every station shares.
    smeter_default_unit = "dbfs"

    # Transmit audio wider than this is drawn as refused (None: no limit).
    tx_width_limit: float | None = None

    # ------------------------------------------------------- the band plan
    wide_lo = 0.0                     # the wide scope's extent, Hz
    wide_hi = 0.0
    segments: tuple = ()              # (lo, hi, label, mode classes or None, max bandwidth)

    def segment_at(self, f: float) -> dict | None:
        """{lo, hi, label, tx, modes, maxBw} for the segment holding f."""
        return None

    def short_label(self, label: str) -> str:
        """A segment's label when its full one does not fit the strip."""
        return label.upper()

    def markers(self) -> list[tuple[str, float, str]]:
        """Fixed markers on the wide scope (NB: the beacons): (key, Hz, label)."""
        return []

    def mhz(self, f: float, places: int = 4) -> str:
        return f"{f / 1e6:.{places}f}"

    # ----------------------------------------------------------- the axis
    axis_unit = "kHz"                 # the caption at the axis's left end

    def axis_label(self, f: float, step: float) -> str:
        raise NotImplementedError

    # -------------------------------------------------------- the readout
    def readout_title(self) -> str:
        """Above the big digits."""
        raise NotImplementedError

    def digit_groups(self, hz: int) -> list[tuple[str, int | None, str]]:
        """The readout's digits as (text, place value of its first digit or
        None, kind) groups; kind is "dim", "bright", "small", "dot", "gap" or
        "gapS". A digit whose place is None does not tune by the wheel."""
        raise NotImplementedError

    def tunable_place(self, place: int) -> bool:
        """Whether the wheel over a digit of this place value (10**place Hz)
        tunes; steps that would leave the band are refused here."""
        return True

    def secondary(self, st: dict) -> tuple[str, str] | None:
        """The readout's second line: (caption, frequency text), or None."""
        return None

    # State keys, beyond the dials, whose change can alter that line (NB's
    # IC-9700 frequency): the readout repaints on them too.
    secondary_keys: tuple = ()

    def parse_freq(self, text: str) -> float:
        """A typed frequency -> dial Hz; ValueError with a sentence."""
        raise NotImplementedError

    freq_hint = ""                    # the readout's editor, empty: examples of what parse_freq takes

    # ---------------------------------------------------------- panels
    def panel(self, key: str, bridge, prefs, parent=None, big: bool = False):
        """The app's own mode panel for panel key `key` ("fm"), or None for
        the core's."""
        return None

    # ------------------------------------------------ the second display
    def big_freq(self, hz: int) -> str:
        """The dial as the second display writes it, large."""
        raise NotImplementedError

    # ------------------------------------------------------------ on the air
    # The state keys on_air() reads: a widget showing it repaints on these.
    on_air_keys: tuple = ("keyed", "txOnAir")

    def on_air(self, st: dict) -> bool:
        """Whether the transmitter is radiating now - what the red frame,
        ON AIR and the scopes' red TX band follow. Not `keyed`: that is
        true from the moment an over is queued, and an FT8 over is queued
        2.5 s into the slot before its own, so following it showed ON AIR
        through most of every receive slot while nothing was on the air
        (Ray, 12/10/2026). An app whose over goes out on another radio says
        what that radio reports instead (NB's IC-9700)."""
        return bool(st.get("keyed") and st.get("txOnAir"))

    def big_status(self, st: dict) -> tuple[str, str] | None:
        """(text, colour token) at the right of the second display's
        frequency bar while not transmitting, or None."""
        return None
