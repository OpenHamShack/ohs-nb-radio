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
from ohscore.dsp.wfm import DEEMPHASIS_US
from ohscore.state import Registry, add_shared_keys

from ohsradio.i18n import _

from . import bands, bcastgain, notch, plans, power, xvtr

# JS8 joined 10/10/2026, receive only, once ohsdigi decoded it everywhere
# (ohscore/modes/js8.py): before, it needed JS8Call's js8, which the Radio
# store image could not carry.
# Wide FM (wfm) joined 23/10/2026 for broadcast listening, receive only
# (ohscore/dsp/wfm.py; ohscore/modes_glue.py RX_ONLY_MODES).
MODES = ["usb", "lsb", "cw", "am", "fm", "wfm", "ft8", "ft4", "js8", "psk31", "psk63", "psk125", "rtty", "freedv",
         "sstv"]
DIGITAL = {"ft8", "ft4", "js8", "psk31", "psk63", "psk125", "rtty", "freedv", "sstv"}
TONE_CHOICES = [0.0] + list(TONES)
HL2_RATES = [48_000, 96_000, 192_000, 384_000]

REG = Registry(MODES, DIGITAL)
add_shared_keys(REG)
_k = REG.add
_o = REG.override

# --- device -----------------------------------------------------------------
_o("device", choices=["sim", "pluto", "libresdr", "hl2", "rtlsdr", "sdrplay", "soapy"],
   help="Which radio. The simulator (HF and VHF/UHF bands, busy with other stations) needs no hardware and is the "
        "default. An RTL-SDR or an SDRplay RSP only receives; an RSP needs SDRplay's own API installed.")
_o("sampleRate", choices=[1_200_000, 2_400_000],
   help="Pluto sample rate. 1.2 MS/s suits a Raspberry Pi; 2.4 MS/s shows all of 2 m's busy part at once and is "
        "the Pluto nano's native rate (at 1.2 MS/s the nano runs at 2.4 and the program converts).")
with REG.after("sampleRate"):
    # The RTL-SDR's and the RSP's (ohscore/devices/sdrsource.py): which one of
    # several alike, and the RSP's LNA state, which Radio's one gain control
    # does not cover (RADIO-SDR-PLAN §6.2; SoapySDR's rfgain_sel before).
    _k("sdrSerial", "str", "", "setting", restart=True,
       help="The RTL-SDR's or SDRplay RSP's serial number, to pick one of several alike. Empty: the first found.")
    _k("sdrplayLna", "int", 4, "setting", lo=0, hi=27, restart=True,
       help="The SDRplay RSP's LNA state: higher attenuates more. 4 suits an HF dipole in the evening; the "
            "range each band allows is in SDRplay's API notes.")
    # The RSP's front-end notches (ohsradio/notch.py; Brian, 24/10/2026: a
    # DAB transmitter 8 km away overloads the RSPdx on 2 m). Live, no
    # restart: each is one API update on the running stream.
    _k("dabNotch", "enum", "auto", "setting", choices=list(notch.CHOICES),
       help="The SDRplay RSP's DAB notch (about 160-230 MHz), ahead of its LNA: for a strong Band III "
            "transmitter that overloads the receiver wherever it is tuned. In, it costs about 4 dB of signal "
            "and 2.5 dB over the noise on 2 m (measured on an RSPdx at 145.3 MHz). Automatic: out, until the "
            "radio reports overload for three seconds running while tuned outside 150-240 MHz; then in, and "
            "out again after 5 minutes with no overload (longer if it keeps coming back). Always out within "
            "150-240 MHz, its own stopband (Band III, marine VHF and AIS), and while a DAB station or AIS "
            "plays. On or off holds it. RSPdx, RSP1A, RSP1B and RSPduo only (not the RSPduo's Hi-Z input); on "
            "any other radio, the RSP2 and RSP1 included, it does nothing.")
    _k("rfNotch", "enum", "auto", "setting", choices=list(notch.CHOICES),
       help="The SDRplay RSP's broadcast notch, ahead of its LNA: one switch for the FM band (about 77-115 MHz) "
            "and MW (about 500-1530 kHz). Automatic: in only while the receiver is tuned below 60 MHz, except "
            "within the LW and MW broadcast bands; out above 60 MHz, because in it costs at least 4 dB on 2 m "
            "(SDRplay's RSPdx figure). On holds it in everywhere: for a station near a strong FM transmitter. "
            "Off holds it out. RSPdx, RSP1A, RSP1B, RSP2 and RSPduo (on Tuner 1's Hi-Z input, that port's MW "
            "notch); on any other radio, the RSP1 included, it does nothing.")
    # The zero-IF receivers' DC spike (ohscore/dsp/dcblock.py; Brian,
    # 23/10/2026): auto takes it out where the radio makes one.
    _k("dcBlock", "enum", "auto", "setting", choices=["auto", "on", "off"],
       help="Take out the line a receiver's own DC offset puts at the centre of the span. Automatic: on for the "
            "Pluto family, RTL-SDR, SDRplay and SoapySDR receivers, off for the Hermes-Lite 2 and the simulator.")
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
    _k("sMeterCal", "str", "", "setting",
       help="S-meter calibration, per radio, band and antenna input, as one line of JSON "
            "({\"pluto:ip:192.168.2.1|2m\": {\"offset\": -12.3, \"gain\": 40.0, \"when\": \"2026-10-23\"}, ...}): "
            "held here, not in a window's own preferences, so the store web page and OpenHamShack Remote read the "
            "same calibrated S-units as this window. Settings' Radio page writes and reads it with Calibrate…, "
            "never by hand (ohscore/smeter_cal.py has the math).")

