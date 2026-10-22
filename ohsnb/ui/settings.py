"""QO-100 NB's Settings: the shared dialog (ohscore/ui/settings.py) with
the LNB & locks page, the Transmitter page (the Pluto, or an IC-9700 NB
tunes, and keys only for its digital modes when allowed), the Converters page (the shared list, and which is
the LNB and which each transmitter's upconverter), the power limits and
level guard on Transmit & safety, the transponder simulator's settings,
and NB's words for its keys."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QCursor
from PyQt6.QtWidgets import QApplication, QComboBox, QHBoxLayout, QLabel, QWidget

from ohscore.ui import settings as core
from ohscore.ui import theme
from ohscore.ui.controls import Button
from ohsnb.i18n import _


def _hex_address(text: str) -> int:
    t = text.lower().removeprefix("0x").removesuffix("h")
    try:
        return int(t, 16)
    except ValueError:
        raise ValueError(_("CI-V address: a hex number such as A2")) from None


def _tcp_port(text: str) -> int:
    try:
        return int(text)
    except ValueError:
        raise ValueError(_("rigctld port: a number such as 4532")) from None


class SettingsDialog(core.SettingsDialog):
    PAGES = [("star", "Station", "page_station"), ("antenna", "Radio", "page_radio"),
             ("lock", "Licence", "page_licence"),
             ("send", "Transmitter", "page_transmitter"), ("satellite", "LNB & locks", "page_lnb"),
             ("waves", "Converters", "page_converters"), ("lock", "Transmit & safety", "page_transmit"),
             ("mic", "Audio", "page_audio"), ("waves", "Display", "page_display"),
             ("screen", "Second display", "page_second"), ("link", "Controller", "page_controller"), ("keyboard", "Control pad", "page_pad"),
             ("gear", "Simulator", "page_simulator")]
    LABELS = {**core.LABELS,
              "beaconMode": "Beacon lock", "beacon": "Lock to",
              "beaconSearchHz": "Beacon search range", "txLock": "TX lock", "lnbGpsLocked": "LNB is GPS-locked",
              "rttSec": "Satellite round trip", "levelMode": "Level guard",
              "mmbDecode": "Receive the multimedia beacon",
              "midTextDecode": "Decode the middle beacon's text",
              "kgstvDecode": "Receive KG-STV pictures",
              "skimDecode": "Skim the whole band", "skimBudget": "Band skimmer's share of the CPU",
              "opWatch": "Watch for signals over the beacon and LEILA",
              "leilaCapture": "Keep LEILA evidence (20 s of IQ)",
              "levelMarginDb": "Margin under the beacon", "txGainCeiling": "TX gain ceiling",
              "simRxErrorHz": "Simulated LNB error", "simDriftHz": "Simulated drift",
              "simUlErrorHz": "Simulated TX error", "simRefGainDb": "Gain where our signal equals the beacon",
              "simDriftSec": "Drift timescale",
              "txRadio": "Transmitter", "civPort": "CI-V port", "civBaud": "CI-V baud rate",
              "civAddress": "CI-V address (hex)", "rigctldHost": "rigctld host", "rigctldPort": "rigctld port",
              "rxConverter": "LNB", "txConverter": "Pluto's upconverter", "rigTxConverter": "IC-9700's upconverter",
              "rigIfBand": "IC-9700 band (the IF)",
              "rigPollMs": "Poll interval", "rigTxCorrMaxHz": "Largest TX lock correction", "rigRxFollows": "Receive dial follows the radio's knob",
              "rigFmToSsb": "Switch the radio from FM to SSB",
              "rigAudio": "Receive audio while it transmits", "rigAudioLowerDb": "Lower by",
              "rigCatPtt": "Key the IC-9700 for digital modes (CAT PTT)", "rigTxAudioOut": "IC-9700 sound device",
              "rigTxAudioDb": "Digital audio level", "rigPttDelayMs": "Delay before audio (PA and relays)",
              "rigPttTailMs": "Tail before unkeying"}
    CHOICE_LABELS = {**core.CHOICE_LABELS,
                     "sampleRate": {600000: "600 kS/s", 1200000: "1.2 MS/s"},
                     "beacon": {"middle": "Middle (BPSK)", "lower": "Lower (CW)"},
                     "beaconMode": {"auto": "Auto", "hold": "Hold", "manual": "Manual"},
                     "levelMode": {"manual": "Warn only", "limit": "Limit", "auto": "Automatic"},
                     "txRadio": {"sdr": "SDR (Pluto)", "civ": "IC-9700 (CI-V)", "rigctld": "Hamlib rigctld"},
                     "rigIfBand": {"23cm": "23 cm", "70cm": "70 cm", "2m": "2 m"},
                     "rigAudio": {"mute": "Mute", "lower": "Lower", "keep": "Keep playing"}}
    EXTRA_HELP = {**core.EXTRA_HELP,
                  "civAddress": "The radio's CI-V address. The IC-9700's default is A2."}
    STEPS = {**core.STEPS, "beaconSearchHz": 1000, "rttSec": 0.005, "levelMarginDb": 1, "txGainCeiling": 0.25,
             "simRxErrorHz": 100, "simDriftHz": 50, "simUlErrorHz": 100, "simRefGainDb": 0.5, "simDriftSec": 10,
             "rigPollMs": 10, "rigTxCorrMaxHz": 50, "rigAudioLowerDb": 1, "rigTxAudioDb": 1, "rigPttDelayMs": 10, "rigPttTailMs": 10}
    SIM_KEYS = ("simSignals", "simRxErrorHz", "simDriftHz", "simDriftSec", "simUlErrorHz", "simRefGainDb")
    SIM_TEXT = ("The simulated transponder used when Radio is 'Simulator': no dish, and no licence needed to try "
                "everything, transmitting included - nothing it sends leaves this computer. Changes restart the "
                "radio.")

    def unit_fmt(self, key):
        if key == "beaconSearchHz":
            return lambda v: f"±{v / 1000:.0f} kHz"
        return super().unit_fmt(key)

    TYPED_FIELDS = {"civAddress": (lambda v: f"{int(v):02X}", _hex_address, "A2"),
                    "rigctldPort": (lambda v: str(int(v)), _tcp_port, "4532")}
    RIG_LINK_KEYS = ("txRadio", "civPort", "civBaud", "civAddress", "rigctldHost", "rigctldPort")

    def page_transmitter(self) -> QWidget:
        sc, lay = self._scroll(self.tr("Transmitter"), self.tr("What transmits: the SDR, keyed by OpenHamShack QO-100 "
                                                               "NB, or an IC-9700 (through an upconverter to 13 cm) "
                                                               "that you key yourself for voice, and NB keys for its "
                                                               "digital modes only if you allow it below."))
        self._add(lay, "txRadio")
        self.keys_note = QLabel("")
        self.keys_note.setObjectName("Faint")
        self.keys_note.setWordWrap(True)
        lay.addWidget(self.keys_note)
        self._section(lay, self.tr("IC-9700 over USB (CI-V)"))
        port = self._add(lay, "civPort")
        find = Button(self.tr("Find"), icon="antenna", small=True)
        find.clicked.connect(self.find_serial)
        self.serial_found = QComboBox()
        self.serial_found.hide()
        self.serial_found.activated.connect(
            lambda _i: port.w.setText(self.serial_found.currentData() or port.w.text()))
        r = QHBoxLayout()
        r.addWidget(find)
        r.addWidget(self.serial_found, 1)
        r.addStretch(1)
        lay.addLayout(r)
        self._add(lay, "civBaud")
        self._add(lay, "civAddress")
        self._section(lay, self.tr("Hamlib rigctld"))
        self._add(lay, "rigctldHost")
        self._add(lay, "rigctldPort")
        r = QHBoxLayout()
        test = Button(self.tr("Test connection"), icon="check", small=True)
        test.setToolTip(self.tr("Reads the radio's frequency once, with the settings above. Sends nothing else."))
        test.clicked.connect(self.test_rig)
        r.addWidget(test)
        self.rig_result = QLabel("")
        self.rig_result.setWordWrap(True)
        self.rig_result.setTextFormat(Qt.TextFormat.PlainText)
        r.addWidget(self.rig_result, 1)
        lay.addLayout(r)
        self._section(lay, self.tr("Upconverter"))
        self._pointer(lay, self.tr("The IC-9700's upconverter (its LO, and whether it is high-side) is chosen on the "
                                   "Converters page, from the list there."))
        self._add(lay, "rigIfBand")
        self._section(lay, self.tr("Following the radio"))
        self._add(lay, "rigRxFollows")
        self._add(lay, "rigFmToSsb")
        self._add(lay, "rigPollMs")
        self._section(lay, self.tr("TX lock"))
        self._add(lay, "rigTxCorrMaxHz")
        self._section(lay, self.tr("Receive audio while it transmits"))
        self._add(lay, "rigAudio")
        self._add(lay, "rigAudioLowerDb")
        self._section(lay, self.tr("Digital modes by CAT"))
        r = QHBoxLayout()
        setup = Button(self.tr("IC-9700 setup…"), icon="gear", small=True)
        setup.setToolTip(self.tr("Finds the radio's CI-V address and sound device, checks and sets DATA MOD, "
                                 "satellite mode and the band on MAIN with your say-so (and puts them back on "
                                 "request), and sets the audio level into a dummy load."))
        setup.clicked.connect(self.open_rig_setup)
        r.addWidget(setup)
        diagnose = Button(self.tr("IC-9700 diagnostic…"), small=True)
        diagnose.setToolTip(self.tr("A report on the radio and its connection to send to the people who write NB: "
                                    "reads only, or with a few short overs into a dummy load."))
        diagnose.clicked.connect(self.open_rig_diagnostic)
        r.addWidget(diagnose)
        r.addStretch(1)
        lay.addLayout(r)
        cat = self._add(lay, "rigCatPtt")
        cat.w.toggled.connect(lambda on: self._keys_note(bool(on)))
        cap = QLabel(self.LABELS["rigTxAudioOut"])
        cap.setObjectName("Muted")
        lay.addWidget(cap)
        self.rig_audio = QComboBox()
        self.rig_audio.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.rig_audio.setMinimumContentsLength(24)
        lay.addWidget(self.rig_audio)
        self._pointer(lay, self.spec["rigTxAudioOut"]["help"])
        self._fill_rig_audio()
        self._add(lay, "rigTxAudioDb")
        self._add(lay, "rigPttDelayMs")
        self._add(lay, "rigPttTailMs")
        self._pointer(lay, self.tr("On the IC-9700: SET > Connectors > MOD Input > DATA MOD = USB. NB reads it and "
                                   "will not key the radio while it is anything without USB."))
        self._keys_note(bool(self.st.get("rigCatPtt")))
        lay.addStretch(1)
        return sc

    def open_rig_setup(self):
        """The IC-9700 setup assistant's window (ohsnb/ui/rigsetup.py), over
        this dialog: what it finds goes into these fields, unsaved."""
        from ohsnb.ui.rigsetup import RigSetupDialog
        self.rig_setup = RigSetupDialog(self)
        self.rig_setup.show()
        return self.rig_setup

    def open_rig_diagnostic(self):
        """The IC-9700 diagnostic's window (ohsnb/ui/rigdiag.py)."""
        from ohsnb.ui.rigdiag import RigDiagnosticDialog
        self.rig_diagnostic = RigDiagnosticDialog(self)
        self.rig_diagnostic.show()
        return self.rig_diagnostic

    def _keys_note(self, cat: bool) -> None:
        """What NB does with an IC-9700, as the CAT PTT toggle now stands
        (both sentences: until 12/10/2026 there was only the first)."""
        if cat:
            text = self.tr("OpenHamShack QO-100 NB keys the IC-9700 by CAT for its own digital-mode overs - Enable "
                           "TX in FT8 and FT4, and the lines you send in PSK, RTTY and CW - putting it in USB-D and "
                           "sending the audio to its USB sound device, after every check NB makes on its own "
                           "transmitter. Halt TX, Escape or Enable TX off unkeys it at once. For voice you still key "
                           "the radio yourself: NB never keys it for speech. NB also tunes it, follows its knob, "
                           "shows and corrects where it lands, and mutes receive audio while it transmits.")
        else:
            text = self.tr("OpenHamShack QO-100 NB never keys the IC-9700: you transmit with the radio's own PTT. "
                           "NB puts it on the frequency the dial shows, follows its knob, shows on the scope where "
                           "your signal lands, corrects it between overs from a CW carrier, measures your level "
                           "against the beacon, and mutes receive audio while you transmit. Its warnings about "
                           "where you are aimed are advice: NB cannot stop the radio transmitting.")
        self.keys_note.setText(text)

    def _fill_rig_audio(self) -> None:
        """The IC-9700's sound device: an output, by name, never "System
        default" (rigTxAudioOut's help says why)."""
        from ohscore import audio
        try:
            devs = audio.list_devices()
        except Exception:  # noqa: BLE001 - PortAudio fails in many ways; the list is just empty
            devs = []
        cur = self.st.get("rigTxAudioOut", "")
        cb = self.rig_audio
        cb.clear()
        cb.addItem(self.tr("None chosen"), "")
        for d in devs:
            if d["outputs"] > 0:
                core.add_device(cb, d)
        i = core.find_device(cb, cur)
        if i < 0 and cur:
            i = core.add_missing_device(cb, cur, self.tr("{device} (not connected)").format(
                device=audio.display_name(cur)))
        cb.setCurrentIndex(max(0, i))

    def find_serial(self):
        try:
            from serial.tools import list_ports
        except ImportError:
            from ohscore import host
            self._say(host.hint("pyserial"))
            return
        ports = sorted(list_ports.comports(), key=lambda p: p.device)
        self.serial_found.clear()
        for p in ports:
            self.serial_found.addItem(f"{p.device}  —  {p.description}", p.device)
        if not ports:
            self._say(self.tr("No serial ports found. Is the IC-9700 switched on and its USB cable connected (and, "
                              "on Windows, Icom's USB driver installed)?"))
            self.serial_found.hide()
        else:
            self.serial_found.show()
            self._say("")

    def test_rig(self):
        """Read the radio's frequency once with the link settings as typed
        here (not yet saved): the engine does the reading."""
        from ohscore.rig import RigError
        changes = {}
        try:
            for k in self.RIG_LINK_KEYS:
                if k in self.fields:
                    changes[k] = self.fields[k].get()
        except ValueError as e:
            self._rig_say(str(e), False)
            return
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))
        try:
            text = self.bridge.radio.test_rig(changes)
            ok = True
        except (RigError, ValueError, OSError) as e:
            text, ok = str(e), False
        finally:
            QApplication.restoreOverrideCursor()
        self._rig_say(text, ok)

    def _rig_say(self, text: str, ok: bool):
        self.rig_result.setText(text)
        self.rig_result.setStyleSheet(f"color: {theme.t()['ok' if ok else 'err']};")

    def page_licence(self) -> QWidget:
        # Since 08/10/2026 the uplink is checked against the licence in force
        # (ohsnb/radio.py _uplink_refusal): a class with no 13 cm, or a
        # licence without the amateur-satellite service there, locks it.
        sc, lay = self._scroll(self.tr("Licence"), self.tr("Whose licence the station transmits under. OpenHamShack "
                                                           "QO-100 NB transmits to QO-100 only where that licence "
                                                           "allows your class an amateur-satellite uplink on "
                                                           "2400.050-2400.300 MHz."))
        self._licence_section(lay)
        lay.addStretch(1)
        return sc

    def page_lnb(self) -> QWidget:
        sc, lay = self._scroll(self.tr("LNB & locks"), self.tr("Frequency references, beacon lock (receive) and "
                                                               "own-signal lock (transmit)."))
        self._pointer(lay, self.tr("The LNB (its local oscillator: 9750 MHz for a standard 25 MHz-reference LNB) is "
                                   "chosen on the Converters page. Beacon lock measures its error; you do not need "
                                   "to know it."))
        self._add(lay, "lnbGpsLocked")
        self._section(lay, self.tr("Beacon lock"))
        self._add(lay, "beaconMode")
        self._add(lay, "beacon")
        self._add(lay, "beaconSearchHz")
        self._section(lay, self.tr("TX lock"))
        self._add(lay, "txLock")
        self._add(lay, "rttSec")
        self._section(lay, self.tr("Multimedia beacon"))
        self._add(lay, "mmbDecode")
        self._section(lay, self.tr("Middle beacon text"))
        self._add(lay, "midTextDecode")
        self._section(lay, self.tr("KG-STV pictures"))
        self._add(lay, "kgstvDecode")
        self._section(lay, self.tr("Band skimmer"))
        self._add(lay, "skimDecode")
        self._add(lay, "skimBudget")
        self._section(lay, self.tr("Over-power and LEILA"))
        self._add(lay, "opWatch")
        self._add(lay, "leilaCapture")
        lay.addStretch(1)
        return sc

    def _pointer(self, lay, text: str) -> None:
        n = QLabel(text)
        n.setObjectName("Faint")
        n.setWordWrap(True)
        lay.addWidget(n)

    # ------------------------------------------------------------ converters
    CONVERTER_PACKS = ("qo100", "vhf")
    CONVERTER_TEXT = ("The LNB, and any upconverter between a transmitter and 2400 MHz. The transponder's own "
                      "8089.5 MHz is not a converter: OpenHamShack QO-100 NB applies it itself.")
    CONVERTER_KEYS = ("rxConverter", "txConverter", "rigTxConverter")

    def _converter_ranges(self):
        from ohsnb import bandplan
        return [(bandplan.DL_LO, bandplan.DL_HI, "rx"), (bandplan.UL_LO, bandplan.UL_HI, "tx")]

    def _converter_uses(self, lay) -> None:
        from ohscore import converters as cv
        from ohsnb import converters as nbconv
        self._section(lay, self.tr("In use"))
        self.conv_combos = {}
        for key, none, ok in [("rxConverter", None, lambda d: not nbconv.rx_ok(cv.Converter.from_dict(d))),
                              ("txConverter", "None: the Pluto transmits on 2400 MHz itself",
                               lambda d: cv.Converter.from_dict(d).transmits),
                              ("rigTxConverter", "None chosen (the IC-9700 cannot transmit until one is)",
                               lambda d: cv.Converter.from_dict(d).transmits)]:
            cap = QLabel(self.LABELS[key])
            cap.setObjectName("Muted")
            lay.addWidget(cap)
            cb = self._converter_combo(self.st.get(key, ""), none, ok, key=key)
            self.conv_combos[key] = cb
            lay.addWidget(cb)
            h = QLabel(self.spec[key]["help"])
            h.setTextFormat(Qt.TextFormat.PlainText)
            h.setObjectName("Faint")
            h.setWordWrap(True)
            lay.addWidget(h)

    def _converter_in_use(self, title: str) -> str:
        for key, cb in getattr(self, "conv_combos", {}).items():
            if (cb.currentData() or "") == title:
                return f"it is the {self.LABELS[key]}"
        return ""

    def collect(self) -> dict:
        changes = super().collect()
        combos = dict(getattr(self, "conv_combos", {}))
        if getattr(self, "rig_audio", None) is not None:
            combos["rigTxAudioOut"] = self.rig_audio
        for key, cb in combos.items():
            v = cb.currentData() or ""
            if v != self.st.get(key, ""):
                changes[key] = v
        return changes

    def _transmit_limits(self, lay) -> None:
        # Power is the Pluto's gain in dB, held under a ceiling and, by the
        # level guard, under the beacon.
        self._add(lay, "txGainCeiling")
        self._add(lay, "levelMode")
        self._add(lay, "levelMarginDb")
