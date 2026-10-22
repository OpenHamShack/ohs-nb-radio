"""Every state key QO-100 NB's engine has: the single source of truth.

The registry machinery and the keys OpenHamShack Radio shares are ohscore/state.py
(which explains the setting/control/status kinds and the `auth` and
`restart` marks). This module builds NB's registry from them: it gives the
shared keys their QO-100 ranges and wording, adds the keys only a QO-100
station has (LNB, beacon lock, TX lock, the beacon-level guard, the
transponder simulator's errors), and the QO-100 cross-key rules.

The public names are what they were before the core split - SPEC, MODES,
DIGITAL, coerce, defaults, persisted, check_combined - so the engine, the
UI and the tests read NB's state exactly as before.
"""
from __future__ import annotations

from ohscore import converters as cv
from ohscore.state import Registry, add_shared_keys

from ohsnb.i18n import _

from . import bandplan
from . import converters as nbconv

# Modes the engine knows. Voice and CW are demodulated by the engine itself;
# the digital ones are USB plus a decoder/encoder from ohscore.modes (when the
# installed pieces allow - see modes_glue).
MODES = ["usb", "lsb", "cw", "am", "ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty", "freedv",
         "sstv", "hsmodem"]
DIGITAL = {"ft8", "ft4", "q65", "js8", "psk31", "psk63", "psk125", "rtty", "freedv", "sstv", "hsmodem"}

REG = Registry(MODES, DIGITAL)
add_shared_keys(REG)
_k = REG.add
_o = REG.override

# --- device -----------------------------------------------------------------
_o("device", help="Which radio. The simulated transponder needs no hardware and is the default.")
_o("sampleRate", choices=[600_000, 1_200_000],
   help="Complex sample rate shared by receive and transmit. 1.2 MS/s keeps the transponder in the flat middle of "
        "the SDR's filter and lets one TX LO position reach almost the whole band; 600 kS/s costs about a third "
        "less CPU but cannot transmit on 2400.210-2400.290 MHz.")
# --- converters (ohsnb/converters.py): the LNB and any transmit upconverter ----
# The LNB's LO was one setting, lnbLo, up to 0.1.6; config.py migrates it.
with REG.after("sampleRate"):
    _k("converters", "list", list(nbconv.DEFAULT_LIST), "setting", auth=True, restart=True,
       validate=cv.clean_list,
       help="Converter definitions, in your order: LNBs, upconverters, transverters. Each has a title, a type "
            "(down: the radio below the air frequency; up: above), RX only, TX only or RX/TX, RX and TX "
            "offsets in Hz, whether it inverts, and the most drive its input takes.")
    _k("rxConverter", "str", nbconv.LNB_DEFAULT.title, "setting", restart=True,
       help="The LNB: the converter the receiver works through (9750 MHz for a standard 25 MHz-reference LNB). "
            "Beacon lock measures its error; you do not need to know it.")
    _k("txConverter", "str", "", "setting", auth=True, restart=True,
       help="The converter between the Pluto and 2400 MHz, if any. Usually none: the Pluto transmits on the "
            "uplink itself.")