# --- operating controls -------------------------------------------------------
_o("vfo", default=145_500_000.0, lo=100_000.0, hi=6_000_000_000.0, help="Receive dial (on-air frequency).")
_o("txVfo", default=145_500_000.0, lo=100_000.0, hi=6_000_000_000.0,
   help="Transmit dial (VFO B) when split is on.")
_o("mode", default="fm")
# AM's filter, either side of the carrier: 4 kHz here (8 kHz in all) against
# the shared 3 kHz. 3 kHz put the filter's -6 dB point on the top of
# airband voice (±3-4 kHz on an 8.33 kHz channel) and cut a 9 kHz MW or LW
# broadcast station to telephone quality; 4 kHz still stops short of an
# 8.33 kHz neighbour's sideband (5.3 kHz away). NB, on QO-100, keeps 3 kHz.
_o("amWidth", default=4000.0,
   help="AM filter, either side of the carrier: 4 kHz suits airband voice and broadcast; narrower for a crowded "
        "amateur band.")
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
    # 50 us is Europe's (and most of the world's); the Americas and South
    # Korea use 75 us. A choice rather than following the station country,
    # because a listener near a border hears the other side's stations.
    _k("wfmDeemphasis", "enum", 50.0, "control", choices=list(DEEMPHASIS_US), unit="µs",
       help="Wide FM de-emphasis: 50 µs in Europe and most of the world, 75 µs in the Americas. The wrong one "
            "sounds dull or harsh.")
    # The store form's timeshift (ohscore/server/timeshift.py; Brian,
    # 24/10/2026, for the TV's DAB Radio). An hour by default: what "I
    # missed the start of that" usually means, at most 690 MB on the
    # controller's disk and usually far less.
    _k("timeshiftMinutes", "int", 60, "setting", lo=0, hi=240, unit="min",
       help="On a controller: how much of the DAB or wide FM station playing is kept, to listen from behind live "
            "or record from the past. 0 keeps nothing. Cleared when the station changes or stops.")
    _k("recordLeadSeconds", "int", 30, "setting", lo=0, hi=300, unit="s",
       help="On a controller: while a DAB or wide FM station plays, a recording started without saying when "
            "begins this long ago, from the timeshift, so the moment that made you press Record is in it.")
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
       help="The most CW signals the skimmer decodes at once, strongest first. Each takes about half a per "
            "cent of one processor core.")
    # The skimmer's callsign list is the RBN week shipped with shack_cw; an
    # operator may add MASTER.SCP, which is never bundled (shack_cw.skim.scp
    # says why). Downloading it is opt-in: it is a request to a third party
    # on the operator's behalf, and it adds few calls (72 against 70 RBN
    # calls on the measurements in shack_cw.skim.calls).
    _k("cwSkimScp", "bool", False, "setting",
       help="Also download Super Check Partial's list of contest callsigns (MASTER.SCP) from "
            "supercheckpartial.com once a day while the skimmer runs, so more calls are spotted after two "
            "decodes instead of three. Radio already carries a list of calls the Reverse Beacon Network heard "
            "recently. Off: a copy you put in the data folder is still used.")

