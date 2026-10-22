"""Every state key OpenHamShack Radio's engine has.

The registry machinery and the keys both apps share are ohscore/state.py
(which explains the setting/control/status kinds and the `auth` and
`restart` marks). This module gives the shared keys their terrestrial
ranges and wording and adds what a station on the amateur bands needs:
the licence and band plan, band stacks, transmit drive and the power
chain, FM and repeaters, the PTT sequencer, the Hermes-Lite 2, and the
band simulator's own settings (docs/ham/DESIGN-HAM.md sections 2.3, 5, 6).

Transmit power is `drive`, 0..1 of the device's full output amplitude,
not NB's Pluto gain in dB: "-10 dB" means nothing on an HL2 or on the far
side of a PA. The power chain (ohsradio/power.py) turns drive into watts.
"""
from __future__ import annotations

from ohscore import converters as cv
from ohscore.dsp.fm import TONES
from ohscore.state import Registry, add_shared_keys

from ohsradio.i18n import _

from . import bands, plans, power, xvtr

# JS8 joined 10/10/2026, receive only, once ohsdigi decoded it everywhere
# (ohscore/modes/js8.py): before, it needed JS8Call's js8, which the Radio
# store image could not carry.
MODES = ["usb", "lsb", "cw", "am", "fm", "ft8", "ft4", "js8", "psk31", "psk63", "psk125", "rtty", "freedv",
         "sstv"]
DIGITAL = {"ft8", "ft4", "js8", "psk31", "psk63", "psk125", "rtty", "freedv", "sstv"}
TONE_CHOICES = [0.0] + list(TONES)
HL2_RATES = [48_000, 96_000, 192_000, 384_000]

REG = Registry(MODES, DIGITAL)
add_shared_keys(REG)
_k = REG.add
_o = REG.override

# --- device -----------------------------------------------------------------
_o("device", choices=["sim", "pluto", "hl2", "soapy"],
   help="Which radio. The simulator (HF and VHF/UHF bands, busy with other stations) needs no hardware and is the "
        "default.")
_o("sampleRate", choices=[1_200_000, 2_400_000],
   help="Pluto sample rate. 1.2 MS/s suits a Raspberry Pi; 2.4 MS/s shows all of 2 m's busy part at once and is "
        "the Pluto nano's native rate (at 1.2 MS/s the nano runs at 2.4 and the program converts).")
with REG.after("sampleRate"):
    _k("hl2Address", "str", "", "setting", auth=True, restart=True,
       help="Hermes-Lite 2 address (ip or ip:port). Empty: find it by broadcast on port 1024.")
    _k("hl2Rate", "enum", 192_000, "setting", choices=HL2_RATES, unit="S/s", restart=True,
       help="Hermes-Lite 2 receive rate. 192 kS/s covers the busy part of any HF band at a sixth of a Pi's "
            "budget for 384 kS/s.")
    _k("hl2Lna", "float", 20.0, "setting", lo=-12.0, hi=48.0, unit="dB",
       help="Hermes-Lite 2 receiver gain (the AD9866's LNA).")
    _k("hl2Pa", "bool", True, "setting", auth=True, restart=True,
       help="Hermes-Lite 2 power amplifier (about 5 W). Off: the low-level RF1 output, up to 17 dBm - still enough "
            "to destroy a transverter that wants 0 dBm.")
    _k("hl2TxSwapIQ", "bool", False, "setting", auth=True, restart=True,
       help="Swap the Hermes-Lite 2's transmit I and Q. Whether HL2 clients swap them is not documented; a wrong "
            "choice mirrors the signal (USB comes out as LSB). Settle it with a known tone into a dummy load.")
    _k("ppm", "float", 0.0, "setting", lo=-50.0, hi=50.0, unit="ppm",
       help="The device's reference error, measured once against a known signal; applied to every tune.")
    # Transverters and up/down-converters (ohscore/converters.py; ohsradio/xvtr.py
    # says how a band uses one). Both decide where and how hard the device
    # transmits, so they are Settings-only; a change retunes everything, so
    # the radio restarts.
    _k("converters", "list", [], "setting", auth=True, restart=True, validate=cv.clean_list,
       help="Converter definitions, in your order: transverters, up/down-converters. Each has a title, a type "
            "(down: the radio below the air frequency; up: above), RX only, TX only or RX/TX, RX and TX "
            "offsets in Hz, whether it inverts, and the most drive its input takes.")
    _k("bandConverters", "dict", {}, "setting", auth=True, restart=True, validate=xvtr.clean_band_converters,
       help="Per band, the converter it is worked through (none: the radio tunes the band itself). A band the "
            "radio cannot reach - 23 cm on a Hermes-Lite 2, 6 m anywhere - is offered through one.")