# --- locks --------------------------------------------------------------------
with REG.after("rxGain"):
    _k("rxCorr", "float", 0.0, "control", lo=-250_000.0, hi=250_000.0, unit="Hz",
       help="Receive error: how far high every signal appears. Beacon lock maintains it; persisted so the next "
            "start begins close.")
    _k("txCorr", "float", 0.0, "control", lo=-120_000.0, hi=120_000.0, unit="Hz",
       help="Correction added to the uplink so our signal lands where the VFO says. TX lock maintains it.")
    _k("txCorrTrusted", "bool", False, "control",
       help="txCorr came from a TX lock (or a GPS-LNB prediction), so the first search can be narrow.")
    _k("rxCorrHand", "bool", False, "control",
       help="rxCorr was last set by the operator (typed, nudged or click-to-lock), not found by beacon lock's own "
            "search. The GPS-locked LNB's transmit prediction never uses such a value.")
    _k("beaconMode", "enum", "auto", "setting", choices=["auto", "hold", "manual"],
       help="Beacon lock. Auto tracks a beacon and corrects the receive frequency continuously. Hold stops tracking "
            "and keeps the correction exactly as it is (a fading beacon, or your own overs). Manual: no tracking; "
            "set rxCorr by hand. In Hold and Manual nothing follows the LNB's drift.")
    _k("beacon", "enum", "middle", "setting", choices=["middle", "lower"],
       help="Beacon to lock to. The middle BPSK beacon is GPS-referenced and mid-band; the lower F1A beacon is the "
            "fallback (and is used automatically when the chosen one is not heard).")
    _k("beaconSearchHz", "float", 50_000.0, "setting", lo=2_000.0, hi=55_000.0, unit="Hz",
       help="How far either side of the expected position to search for a beacon. Unmodified LNBs need tens of kHz.")
    _k("txLock", "bool", True, "setting", help="Find our own signal in the downlink while transmitting and correct txCorr.")
    _k("lnbGpsLocked", "bool", False, "setting",
       help="The LNB has a GPS/reference-locked oscillator. Then the beacon error is mostly the SDR's own reference, "
            "and a first txCorr is predicted from it before ever keying.")
    _k("mmbDecode", "bool", True, "setting",
       help="Receive AMSAT-DL's multimedia beacon (10489.995 MHz: bulletins, pictures, DX-cluster spots, "
            "transponder spectra) in the background, from the wide receive signal, whatever you are tuned to. "
            "About half a per cent of one core on a laptop.")
    _k("midTextDecode", "bool", True, "setting",
       help="Decode the middle beacon's text (10489.750 MHz, 400 bit/s BPSK: DK0SB's K, L, M and N message "
            "blocks) in the background, whatever you are tuned to. Needs beacon lock, or a receive correction "
            "within a few hundred hertz.")
    _k("kgstvDecode", "bool", True, "setting",
       help="Receive KG-STV pictures (10489.6249 MHz USB: 320x240, about two minutes each, one 16x16 block at a "
            "time) in the background, whatever you are tuned to. Pictures of 50 blocks or more are saved.")
    _k("skimDecode", "bool", True, "setting",
       help="Find and name every signal on the transponder in the background, whatever you are tuned to: SSB "
            "voices with their dial measured, CW, data, the beacons and the FT8 windows (the Band view, and "
            "marks on the wide scope).")
    _k("skimBudget", "float", 10.0, "setting", lo=1.0, hi=50.0, unit="%",
       help="The most of one processor core the band skimmer may use. Less only means SSB dials are measured "
            "more slowly; receiving is never held up.")
    _k("opWatch", "bool", True, "setting",
       help="Watch the whole transponder in the background for signals with more power than the middle beacon, "
            "and for AMSAT-DL's LEILA siren that marks them (the over-power list in the Band view, and marks on "
            "the wide scope). About 4 per cent of one core.")
    _k("leilaCapture", "bool", False, "setting",
       help="Keep the last 20 s of receive IQ (about 96 MB of memory) and save it to Recordings when a LEILA "
            "siren ends, or when you press Save in the Band view: evidence to check the siren detector against. "
            "Nothing is kept while this is off.")
    _k("rttSec", "float", 0.25, "setting", lo=0.20, hi=0.40, unit="s",
       help="Satellite round trip (about 0.24-0.28 s depending on where you are).")
    _k("levelMode", "enum", "limit", "setting", choices=["manual", "limit", "auto"],
       help="Own-signal level against the beacon: manual warns only; limit trims TX gain down when we are less than "
            "the margin below the beacon; auto also raises it back up (never above the ceiling).")
    _k("levelMarginDb", "float", 6.0, "setting", lo=0.0, hi=30.0, unit="dB",
       help="How far below beacon level our downlink should sit.")