# --- local frequencies (ohsradio/localfreq.py, docs/SERVER-API.md) -------------
# The radius is a control-level setting (a Remote may change it); the
# openAIP key is a credential, so the store form refuses it over api/set
# and takes the module setting OPENAIP_API_KEY instead (ohscore/server/
# app.py PLATFORM_KEYS): api/state would otherwise show it to every viewer.
with REG.after("cwSkimScp"):
    _k("localRadiusKm", "int", 100, "setting", lo=1, hi=2000, unit="km",
       help="Local frequencies lists what is within this distance of the station's locator: airfields, area "
            "control, coast stations and marinas, nearest first.")
    _k("openAipKey", "str", "", "setting",
       help="Your openAIP API key (openaip.net, your profile's API clients), used only when you refresh the "
            "local frequencies, to fetch area control around the station. Empty: the copy Radio came with.")

# --- the band scan (ohsradio/bandscan.py) ----------------------------------------
# The weekly FM and DAB station lists, made at night while the radio is idle
# (Brian, 23/10/2026). Control level: none of them transmits or touches more
# than the receiver, which the scan always gives back.
with REG.after("openAipKey"):
    _k("scanAuto", "bool", True, "setting",
       help="Make the FM and DAB station lists by itself: once a week, at night, while nobody is using the radio. "
            "It gives the radio back the moment anyone does, with everything as it was.")
    _k("scanHour", "int", 3, "setting", lo=0, hi=23, unit="h",
       help="The hour of the night (local time) the weekly station scan is tried. Busy then, it tries the next "
            "night.")
    _k("scanEveryDays", "int", 7, "setting", lo=1, hi=60, unit="days",
       help="How old a station list may be before the night's scan makes it again.")
    _k("scanIdleMinutes", "int", 30, "setting", lo=1, hi=720, unit="min",
       help="How long the radio must have been left alone (nobody tuning or listening) before a night's scan "
            "may start.")

# --- DAB logos from RadioDNS (ohsradio/radiodns.py) ------------------------------
# On by default (Brian, 24/10/2026: "as long as it can still be used without
# internet"): offline it changes nothing. Off means no traffic at all and the
# fetched logos hidden. The help says exactly what goes out.
with REG.after("scanIdleMinutes"):
    _k("radioDnsLogos", "bool", True, "setting",
       help="Fetch DAB station logos from the internet in the background, so the station list has them before "
            "Radio has heard each ensemble's own. What goes out: DNS look-ups of each station's RadioDNS name, "
            "then web requests to the broadcasters' service-information servers and the logo addresses they "
            "give, saying only \"OpenHamShack-Radio\" and its version. Logos sent over the air always win; "
            "without internet nothing changes.")