# --- licence and band plan -----------------------------------------------------
# The licence keys themselves (licence, licenceClass, customLicence, and the
# station's country) are shared with NB since 08/10/2026: ohscore/state.py.
# No default class (Brian, 05/10/2026): Foundation used to be, as the most
# restrictive, but it refused a Full licensee for no reason and let anyone
# who skipped Welcome key under a class they might not hold. "" is "not
# chosen": receive works, transmit is refused until one is.
_o("licenceClass", help="Your licence class, within the licence in force. The guard holds every transmission inside "
                        "what this class may use. There is no default: until you choose one, transmit is refused "
                        "(receiving works).")
with REG.after("rxGain"):
    _k("plan", "enum", plans.AUTO, "setting", choices=[plans.AUTO] + list(plans.PLANS),
       help="The band plan shown and checked. auto: the station country's national plan where one is written, "
            "else its IARU region's.")
    _k("planGuard", "enum", "warn", "setting", choices=["warn", "enforce", "off"], auth=True,
       help="What a transmission outside its band-plan segment does: warn (and transmit), be refused, or "
            "nothing. Beacon and satellite segments are refused whatever this says.")
    _k("nearLondon", "bool", False, "setting", auth=True,
       help="The station is within 100 km of Charing Cross, where 431-432 MHz may not be used.")

# --- operating controls -------------------------------------------------------
_o("vfo", default=145_500_000.0, lo=100_000.0, hi=6_000_000_000.0, help="Receive dial (on-air frequency).")
_o("txVfo", default=145_500_000.0, lo=100_000.0, hi=6_000_000_000.0,
   help="Transmit dial (VFO B) when split is on.")
_o("mode", default="fm")
# Which modes noise reduction applies to is ohscore.dsp.nr.NR_MODES; each
# app names its own here, so the help never offers a mode the app lacks.
_o("nr", help="Noise reduction (WDSP's NR2) on what you hear in USB, LSB, CW, AM and FM. Decoders always get the "
              "audio without it.")
with REG.after("mute"):
    _k("drive", "float", 0.25, "control", lo=0.0, hi=1.0,
       help="Transmit drive, 0..1 of the device's full output. Cannot exceed this band's ceiling (Settings).")
    _k("bandStacks", "dict", {}, "control", validate=bands.clean_stacks,
       help="Per band: three registers (dial, mode, ...) and which one was last used.")
    _k("rptShift", "enum", "auto", "control", choices=["auto", "simplex", "minus", "plus"],
       help="FM repeater shift: auto follows the band plan's repeater channels; minus/plus use rptOffsetHz.")
    _k("rptOffsetHz", "float", 600_000.0, "control", lo=0.0, hi=50_000_000.0, unit="Hz",
       help="Repeater offset for a manual minus or plus shift. Set to the band's usual split in the plan or "
            "country in force on arriving in a band (plans/repeaters.py); a band-stack register remembers its own.")
    _k("rptReverse", "bool", False, "control", help="Listen on the repeater's input (and transmit on its output).")
    _k("ctcssTx", "enum", 0.0, "control", choices=TONE_CHOICES, unit="Hz", help="CTCSS tone sent with FM (0 = none).")
    _k("ctcssRx", "enum", 0.0, "control", choices=TONE_CHOICES, unit="Hz",
       help="Tone squelch: open only for this CTCSS tone (0 = carrier/noise squelch only).")
    _k("sqlLevel", "float", 0.5, "control", lo=0.0, hi=1.0, help="FM squelch: 0 open, 1 only strong signals.")
    _k("fmDeviation", "enum", 2500.0, "control", choices=[2500.0, 5000.0], unit="Hz",
       help="FM peak deviation: 2.5 kHz for 12.5 kHz channels (UK standard), 5 kHz for 25 kHz.")
