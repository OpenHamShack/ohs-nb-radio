"""QO-100 NB's transmit card: power as the Pluto's transmit gain in dB
under the ceiling set in Settings, the ALC meter, and the own-signal-vs-
beacon meter with the level guard's sentence. With an IC-9700 as the
transmitter (Settings > Transmitter) the power and ALC give way to the
radio's own state - link, frequency, RX/TX, and any warning about where it
is aimed - because NB neither sets its power nor keys it; the beacon meter
stays, measured from the downlink. Under the power slider, the standing
warning (ohscore.ui.controls.StandingWarning): our downlink over the beacon,
the level guard's trim, the IC-9700 transmitting where NB would not.

How much of it shows is ohscore/ui/txcard.py's: one line in a run that
cannot transmit, the compact form (power, warning, beacon meter; ALC and
the level guard's sentence back on the air), and never less than all of
it while anything is on the air or a warning stands."""
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QLabel

from ohscore.i18n import fmt
from ohscore.ui import theme
from ohscore.ui.controls import Slider, StandingWarning
from ohscore.ui.meters import BarMeter
from ohscore.ui.txcard import TxCard

from .. import state as state_mod
from .meters import BeaconMeter

RIG_KEYS = ("txRadio", "rigLink", "rigError", "rigFreq", "rigKeyed", "rigMode", "rigTxBlocked", "rigTxCorr",
            "txWarning")