# --- ships on a map (ohsradio/ais.py, ohsradio/mapdata.py) -------------------------
# Brian, 28/10/2026: AIS decodes only while a client has the map open; the
# map's tiles come from OpenStreetMap only when the controller has internet,
# and the bundled land map works without.
with REG.after("radioDnsLogos"):
    _k("aisKeepMinutes", "int", 60, "setting", lo=1, hi=1440, unit="min",
       help="How long a ship stays on the AIS map after it was last heard.")
    # Aircraft on the same map (ohsradio/adsb.py), likewise only while a
    # client has it open.
    _k("adsbKeepMinutes", "int", 5, "setting", lo=1, hi=60, unit="min",
       help="How long an aircraft stays on the ADS-B map after it was last heard.")
    _k("mapOnlineTiles", "bool", True, "setting",
       help="Show OpenStreetMap's map under the ships when Radio has internet: Radio fetches only the map "
            "pictures a screen is showing, keeps them for a while, and serves them itself, so no screen goes to "
            "the internet. What goes out: requests to tile.openstreetmap.org saying only \"OpenHamShack-Radio\" "
            "and its version. Off, or offline, the map draws its own coastline.")
    _k("mapTileCacheMb", "int", 200, "setting", lo=10, hi=5000, unit="MB",
       help="The most disk the OpenStreetMap map pictures may take; the least recently shown go first.")

# --- DMR callsigns and names (ohsradio/dmrids.py) --------------------------------
# On by default, like RadioDNS's logos (Brian: internet features are
# optional extras, and offline nothing changes). Off means no traffic at all
# and bare IDs, as before. The help says exactly what goes out.
with REG.after("mapTileCacheMb"):
    _k("dmrIdLookup", "bool", True, "setting",
       help="Show callsigns and names for the radio IDs a DMR decoder hears, and names for talkgroups. Radio "
            "downloads radioid.net's list of registered IDs and Brandmeister's talkgroup names once a week in the "
            "background, keeps them on this computer, and answers every screen itself. What goes out: two web "
            "requests a week saying only \"OpenHamShack-Radio\" and its version. A talker alias the caller's "
            "radio sends always wins; without internet the decoder shows the bare IDs.")

# --- flight routes for ADS-B's aircraft (ohsradio/flightroutes.py) ---------------
# On by default, like the other online extras above. Off means no traffic at
# all and no routes shown, even ones already cached (flightroutes.py).
with REG.after("dmrIdLookup"):
    _k("adsbRouteLookup", "bool", True, "setting",
       help="Show where each aircraft on the ADS-B map is flying from and to. Radio asks adsbdb.com, a free "
            "public lookup, for each new callsign it hears, once, in the background, and keeps the answer on "
            "this computer. What goes out: one web request per new callsign (at most one a second), saying only "
            "the callsign, \"OpenHamShack-Radio\" and its version. Without internet, or for a callsign adsbdb "
            "does not know, the aircraft shows no route.")

# --- radiosondes and SondeHub (ohsradio/sonde.py, sondehub.py) ---------------------
# Both on by default, like the other online extras above (Brian: offline,
# nothing changes). The upload is what radiosonde_auto_rx does by default
# and asks every station to leave on; its help says exactly what goes out,
# including that the station is placed only at its locator's centre.
with REG.after("adsbRouteLookup"):
    _k("sondeHubUpload", "bool", True, "setting",
       help="Send the radiosondes Radio decodes to SondeHub (sondehub.org), the public map of radiosonde "
            "flights, as radiosonde_auto_rx stations do. What goes out: each decoded frame, your callsign, and "
            "the centre of your 6-character locator (never your exact position), every 15 seconds while a "
            "sonde is being decoded, saying \"OpenHamShack-Radio\" and its version. Without internet nothing "
            "is sent and the map works as before.")
    _k("sondeOnline", "bool", True, "setting",
       help="Show upcoming radiosonde launches from nearby sites, and predict where a sonde will burst and land "
            "with SondeHub's predictor. What goes out: a request a day for SondeHub's list of launch sites, and "
            "a sonde's position and climb once a minute while one is being decoded. Off, or offline, the "
            "launch list is empty and Radio makes its own simple estimate.")