# --- an external transmitter (ohsnb/extrig.py): the IC-9700 + upconverter -------
with REG.after("levelMarginDb"):
    _k("txRadio", "enum", "sdr", "setting", choices=["sdr", "civ", "rigctld"], auth=True, restart=True,
       help="What transmits. The SDR (the Pluto) is keyed by OpenHamShack QO-100 NB. An IC-9700 is keyed on the radio "
            "itself for voice: OpenHamShack QO-100 NB tunes it, follows it, shows and corrects where it lands, and keys "
            "it only for its own digital-mode overs if 'Key the IC-9700 for digital modes' is on.")
    _k("civPort", "str", "", "setting", restart=True,
       help="The IC-9700's USB serial port: COM5 (Windows), /dev/ttyUSB0 or /dev/serial/by-id/... (Linux), or "
            "socket://host:port for a network serial port.")
    _k("civBaud", "enum", 115200, "setting", choices=[4800, 9600, 19200, 38400, 57600, 115200], restart=True,
       unit="baud", help="CI-V speed. The IC-9700's CI-V USB Baud Rate is Auto by default, which follows this.")
    _k("civAddress", "int", 0xA2, "setting", lo=1, hi=0xDF, restart=True,
       help="The radio's CI-V address (the IC-9700's default is A2h).")
    _k("rigctldHost", "str", "127.0.0.1", "setting", restart=True,
       help="The computer rigctld runs on (127.0.0.1: this one).")
    _k("rigctldPort", "int", 4532, "setting", lo=1, hi=65535, restart=True,
       help="rigctld's TCP port (4532 unless started with -t).")
    _k("rigTxConverter", "str", "", "setting", auth=True, restart=True,
       help="The IC-9700's upconverter to 2400 MHz, from the converter list. Required, and deliberately without "
            "a default: a guessed LO would put the uplink somewhere else entirely. An inverting (high-side) one "
            "turns the radio's USB into LSB and runs its knob the other way; OpenHamShack QO-100 NB converts.")
    _k("rigIfBand", "enum", "23cm", "setting", choices=["23cm", "70cm", "2m"],
       help="The IC-9700 band feeding the upconverter.")
    _k("rigPollMs", "int", 100, "setting", lo=50, hi=1000, unit="ms", restart=True,
       help="How often the radio is asked its frequency and whether it is transmitting: the delay before the "
            "TX marker follows its knob and before receive audio mutes.")
    # The most rigTxCorr may be (Radio._rig_unkeyed): 0.1.18 let it run to
    # +5441 Hz on a find that never moved with the radio (Ray, 13/10/2026).
    # 1 kHz covers a free-running IC-9700 (0.5 ppm is 650 Hz at 23 cm) and
    # the 840 Hz Ray's landed on 12/10, and stops a runaway well short of
    # the next station; a GPS-locked radio and upconverter want a few
    # hundred.
    _k("rigTxCorrMaxHz", "float", 1000.0, "setting", lo=20.0, hi=20_000.0, unit="Hz",
       help="The most TX lock may correct the external radio's uplink by. A larger error is shown, not "
            "corrected. A GPS-locked radio and upconverter need a few hundred hertz at most; a free-running "
            "IC-9700 is specified to about 650 Hz at 23 cm.")
    _k("rigRxFollows", "bool", True, "setting",
       help="Turning the radio's knob moves the receive dial too, as on a transceiver. Off: it moves only the "
            "transmit dial (split).")
    _k("rigFmToSsb", "bool", True, "setting",
       help="When the radio is found in FM, which the narrowband transponder does not carry, switch it to SSB "
            "(USB on air), between overs. Off: NB never changes the radio's mode, and only warns.")
    _k("rigAudio", "enum", "mute", "setting", choices=["mute", "lower", "keep"],
       help="Receive audio while the radio transmits. Mute stops your microphone hearing your own downlink "
            "from the speaker; the scopes, locks and level measurement carry on regardless.")
    _k("rigAudioLowerDb", "float", 20.0, "setting", lo=3.0, hi=60.0, unit="dB",
       help="How far 'Lower' turns receive audio down while the radio transmits.")
    # CAT PTT for digital modes (ohsnb/extrig.py CatPtt; Brian, 12/10/2026).
    # Off by default and Settings-only (auth): the default must stay what
    # every existing install had, an IC-9700 NB never keys.
    _k("rigCatPtt", "bool", False, "setting", auth=True,
       help="Key the IC-9700 by CAT for NB's own digital-mode overs (FT8, FT4, Q65, JS8, PSK, RTTY and CW lines), "
            "as WSJT-X does, sending the audio to the radio's USB sound device and putting it in USB-D first. "
            "Never for voice: speech is always keyed on the radio. Off: NB never keys the radio.")
    _k("rigTxAudioOut", "str", "", "setting", auth=True,
       help="The IC-9700's own sound device, which carries NB's digital-mode audio to it (usually 'USB Audio "
            "CODEC'). Never the system default: with none chosen NB will not key the radio.")
    _k("rigTxAudioDb", "float", -10.0, "setting", lo=-40.0, hi=0.0, unit="dB",
       help="Level of the digital-mode audio sent to the IC-9700. Set it, with the radio's USB MOD Level, where "
            "the radio's power stops rising (its ALC reads with any audio): more makes splatter, not power.")
    _k("rigPttDelayMs", "int", 100, "setting", lo=0, hi=1000, unit="ms",
       help="After NB keys the IC-9700, how long it waits before the audio starts, so the radio, its PA and the "
            "upconverter's relays have switched to transmit. A timed over (FT8) is keyed this much early.")
    _k("rigPttTailMs", "int", 50, "setting", lo=0, hi=1000, unit="ms",
       help="After the last of the audio has played, how long NB waits before unkeying the IC-9700.")
    # The setup assistant's record of what it changed (ohsnb/rigsetup.py),
    # kept until "Restore the radio as it was": leave-as-found outlives a
    # restart of NB. Written only by the assistant (auth), never shown.
    _k("rigSetupSaved", "dict", {}, "setting", auth=True,
       help="The IC-9700 settings as they were before the setup assistant changed them, kept so that 'Restore "
            "the radio as it was' can put them back. Empty when nothing is waiting to be restored.")