_o("txFilterHi", help="Transmit audio high edge (SSB).")

# --- safety -------------------------------------------------------------------
with REG.after("pttMode"):
    _k("bandPower", "dict", {}, "setting", auth=True, validate=power.clean,
       help="Per band: the power chain (device output, PA gain, feeder loss, antenna gain) and the drive ceiling.")
    _k("tuneDrive", "float", 0.25, "setting", lo=0.05, hi=0.5, auth=True,
       help="Drive for a tune carrier (an ATU or PA tune), as a share of your current Drive: at 25 % with "
            "Drive at 40 %, the carrier goes out at 10 %.")
    _k("swrLimit", "float", 3.0, "setting", lo=1.5, hi=5.0, auth=True,
       help="Unkey when the measured SWR stays above this (devices that measure it: HL2, simulator).")
    _k("paTempLimit", "float", 50.0, "setting", lo=30.0, hi=60.0, unit="°C", auth=True,
       help="Unkey when the PA is hotter than this (HL2: below the gateware's own 55 °C cut-out).")
    _k("toneburstMs", "float", 500.0, "setting", lo=100.0, hi=2000.0, unit="ms",
       help="Length of a 1750 Hz toneburst.")
    _k("ctcssLevel", "float", 0.12, "setting", lo=0.05, hi=0.25,
       help="CTCSS tone level as a fraction of peak deviation (10-15 % is common practice; no UK figure was found).")

# --- PTT sequencer -------------------------------------------------------------
with REG.after("ctcssLevel"):
    _k("seqOutput", "enum", "none", "setting", choices=["none", "serial"], auth=True, restart=True,
       help="Where the PTT line for a PA or relays comes from: none, or a USB-serial adapter's RTS/DTR "
            "(which drop when the port closes, so a crash leaves the PA unkeyed).")
    _k("seqPort", "str", "", "setting", auth=True, restart=True, help="Serial port for the PTT line, e.g. /dev/ttyUSB0.")
    _k("seqLine", "enum", "rts", "setting", choices=["rts", "dtr", "both"], auth=True, restart=True,
       help="Which serial line keys the PA.")
    _k("seqDelayMs", "float", 25.0, "setting", lo=0.0, hi=500.0, unit="ms", auth=True,
       help="Key-up: wait this long after the PTT line before RF; key-down: after RF before releasing it.")

# --- simulator (device "sim") --------------------------------------------------
with REG.after("simRealtime"):
    _k("simHourUtc", "float", -1.0, "setting", lo=-1.0, hi=23.99, restart=True,
       help="Simulate the band at this UTC hour (-1: the real time of day).")
    _k("simAntSwr", "float", 1.3, "setting", lo=1.0, hi=10.0, restart=True,
       help="The simulated antenna's SWR (the SWR guard's test).")

# PSKReporter (ohscore/pskreporter.py): HAM decodes FT8, FT4 and JS8, so the
# shared help's Q65 would promise what this app does not have.
_o("pskReporter", help="Send the callsigns you decode in FT8, FT4 and JS8 to PSKReporter every five minutes: "
                       "their call, frequency, mode, signal report and grid, with your callsign, locator and this "
                       "program's name.")

