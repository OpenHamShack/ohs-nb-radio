"""OpenHamShack Radio's first-run steps and About box: the shared dialogs
(ohscore/ui/welcome.py) with what HAM says - the licence it enforces (and
the class it asks for on the licence step), the Pluto's harmonics, and
the band simulator."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from ohscore.ui import welcome as core

from .face import HamFace

# The class question, as whole sentences (they will be translated whole).
CLASS_CAP = QT_TRANSLATE_NOOP(
    "Welcome",
    "Your licence class - none is chosen for you: until you pick one, OpenHamShack Radio receives but will not "
    "transmit.")
NO_LICENCE_YET = QT_TRANSLATE_NOOP(
    "Welcome",
    "No licence for {country} is written into OpenHamShack yet, so there is no class to pick here. OpenHamShack "
    "Radio will receive; to transmit, choose a licence or enter your own in Settings › Licence & plan.")
NO_CALL_YET = core.NO_CALL_YET


def class_choices(call: str, override: str = "") -> tuple[list[tuple[str, str]], str]:
    """Radio's classes for this callsign (ohscore/ui/welcome.py
    class_choices, with Radio's sentence for a country with none)."""
    return core.class_choices(call, override, NO_LICENCE_YET)


def version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    except OSError:
        return ""


class Welcome(core.Welcome):
    TAGLINE = QT_TRANSLATE_NOOP("Welcome", "An all-band amateur transceiver")
    RULES = QT_TRANSLATE_NOOP(
        "Welcome",
        "<ul style='margin-left:-18px; line-height:150%'>"
        "<li>OpenHamShack Radio holds every transmission inside <b>what your licence class allows</b>. Power is "
        "advisory until measured: it warns when the power chain you enter in Settings estimates more than "
        "your class's limit, and unkeys when a radio that measures its output goes over it.</li>"
        "<li>It warns when you leave what the <b>band plan</b> of your country (or IARU region) intends, and "
        "never transmits on the beacon or satellite sub-bands.</li>"
        "<li>A Pluto has <b>no output filter</b>: check its output into a dummy load on a spectrum analyser "
        "before it drives any PA, and never connect it straight to an antenna.</li>"
        "<li>Space or the TX button keys; <b>Esc always stops</b>. A time-out and a watchdog stop it too.</li>"
        "</ul>")
    ACK = QT_TRANSLATE_NOOP("Welcome", "I understand, and I hold an amateur licence of the class I have chosen above.")
    RADIO_TEXT = QT_TRANSLATE_NOOP(
        "Welcome",
        "Start with the simulator to learn the controls on busy simulated bands - no radio needed. "
        "You can switch in Settings at any time.")
    DEVICES = (("sim", "waves", QT_TRANSLATE_NOOP("Welcome", "Simulator"),
                QT_TRANSLATE_NOOP("Welcome", "Simulated bands, 160 m to 6 cm: SSB, CW, FT8, FM repeaters.")),
               ("pluto", "antenna", QT_TRANSLATE_NOOP("Welcome", "ADALM-Pluto family"),
                QT_TRANSLATE_NOOP("Welcome", "2 m to 6 cm (Pluto, Pluto+, LibreSDR, nano).")),
               ("hl2", "antenna", QT_TRANSLATE_NOOP("Welcome", "Hermes-Lite 2"),
                QT_TRANSLATE_NOOP("Welcome", "160 m to 10 m over Ethernet.")))

    # On the licence step, above the box that names it ("the class I have
    # chosen above"), which may not be ticked with none chosen.
    CLASS_PAGE = 1
    CLASS_CAP = CLASS_CAP
    NO_LICENCE_YET = NO_LICENCE_YET
    ACK_NEEDS_CLASS = True


class About(core.About):
    def __init__(self, parent=None):
        super().__init__(HamFace(), version(),
                         QCoreApplication.translate(
                             "About", "An all-amateur-bands transceiver: SSB, CW, AM, FM with CTCSS and repeaters, "
                                      "FT8/FT4, PSK, RTTY, FreeDV and SSTV, holding every transmission to the licence "
                                      "of the country it is in."), parent)