with REG.after("txCorrTrusted"):
    _k("rigTxCorr", "float", 0.0, "control", lo=-120_000.0, hi=120_000.0, unit="Hz",
       help="Correction added to the external radio's uplink (its reference and the upconverter's LO error "
            "together), kept apart from txCorr, which is the SDR's. TX lock maintains it from a carrier or from NB's "
            "own CAT PTT digital overs.")
    _k("rigTxCorrTrusted", "bool", False, "control",
       help="rigTxCorr came from a TX lock, so the first search can be narrow.")

# --- operating controls -------------------------------------------------------
# The dial is a QO-100 downlink frequency (DESIGN.md "Frequencies").
_o("vfo", default=10_489_700_000.0, lo=bandplan.DL_LO - 20_000.0, hi=bandplan.DL_HI + 20_000.0,
   help="Receive dial (downlink).")
_o("txVfo", default=10_489_700_000.0, lo=bandplan.DL_LO, hi=bandplan.DL_HI,
   help="Transmit dial (downlink) when split is on.")
# Which modes noise reduction applies to is ohscore.dsp.nr.NR_MODES; each
# app names its own here, so the help never offers a mode the app lacks.
_o("nr", help="Noise reduction (WDSP's NR2) on what you hear in USB, LSB, CW and AM. Decoders always get the audio "
              "without it.")
_o("freedvMode",
   help="FreeDV waveform. 700D is the robust choice heard on QO-100; 1600 and 2020 sound better on a strong "
        "signal. Only those the installed libcodec2 can open are usable (caps lists them).")