# --- weather satellites (ohsradio/wxsat.py, wxsat_tle.py) ------------------------
# Brian, 29/10/2026: Meteor-M LRPT passes recorded by themselves. Control
# level: a pass only receives, and gives the receiver back as it was. The
# satellites are one comma-separated value because a setting reaches a
# store container one variable per line; so is the pasted TLE ("|" between
# lines), which wxsat_tle.parse reads either way.
with REG.after("adsbRouteLookup"):
    _k("wxsatAuto", "bool", True, "setting",
       help="Record weather satellite passes (Meteor-M LRPT on 137 MHz) by themselves, as IQ, while the receiver "
            "is free. It never takes the radio from someone using it, a recording, a scan or transmit; the dial "
            "goes back where it was after each pass.")
    _k("wxsatMinElevDeg", "int", 15, "setting", lo=0, hi=90, unit="°",
       help="Record only passes that rise at least this high: a pass lower than this is mostly below the trees "
            "and roofs.")
    _k("wxsatSatellites", "str", "meteor-m2-3,meteor-m2-4", "setting",
       help="Which weather satellites to record, comma-separated: meteor-m2-3 (137.1 MHz), meteor-m2-4 (137.9 MHz).")
    _k("wxsatAntenna", "str", "", "setting",
       help="The receiver input to record passes on, by its name or your label for it (Settings › Radio's "
            "antenna table). Empty: the input whose label says 2 m (\"2 m\", \"VHF\", \"dual band\", a Diamond "
            "X-series model), else whichever input is in use.")
    _k("wxsatOnlineTle", "bool", True, "setting",
       help="Fetch the satellites' current orbits from Celestrak once a day in the background and keep them on "
            "this computer. What goes out: one web request a day to celestrak.org saying only "
            "\"OpenHamShack-Radio\" and its version. Off, or offline, Radio uses the last ones fetched, or the "
            "ones it came with.")
    _k("wxsatTle", "str", "", "setting",
       help="Your own orbital elements (two-line element sets, lines separated by \"|\"), used before Celestrak's "
            "for the satellites they name. Empty: Celestrak's, or the ones Radio came with.")

