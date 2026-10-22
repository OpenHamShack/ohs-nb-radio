"""NB's state registry after the core split, and the registry machinery.

PRE_SPLIT is ohsnb.state.SPEC as it was on main at a7cf1e8, before the
registry moved to ohscore (docs/ham/DESIGN-HAM.md section 2.5 step 6),
captured as data. NB building the identical SPEC - every field of every
key, in the same order - is what proves the split changed nothing an
operator, the UI or a saved config could see. When a key is deliberately
changed later, change it here too: this is a record, not a cage.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import unittest

from ohscore.state import Registry, add_shared_keys
from ohsnb import state

PRE_SPLIT = {
    'device': {'type': 'enum', 'default': 'sim', 'kind': 'setting', 'min': None, 'max': None, 'choices': ['sim', 'pluto', 'soapy'], 'unit': '', 'persist': True, 'auth': True, 'restart': True, 'help': 'Which radio. The simulated transponder needs no hardware and is the default.'},
    'plutoUri': {'type': 'str', 'default': 'ip:192.168.2.1', 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': True, 'restart': True, 'help': 'libiio URI: ip:192.168.2.1 (Pluto over USB), ip:pluto.local, ip:<address> (Pluto+, LibreSDR), usb:<bus>.<dev>.<n>.'},
    'soapyArgs': {'type': 'str', 'default': 'driver=rtlsdr', 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': True, 'help': 'SoapySDR device arguments for a receive-only SDR, e.g. driver=airspy.'},
    'sampleRate': {'type': 'enum', 'default': 1200000, 'kind': 'setting', 'min': None, 'max': None, 'choices': [600000, 1200000], 'unit': 'S/s', 'persist': True, 'auth': False, 'restart': True, 'help': "Complex sample rate shared by receive and transmit. 1.2 MS/s keeps the transponder in the flat middle of the SDR's filter and lets one TX LO position reach almost the whole band; 600 kS/s costs about a third less CPU but cannot transmit on 2400.210-2400.290 MHz."},
    'lnbLo': {'type': 'float', 'default': 9750000000.0, 'kind': 'setting', 'min': 9000000000.0, 'max': 10400000000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': "The LNB's local oscillator as designed (9750 MHz for a 25 MHz LNB). Beacon lock measures the error."},
    'rxGainMode': {'type': 'enum', 'default': 'slow_attack', 'kind': 'setting', 'min': None, 'max': None, 'choices': ['manual', 'slow_attack', 'fast_attack'], 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Receiver gain control in the SDR.'},
    'rxGain': {'type': 'float', 'default': 40.0, 'kind': 'setting', 'min': 0.0, 'max': 73.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': False, 'restart': False, 'help': 'Receiver gain when gain control is manual.'},
    'rxCorr': {'type': 'float', 'default': 0.0, 'kind': 'control', 'min': -250000.0, 'max': 250000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'Receive error: how far high every signal appears. Beacon lock maintains it; persisted so the next start begins close.'},
    'txCorr': {'type': 'float', 'default': 0.0, 'kind': 'control', 'min': -120000.0, 'max': 120000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'Correction added to the uplink so our signal lands where the VFO says. TX lock maintains it.'},
    'txCorrTrusted': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'txCorr came from a TX lock (or a GPS-LNB prediction), so the first search can be narrow.'},
    'beacon': {'type': 'enum', 'default': 'middle', 'kind': 'setting', 'min': None, 'max': None, 'choices': ['middle', 'lower'], 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Beacon to lock to. The middle BPSK beacon is GPS-referenced and mid-band; the lower F1A beacon is the fallback (and is used automatically when the chosen one is not heard).'},
    'beaconSearchHz': {'type': 'float', 'default': 50000.0, 'kind': 'setting', 'min': 2000.0, 'max': 55000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'How far either side of the expected position to search for a beacon. Unmodified LNBs need tens of kHz.'},
    'txLock': {'type': 'bool', 'default': True, 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Find our own signal in the downlink while transmitting and correct txCorr.'},
    'lnbGpsLocked': {'type': 'bool', 'default': False, 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': "The LNB has a GPS/reference-locked oscillator. Then the beacon error is mostly the SDR's own reference, and a first txCorr is predicted from it before ever keying."},
    'rttSec': {'type': 'float', 'default': 0.25, 'kind': 'setting', 'min': 0.2, 'max': 0.4, 'choices': None, 'unit': 's', 'persist': True, 'auth': False, 'restart': False, 'help': 'Satellite round trip (about 0.24-0.28 s depending on where you are).'},
    'levelMode': {'type': 'enum', 'default': 'limit', 'kind': 'setting', 'min': None, 'max': None, 'choices': ['manual', 'limit', 'auto'], 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Own-signal level against the beacon: manual warns only; limit trims TX gain down when we are less than the margin below the beacon; auto also raises it back up (never above the ceiling).'},
    'levelMarginDb': {'type': 'float', 'default': 6.0, 'kind': 'setting', 'min': 0.0, 'max': 30.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': False, 'restart': False, 'help': 'How far below beacon level our downlink should sit.'},
    'vfo': {'type': 'float', 'default': 10489700000.0, 'kind': 'control', 'min': 10489480000.0, 'max': 10490020000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'Receive dial (downlink).'},
    # 'mode's own choices list deliberately changed (07/10): Q65 added as a
    # receive/transmit mode (ohscore/modes/q65.py), then JS8 as a
    # receive-only mode (ohscore/modes/js8.py) - not a new key, so not
    # ADDED_SINCE; this is the "change it here too" case the module
    # docstring describes. HSmodem added the same way (07/10:
    # ohscore/modes/hsmodem.py, station to station).
    'mode': {'type': 'enum', 'default': 'usb', 'kind': 'control', 'min': None, 'max': None, 'choices': ['usb', 'lsb', 'cw', 'am', 'ft8', 'ft4', 'q65', 'js8', 'psk31', 'psk63', 'psk125', 'rtty', 'freedv', 'sstv', 'hsmodem'], 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'split': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Transmit on txVfo instead of following the receive dial.'},
    'txVfo': {'type': 'float', 'default': 10489700000.0, 'kind': 'control', 'min': 10489500000.0, 'max': 10490000000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'Transmit dial (downlink) when split is on.'},
    'rit': {'type': 'float', 'default': 0.0, 'kind': 'control', 'min': -5000.0, 'max': 5000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'ritOn': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'xit': {'type': 'float', 'default': 0.0, 'kind': 'control', 'min': -5000.0, 'max': 5000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'xitOn': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'filterLo': {'type': 'float', 'default': 300.0, 'kind': 'control', 'min': 0.0, 'max': 1000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'SSB/digital receive filter low edge.'},
    'filterHi': {'type': 'float', 'default': 2700.0, 'kind': 'control', 'min': 1000.0, 'max': 4000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'SSB/digital receive filter high edge.'},
    'cwWidth': {'type': 'float', 'default': 500.0, 'kind': 'control', 'min': 50.0, 'max': 1500.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'cwPitch': {'type': 'float', 'default': 700.0, 'kind': 'control', 'min': 300.0, 'max': 1200.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'freedvMode': {'type': 'enum', 'default': '700d', 'kind': 'control', 'min': None, 'max': None, 'choices': ['700d', '700c', '700e', '1600', '2020'], 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'FreeDV waveform. 700D is the robust choice heard on QO-100; 1600 and 2020 sound better on a strong signal. Only those the installed libcodec2 can open are usable (caps lists them).'},
    'amWidth': {'type': 'float', 'default': 3000.0, 'kind': 'control', 'min': 1000.0, 'max': 5000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'AM filter, either side of carrier.'},
    'agc': {'type': 'enum', 'default': 'medium', 'kind': 'control', 'min': None, 'max': None, 'choices': ['off', 'fast', 'medium', 'slow'], 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'rfGain': {'type': 'float', 'default': 0.0, 'kind': 'control', 'min': -20.0, 'max': 60.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': False, 'restart': False, 'help': 'Fixed audio gain when AGC is off.'},
    'nb': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Impulse noise blanker.'},
    'nbThreshold': {'type': 'float', 'default': 8.0, 'kind': 'control', 'min': 3.0, 'max': 30.0, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Blank samples this many times the mean level.'},
    'nr': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': "Noise reduction (WDSP's NR2) on what you hear in USB, LSB, CW and AM. Decoders always get the audio without it."},
    'nrStrength': {'type': 'float', 'default': 50.0, 'kind': 'control', 'min': 0.0, 'max': 100.0, 'choices': None, 'unit': '%', 'persist': True, 'auth': False, 'restart': False, 'help': 'How far noise reduction may pull the noise down: 0 % leaves the audio untouched, 100 % up to 40 dB.'},
    'volume': {'type': 'float', 'default': 0.5, 'kind': 'control', 'min': 0.0, 'max': 1.0, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'mute': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'txGain': {'type': 'float', 'default': -40.0, 'kind': 'control', 'min': -89.75, 'max': 0.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': False, 'restart': False, 'help': 'SDR transmit gain. Cannot exceed txGainCeiling.'},
    'micGain': {'type': 'float', 'default': 0.0, 'kind': 'control', 'min': -20.0, 'max': 30.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'compressor': {'type': 'float', 'default': 6.0, 'kind': 'control', 'min': 0.0, 'max': 20.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': False, 'restart': False, 'help': 'Speech compression (0 = off).'},
    'txFilterLo': {'type': 'float', 'default': 300.0, 'kind': 'setting', 'min': 50.0, 'max': 1000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'txFilterHi': {'type': 'float', 'default': 2700.0, 'kind': 'setting', 'min': 1500.0, 'max': 2950.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'Transmit audio high edge. The occupied width (high - low) may not exceed 2.7 kHz.'},
    'monitor': {'type': 'bool', 'default': False, 'kind': 'control', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Hear your own transmit audio.'},
    'monitorLevel': {'type': 'float', 'default': 0.3, 'kind': 'control', 'min': 0.0, 'max': 1.0, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'cwWpm': {'type': 'float', 'default': 20.0, 'kind': 'control', 'min': 5.0, 'max': 50.0, 'choices': None, 'unit': 'wpm', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'pttMode': {'type': 'enum', 'default': 'hold', 'kind': 'control', 'min': None, 'max': None, 'choices': ['hold', 'toggle'], 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': "How the UI's space bar keys (UI-side)."},
    'txGainCeiling': {'type': 'float', 'default': -10.0, 'kind': 'setting', 'min': -89.75, 'max': 0.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': True, 'restart': False, 'help': 'The most transmit gain any control can set.'},
    'txTimeoutSec': {'type': 'float', 'default': 300.0, 'kind': 'setting', 'min': 10.0, 'max': 1800.0, 'choices': None, 'unit': 's', 'persist': True, 'auth': True, 'restart': False, 'help': 'Unkey after this long transmitting.'},
    'deadAirSec': {'type': 'float', 'default': 3.0, 'kind': 'setting', 'min': 1.0, 'max': 30.0, 'choices': None, 'unit': 's', 'persist': True, 'auth': True, 'restart': False, 'help': 'Voice modes: unkey after this long with no microphone audio.'},
    'watchdogSec': {'type': 'float', 'default': 2.0, 'kind': 'setting', 'min': 0.5, 'max': 10.0, 'choices': None, 'unit': 's', 'persist': True, 'auth': True, 'restart': False, 'help': 'Unkey if the user interface stops servicing the engine for this long.'},
    'wideBins': {'type': 'int', 'default': 2048, 'kind': 'control', 'min': 256, 'max': 8192, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'Bins across the wide scope.'},
    'wideAvg': {'type': 'int', 'default': 2, 'kind': 'control', 'min': 1, 'max': 16, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': 'FFTs averaged per wide line.'},
    'zoomSpanHz': {'type': 'float', 'default': 12000.0, 'kind': 'control', 'min': 2000.0, 'max': 50000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'zoomBins': {'type': 'int', 'default': 1024, 'kind': 'control', 'min': 128, 'max': 4096, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'zoomAvg': {'type': 'int', 'default': 2, 'kind': 'control', 'min': 1, 'max': 16, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'zoomPan': {'type': 'float', 'default': 0.0, 'kind': 'control', 'min': -25000.0, 'max': 25000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': False, 'help': 'Zoom scope centre relative to the receive dial.'},
    'scopeFps': {'type': 'float', 'default': 20.0, 'kind': 'control', 'min': 1.0, 'max': 50.0, 'choices': None, 'unit': 'lines/s', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'audioBackend': {'type': 'enum', 'default': 'portaudio', 'kind': 'setting', 'min': None, 'max': None, 'choices': ['portaudio', 'null'], 'unit': '', 'persist': True, 'auth': False, 'restart': True, 'help': 'null runs with no sound card (headless, tests).'},
    'audioIn': {'type': 'str', 'default': '', 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': True, 'help': 'Microphone device name; empty for the system default.'},
    'audioOut': {'type': 'str', 'default': '', 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': True, 'help': 'Speaker device name; empty for the system default.'},
    'audioOut2': {'type': 'str', 'default': '', 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': True, 'help': 'Optional second output carrying receive audio to other software (e.g. a loopback device).'},
    'callsign': {'type': 'str', 'default': '', 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'locator': {'type': 'str', 'default': '', 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': False, 'help': ''},
    'simRxErrorHz': {'type': 'float', 'default': 1800.0, 'kind': 'setting', 'min': -60000.0, 'max': 60000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': True, 'help': 'Simulated LNB error at start: how far high everything appears.'},
    'simDriftHz': {'type': 'float', 'default': 400.0, 'kind': 'setting', 'min': 0.0, 'max': 20000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': True, 'help': "Size of the simulated LNB's slow wander."},
    'simDriftSec': {'type': 'float', 'default': 600.0, 'kind': 'setting', 'min': 10.0, 'max': 7200.0, 'choices': None, 'unit': 's', 'persist': True, 'auth': False, 'restart': True, 'help': "Timescale of the simulated LNB's wander."},
    'simUlErrorHz': {'type': 'float', 'default': -11000.0, 'kind': 'setting', 'min': -70000.0, 'max': 70000.0, 'choices': None, 'unit': 'Hz', 'persist': True, 'auth': False, 'restart': True, 'help': 'Simulated SDR transmit error: where our signal really goes, relative to where we aim it.'},
    'simRefGainDb': {'type': 'float', 'default': -20.0, 'kind': 'setting', 'min': -89.75, 'max': 0.0, 'choices': None, 'unit': 'dB', 'persist': True, 'auth': False, 'restart': True, 'help': 'Transmit gain at which our simulated downlink equals the beacon.'},
    'simSignals': {'type': 'bool', 'default': True, 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': True, 'help': 'Populate the simulated band with other stations.'},
    'simSeed': {'type': 'int', 'default': 0, 'kind': 'setting', 'min': 0, 'max': 2147483647, 'choices': None, 'unit': '', 'persist': True, 'auth': False, 'restart': True, 'help': '0 = different every run.'},
    'simRealtime': {'type': 'bool', 'default': True, 'kind': 'setting', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': True, 'help': 'Pace the simulator to real time (tests turn this off to run faster).'},
    'running': {'type': 'bool', 'default': False, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'The engine has the device open and is receiving.'},
    'keyed': {'type': 'bool', 'default': False, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Transmitting.'},
    # txSource's help deliberately changed (08/10): a voice memory keys as
    # voice:<n> (ohscore/keyer.py).
    'txSource': {'type': 'str', 'default': '', 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'What is keying: ptt, send:<mode>, tune, voice:<n> (voice memory n).'},
    'txSeconds': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Seconds into the current transmission.'},
    'txOnAir': {'type': 'bool', 'default': False, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'The over is on the air: past its slot wait and key-up. keyed is true from the moment an over is queued, so a timed FT8 over is keyed for most of the slot before it; this is what an on-air light should follow.'},
    'txStartAt': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': "When the queued over's audio is due (UTC seconds), for a timed one (FT8, FT4, Q65, JS8); 0 otherwise."},
    'canTx': {'type': 'bool', 'default': False, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'The open device can transmit.'},
    'txBlocked': {'type': 'str', 'default': '', 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': "Why keying here would be refused right now ('' = it would not)."},
    'rxDial': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Downlink the receiver is demodulating (vfo + RIT).'},
    'txDial': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Downlink our transmission is meant to land on (txVfo or vfo, + XIT).'},
    'txUl': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Uplink we are aiming at, including txCorr.'},
    'segment': {'type': 'str', 'default': '', 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Bandplan segment under the receive dial.'},
    'rxLock': {'type': 'str', 'default': 'off', 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Beacon lock: searching, locked, lost (Auto), hold, manual; off before the radio starts.'},
    'rxErr': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Last measured beacon error after correction, Hz.'},
    'rxRate': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Drift rate, Hz/s.'},
    'rxSnr': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Beacon SNR in 2.5 kHz, dB.'},
    'beaconUsed': {'type': 'str', 'default': '', 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Which beacon is steering rxCorr.'},
    'beaconLevel': {'type': 'float', 'default': -200.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Beacon power, dBFS.'},
    'txLockState': {'type': 'str', 'default': 'idle', 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'TX lock: idle, searching (own signal not yet found this over), landed (found txErr off the dial; correcting), locked.'},
    'txErr': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Last measured own-signal error, Hz.'},
    'txConfidence': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Peak-to-noise of the last own-signal measurement.'},
    'ownDl': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Where our own signal was last seen landing (corrected downlink, dial frequency).'},
    'vsBeacon': {'type': 'float', 'default': None, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Own downlink level relative to the beacon, dB (None until measured).'},
    'txPpm': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'txCorr as parts per million of the uplink.'},
    'fs': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Device sample rate.'},
    # 'cpu's help text deliberately changed (07/10): it used to be wall-clock
    # time per receive block, which counted waiting for the GIL as work
    # done; it is now that thread's own CPU time, and the wait it used to
    # hide is the new 'cpuWait' key (ADDED_SINCE) - "change it here too".
    'cpu': {'type': 'float', 'default': 0.0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': "Receive thread's own CPU time (time.thread_time()) as a fraction of real time."},
    # 'overruns's help text deliberately changed (17/10/2026): it counted
    # every block processed slower than real time, which made each slow
    # window action look like lost receive; behind the prefetch queue
    # (ohscore/rxprefetch.py) it counts samples actually lost, and the slow
    # blocks are the new 'rxLate' (ADDED_SINCE) - "change it here too".
    'overruns': {'type': 'int', 'default': 0, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': "Times receive lost samples: the radio's stream had a gap (a stalled link, a busy USB bus) or processing fell more than two seconds behind. On a device read without the prefetch queue (ohscore/rxprefetch.py), blocks processed slower than real time, the best sign of loss there is."},
    'deviceStatus': {'type': 'dict', 'default': {}, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Device status, shown verbatim.'},
    'audio': {'type': 'dict', 'default': {}, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Audio status: devices, rates, buffer fill.'},
    'modes': {'type': 'dict', 'default': {}, 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Per mode: whether it can decode/encode here, or the sentence saying what to install.'},
    'error': {'type': 'str', 'default': '', 'kind': 'status', 'min': None, 'max': None, 'choices': None, 'unit': '', 'persist': False, 'auth': False, 'restart': False, 'help': 'Why the engine is not running, if it is not.'},
}


# Keys added since the split, deliberately; everything else must still be
# exactly as it was. The external transmitter (ohsnb/extrig.py, 05/10):
ADDED_SINCE = {"txRadio", "civPort", "civBaud", "civAddress", "rigctldHost", "rigctldPort", "rigIfBand", "rigPollMs", "rigRxFollows", "rigAudio", "rigAudioLowerDb",
               "rigTxCorr", "rigTxCorrTrusted", "rigLink", "rigError", "rigFreq", "rigKeyed", "rigMode",
               "rigAimDl", "rigTxBlocked",
               # CAT PTT for digital modes (12/10/2026, ohsnb/extrig.py CatPtt).
               "rigCatPtt", "rigTxAudioOut", "rigTxAudioDb", "rigPttDelayMs", "rigPttTailMs", "rigCatKeyed",
               "rigModInput",
               # The IC-9700 setup assistant's record for its restore (12/10/2026, ohsnb/rigsetup.py).
               "rigSetupSaved",
               # TX lock's limit on the IC-9700's correction (14/10/2026, Radio._rig_unkeyed).
               "rigTxCorrMaxHz",
               # Beacon lock's modes and click-to-lock (0.1.4): beaconLock (on/off)
               # became beaconMode (ohsnb/config.py migrates it), and rxLock's
               # help above names the new states.
               "rxCorrHand", "beaconMode", "rxWindow", "rxReject",
               # The IC-9700 taken out of FM (08/10, ohsnb/extrig.py).
               "rigFmToSsb",
               # The FT8 sequencer's DX call, for jt9 -x (06/10).
               "dxCall",
               # The multimedia beacon's receiver (06/10, ohsnb/beaconrx.py).
               "mmbDecode", "mmbState", "mmbMer", "mmbFrames", "mmbLost", "mmbLast", "mmbFreq", "mmbCpu",
               # Converters (07/10): the shared list, the LNB chosen from it, and
               # each transmitter's upconverter (ohsnb/converters.py).
               "converters", "rxConverter", "txConverter", "rigTxConverter",
               # IQ recording (07/10, ohscore/sigmf.py): its time limit and
               # the status the REC item shows.
               "recLimitMin", "recording", "recFile", "recSeconds", "recBytes", "recDropped",
               # Auto-tune and best audio (07/10, ohscore/dsp/autotune.py, autoaudio.py).
               "autoBusy", "autoTune", "autoTuneRefused", "autoAudio", "autoAudioWhy", "autoAudioRefused",
               # IQ playback (07/10, ohscore/devices/filedev.py): looping, and the
               # status the PLAYBACK item shows.
               "playLoop", "playing", "playFile", "playPos", "playLength", "playUtc", "playEnded",
               # Dish alignment (07/10, ohsnb/dishmeter.py): its tone, phone page
               # and port, and the numbers it shows.
               "dishTone", "dishPhone", "dishPort", "dishOpen", "dishSnr", "dishBest", "dishRise", "dishWhere",
               "dishGain", "dishUrls", "dishPhoneError",
               # ... and the gain it holds, marked in a recording (17/10/2026,
               # Mac test finding 11: the hold was said nowhere but the dialog).
               "dishHeldDb",
               # Self-update (07/10, ohscore/update.py, ohscore/ui/update.py): the
               # setting that turns the automatic check off.
               "checkUpdates",
               # Mode auto-tune (07/10, ohscore/engine.py Engine.set_mode_tuned):
               # the Settings toggle for tuning to a mode's usual frequency.
               "modeAutoTune",
               # Honest CPU readout (07/10, ohscore/engine.py Engine._rx_loop):
               # the GIL/scheduler wait that 'cpu' used to hide (see its own
               # comment above).
               "cpuWait",
               # Receive lost and late said apart (17/10/2026, ohscore/rxprefetch.py),
               # and a recording's gaps in the radio's stream apart from the disk's.
               "rxLate", "rxLostS", "rxBehindS", "recRxLost",
               # ... and what share of the stream arrived lately (17/10/2026,
               # Windows test: "1.2 MS/s" while 37 % of it was arriving).
               "rxStreamPct",
               # HSmodem station to station (07/10, ohscore/modes/hsmodem.py):
               # the speed both ends must agree on, sending and receiving.
               "hsSpeed",
               # ohsdigi the FT8/FT4 decoder (07/10, ohscore/modes/ft8.py): the
               # setting that puts jt9 first, and which decoder is in use.
               "ft8Decoder", "ft8DecoderInUse",
               # A chosen mode with no decoder says so (10/10, ohscore/engine.py
               # Engine._swap_decoder): 0.1.10-beta.1's store FT8 was silent.
               "decoderMissing",
               # The transmit card's one standing warning (08/10,
               # ohscore/engine.py Engine.tx_warn), instead of stacked toasts.
               "txWarning",
               # The SIMULATOR badge (08/10, ohscore/engine.py Engine._sim_status):
               # why the open device is the simulator, and whether it stood in.
               "simWhy", "simFallback",
               # PSKReporter spotting (08/10, ohscore/pskreporter.py): opt-in.
               "pskReporter",
               # The voice keyer (08/10, ohscore/keyer.py Engine.send_voice):
               # the CQ loop and its pause.
               "keyerRepeat", "keyerRepeatSec",
               # Auto-tune listening until sure (08/10, autotune.Listener):
               # the seconds heard so far.
               "autoHeard",
               # International use (08/10, ohscore/countries.py, ohscore/licences):
               # where the station is, the licence in force, and its status.
               "stationCountry", "licence", "licenceClass", "stationConditions", "customLicence", "station",
               # The middle beacon's text (08/10, ohsnb/beacontext.py, ohsnb/dsp/ao40.py).
               "midTextDecode", "midTextState", "midTextSnr", "midTextFrames", "midTextLost", "midTextLast",
               "midTextFreq",
               # KG-STV pictures (08/10, ohsnb/kgstvrx.py, ohscore/dsp/kgstv.py).
               "kgstvDecode", "kgstvState", "kgstvFrames", "kgstvLost", "kgstvLast", "kgstvCall", "kgstvFreq",
               # The band skimmer (08/10, ohsnb/skimmer.py, ohsnb/dsp/skim.py).
               "skimDecode", "skimBudget", "skimState", "skimSignals", "skimExact", "skimCpu", "skimLevel",
               "skimLooks", "skimDropped",
               # The over-power and LEILA watch (17/10, ohsnb/overpower.py, ohsnb/dsp/overpower.py).
               "opWatch", "leilaCapture", "opState", "opBeacon", "opActive", "opLeila", "opCpu", "opDropped",
               "opCapture",
               # The SoapySDR receiver's antenna input (12/10, an RSPdx's Antenna C).
               "soapyAntenna",
               # Decoder sessions (22/10/2026, ohscore/decoders.py, Radio's SDR
               # milestone 1): how many, their processor share, the saved
               # sessions, and their status.
               "decodersMax", "decodeCpuMax", "decoderSessions", "decoders"}
# Keys removed since, deliberately: the LNB's LO and the IC-9700's
# upconverter LO and side became converter choices (07/10; ohsnb/config.py
# migrates them - upconverterLo and upconverterSide had been added after
# the split, so only lnbLo was ever in PRE_SPLIT).
REMOVED_SINCE = {"lnbLo"}


class NbSpecUnchanged(unittest.TestCase):
    def test_same_keys_in_the_same_order(self):
        self.assertEqual([k for k in state.SPEC if k not in ADDED_SINCE],
                         [k for k in PRE_SPLIT if k not in REMOVED_SINCE])
        self.assertFalse(REMOVED_SINCE & set(state.SPEC))
        self.assertLessEqual(ADDED_SINCE, set(state.SPEC))

    def test_every_field_of_every_key_is_identical(self):
        # repr, not ==: 1 == 1.0 in Python, but an int limit where a float
        # was is a change coerce() would show.
        for k, spec in PRE_SPLIT.items():
            if k in REMOVED_SINCE:
                continue
            self.assertEqual(repr(state.SPEC[k]), repr(spec), k)

    def test_mode_choices_are_the_mode_list_itself(self):
        self.assertIs(state.SPEC["mode"]["choices"], state.MODES)


class Machinery(unittest.TestCase):
    def setUp(self):
        self.reg = Registry(["usb"], set())
        add_shared_keys(self.reg)

    def test_keys_added_after_an_anchor_follow_it_in_order(self):
        with self.reg.after("rxGain"):
            self.reg.add("a", "bool", False, "setting")
            self.reg.add("b", "bool", False, "setting")
        keys = list(self.reg.spec)
        i = keys.index("rxGain")
        self.assertEqual(keys[i + 1:i + 3], ["a", "b"])
        self.reg.add("c", "bool", False, "setting")
        self.assertEqual(list(self.reg.spec)[-1], "c")

    def test_override_changes_fields_in_place_and_refuses_unknown_ones(self):
        self.reg.override("vfo", lo=1.0, hi=2.0, default=1.5)
        self.assertEqual(self.reg.coerce("vfo", 1.5), 1.5)
        with self.assertRaisesRegex(ValueError, "cannot be above 2"):
            self.reg.coerce("vfo", 3.0)
        with self.assertRaises(KeyError):
            self.reg.override("vfo", colour="red")

    def test_rules_run_in_the_order_added(self):
        seen = []
        self.reg.rule(lambda st: seen.append(1))
        self.reg.rule(lambda st: seen.append(2))
        st = self.reg.defaults()
        self.reg.check_combined(st)
        self.assertEqual(seen, [1, 2])
        st["filterHi"] = st["filterLo"] + 50
        with self.assertRaisesRegex(ValueError, "at least 100 Hz"):
            self.reg.check_combined(st)

    def test_the_shared_keys_carry_no_qo100_assumptions(self):
        # The core's own defaults must not be a QO-100 downlink: an app that
        # forgot to set its dial range would otherwise inherit NB's.
        self.assertIsNone(self.reg.spec["vfo"]["max"])
        self.assertNotIn("lnbLo", self.reg.spec)
        self.assertNotIn("txGain", self.reg.spec)


if __name__ == "__main__":
    unittest.main()