# HSmodem's speed (ohscore/modes/hsmodem.py SPEEDS): sending and receiving
# both, since HSmodem does not detect a sender's speed - both stations pick
# the same one, as in DJ0ABR's program. Offered: the speeds whose measured
# width fits QO-100's 2.7 kHz (bandplan.HSMODEM_SPEEDS) - all ten of
# HSmodem's do. The default is the one HSmodem's own GUI starts on and
# calls the QO-100 standard.
with REG.after("freedvMode"):
    _k("hsSpeed", "enum", 4410, "control", choices=list(bandplan.HSMODEM_SPEEDS), unit="bit/s",
       help="HSmodem speed, sending and receiving: 1200 and 2400 BPSK, 3000-4800 QPSK, 5500-7200 8APSK. Both "
            "stations must use the same. 4410 (QPSK) is HSmodem's QO-100 standard; the faster ones need a "
            "stronger signal.")
# Transmit power is the Pluto's own gain in dB (docs/ham/DESIGN-HAM.md
# section 2.3: NB keeps this vocabulary; HAM's is a normalised drive).
with REG.after("mute"):
    _k("txGain", "float", -40.0, "control", lo=-89.75, hi=0.0, unit="dB",
       help="SDR transmit gain. Cannot exceed txGainCeiling.")
_o("txFilterHi", help="Transmit audio high edge. The occupied width (high - low) may not exceed 2.7 kHz.")

# --- safety -------------------------------------------------------------------
with REG.after("pttMode"):
    _k("txGainCeiling", "float", -10.0, "setting", lo=-89.75, hi=0.0, unit="dB", auth=True,
       help="The most transmit gain any control can set.")

# --- simulator (device "sim"): the transponder's own errors --------------------
with REG.after("locator"):
    _k("simRxErrorHz", "float", 1800.0, "setting", lo=-60_000.0, hi=60_000.0, unit="Hz", restart=True,
       help="Simulated LNB error at start: how far high everything appears.")
    _k("simDriftHz", "float", 400.0, "setting", lo=0.0, hi=20_000.0, unit="Hz", restart=True,
       help="Size of the simulated LNB's slow wander.")
    _k("simDriftSec", "float", 600.0, "setting", lo=10.0, hi=7200.0, unit="s", restart=True,
       help="Timescale of the simulated LNB's wander.")
    _k("simUlErrorHz", "float", -11_000.0, "setting", lo=-70_000.0, hi=70_000.0, unit="Hz", restart=True,
       help="Simulated SDR transmit error: where our signal really goes, relative to where we aim it.")
    _k("simRefGainDb", "float", -20.0, "setting", lo=-89.75, hi=0.0, unit="dB", restart=True,
       help="Transmit gain at which our simulated downlink equals the beacon.")

# --- status (read-only) -------------------------------------------------------
_o("rxDial", help="Downlink the receiver is demodulating (vfo + RIT).")
_o("txDial", help="Downlink our transmission is meant to land on (txVfo or vfo, + XIT).")
with REG.after("txDial"):
    _k("txUl", "float", 0.0, "status", help="Uplink we are aiming at, including txCorr.")
