"""QO-100 NB's first-run steps and About box: the shared dialogs
(ohscore/ui/welcome.py) with what NB says - QO-100's rules (never stronger
than the beacon), the licence it asks for, the licence class beside the
callsign, and the transponder simulator."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import QT_TRANSLATE_NOOP, QCoreApplication

from ohscore.ui import welcome as core

from .face import Qo100Face


def version() -> str:
    try:
        return (Path(__file__).resolve().parents[1] / "VERSION").read_text().strip()
    except OSError:
        return ""


class Welcome(core.Welcome):
    TAGLINE = QT_TRANSLATE_NOOP("Welcome", "A QO-100 narrowband transceiver")
    RULES = QT_TRANSLATE_NOOP(
        "Welcome",
        "<ul style='margin-left:-18px; line-height:150%'>"
        "<li>Transmit only within the terms of <b>your amateur licence</b>.</li>"
        "<li><b>Never be stronger than the beacon.</b> The meter on the right of the main window shows your "
        "downlink against it, and OpenHamShack QO-100 NB trims your power to stay below it.</li>"
        "<li>Stay inside the bandplan: OpenHamShack QO-100 NB refuses to key on the beacons, outside the band, or in a "
        "segment that does not allow your mode.</li>"
        "<li>Space or the TX button keys; <b>Esc always stops</b>. A time-out and a watchdog stop it too.</li>"
        "</ul>")
    ACK = QT_TRANSLATE_NOOP("Welcome", "I understand, and I hold a licence that lets me transmit to QO-100.")
    ACK_NOTE = QT_TRANSLATE_NOOP(
        "Welcome",
        "Leave this unticked to listen only - a radio stays locked to receive until you tick it here or "
        "in Settings › Station. The simulator transmits either way: nothing it sends leaves this computer.")
    RADIO_TEXT = QT_TRANSLATE_NOOP(
        "Welcome",
        "Start with the simulator to learn the controls on a busy simulated band - no dish needed. "
        "You can switch in Settings at any time.")
    # The class beside the callsign, on the first step (decided 17/10/2026,
    # docs/ui-overhaul-2026-10.md 5.8). NB has asked for one in Settings
    # since 08/10/2026 but locks nothing without it (ohsnb/radio.py
    # NO_LICENCE_WARN: every earlier install had none); asking here is
    # what keeps the transmit card's "no licence class" reminder rare. The
    # sentences say so, rather than Radio's "will not transmit". The box
    # on the licence step does not name a class, so it may be ticked
    # without one.
    CLASS_PAGE = 0
    CLASS_CAP = QT_TRANSLATE_NOOP(
        "Welcome",
        "Your licence class - none is chosen for you. With it, OpenHamShack QO-100 NB checks the uplink "
        "against your licence; without it, the transmit card keeps a reminder that it cannot.")
    NO_LICENCE_YET = QT_TRANSLATE_NOOP(
        "Welcome",
        "No licence for {country} is written into OpenHamShack yet, so there is no class to pick here "
        "and the uplink is not checked against your licence. You can enter your own in Settings › "
        "Licence.")
    ACK_NEEDS_CLASS = False
    DEVICES = (("sim", "satellite", QT_TRANSLATE_NOOP("Welcome", "Simulator"),
                QT_TRANSLATE_NOOP("Welcome", "A simulated QO-100 downlink: beacons, stations, FT8, your own echo.")),
               ("pluto", "antenna", QT_TRANSLATE_NOOP("Welcome", "ADALM-Pluto family"),
                QT_TRANSLATE_NOOP("Welcome", "Pluto, Pluto+, LibreSDR, Pluto nano - receive and transmit.")),
               ("soapy", "waves", QT_TRANSLATE_NOOP("Welcome", "Receive-only SDR"),
                QT_TRANSLATE_NOOP("Welcome", "RTL-SDR, Airspy, SDRplay, HackRF via SoapySDR.")))


class About(core.About):
    def __init__(self, parent=None):
        super().__init__(Qo100Face(), version(),
                         QCoreApplication.translate(
                             "About", "A QO-100 narrowband transceiver: SSB, CW, FT8/FT4, PSK, RTTY, FreeDV and "
                                      "SSTV, with beacon lock and own-signal TX lock."), parent)