# --- the CW skimmer (ohsradio/cwskim.py, docs/ENGINE-API.md cwskim/cwspot) -------
# Off by default and switched on per use (Brian, 13/10/2026); 64 channels by
# default, 256 at most. Control-level settings, none of them a transmit key.
with REG.after("pskReporter"):
    _k("cwSkim", "bool", False, "setting",
       help="Decode every CW signal in the band's CW segment at once, whatever the dial is on, and spot the "
            "calls it hears. Receive only; the spots stay on this station.")
    _k("cwSkimSquelch", "float", 6.0, "setting", lo=3.0, hi=20.0, unit="dB",
       help="How far over the noise a CW signal must stand to be decoded by the skimmer. A signal is followed "
            "once it stands this plus 2 dB over the floor.")
    _k("cwSkimMax", "int", 64, "setting", lo=8, hi=256,
       help="The most CW signals the skimmer decodes at once, strongest first. Each takes about a third of a "
            "per cent of one processor core.")

# --- status (read-only) -------------------------------------------------------
_o("rxDial", help="Frequency the receiver is demodulating (vfo + RIT, or the repeater input in reverse).")
_o("txDial", help="Frequency our transmission is meant to land on (with split, repeater shift and XIT).")
with REG.after("txDial"):
    for name, type_, default, help_ in [
        ("band", "str", "", "The band the dial is in ('' between bands)."),
        ("converter", "str", "", "The converter the receive dial's band is worked through ('' for none)."),
        ("radioFreq", "float", 0.0, "What the device itself is tuned to for the receive dial, Hz: the dial, or "
                                    "the converter's IF for it."),
        ("shift", "float", 0.0, "Repeater shift applied to the transmit dial now, Hz."),
        ("channel", "str", "", "Channel name of the dial in the plan in force (the UK's RV55, V40, RB4...)."),
        ("spanLo", "float", 0.0, "Lowest frequency the wide scope can show now."),
        ("spanHi", "float", 0.0, "Highest frequency the wide scope can show now."),
        ("licenceInfo", "dict", {}, "The licence and plan under the transmit dial: class, limit, segment, level, why."),
        ("planInUse", "str", "", "The band plan in force: the plan setting, or for auto the station country's "
                                 "national plan, else its IARU region's."),
        ("estPep", "float", 0.0, "Estimated PEP at the antenna at the current drive, W."),
        ("maxDrive", "float", 1.0, "The most drive this band allows: its ceiling (the licence's power limit only "
                                   "warns on an estimate)."),
        ("ctcssHeard", "float", 0.0, "CTCSS tone on the received FM signal, Hz (0 = none)."),
        ("sqlOpen", "bool", False, "FM squelch open."),
        ("seqState", "str", "rx", "PTT sequencer: rx, seq (lines keyed, waiting), tx, hang."),
        ("swr", "float", 0.0, "Measured SWR while keyed (0 = not measured)."),
        ("fwdW", "float", 0.0, "Measured forward power, W (0 = not measured)."),
        ("paTemp", "float", 0.0, "PA temperature, °C (0 = not measured)."),
        ("swrTripped", "bool", False, "Unkeyed on high SWR; keying refused until acknowledged."),
        ("cwSkimState", "str", "off", "CW skimmer: off, running, partial (part of the segment is outside what "
                                      "the receiver covers), outside, error."),
        ("cwSkimWhy", "str", "", "CW skimmer: why it is outside or in error ('' otherwise)."),
        ("cwSkimSignals", "int", 0, "CW skimmer: signals it is following."),
        ("cwSkimChannels", "int", 0, "CW skimmer: decoders running."),
        ("cwSkimCpu", "float", 0.0, "CW skimmer: its share of one core, per cent."),
        ("cwSkimDropped", "int", 0, "CW skimmer: receive blocks it fell too far behind to take, since it "
                                    "started. Receiving is never held up."),
    ]:
        _k(name, type_, default, "status", help=help_)


@REG.rule
def _drive_ceiling(st):
    if st["drive"] > st.get("maxDrive", 1.0) + 1e-9:
        raise ValueError(_("Drive cannot exceed {percent:.0f} % on this band (its ceiling, "
                           "Settings › Bands & power)").format(percent=st["maxDrive"] * 100))


SPEC = REG.spec
coerce = REG.coerce
defaults = REG.defaults
persisted = REG.persisted
check_combined = REG.check_combined