with REG.after("segment"):
    for name, type_, default, help_ in [
        ("rxLock", "str", "off", "Beacon lock: searching, locked, lost (Auto), hold, manual; off before the "
                                 "radio starts."),
        ("rxWindow", "float", 0.0, "How far either side the beacon search is looking, Hz: +-2 kHz around the "
                                   "correction held first, then beaconSearchHz."),
        ("rxReject", "str", "", "The last signal beacon lock looked at and refused as not a beacon, and why."),
        ("rxErr", "float", 0.0, "Last measured beacon error after correction, Hz."),
        ("rxRate", "float", 0.0, "Drift rate, Hz/s."),
        ("rxSnr", "float", 0.0, "Beacon SNR in 2.5 kHz, dB."),
        ("beaconUsed", "str", "", "Which beacon is steering rxCorr."),
        ("beaconLevel", "float", -200.0, "Beacon power, dBFS."),
        ("txLockState", "str", "idle", "TX lock: idle, searching (own signal not yet found this over), "
                                        "landed (found txErr off the dial; correcting), locked."),
        ("txErr", "float", 0.0, "Last measured own-signal error, Hz."),
        ("txConfidence", "float", 0.0, "Peak-to-noise of the last own-signal measurement."),
        ("ownDl", "float", 0.0, "Where our own signal was last seen landing (corrected downlink, dial frequency)."),
        ("vsBeacon", "float", None, "Own downlink level relative to the beacon, dB (None until measured)."),
        ("txPpm", "float", 0.0, "txCorr as parts per million of the uplink."),
        ("rigLink", "str", "off", "External transmitter link: off, connecting, ok, lost, error."),
        ("rigError", "str", "", "Why the external transmitter link is not working, or what it refused."),
        ("rigFreq", "float", 0.0, "The external radio's own frequency (its IF band), Hz."),
        ("rigKeyed", "bool", False, "The external radio is transmitting (read from it, whoever keyed it)."),
        ("rigCatKeyed", "bool", False, "NB has keyed the external radio by CAT for a digital over (rigCatPtt)."),
        ("rigModInput", "str", "", "Where the external radio takes its transmit audio from in its current mode "
                                   "(mic, acc, mic,acc, usb, mic,usb, lan), when its link can read it."),
        ("rigMode", "str", "", "The external radio's mode on air (after an inverting upconverter)."),
        ("rigAimDl", "float", 0.0, "Downlink the external radio is aimed at, rigTxCorr taken out."),
        ("rigTxBlocked", "str", "", "Why NB would not transmit where the external radio is aimed (advisory: NB "
                                     "cannot stop it being keyed)."),
        ("mmbState", "str", "off", "Multimedia beacon receiver: off, searching, receiving, error (or why it is "
                                   "unavailable)."),
        ("mmbMer", "float", 0.0, "Multimedia beacon decode quality: modulation error ratio of its symbols, dB."),
        ("mmbFrames", "int", 0, "Multimedia beacon frames decoded since the radio started."),
        ("mmbLost", "int", 0, "Multimedia beacon frames that came and did not decode."),
        ("mmbLast", "float", 0.0, "When the last multimedia beacon frame decoded (Unix time; 0: none yet)."),
        ("mmbFreq", "float", 0.0, "How far the multimedia beacon is from 10489.995 MHz after rxCorr, Hz."),
        ("mmbCpu", "float", 0.0, "The multimedia beacon receiver's share of one core, per cent."),
        ("midTextState", "str", "off", "Middle beacon text receiver: off, searching (for its carrier), tracking "
                                       "(carrier found, no block for a minute), receiving, error."),
        ("midTextSnr", "float", 0.0, "Middle beacon text decode quality: its symbols' SNR, dB (0 while searching)."),
        ("midTextFrames", "int", 0, "Middle beacon text blocks decoded since the radio started."),
        ("midTextLost", "int", 0, "Middle beacon text blocks whose sync was heard and which did not decode."),
        ("midTextLast", "float", 0.0, "When the last middle beacon text block decoded (Unix time; 0: none yet)."),
        ("midTextFreq", "float", 0.0, "How far the middle beacon is from 10489.750 MHz after rxCorr, Hz, as its "
                                      "decoder has it."),
        ("kgstvState", "str", "off", "KG-STV picture receiver: off, listening, receiving (a frame decoded in the "
                                     "last 30 s), error."),
        ("kgstvFrames", "int", 0, "KG-STV frames decoded since the radio started (picture blocks, callsigns, "
                                  "end frames)."),
        ("kgstvLost", "int", 0, "KG-STV frames whose sync was heard and which did not decode."),
        ("kgstvLast", "float", 0.0, "When the last KG-STV frame decoded (Unix time; 0: none yet)."),
        ("kgstvCall", "str", "", "The callsign the last KG-STV station sent ('' until one has)."),
        ("kgstvFreq", "float", 0.0, "How far the KG-STV signal's centre is from 10489.6264 MHz after rxCorr, Hz "
                                    "(0 unless receiving)."),
        ("skimState", "str", "off", "Band skimmer: off, running, error."),
        ("skimSignals", "int", 0, "Band skimmer: entries on its list heard in the last 20 s (a calling window "
                                  "counts once)."),
        ("skimExact", "int", 0, "Band skimmer: SSB stations among them whose dial auto-tune has measured."),
        ("skimCpu", "float", 0.0, "Band skimmer: its share of one core over the last 10 s, per cent."),
        ("skimLevel", "int", 0, "Band skimmer: 0 uses every spectrum frame; 1 and 2 every second and fourth, "
                                "when the spectrum alone costs more than half of skimBudget."),
        ("skimLooks", "float", 0.0, "Band skimmer: looks at signals (a voice's dial, a narrow signal's keying) "
                                    "finished in the last minute."),
        ("skimDropped", "int", 0, "Band skimmer: receive blocks it fell too far behind to take, since it "
                                  "started."),
        ("opState", "str", "off", "Over-power and LEILA watch: off, running, error."),
        ("opBeacon", "str", "", "Over-power watch: whether the last spectral line could be judged - ok, unlocked "
                                "(beacon lock has not got the beacon), weak (no beacon above the noise), none."),
        ("opActive", "int", 0, "Over-power watch: signals over the beacon now."),
        ("opLeila", "int", 0, "LEILA sirens heard in the last 30 minutes."),
        ("opCpu", "float", 0.0, "Over-power and LEILA watch: its share of one core over the last 10 s, per cent."),
        ("opDropped", "int", 0, "Over-power watch: receive blocks it fell too far behind to take, since it "
                                "started."),
        ("opCapture", "str", "", "The last LEILA evidence capture saved ('' until one has been)."),
    ]:
        _k(name, type_, default, "status", help=help_)


