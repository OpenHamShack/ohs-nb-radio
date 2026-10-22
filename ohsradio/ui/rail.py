"""OpenHamShack Radio's transmit card (docs/ham/DESIGN-HAM.md section 7): drive
as a share of the device's full output, held under the band's ceiling
(the amber mark), with the estimated PEP printed under it; ALC/peak; and,
where the device measures them, forward power, SWR and PA temperature
(the last shown only once a reading has arrived). A tune button for an
ATU or PA, and the SWR trip's acknowledgement when it has fired. Under
the estimate, the standing warning (ohscore.ui.controls.StandingWarning):
an estimate over the licence's limit (advisory until measured: Brian,
05/10/2026), a power that cannot be estimated, the band plan set to
warn.

How much of it shows is ohscore/ui/txcard.py's: one line in a run that
cannot transmit, the compact form (drive, the estimate, the warning;
the meters back on the air), and never less than all of it while
anything is on the air or a warning stands."""
from __future__ import annotations

from PyQt6.QtWidgets import QHBoxLayout, QLabel

from ohscore.ui.controls import Button, Slider, StandingWarning
from ohscore.ui.meters import BarMeter
from ohscore.ui.txcard import TxCard

from ..guard import watts


class TransmitCard(TxCard):
    def __init__(self, bridge, parent=None):
        super().__init__(self.tr("Transmit"), bridge, parent)
        st = bridge.st
        self.drive = Slider(self.tr("Drive"), 0.0, 1.0, float(st.get("drive", 0.25)), 0.01,
                            lambda v: f"{v * 100:.0f} %", default=0.25, colour="accent")
        self.drive.cap = float(st.get("maxDrive", 1.0))
        self.drive.changed.connect(lambda v: bridge.set(quiet=True, drive=min(v, self.drive.cap)))
        self.drive.committed.connect(lambda v: bridge.set(drive=min(v, self.drive.cap)))
        # Accent, not red: a slider is not on the air (overhaul section 5.3).
        self.drive.setToolTip(self.tr("Transmit drive. The amber mark is this band's ceiling (Settings › Bands & "
                                      "power). An estimated power over your licence's limit warns below; where the "
                                      "radio measures its output, a measured excess unkeys."))
        self.blay.addWidget(self.drive)
        self.power = QLabel("")
        self.power.setObjectName("Faint")
        self.power.setWordWrap(True)
        self.blay.addWidget(self.power)
        # Until 0.1.10 the estimate over the licence had its own amber line
        # here, and the band plan's warning was only a toast at key-up; both
        # are the standing warning now, with the reason in its tooltip.
        self.warning = StandingWarning()
        self.blay.addWidget(self.warning)
        self.alc = BarMeter(self.tr("ALC / peak"), 0, 1, lambda v: f"{v * 100:.0f}", ticks=(0, 0.25, 0.5, 0.75, 1),
                            zones=((0, 0.8, "ok"), (0.8, 0.95, "warn"), (0.95, 1, "err")), unit="%", compact=True)
        self.blay.addWidget(self.alc)
        self.fwd = BarMeter(self.tr("Forward"), 0, 1, lambda v: watts(v), compact=True)
        self.swr = BarMeter(self.tr("SWR"), 1.0, 5.0, lambda v: f"{v:.1f}:1", ticks=(1, 2, 3, 4, 5),
                            zones=((1.0, 2.0, "ok"), (2.0, 3.0, "warn"), (3.0, 5.0, "err")), compact=True)
        self.blay.addWidget(self.fwd)
        self.blay.addWidget(self.swr)
        # PA temperature, from radios that report it (the Hermes-Lite 2;
        # the simulator). Hidden until the first reading, so a Pluto's card
        # has no meter that could only ever say "—". It keeps showing the
        # last reading after the over: a PA cools slowly, and how hot it
        # still is matters for the next one. The amber mark is the limit
        # that unkeys (Settings › Transmit & safety).
        self.temp = BarMeter(self.tr("PA temperature"), 20.0, 70.0, lambda v: f"{v:.0f} °C", compact=True)
        self.temp.hide()
        self._temp_zones(float(st.get("paTempLimit", 50.0)))
        self.blay.addWidget(self.temp)
        row = QHBoxLayout()
        self.tune = Button(self.tr("Tune"), icon="antenna", small=True, checkable=True)
        self.tune.setToolTip(self.tr("A steady carrier for an ATU or a PA, at the tune drive (Settings) times Drive - "
                                     "25 % of 40 % is 10 %. The licence guard applies as to any transmission."))
        self.tune.clicked.connect(self._tune)
        self.ack = Button(self.tr("SWR tripped: acknowledge"), kind="danger", small=True)
        self.ack.clicked.connect(self._ack)
        self.ack.hide()
        row.addWidget(self.tune)
        row.addWidget(self.ack)
        row.addStretch(1)
        self.blay.addLayout(row)
        self.on_state(st)

    def _tune(self):
        r = self.bridge.radio
        try:
            r.tune(self.tune.checked and self.bridge.licence_ok)
        except ValueError as e:
            self.bridge.say(str(e))
            self.tune.set_checked(False)
            return
        if self.tune.checked and not self.bridge.licence_ok:
            self.bridge.say(self.tr("Transmit is locked until the licence box is ticked (Settings › Station)"))
            self.tune.set_checked(False)

    def _temp_zones(self, limit: float):
        self.temp.zones = ((20.0, limit - 10.0, "ok"), (limit - 10.0, limit, "warn"), (limit, 70.0, "err"))
        self.temp.cap = limit
        self.temp.update()

    def _ack(self):
        self.bridge.radio.ack_swr()

    def on_state(self, ch):
        st = self.bridge.st
        if "maxDrive" in ch:
            self.drive.cap = float(ch["maxDrive"])
            self.drive.update()
        if "drive" in ch:
            self.drive.set_value(ch["drive"])
        if "paTempLimit" in ch:
            self._temp_zones(float(ch["paTempLimit"]))
        if "txWarning" in ch:
            self.warning.set_warning(ch["txWarning"])
        if "swrTripped" in ch:
            self.ack.setVisible(bool(ch["swrTripped"]))
        if "keyed" in ch and not ch["keyed"] and self.tune.checked:
            self.tune.set_checked(False)
        if any(k in ch for k in ("estPep", "licenceInfo", "drive", "maxDrive")):
            info = st.get("licenceInfo") or {}
            est = float(st.get("estPep") or 0.0)
            full = float(info.get("fullW") or 0.0)
            lim = info.get("limitW")
            unknown = info.get("powerUnknown") or ""
            # Through a transverter with no output entered the figure would
            # be the radio's milliwatts beside a licence limit in watts: say
            # it is unknown rather than print a reassuring number.
            # A line of fields, each translated whole, joined by " · ".
            fields = [self.tr("Power at the antenna unknown") if unknown else
                      self.tr("≈ {power} PEP at the antenna (estimate)").format(power=watts(est))]
            if full and not unknown:
                fields.append(self.tr("{power} at full drive").format(power=watts(full)))
            if lim:
                fields.append(self.tr("licence {limit:g} W {kind}").format(limit=lim,
                                                                           kind=info.get("limitKind", "PEP")))
            self.power.setText(" · ".join(fields))
            self.fwd.b.hi = max(full * 1.1, 1e-6) if full else 1.0
        # The compact form keeps drive, the estimate and the warning; the
        # meters, which read nothing until an over, come back on the air.
        detail = self.detail()
        for w in (self.alc, self.fwd, self.swr):
            w.setVisible(detail)
        if self.temp.b.valid:                   # hidden until a first reading, whatever the form
            self.temp.setVisible(detail)
        self.sync_form()

    def on_meter(self, m):
        keyed = bool(m.get("keyed"))
        self.alc.set_value(m.get("txPeak") if keyed else None)
        fwd = m.get("fwd") or 0.0
        self.fwd.set_value(fwd if keyed and fwd else None)
        swr = m.get("swr") or 0.0
        self.swr.set_value(swr if keyed and swr else None)
        temp = float(m.get("paTemp") or 0.0)
        if temp > 0:
            if self.temp.isHidden() and self.detail():
                self.temp.show()
            self.temp.set_value(temp)

    def tick(self, dt):
        self.alc.tick(dt)
        self.fwd.tick(dt)
        self.swr.tick(dt)
        self.temp.tick(dt)
        self.tick_form()