# --- each job's receiver gain (ohsradio/bcastgain.py job_gain_settings) ------------
# Brian, 29/10/2026: the operator's rxGain is for their own listening; a job
# that holds the receiver sets its own for as long as it holds it, and the
# operator's comes back after. "auto" (AGC) for the weak-signal services;
# DAB's broadcast policy for DAB. One plain value each, so a store setting
# can carry it.
with REG.after("wxsatTle"):
    _k("dabGain", "str", bcastgain.BROADCAST, "setting", validate=bcastgain.job_gain_validator(True),
       help="Receiver gain while a DAB station plays: \"broadcast\" for Radio's own, which starts low and moves "
            "with the station's errors; \"auto\" for the receiver's AGC; or a gain in the same units as "
            "Receiver gain, which Radio still lowers on overload. Your own gain is back when it stops.")
    _k("aisGain", "str", bcastgain.AUTO, "setting", validate=bcastgain.job_gain_validator(),
       help="Receiver gain while AIS has the receiver: \"auto\" for the receiver's own AGC, or a gain in the "
            "same units as Receiver gain, held. Your own gain is back when it ends.")
    _k("adsbGain", "str", bcastgain.AUTO, "setting", validate=bcastgain.job_gain_validator(),
       help="Receiver gain while ADS-B has the receiver: \"auto\" for the receiver's own AGC, or a gain in the "
            "same units as Receiver gain, held. Your own gain is back when it ends.")
    _k("aprsGain", "str", bcastgain.AUTO, "setting", validate=bcastgain.job_gain_validator(),
       help="Receiver gain while APRS has the receiver: \"auto\" for the receiver's own AGC, or a gain in the "
            "same units as Receiver gain, held. Your own gain is back when it ends.")
    _k("sondeGain", "str", bcastgain.AUTO, "setting", validate=bcastgain.job_gain_validator(),
       help="Receiver gain while radiosondes have the receiver: \"auto\" for the receiver's own AGC, or a gain "
            "in the same units as Receiver gain, held. Your own gain is back when it ends.")
    _k("wxsatGain", "str", bcastgain.AUTO, "setting", validate=bcastgain.job_gain_validator(),
       help="Receiver gain while a weather satellite pass has the receiver: \"auto\" for the receiver's own "
            "AGC, or a gain in the same units as Receiver gain, held. Your own gain is back when it ends.")


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
        ("dialLabel", "dict", None, "What the dial is on, from the operator's own frequencies and the bundled "
                                    "local-frequency lists (localfreq.py): {kind, name, callsign, place, sub, mode, "
                                    "cc, ctcss, network, distanceKm, bearingDeg, freqHz, rxOffsetHz, source, id, "
                                    "text}; null when nothing known is within the receive passband."),
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
        ("bandScan", "dict", {}, "The band scan running now (ohsradio/bandscan.py): {band, percent, phase, "
                                 "freqHz, text}; {} while none runs."),
        ("stationsAt", "dict", {}, "When each band's station list was last made: {fm, dab}, ISO 8601 UTC or "
                                   "null. Changes when a list does (GET api/fm/stations, api/dab/stations)."),
        ("notches", "dict", {}, "The SDRplay RSP's notch filters (notch.py), per switch the open radio has: "
                                "{dab_notch: {setting, in, why, text}, rf_notch: {...}}; text such as \"in: overload "
                                "seen at 145.300 MHz\". {} for a radio without them."),
        ("broadcastGain", "dict", {}, "The receiver gain a broadcast station (DAB holding the receiver, or wide "
                                      "FM) has in place of the operator's, which rxGain keeps (bcastgain.py): "
                                      "{auto, db, operatorDb, gainModel, adaptive, state, signal, fibBad, overloaded, "
                                      "backoffs, atLimit, floorDb, text}; {auto: false, db: null, why, text} while one plays but "
                                      "the operator's gain stands; {} while none plays."),
        ("ais", "dict", {}, "The AIS session (ais.py): {state (idle, running), why, text, clients, startedAt, "
                            "endsInS, vessels, rev, frames, channelA, channelB, damaged, ...}; GET api/ais/session."),
        ("adsb", "dict", {}, "The ADS-B session (adsb.py): {state (idle, running), why, text, clients, startedAt, "
                             "endsInS, centreHz, rateHz, aircraft, rev, messages, df17, aircraftSeen, ...}; GET "
                             "api/adsb/session."),
        ("aprs", "dict", {}, "The APRS session (aprs.py): {state (idle, running), why, text, clients, startedAt, "
                             "endsInS, freqHz, centreHz, stations, rev, frames, packets, dropped, ...}; GET "
                             "api/aprs/session."),
        ("sonde", "dict", {}, "The radiosonde session (sonde.py): {state (idle, scanning, tracking), why, text, "
                              "clients, startedAt, endsInS, freqHz, tracking, candidates, sondes, rev, frames, "
                              "dropped, scans, detections, ...}; GET api/sonde/session."),
        ("dmrIds", "dict", {}, "DMR callsigns and names (dmrids.py): {available, count, updatedUtc, source, "
                               "talkgroups}; available false offline until a list has been fetched, and with "
                               "dmrIdLookup off."),
        ("rds", "dict", None, "Wide FM: the station's RDS as the receiver decoded it (shack_sdr), "
                              "{pi, ps, rt, pty, ptyName, ta, tp, ct, af, stereo, ts}; null until a station's "
                              "programme identification is heard, and again on every retune."),
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