# --- dish alignment (ohsnb/dishmeter.py, Radio.dish_open) ----------------------
# Its tone and phone page are this session's choices, not kept: a page
# that serves itself on the network because it did last week would be a
# surprise. The port is kept, as a firewall rule made for it would be.
with REG.after("opCapture"):
    _k("dishTone", "bool", False, "control", persist=False,
       help="Dish alignment: a tone that rises with the middle beacon's SNR, in place of the receive audio.")
    _k("dishPhone", "bool", False, "control", persist=False,
       help="Dish alignment: serve the phone page (the same numbers and a tone) to this network while the tool "
            "is open.")
    _k("dishPort", "int", 8099, "control", lo=1024, hi=65535,
       help="Dish alignment: the phone page's port.")
    for name, type_, default, help_ in [
        ("dishOpen", "bool", False, "Dish alignment is open (transmit is refused meanwhile)."),
        ("dishSnr", "float", None, "Dish alignment: the middle beacon's SNR in 2.5 kHz, dB (None: not measured)."),
        ("dishBest", "float", None, "Dish alignment: the best SNR since it opened or was reset, dB."),
        ("dishRise", "float", None, "Dish alignment: the transponder's noise over the noise beside it, dB "
                                    "(None: no room beside it at this sample rate)."),
        ("dishWhere", "str", "", "Dish alignment: where the beacon was measured (where beacon lock has it, or "
                                 "the strongest signal near where it should be)."),
        ("dishGain", "str", "", "Dish alignment: what it did to the receive gain, and that it is restored."),
        ("dishHeldDb", "float", None, "Dish alignment: the receive gain it is holding, dB (None: not holding). "
                                      "Marked in a recording."),
        ("dishUrls", "str", "", "Dish alignment: the phone page's addresses, comma-separated ('' when off)."),
        ("dishPhoneError", "str", "", "Dish alignment: why the phone page could not start."),
    ]:
        _k(name, type_, default, "status", help=help_)


@REG.rule
def _qo100_occupied_width(st):
    if st["txFilterHi"] - st["txFilterLo"] > bandplan.MAX_BW:
        raise ValueError(_("The transmit filter may be 2.7 kHz wide at most (QO-100 rule)"))


@REG.rule
def _tx_gain_ceiling(st):
    if st["txGain"] > st["txGainCeiling"]:
        raise ValueError(_("Transmit gain cannot exceed the ceiling of {ceiling:g} dB set in Settings").format(
            ceiling=st["txGainCeiling"]))


SPEC = REG.spec
coerce = REG.coerce
defaults = REG.defaults
persisted = REG.persisted
check_combined = REG.check_combined