class TransmitCard(TxCard):
    def __init__(self, bridge, parent=None):
        super().__init__(self.tr("Transmit"), bridge, parent)
        st = bridge.st
        sp = state_mod.SPEC["txGain"]
        self.power = Slider(self.tr("Power (TX gain)"), -60.0, 0.0, st.get("txGain", -40), 0.5,
                            lambda v: f"{v:.1f} dB", default=-40, colour="accent")
        self.power.lo = max(sp["min"], -60.0)
        self.power.cap = st.get("txGainCeiling", -10)
        self.power.changed.connect(lambda v: bridge.set(quiet=True, txGain=min(v, self.power.cap)))
        self.power.committed.connect(lambda v: bridge.set(txGain=min(v, self.power.cap)))
        # Accent, not red: a slider is not on the air (overhaul section 5.3).
        self.power.setToolTip(self.tr("Transmit gain. The amber mark is the ceiling set in Settings; nothing here "
                                      "can pass it."))
        self.blay.addWidget(self.power)
        self.warning = StandingWarning()
        self.blay.addWidget(self.warning)
        self.alc = BarMeter(self.tr("ALC / peak"), 0, 1, lambda v: f"{v * 100:.0f}", ticks=(0, 0.25, 0.5, 0.75, 1),
                            zones=((0, 0.8, "ok"), (0.8, 0.95, "warn"), (0.95, 1, "err")), unit="%", compact=True)
        self.blay.addWidget(self.alc)
        # The external radio, when it is the transmitter.
        self.rig = QLabel("")
        self.rig.setTextFormat(Qt.TextFormat.PlainText)
        self.rig.setWordWrap(True)
        self.rig.setFont(theme.font(12.5, theme.QFont.Weight.DemiBold, mono=True))
        self.blay.addWidget(self.rig)
        self.rig_warn = QLabel("")
        self.rig_warn.setTextFormat(Qt.TextFormat.PlainText)
        self.rig_warn.setWordWrap(True)
        self.blay.addWidget(self.rig_warn)
        self.beacon = BeaconMeter()
        self.blay.addWidget(self.beacon)
        self.level = QLabel("")
        self.level.setObjectName("Faint")
        self.level.setWordWrap(True)
        self.blay.addWidget(self.level)
        self.on_state(st)

    def external(self) -> bool:
        return self.bridge.st.get("txRadio", "sdr") != "sdr"

    def on_state(self, ch):
        if "txGainCeiling" in ch:
            self.power.cap = ch["txGainCeiling"]
            self.power.update()
        if "txGain" in ch:
            self.power.set_value(ch["txGain"])
        if "txWarning" in ch:
            self.warning.set_warning(ch["txWarning"])
        st = self.bridge.st
        ext = self.external()
        self.power.setVisible(not ext)
        detail = self.detail()
        self.alc.setVisible(not ext and detail)
        self.level.setVisible(detail)
        self.rig.setVisible(ext)
        self.beacon.margin = float(st.get("levelMarginDb", 6.0))
        if ext:
            self.level.setText(self.tr("Level: measured from the downlink while the IC-9700 transmits. Set its "
                                       "power on the radio - OpenHamShack QO-100 NB never changes it."))
        else:
            lm = st.get("levelMode", "limit")
            self.level.setText({"limit": self.tr("Level guard: trims TX gain to stay {margin:g} dB under the "
                                                 "beacon.").format(margin=self.beacon.margin),
                                "auto": self.tr("Level guard: holds {margin:g} dB under the beacon (up and "
                                                "down).").format(margin=self.beacon.margin),
                                "manual": self.tr("Level guard: warn only.")}.get(lm, ""))
        if ext and (ch is st or any(k in ch for k in RIG_KEYS)):
            self._sync_rig(st)
        elif not ext:
            self.rig_warn.hide()
        if "vsBeacon" in ch:
            self.beacon.set_value(ch["vsBeacon"])
        if "beaconLevel" in ch:
            self.beacon.beacon_dbfs = ch["beaconLevel"]
        self.sync_form()

    def _sync_rig(self, st):
        link = st.get("rigLink", "off")
        f = float(st.get("rigFreq") or 0.0)
        if link == "ok" and f:
            keyed = bool(st.get("rigKeyed"))
            mode = (st.get("rigMode") or "").upper()
            # The rig's dial to the hertz, in the locale's decimal form
            # (ohscore/i18n/fmt.py): a status line, not the digit-by-digit
            # readout, so the shared frequency rules apply as they stand.
            self.rig.setText(self.tr("IC-9700  {freq}  {mode}  {direction}").format(
                freq=fmt.frequency(int(round(f)), "MHz", 6), mode=mode,
                direction=("TX (CAT)" if st.get("rigCatKeyed") else "TX") if keyed else "RX"))
            self.rig.setStyleSheet(f"color: {theme.t()['err' if keyed else 'text']};")
        else:
            self.rig.setText({"connecting": self.tr("IC-9700: connecting…"), "lost": self.tr("IC-9700: link lost"),
                              "error": self.tr("IC-9700: not connected"),
                              "off": self.tr("IC-9700: not connected")}.get(link, link))
            self.rig.setStyleSheet(f"color: {theme.t()['warn']};")
        blocked = st.get("rigTxBlocked") or ""
        if (st.get("txWarning") or {}).get("key") == "rig-aim":
            blocked = ""        # the standing warning says it, more urgently, while it transmits
        err = st.get("rigError") or ""
        if blocked and st.get("rigCatPtt"):
            # With CAT PTT (12/10/2026) the same judgement also stops NB
            # keying it there; only the radio's own PTT is beyond NB.
            self.rig_warn.setText(self.tr("Aimed where OpenHamShack QO-100 NB would not transmit: {blocked}. NB will "
                                          "not key it there, and cannot stop the radio's own PTT.").format(
                blocked=blocked))
            self.rig_warn.setStyleSheet(f"color: {theme.t()['err']};")
        elif blocked:
            self.rig_warn.setText(self.tr("Aimed where OpenHamShack QO-100 NB would not transmit: {blocked}. Advice "
                                          "only - NB cannot stop the radio transmitting.").format(blocked=blocked))
            self.rig_warn.setStyleSheet(f"color: {theme.t()['err']};")
        elif err:
            self.rig_warn.setText(err)
            self.rig_warn.setStyleSheet(f"color: {theme.t()['warn']};")
        self.rig_warn.setVisible(bool(blocked or err))

    def on_meter(self, m):
        keyed = bool(m.get("keyed"))
        self.alc.set_value(m.get("txPeak") if keyed else None)
        if m.get("vsBeacon") is not None:
            self.beacon.set_value(m["vsBeacon"])
        if m.get("beacon") is not None:
            self.beacon.beacon_dbfs = m["beacon"]

    def tick(self, dt):
        self.alc.tick(dt)
        self.beacon.tick(dt)
        self.tick_form()
