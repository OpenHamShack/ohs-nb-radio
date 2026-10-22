"""OpenHamShack Radio's Settings: the shared dialog (ohscore/ui/settings.py) with
the Licence & plan page, the Bands & power page (the power chain per band:
what turns drive into watts for the licence guard), the PTT sequencer, the
Hermes-Lite 2 and reference calibration on the Radio page, the band
simulator's settings, and HAM's words for its keys."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QComboBox, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from ohscore.devices import hl2
from ohscore.ui import settings as core
from ohscore.ui import theme
from ohscore.ui.controls import Button

from ohsradio.i18n import _

from .. import bands, plans, power, xvtr
from ..guard import watts


class SettingsDialog(core.SettingsDialog):
    PAGES = [("star", "Station", "page_station"), ("antenna", "Radio", "page_radio"),
             ("waves", "Decoders", "page_decoders"),
             ("lock", "Licence & plan", "page_licence"), ("waves", "Bands & power", "page_power"),
             ("antenna", "Converters", "page_converters"),
             ("lock", "Transmit & safety", "page_transmit"), ("antenna", "PTT sequencer", "page_sequencer"),
             ("mic", "Audio", "page_audio"), ("waves", "Display", "page_display"),
             ("screen", "Second display", "page_second"), ("link", "Controller", "page_controller"), ("keyboard", "Control pad", "page_pad"),
             ("gear", "Simulator", "page_simulator")]
    LABELS = {**core.LABELS,
              "sdrSerial": "Receiver serial", "sdrplayLna": "RSP LNA state",
              "decodersMax": "Decoders at once", "decodeCpuMax": "Processor share for decoders",
              "hl2Address": "Hermes-Lite 2 address", "hl2Rate": "Hermes-Lite 2 rate", "hl2Lna": "HL2 receiver gain",
              "hl2Pa": "HL2 power amplifier", "hl2TxSwapIQ": "Swap HL2 transmit I/Q",
              "ppm": "Reference error", "plan": "Band plan", "planGuard": "Band-plan guard",
              "tuneDrive": "Tune drive", "swrLimit": "SWR limit", "paTempLimit": "PA temperature limit",
              "toneburstMs": "Toneburst length", "ctcssLevel": "CTCSS level", "seqOutput": "PTT line",
              "seqPort": "Serial port", "seqLine": "Line", "seqDelayMs": "Sequence delay",
              "simHourUtc": "Time of day (UTC)", "simAntSwr": "Simulated antenna SWR",
              "cwSkim": "CW skimmer", "cwSkimSquelch": "CW skimmer squelch", "cwSkimMax": "CW skimmer channels",
              "cwSkimScp": "Download MASTER.SCP"}
    CHOICE_LABELS = {**core.CHOICE_LABELS,
                     "device": {"sim": "Simulator", "pluto": "Pluto family", "libresdr": "LibreSDR",
                                "hl2": "Hermes-Lite 2", "rtlsdr": "RTL-SDR (RX only)",
                                "sdrplay": "SDRplay RSP (RX only)", "soapy": "SoapySDR (RX only)"},
                     "sampleRate": {1200000: "1.2 MS/s", 2400000: "2.4 MS/s"},
                     "hl2Rate": {48000: "48 k", 96000: "96 k", 192000: "192 k", 384000: "384 k"},
                     "plan": {plans.AUTO: "Follow the country", **{pid: p.SHORT for pid, p in plans.PLANS.items()}},
                     "planGuard": {"warn": "Warn", "enforce": "Enforce", "off": "Off"},
                     "seqOutput": {"none": "None", "serial": "Serial RTS/DTR"},
                     "seqLine": {"rts": "RTS", "dtr": "DTR", "both": "Both"}}
    STEPS = {**core.STEPS, "hl2Lna": 1, "ppm": 0.05, "tuneDrive": 0.05, "swrLimit": 0.1, "paTempLimit": 1,
             "toneburstMs": 50, "ctcssLevel": 0.01, "seqDelayMs": 5, "simHourUtc": 0.5, "simAntSwr": 0.1,
             "cwSkimSquelch": 0.5, "cwSkimMax": 8, "decodeCpuMax": 0.05}
    SIM_KEYS = ("simSignals", "simHourUtc", "simAntSwr")
    SIM_TEXT = ("The simulated bands used when Radio is 'Simulator': 160 m to 6 cm with stations that come and go "
                "with the time of day, FM repeaters that open to the right tone, and a simulated antenna for the "
                "SWR guard. Changes restart the radio.")

    def unit_fmt(self, key):
        if key in ("tuneDrive", "ctcssLevel"):
            return lambda v: f"{v * 100:.0f} %"
        if key == "swrLimit":
            return lambda v: f"{v:.1f}:1"
        if key == "simHourUtc":
            return lambda v: self.tr("real time") if v < 0 else f"{int(v):02d}:{int(round((v % 1) * 60)):02d}"
        if key == "simAntSwr":
            return lambda v: f"{v:.1f}:1"
        if key == "decodeCpuMax":
            return lambda v: self.tr("{pct} % of a core").format(pct=f"{v * 100:.0f}")
        return super().unit_fmt(key)

    def page_station(self) -> QWidget:
        # The CW skimmer under Spotting, where the other thing that listens
        # for calls is (PSKReporter); its view is View › CW Activity, whose
        # switch is this same setting.
        sc = super().page_station()
        lay = sc.widget().layout()
        at = lay.count() - 1                      # before the trailing stretch
        tmp = QWidget()
        from PyQt6.QtWidgets import QVBoxLayout
        box = QVBoxLayout(tmp)
        box.setContentsMargins(0, 0, 0, 0)
        self._section(box, self.tr("CW skimmer"))
        self._add(box, "cwSkim")
        self._add(box, "cwSkimSquelch")
        self._add(box, "cwSkimMax")
        self._add(box, "cwSkimScp")
        lay.insertWidget(at, tmp)
        return sc

    def page_radio(self) -> QWidget:
        sc = super().page_radio()
        lay = sc.widget().layout()
        at = lay.count() - 1                      # before the trailing stretch
        tmp = QWidget()
        from PyQt6.QtWidgets import QVBoxLayout
        box = QVBoxLayout(tmp)
        box.setContentsMargins(0, 0, 0, 0)
        self._section(box, self.tr("Hermes-Lite 2"))
        f = self._add(box, "hl2Address", help_=self.tr("Empty: found by broadcast when the radio starts. Find lists "
                                                        "what answers now; pick one to fix its address. A radio on "
                                                        "another subnet: type its address, and Find asks it "
                                                        "directly."))
        find = Button(self.tr("Find"), icon="antenna", small=True)
        find.clicked.connect(self.find_hl2)
        self.hl2_found = QComboBox()
        self.hl2_found.hide()
        self.hl2_found.activated.connect(lambda _i: f.w.setText(self.hl2_found.currentData() or f.w.text()))
        r = QHBoxLayout()
        r.addWidget(find)
        r.addWidget(self.hl2_found, 1)
        r.addStretch(1)
        box.addLayout(r)
        self._add(box, "hl2Rate")
        self._add(box, "hl2Lna")
        self._add(box, "hl2Pa")
        self._add(box, "hl2TxSwapIQ")
        # The receivers shack_sdr reaches (ohscore/devices/sdrsource.py). What
        # the chosen one needs and does not have here - SDRplay's API above
        # all, which Radio never includes - is said under them, as the
        # device is picked, rather than only when Start fails.
        self._section(box, self.tr("RTL-SDR and SDRplay"))
        self._add(box, "sdrSerial")
        self._add(box, "sdrplayLna")
        self.sdr_why = QLabel()
        self.sdr_why.setWordWrap(True)
        self.sdr_why.setObjectName("Muted")
        box.addWidget(self.sdr_why)
        dev = self.fields.get("device")
        if dev is not None:
            dev.w.picked.connect(lambda v: self._show_sdr_why(v))
        self._show_sdr_why(str(self.st.get("device", "sim")))
        self._section(box, self.tr("Calibration"))
        self._add(box, "ppm")
        lay.insertWidget(at, tmp)
        return sc

    def page_decoders(self) -> QWidget:
        """Settings › Decoders (RADIO-SDR-PLAN §4.5): how many decoders may
        run beside the mode's and the processor share they may use, and
        the codecs: which this computer has, which were refused and why,
        the folder to put one in, and Look again."""
        sc, lay = self._scroll(self.tr("Decoders"), self.tr(
            "Decoders that listen on frequencies of their own, beside the mode's (View › Decoders), and the "
            "codecs some decoders need. A change here applies when the radio next starts."))
        self._add(lay, "decodersMax")
        self._add(lay, "decodeCpuMax")
        self._section(lay, self.tr("Codecs"))
        note = QLabel(self.tr("codec2, for FreeDV, comes with Radio on Windows and macOS and with your system on "
                              "Linux. Radio never includes the codecs whose patents or licences keep them out of "
                              "free software (faad2 and fdk-aac for DAB+ and DRM sound, mbelib for digital voice): "
                              "it uses them only if you install them, or put them in the codecs folder. Nothing in "
                              "this version needs them yet."))
        note.setWordWrap(True)
        note.setObjectName("Muted")
        lay.addWidget(note)
        self.codec_rows = QVBoxLayout()
        lay.addLayout(self.codec_rows)
        r = QHBoxLayout()
        self.codecs_folder_btn = Button(self.tr("Open codecs folder"), small=True)
        self.codecs_folder_btn.clicked.connect(self.open_codecs_folder)
        r.addWidget(self.codecs_folder_btn)
        again = Button(self.tr("Look again"), small=True)
        again.clicked.connect(lambda: self._fill_codecs(rescan=True))
        r.addWidget(again)
        r.addStretch(1)
        lay.addLayout(r)
        self._fill_codecs(rescan=False)
        lay.addStretch(1)
        return sc

    def _fill_codecs(self, rescan: bool) -> None:
        while self.codec_rows.count():
            w = self.codec_rows.takeAt(0).widget()
            if w is not None:
                w.deleteLater()
        dec = getattr(self.bridge.radio, "decoders", None)
        try:
            rows = dec.codecs(rescan=rescan) if dec is not None else []
        except Exception as e:  # noqa: BLE001 - a loader that fails is said, never a broken dialog
            rows = []
            self._say(self.tr("Could not look for codecs: {error}").format(error=e))
        if not rows:
            lab = QLabel(self.tr("This installation has no codec loader (shack-sdr)."))
            lab.setObjectName("Muted")
            self.codec_rows.addWidget(lab)
        for c in rows:
            lab = QLabel(f"{c['id']}: {c.get('whyText') or c.get('state')}")
            lab.setWordWrap(True)
            lab.setTextFormat(Qt.TextFormat.PlainText)
            self.codec_rows.addWidget(lab)
        from ohscore import sdr
        codecs = sdr.codecs()
        self.codecs_folder_btn.setEnabled(codecs is not None and codecs.folder() is not None)

    def open_codecs_folder(self) -> None:
        """The codecs folder, made if it is not there yet, in the system's
        file manager."""
        from PyQt6.QtCore import QUrl
        from PyQt6.QtGui import QDesktopServices
        from ohscore import sdr
        codecs = sdr.codecs()
        folder = codecs.folder() if codecs is not None else None
        if folder is None:
            return
        try:
            folder.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            self._say(self.tr("Could not make {folder}: {error}").format(folder=folder, error=e))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _show_sdr_why(self, device: str) -> None:
        """Under the RTL-SDR and SDRplay settings: whether the radio picked
        can be used here, and if not, what to install."""
        if device not in ("rtlsdr", "sdrplay"):
            self.sdr_why.setText(self.tr("An RTL-SDR or an SDRplay RSP only receives. Choose one above to see "
                                         "whether this computer has what it needs."))
            return
        from ohscore.devices import sdrsource
        ok, why = sdrsource.availability(device)
        if ok:
            self.sdr_why.setText(self.tr("This computer has what the {radio} needs.")
                                 .format(radio="RTL-SDR" if device == "rtlsdr" else "SDRplay RSP"))
        else:
            self.sdr_why.setText(why)

    def find_hl2(self):
        # The same broadcast the driver sends when its address is empty
        # (ohscore.devices.hl2.discover), plus a direct probe of whatever is
        # typed, so a radio on another subnet can be checked too. It blocks
        # for the discovery time, as the Pluto's Find does: a second at most.
        typed = self.fields["hl2Address"].w.text().strip()
        try:
            found = hl2.discover(1.0, typed)
        except Exception as e:  # noqa: BLE001 - a name that does not resolve, no network: say so, keep the dialog
            self._say(str(e))
            return
        self.hl2_found.clear()
        if not found:
            self.hl2_found.hide()
            # Two whole sentences, with the typed address and without,
            # rather than " or {typed}" spliced into one.
            if typed:
                said = self.tr("No Hermes-Lite 2 answered the broadcast on UDP port 1024 or {address}. Check it is "
                               "powered and on this network (a radio with no DHCP server falls back to "
                               "169.254.19.221), and that no firewall drops UDP 1024 and 1025. Leaving the address "
                               "empty still finds it by broadcast when the radio starts.").format(address=typed)
            else:
                said = self.tr("No Hermes-Lite 2 answered the broadcast on UDP port 1024. Check it is powered and on "
                               "this network (a radio with no DHCP server falls back to 169.254.19.221), and that no "
                               "firewall drops UDP 1024 and 1025. Leaving the address empty still finds it by "
                               "broadcast when the radio starts.")
            self._say(said)
            return
        usable = [d for d in found if not d["problem"]]
        for d in usable + [d for d in found if d["problem"]]:
            addr = d["ip"] if d["port"] == hl2.PORT else f"{d['ip']}:{d['port']}"
            what = f"{d['boardName']}, gateware {d['gateware']}, {d['mac']}"
            if d["busy"]:
                what += " - busy, streaming to another program"
            if d["problem"]:
                what += " - cannot be used"
            self.hl2_found.addItem(f"{addr}  —  {what}", addr)
        # Listed, not written into the address: an empty address keeps
        # finding the radio by broadcast wherever DHCP puts it, and filling
        # it in would pin today's lease. Picking one from the list fixes it.
        self.hl2_found.show()
        self._say("" if usable else found[0]["problem"])

    def page_licence(self) -> QWidget:
        sc, lay = self._scroll(self.tr("Licence & plan"), self.tr("What the transmit guard enforces. The licence is "
                                                                  "law and is always enforced; the band plan is a "
                                                                  "code of practice."))
        self._licence_section(lay)
        self._section(lay, self.tr("Band plan"))
        self._add(lay, "plan")
        self._add(lay, "planGuard", help_=self.tr("Warn: a transmission outside what its segment is for goes ahead "
                                                  "with a warning. Enforce: it is refused. Beacon and satellite "
                                                  "sub-bands are refused whatever this says."))
        lay.addStretch(1)
        return sc

    def page_power(self) -> QWidget:
        sc, lay = self._scroll(self.tr("Bands & power"), self.tr("Per band, what turns drive into watts at the "
                                                                 "antenna. An estimate over your class's limit there "
                                                                 "is a warning, not a refusal; where the radio "
                                                                 "measures its own output and no PA gain is entered, "
                                                                 "the measurement is held to the limit."))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(4)
        heads = [self.tr("Band"), self.tr("Device W"), self.tr("PA gain dB"), self.tr("Feeder loss dB"),
                 self.tr("Antenna dBi"), self.tr("Ceiling %"), self.tr("At full drive")]
        for j, h in enumerate(heads):
            lab = QLabel(h)
            lab.setFont(theme.caps(10))
            lab.setStyleSheet(f"color: {theme.t()['text3']};")
            grid.addWidget(lab, 0, j)
        self.power_edits: dict[str, dict[str, QLineEdit]] = {}
        self.power_full: dict[str, QLabel] = {}
        cur = self.st.get("bandPower") or {}
        dev_w = self.bridge.radio._device_full_w
        for i, b in enumerate([b for b in bands.BANDS if not xvtr.deferred(self.st, b)], start=1):
            c = power.chain(cur, b.name)
            grid.addWidget(QLabel(b.name), i, 0)
            row = {}
            vals = [("devW", "" if not c["devW"] else f"{c['devW']:g}"), ("paGainDb", f"{c['paGainDb']:g}"),
                    ("lossDb", f"{c['lossDb']:g}"), ("antGainDbi", f"{c['antGainDbi']:g}"),
                    ("ceiling", f"{c['ceiling'] * 100:g}")]
            for j, (k, v) in enumerate(vals, start=1):
                e = QLineEdit(v)
                e.setFixedWidth(84)
                if k == "devW":
                    e.setPlaceholderText(watts(dev_w(b.centre)).replace(" ", ""))
                e.textChanged.connect(lambda _t, name=b.name: self._power_preview(name))
                grid.addWidget(e, i, j)
                row[k] = e
            full = QLabel("")
            full.setObjectName("Faint")
            grid.addWidget(full, i, 6)
            self.power_edits[b.name] = row
            self.power_full[b.name] = full
            self._power_preview(b.name)
        lay.addLayout(grid)
        n = QLabel(self.tr("Device W empty: the device's own figure (a Pluto about 4.5 mW, the Hermes-Lite 2 about "
                           "5 W). A Pluto has no output filter: check its output into a dummy load on a spectrum "
                           "analyser before it drives any PA, and never connect it straight to an antenna. Whether a "
                           "PA's own filter is then enough is what that check shows."))
        n.setWordWrap(True)
        n.setObjectName("Faint")
        lay.addWidget(n)
        lay.addStretch(1)
        return sc

    def _power_row(self, name: str) -> dict:
        row = self.power_edits[name]
        out = {}
        for k, e in row.items():
            t = e.text().strip().replace(",", ".")
            if k == "devW" and not t:
                continue
            v = float(t)
            out[k] = v / 100.0 if k == "ceiling" else v
        return out

    def _power_preview(self, name: str):
        try:
            c = power.chain({name: self._power_row(name)}, name)
            b = bands.BY_NAME[name]
            self.power_full[name].setText(watts(power.full_pep(c, self.bridge.radio._device_full_w(b.centre))))
        except (ValueError, KeyError):
            self.power_full[name].setText("—")

    # ------------------------------------------------------------ converters
    CONVERTER_PACKS = ("vhf",)
    CONVERTER_DRIVE_REQUIRED = True
    CONVERTER_TEXT = ("Transverters and up/down-converters, and which band is worked through which. The dial, the "
                      "licence and band-plan guard, the log and the band bar stay on the air; only the radio is "
                      "told the converter's IF. A transverter's gain goes in PA gain on Bands & power.")

    def _converter_ranges(self):
        return [(b.lo, b.hi, "both") for b in bands.BANDS]

    def _converter_uses(self, lay) -> None:
        self._section(lay, self.tr("Bands"))
        n = QLabel(self.tr("Direct: the radio tunes the band itself. Through a converter, the band is on the band "
                           "bar whenever the radio reaches the converter's IF for it (6 m included), and transmits "
                           "only through an RX/TX or TX only one with its most drive given. A TX only one is "
                           "transmitted through and the band received directly."))
        n.setWordWrap(True)
        n.setObjectName("Faint")
        lay.addWidget(n)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(4)
        self.band_conv: dict[str, QComboBox] = {}
        cur = self.st.get("bandConverters") or {}
        for i, b in enumerate(bands.BANDS):
            grid.addWidget(QLabel(b.name), i // 2, (i % 2) * 2)
            cb = self._converter_combo(cur.get(b.name, ""), self.tr("Direct"))
            cb.setMinimumWidth(220)
            grid.addWidget(cb, i // 2, (i % 2) * 2 + 1)
            self.band_conv[b.name] = cb
        lay.addLayout(grid)

    def _converter_in_use(self, title: str) -> str:
        used = [b for b, cb in getattr(self, "band_conv", {}).items() if (cb.currentData() or "") == title]
        return f"{', '.join(used)} {'is' if len(used) == 1 else 'are'} worked through it" if used else ""

    def page_sequencer(self) -> QWidget:
        sc, lay = self._scroll(self.tr("PTT sequencer"), self.tr("The line that keys a PA, a preamp's bypass relay "
                                                                 "or a transverter: on before RF, off after it."))
        self._add(lay, "seqOutput")
        self._add(lay, "seqPort")
        self._add(lay, "seqLine")
        self._add(lay, "seqDelayMs")
        n = QLabel(self.tr("Opening a serial port raises RTS and DTR for an instant before OpenHamShack Radio can "
                           "clear them (Linux does this, not the program); a relay does not follow it and no RF is "
                           "ever sent then. If your PA keys on the slightest glitch, drive it through an inverter with "
                           "a pull-down. When the program stops for any reason the port closes and both lines drop."))
        n.setWordWrap(True)
        n.setObjectName("Faint")
        lay.addWidget(n)
        lay.addStretch(1)
        return sc

    def _transmit_limits(self, lay) -> None:
        self._add(lay, "tuneDrive")
        self._add(lay, "swrLimit")
        self._add(lay, "paTempLimit")
        self._section(lay, "FM")
        self._add(lay, "toneburstMs")
        self._add(lay, "ctcssLevel")

    def collect(self) -> dict:
        changes = super().collect()
        new = {}
        for name in self.power_edits:
            try:
                row = self._power_row(name)
            except ValueError:
                raise ValueError(_("Bands & power, {band}: not a number").format(band=name)) from None
            if row != {k: v for k, v in power.DEFAULT.items() if k != "devW"}:
                new[name] = row
        if new != (self.st.get("bandPower") or {}):
            changes["bandPower"] = new
        if hasattr(self, "band_conv"):
            bc = {b: cb.currentData() for b, cb in self.band_conv.items() if cb.currentData()}
            if bc != (self.st.get("bandConverters") or {}):
                changes["bandConverters"] = bc
        return changes
