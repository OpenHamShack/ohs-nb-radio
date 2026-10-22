# OpenHamShack Radio — design

An all-amateur-bands SDR transceiver: one native PyQt6 desktop application,
the terrestrial sibling of OpenHamShack QO-100 NB. It drives a **Hermes-Lite 2** on HF
(160 m – 10 m; it has no 6 m — see below), a **Pluto-family** SDR on VHF/UHF/microwave (4 m – 6 cm,
directly or through a PA or transverter), and receive-only SDRs through
SoapySDR. It shares its engine, DSP, modes, devices, audio, logbook and most
of its UI with OpenHamShack QO-100 NB through a common package, `ohscore`; each app keeps
what is particular to it.

This document is the contract, as `DESIGN.md` is for OpenHamShack QO-100 NB. Written
04/10/2026 from Brian's decisions of that day. Facts about the HL2 are in
[`hl2-research.md`](hl2-research.md); bandplans and licence limits in
[`bandplan-r1-uk.md`](bandplan-r1-uk.md). Anything here marked
**[unverified]** has not been checked on hardware or against a primary
source and must be before it is relied on.

Brian's decisions this design takes as given:

- Name **OpenHamShack Radio**; native PyQt6 desktop app; Linux laptops first, maybe a
  Pi 400/500, Windows (the NB Windows port lands first and is inherited).
- Operator GM4BRI, UK: **IARU Region 1 / RSGB band plan and Ofcom licence
  conditions** are the primary target; plans are data so other regions can
  be added.
- Radios: Pluto family on 6 m(?) / 4 m / 2 m / 70 cm / 23 cm / 13 cm / 9 cm /
  6 cm; Hermes-Lite 2 on 160 m – 6 m TX+RX; RX-only via SoapySDR (RTL-SDR v4,
  SDRplay, Airspy HF+). Rigs via CAT are out of scope for now.

**Two facts found while writing this that change the brief:**

1. **The Hermes-Lite 2 has no 6 m.** It covers 0–38.4 MHz; its FAQ says so
   in terms ("there is no 6 m, unlike the Hermes"); the N2ADR filters stop
   at 10 m (`hl2-research.md` §1). **And the Pluto cannot receive on 6 m**:
   the ADI driver will not put the RX LO below 70 MHz (§4.3). So 6 m has no
   native home in this hardware set. It takes a 6 m transverter on the HL2's
   28 MHz IF, or a separate 6 m receiver (an RX-only SDR) paired with Pluto
   TX — see question 5.
2. **The Ofcom Full licence is 1000 W PEP only on Primary bands**; 400 W on
   most secondary ones and less on some (32 W on 1850–2000 kHz, 100 W on 51–52
   MHz, 160 W on 4 m, 40 W ERP on 430–432 MHz). The guard is per
   sub-allocation, not per band (`bandplan-r1-uk.md` §1).
- **Shared core, two apps**, both shipping as their own .deb (and Windows
  installer). **OpenHamShack QO-100 NB must not regress; its tests stay green
  throughout.**

---

## 1. Shape

```
 Hermes-Lite 2 (UDP, openHPSDR P1) ─IQ─┐   ┌───────────── one process ─────────────┐
 Pluto / Pluto+ / LibreSDR / nano  ─IQ─┤   │ engine  (ohscore.engine + ohsradio.radio)  │
 RTL-SDR v4 / Airspy HF+ / SDRplay ─IQ─┼──►│  numpy DSP, modes, TX guard, sequencer ◄──► Qt UI (ohscore.ui + ohsradio.ui)
 simulated HF/VHF band (default) ──IQ─┘   │                                        │
 PA / transverter / relays ◄─ PTT lines ─ │  sequencer: HL2 OC, serial RTS/DTR,    │
                     sound card ◄───────► │  Pi GPIO, Pluto GPO                    │
                                          └────────────────────────────────────────┘
```

Everything in OpenHamShack QO-100 NB's `DESIGN.md` "Shape" holds unchanged: the engine
never imports Qt, the UI never touches DSP or a device, audio is 12 kHz mono
float32, one RX thread, one TX thread only while keyed, slow decoders on
their own worker, no per-sample Python loops on RX or TX paths, a missing
optional package disables one feature with a sentence. The differences:

| | OpenHamShack QO-100 NB | OpenHamShack Radio |
| --- | --- | --- |
| command / package | `openhamshack-nb` / `ohsnb` | `openhamshack-ham` / `ohsradio` |
| config | `$OHS_NB_CONF`, `~/.config/openhamshack-nb/config.json` | `$OHS_RADIO_CONF`, `~/.config/openhamshack-radio/config.json` |
| data | `$OHS_NB_DATA`, `~/.local/share/openhamshack-nb/` | `$OHS_RADIO_DATA`, `~/.local/share/openhamshack-radio/` |
| frequency the operator sees | QO-100 downlink (`dl`) | on-air frequency (`rf`) |
| correction | beacon lock (rxCorr), TX lock (txCorr) | per-device ppm calibration; no lock |
| TX guard | QO-100 bandplan (law of the transponder) | Ofcom licence class (hard) + RSGB/IARU plan (configurable) |
| power | Pluto dB, beacon-level guard | drive 0..1 → estimated/measured watts, licence-class ceiling |
| duplex | full duplex always | half duplex; RX muted or kept per device |
| PTT | the SDR alone | a sequencer: relays, preamp bypass, PA, then RF |

The two apps are separate programs with separate configs and logs. They can
be installed side by side; they cannot share a radio at the same time (the
second to open the device gets the device's own "busy" sentence).

---

## 2. Code split: one repository, a core package, two apps

### 2.1 Decision: monorepo

One repository (today's `openhamshack-nb`), three top-level packages:

```
ohscore/     the shared core — never imports ohsnb or ohsradio
ohsnb/       OpenHamShack QO-100 NB  — imports ohscore
ohsradio/      OpenHamShack Radio — imports ohscore
tests/      flat, as now: test_core_*.py, test_<nb>.py (existing names kept), test_ham_*.py
packaging/  nb/ and ham/  (launcher, .desktop, icon, metainfo, man page, postinst/rm)
tools/      build-deb.sh <app>, release.sh <app> <version>, site-build.py
```

Why one repository and not three (core library + two apps):

1. **Atomic changes.** Most core changes in the first year will be made *for*
   one app and must not break the other. In one repo the change, the other
   app's adaptation and both suites land in one commit and one test run. In
   three repos a core change is a release, a pin bump in each app and two
   more test runs — and the "union is wrong" failure Brian's CLAUDE.md records
   (each branch green, the combination broken) is exactly what multi-repo
   pinning invites.
2. **No packaging seam.** `ohscore` is not published anywhere; each .deb
   carries its own private copy (§2.6). No third package, no version
   lockstep, no dependency resolution between our own debs.
3. **History.** Every line moved into `ohscore` keeps its `git log --follow`
   history, which a split repository loses.
4. **Cost**: the repo name says "nb". Renaming the hub repository is cheap
   but touches gitsync and the release paths, so it is a separate decision
   (question 1 in §12), not part of the refactor.

The rule that keeps the monorepo honest: **`ohscore` never imports `ohsnb` or
`ohsradio`**, enforced by a test that imports every `ohscore` module in a
subprocess with `ohsnb` and `ohsradio` made unimportable (a behavioural test —
it runs the imports, it does not grep source).

### 2.2 What moves to `ohscore`, what stays, what is new

Module by module, from the tree at `6bf0eec` plus the Windows port
(`ohsnb/host.py`) which merges first. Steps 0-11 of §2.5 are done (branch
`worktree-agent-a940dcc8eaadb419f`, 04/10/2026); where what was built
differs from these tables, §2.7 says how and why.

**Engine side**

| today | goes to | why |
| --- | --- | --- |
| `ohsnb/dsp/agc.py, bank.py, fir.py, mod.py, morse.py, multirate.py, resample.py, spectrum.py` | `ohscore/dsp/` unchanged | pure DSP; no QO-100 knowledge |
| `ohsnb/dsp/demod.py` | `ohscore/dsp/demod.py` | one comment says QO-100 needs no squelch; HAM adds squelch and FM beside it (§5.3) |
| `ohsnb/dsp/lock.py` | **stays** `ohsnb/dsp/lock.py` | beacon lock and TX lock are QO-100 only |
| `ohsnb/modes/*` (cw, rtty, psk, ft8, freedv, sstv, `__init__`, PERF.md) | `ohscore/modes/` unchanged | pure 12 kHz audio modules |
| `ohsnb/modes_glue.py` | `ohscore/modes_glue.py` | binds engine to registry; no QO-100 content |
| `ohsnb/devices/base.py` | `ohscore/devices/base.py`, extended (§4.1) | the interface |
| `ohsnb/devices/pluto.py` | `ohscore/devices/pluto.py` | AD936x is the same radio for both apps; discovery, FIR fallback, rate conversion all shared |
| `ohsnb/devices/soapy.py` | `ohscore/devices/soapy.py`, extended (gain, antenna, direct sampling) | |
| `ohsnb/devices/simsignals.py` | `ohscore/devices/simsignals.py` | voice, CW, FT8, PSK, RTTY templates serve both sims |
| `ohsnb/devices/sim.py` | **split**: `Presence`, `Station`, `FT8Activity`, the noise bank and the TX loopback plumbing → `ohscore/devices/simcore.py`; `SimDevice` (the transponder, beacons, LNB drift, uplink error) **stays** `ohsnb/devices/sim.py` | |
| `ohsnb/devices/__init__.py` `make_device` | `ohscore/devices/registry.py`: a name→factory table; each app registers its own `sim` | NB's `sim` is a transponder, HAM's a band |
| `ohsnb/audio.py` | `ohscore/audio.py` | |
| `ohsnb/host.py` (Windows port) | `ohscore/host.py` | per-OS answers belong to every app |
| `ohsnb/config.py` | `ohscore/config.py`, parametrised by an `AppId` (`name="openhamshack-nb"`, `env="OHSNB"`) and a registry; `ohsnb/config.py` becomes three lines binding them | |
| `ohsnb/state.py` | **split**: the machinery (`Registry`: `add`, `coerce`, `defaults`, `persisted`, `check_combined` hooks) and the **shared keys** (§3) → `ohscore/state.py`; the QO-100 keys and limits **stay** in `ohsnb/state.py`, which builds its registry and re-exports `SPEC`, `MODES`, `coerce`, … under the same names | the UI and tests keep calling `ohsnb.state.SPEC` |
| `ohsnb/bandplan.py` | **stays** | QO-100 plan |
| `ohsnb/radio.py` | **split** (§3.2): `Feed`, `TxRefused`, `slot_start`, the thread scaffolding, `set/state/subscribe/heartbeat`, the supervisor (TX timeout, dead air, watchdog), the TX loop, `ptt/send/_render`, memories and log → `ohscore/engine.py` (`Engine`); `ohsnb/radio.py` keeps `Radio(Engine)` with beacon lock, TX lock, level guard, `plan_tx_lo`, the dl/ul frequency model and the QO-100 guard | |
| log + ADIF inside `radio.py` | `ohscore/logbook.py` with an app hook for ADIF fields (NB: `PROP_MODE SAT`, `SAT_NAME QO-100`, `BAND 13cm`, `BAND_RX 3cm`; HAM: `BAND` from frequency, `TX_PWR`, `PROP_MODE` only when the operator says) | |
| memories inside `radio.py` | `ohscore/memories.py`; built-in presets come from the app | |
| `ohsnb/bench.py` | measurement harness → `ohscore/bench.py`; the NB scenario stays as `ohsnb/bench.py` | |

**UI side** (`ohsnb/ui/`, ~8k lines). Almost all of it is generic instrument
UI. QO-100 knowledge sits in a handful of places (found by reading every
`ui` module for beacon/rxCorr/txCorr/uplink/QO-100 references):

| today | goes to | note |
| --- | --- | --- |
| `theme.py, palettes.py, controls.py, icons.py, scopecore.py, wfpanel.py, tuning.py, prefs.py, audiotest.py, bridge.py, ft8seq.py` | `ohscore/ui/` unchanged | `theme` keeps its `beacon` colour key (NB uses it; HAM may for IBP beacons) |
| `meters.py` | `BarMeter` → `ohscore/ui/meters.py`; `BeaconMeter` stays `ohsnb/ui/meters.py` | |
| `status.py` | `PttButton`, `OnAirGlow`, `ToastHost`, `fmt_hz` → core; `LockBadge` stays NB | |
| `chrome.py` | `IconButton`, `ShortcutOverlay` → core; `StatusStrip` → core with app-supplied items (NB supplies rxCorr/txCorr/ppm) | |
| `readout.py` | core, with a *secondary line provider* (NB: "uplink 2400.xxx"; HAM: "TX 144.900 −600 kHz" / transverter IF) | imports `bandplan` today; the provider removes that |
| `scope.py` | core `ScopeView` taking a *plan provider* (segments, markers, colours) instead of importing `ohsnb.bandplan` | the bandplan strip, markers and passband drawing are reused as they are |
| `rail.py` | `ModeGrid`, `ReceiveCard` → core; `TransmitCard` → core with an app slot where NB puts the `BeaconMeter` and HAM the power/SWR meters | |
| `panels/` (ft8, text, voice, sstv, common) | core | `voice.py`'s "QO-100 allows 2.7 kHz" and "AM is receive-only" sentences come from the app's guard (`guard.describe()`) |
| `logbook.py` (Log/Memories views) | core | it imports `bandplan` for frequency labels → provider |
| `second.py` | core | |
| `settings.py` | core *framework* (pages, `authorise=True` save, Pluto Find, audio test); pages: Device/Audio/Station/Display shared; **LNB & locks** page stays NB; HAM adds Licence, Bands & antennas, Transverters, Sequencer, HL2 | |
| `welcome.py` | core framework (steps, licence acknowledgement, device choice); the text and the licence sentence are the app's | |
| `mainwindow.py` | core `BaseWindow` (layout, shortcuts, PTT, panels, feeds wiring); `ohsnb/ui/mainwindow.py` and `ohsradio/ui/mainwindow.py` compose it | |
| `appicon.py` | core loader; the icon asset is per app | touched by the Windows port — moves after it merges |
| `screenshots.py`, `uibench.py` | core harness; per-app scenes | |

**New in `ohsradio`** (detail in §5):

```
ohsradio/__main__.py          python3 -m ohsradio [--headless]
ohsradio/radio.py             Radio(Engine): rf frequency model, transverters, band stack, sequencer, guard
ohsradio/state.py             HAM keys + shared keys with HAM ranges
ohsradio/plans/               data: iaru_r1_hf.py, iaru_r1_vhf.py, rsgb_2026.py (segments, centres of activity, dial frequencies)
ohsradio/licences/ofcom.py    data: Foundation / Intermediate / Full bands and power (sourced, dated)
ohsradio/guard.py             licence guard (hard) + bandplan guard (configurable) + beacon/IBP refusal
ohsradio/bands.py             band table, band stack registers, per-band defaults (mode, dial, repeater shift)
ohsradio/sequencer.py         PTT sequencing over output drivers (hl2_oc, serial, gpio, pluto_gpo, none)
ohsradio/devices/sim.py       simulated HF/VHF band (default device)
ohsradio/ui/                  band bar, VFO A/B, FM/repeater panel, PA meters, licence chip, settings pages
ohscore/devices/hl2.py      Hermes-Lite 2, openHPSDR Protocol 1 over UDP (in core because devices live in core,
                           not because NB needs it)
ohscore/devices/hl2sim.py   a Protocol 1 HL2 emulator on localhost UDP (tests the real driver)
ohscore/dsp/fm.py           NBFM demod/mod, CTCSS encode/decode, toneburst, squelch
ohscore/dsp/nr.py           spectral noise reduction and FFT auto-notch
ohscore/modes/wspr.py       WSPR via wsprd/wsprcode (WSJT-X package)
```

FM, AM TX, noise reduction, notch and WSPR go into the **core**, not `ohsradio`:
none is QO-100-specific in itself; NB simply refuses FM/AM to transmit (its
guard says why) and may later offer NR and notch to its operators for free.

### 2.3 The state registry: shared vs extended

Today `ohsnb/state.py` is a module-level `SPEC` dict filled by `_k(...)`
calls, with `coerce`, `defaults`, `persisted`, `check_combined`. Tomorrow:

```python
# ohscore/state.py  (as built)
class Registry:
    def __init__(self, modes, digital)                         # the app's mode list and its digital modes
    def add(self, name, type_, default, kind, **kw)            # today's _k
    def after(self, key)                                       # context manager: keys added inside follow `key`
    def override(self, name, **kw)                             # an app narrows/rewords a shared key in place
    def rule(self, fn)                                         # cross-key check, raises ValueError; run in order
    def coerce(self, key, value) / defaults(kinds) / persisted() / check_combined(st)

def add_shared_keys(reg)    # the keys both apps have, app-neutral wording; the receive-filter-width rule
```

```python
# ohsnb/state.py  (public names unchanged: SPEC, MODES, DIGITAL, coerce, defaults, persisted, check_combined)
REG = Registry(MODES, DIGITAL)
add_shared_keys(REG)
REG.override("vfo", default=10_489_700_000.0, lo=DL_LO - 20_000.0, hi=DL_HI + 20_000.0, help="Receive dial (downlink).")
with REG.after("rxGain"):
    REG.add("rxCorr", ...); REG.add("beaconLock", ...); ...     # QO-100 keys, in their old places
@REG.rule
def _qo100_occupied_width(st): ...                              # 2.7 kHz
SPEC = REG.spec; coerce, defaults, persisted, check_combined = REG.coerce, REG.defaults, ...
```

Key order matters (the engine builds its state snapshot by walking the
registry), which is why `after()` exists: NB's SPEC is identical to the
pre-split one field by field and in order (tests/test_state_registry.py
holds the old one as data). The shared `sampleRate` offers only 1.2 MS/s
and the shared `vfo` has no range: an app that forgets to set its own
inherits nothing of the other's.

**Shared keys** (same name, same meaning, app may override range/default):
`device, plutoUri, soapyArgs, sampleRate, rxGainMode, rxGain, vfo, mode,
split, txVfo, rit, ritOn, xit, xitOn, filterLo, filterHi, cwWidth, cwPitch,
amWidth, agc, rfGain, nb, nbThreshold, volume, mute, micGain, compressor,
txFilterLo, txFilterHi, monitor, monitorLevel, cwWpm, pttMode, freedvMode,
txTimeoutSec, deadAirSec, watchdogSec, wide*/zoom*/scopeFps, audio*,
callsign, locator, simSeed, simSignals, simRealtime`, and the status keys
`running, keyed, txSource, txSeconds, canTx, txBlocked, rxDial, txDial,
segment, fs, cpu, overruns, deviceStatus, audio, modes, error`.

**Transmit power is the one shared concept with two vocabularies.** NB's
`txGain`/`txGainCeiling` are Pluto dB (−89.75..0) and stay exactly as they
are. HAM uses `drive` (0..1, device-normalised) with a per-band ceiling and
a watts estimate (§6 rule 6), because "−10 dB" means nothing on an HL2 and
nothing on the far side of a 100 W PA. The engine asks the app's *power
model* for the device gain; NB's model is the identity on `txGain`.

`mode` choices are per app: NB keeps today's list in today's order; HAM's is
`usb, lsb, cw, am, fm, ft8, ft4, wspr, psk31, psk63, psk125, rtty, freedv,
sstv` (FM and WSPR new; `am` transmits in HAM).

Persisted dict-valued keys (HAM has several: band stacks, transverters,
sequencer, antenna map, S-meter calibration, per-band drive ceilings) get a
`validate=` callable in the registry, so a hand-edited config still costs one
setting and never the radio (today's `config.clean` contract).

### 2.4 The engine API: shared vs extended

`ohscore.engine.Engine` *is* today's `Radio` minus QO-100. Everything in
`docs/ENGINE-API.md` "Lifecycle and threading", "Radio methods", "Feeds",
"Safety behaviour" 1, 3, 4, 5 is core behaviour. The design sketched the
app's part as five objects (FreqModel, TxGuard, PowerModel, Sequencer,
rx_consumers). **As built** they are methods the subclass overrides, with
defaults for an app that has nothing to add (ohscore/engine.py's docstring
lists them):

```python
class Radio(Engine):                 # class attributes: the app's registry, config, devices, feeds, presets, log ids
    STATE, CONFIG, DEVICES, FEED_KINDS, PRESETS, FREQ_KEY, LOG_TITLE, PROGRAM_ID, THREAD_PREFIX, LOGGER, DERIVE_ON
    # frequency model
    def _off(self, dial) / _dial_at(self, off) / _initial_tuning(self) / wide_span(self)
    # transmit guard: '' or the refusal sentence
    def _tx_guard(self, mode, dial, occupied)
    # key-up / key-down choreography and power (NB: Pluto gain to -89.75 dB around tx_start/tx_stop)
    def _tx_key_up(self, dev) / _tx_follow(self, dev) / _tx_sent(self, dev, bb) / _tx_key_down(self, dev)
    def _adjust_set(self, clean) / _after_set(self, changed)   # NB: lowering the ceiling lowers the gain
    # receive consumers (NB: beacon lock first; TX monitor; re-centring the hardware)
    def _start_consumers / _configure_consumers / _rx_track / _rx_monitor / _rx_done
    # status
    def _derived / _start_status / _on_keyed / _on_unkeyed / _meter_extra / _supervise_status / _save_extra
    def _adif_fields(self, record)
```

Why methods: NB's frequency model, guard and power all read and write
the same engine state (TX lock moves `txCorr`, which the guard and the
frequency model both use), so separate objects would have reached back
into the engine for everything. No sequencer hook exists yet: NB's would
be null, and HAM's (§6.1) will add `_tx_key_up`/`_tx_key_down` around the
device calls it already overrides. tests/test_core_engine.py runs a
minimal Engine subclass with only the required hooks.

- `FreqModel` — NB: `rx_tune(dl) = dl − lnbLo + rxCorr`, `tx_tune(dl) =
  dl − 8089.5 MHz + txCorr`, plus `plan_tx_lo` (LO outside the uplink
  passband). HAM: `rx_tune(rf) = xv(rf) · (1 + ppm·10⁻⁶)` where `xv` applies
  the band's transverter (offset, inversion), and the Pluto TX LO planner
  (§4.3).
- Feeds: same kinds. HAM adds fields, never removes: `meter` gains `sMeter`
  (S-units), `dbm` (calibrated), `fwd`, `rev`, `swr`, `paTemp`, `paCurrent`,
  `supply` (HL2), `seq` (sequencer step). NB's `lock` feed has no HAM
  counterpart (nobody subscribes). A new `ctcss` event goes through `events`
  (`{"mode":"fm","ctcss":88.5}`).
- Methods HAM adds: `band(name)` (select / cycle band stack), `store_stack()`,
  `tune(on)` (carrier at reduced drive for an ATU/PA tune, guard applies),
  `toneburst()`. Everything else is `set()`.

`docs/ENGINE-API.md` becomes `ohscore/ENGINE-API.md` (core) plus a short
per-app appendix; the NB appendix is today's QO-100 material. *(Not done
in the split: ENGINE-API.md stays NB's and says which part is the core's;
it is worth splitting when HAM's own API exists to describe.)*

### 2.5 Migration plan — small, individually green steps

*Status 04/10/2026: steps 0-11 done, one or more commits each, every
commit gated on the full suite, a headless run locking on the sim, the
.deb build with its packaging tests (the installed package imports its
own `ohscore`), and screenshots compared pixel for pixel. Step 12 (the
`ohsradio` skeleton) is done too, with much of phases 1-2 of section 8:
§2.8 says what was built. Differences from the plan below are in §2.7.*

**Preconditions.** The Windows port branch is merged to `main` and green.
No other branch is mid-flight in `ohsnb/` (check `git branch -a
--no-merged`; tell the other sessions "core split starting, rebase after
each step"). Tag `pre-core-split`.

**Rules for every step.** One concern per commit. Files move with `git mv`
and their bodies change only in import lines, so rename detection carries
any later edit made on another branch across the move. All imports are
rewritten in the same commit — **no compatibility shims**: aliasing
`ohsnb.dsp` to `ohscore.dsp` through `sys.modules` produces two copies of each
module (two `Geometry` classes that fail `isinstance` against each other),
which is a worse bug than a merge conflict on an import line. After each
step: the full suite (`python3 -m unittest discover -s tests`), `python3 -m
ohsnb --headless --seconds 10`, the .deb build and its install test, and a
pixel comparison of `python3 -m ohsnb.ui.screenshots` against the
`pre-core-split` set (the screenshots run on a fixed `simSeed`; if they turn
out not to be deterministic, step 0 makes them so).

| # | step | leaves |
| --- | --- | --- |
| 0 | Make the NB screenshots deterministic if needed; add the "ohscore imports nothing of an app" test (vacuous at first); `build-deb.sh` copies `ohscore/` beside `ohsnb/` (empty package); packaging test asserts the installed app imports `ohscore` | NB unchanged, .deb carries an empty core |
| 1 | `git mv` the eight pure DSP modules (`agc bank fir mod morse multirate resample spectrum`) + `demod` to `ohscore/dsp/`; rewrite imports | the most-imported, least-edited code moves first: every later step depends on it, and nobody edits it concurrently |
| 2 | `git mv ohsnb/modes ohscore/modes`, `modes_glue.py` → core | modes are self-contained; the Windows port's ft8/freedv edits are already in |
| 3 | `audio.py`, `host.py` → core | |
| 4 | `devices/base.py`, `soapy.py`, `pluto.py`, `simsignals.py` → core; `make_device` becomes a registry the app fills (NB registers `sim`, `pluto`, `soapy` — same choices, same sentences) | Pluto discovery's Settings use moves with it |
| 5 | Split `sim.py`: generic `Presence/Station/FT8Activity/noise bank/loopback` → `ohscore/devices/simcore.py`; `SimDevice` stays NB | `test_sim.py` unchanged and green is the proof |
| 6 | `state.py` machinery → `ohscore/state.py` (`Registry`); `ohsnb/state.py` builds the identical `SPEC` (a test asserts every key's spec dict equals the `pre-core-split` one, captured as data in the test) | ENGINE-API tables regenerate identically |
| 7 | `config.py` → core with `AppId`; NB's paths and env vars unchanged (tested) | |
| 8a | Extract `Feed`, `TxRefused`, `slot_start`, logbook/ADIF (with NB's hook) and memories (with NB's presets) from `radio.py` into core modules | `radio.py` shrinks; API identical |
| 8b | Introduce `ohscore.engine.Engine` holding threads, set/state, supervisor, TX loop, ptt/send; `ohsnb.radio.Radio(Engine)` supplies `FreqModel`, `TxGuard`, `PowerModel` (identity), null sequencer, `rx_consumers` (BeaconTracker, TxMonitor), `wide_span` | the big one: done after everything it imports has moved, so its diff is pure restructuring; `test_radio.py`, `test_lock.py` unchanged and green |
| 9 | UI leaves → `ohscore/ui/` (theme, palettes, controls, icons, scopecore, wfpanel, tuning, prefs, audiotest, bridge, ft8seq, BarMeter, status parts, chrome parts) | pixel-identical screenshots |
| 10 | `scope.py`, `readout.py`, `logbook.py`, `rail.py`, `panels/` → core behind the plan / secondary-line / guard-text providers; NB supplies them | pixel-identical screenshots |
| 11 | `settings.py`, `welcome.py`, `second.py`, `mainwindow.py` → core frameworks + NB composition; `appicon`, `screenshots`, `uibench` harnesses | NB is now `ohscore` + ~2–3k lines of QO-100 |
| 12 | `ohsradio` skeleton: `python3 -m ohsradio --headless` on the HAM sim, a window with band bar and scope, receive only; `packaging/ham/`, `build-deb.sh ham`, `test_ham_packaging.py` | two apps, both shipping |

Then remove `ohsnb/modes/PERF.md`'s special-case in `build-deb.sh` (it moves
with the modes) and update `DESIGN.md`/`HANDOVER.md`. Steps 1–7 are each a
few minutes of mechanical work and a test run; 8b and 10–11 are the ones to
do with a clear afternoon. Merge pain is minimised by the order: the files
other branches are most likely to be editing (`radio.py`, `mainwindow.py`,
`settings.py`, `scope.py`) move **last**, so they spend the least time in a
state another branch's edits cannot follow, and each of them moves in a
commit that does nothing else.

### 2.6 Packaging and releases

- `tools/build-deb.sh nb|ham [version]` → `openhamshack-nb_<v>_all.deb` /
  `openhamshack-ham_<v>_all.deb`. Each installs into `/usr/lib/<app>/` a copy of
  `ohscore/` and its own package, plus `/usr/bin/<app>`. Two debs never ship
  the same path, so both install side by side and each is internally
  consistent; the core is ~1 MB of Python, so the duplication is free.
- Versions: `ohsnb/VERSION` and `ohsradio/VERSION`, independent. `ohscore` has no
  version of its own — it is versioned by the commit each app is cut from.
  A release of one app tests **both** apps (the release script runs the whole
  suite), so a core change cannot ship in one app having broken the other
  unnoticed.
- Windows: the installer recipe the port introduces is parametrised by app in
  the same way.
- Site: `site/` stays NB's; HAM gets its own page later (question 10).

### 2.7 The split as built (04/10/2026)

What differs from §2.2-2.6, and why. The commits on the branch say the
same at more length.

- **Order.** `host.py` and `audio.py` moved before the modes (the design
  had modes first): `ft8.py` and `freedv.py` import `host`, so the modes
  could not enter the core while `host` was in `ohsnb`. 8a was followed by
  a test (`test_core_engine.py`) that a minimal Engine subclass works;
  step 11 went in five commits (11a second display + icon loader, 11b
  Settings, 11c Welcome/About, 11d the main window, 11e the QApplication).
  The `pre-core-split` tag was not created: `main` at `a7cf1e8` is the
  reference.
- **Screenshots (step 0).** The screenshot tool runs the real window
  against the sim in real time, so two runs of unchanged code differ in
  up to 10 % of pixels. Making it deterministic would have changed what
  the published screenshots show, so each step was checked instead with a
  harness (not committed) that feeds the window seeded spectra with the
  clock frozen and grabs every mode in both themes, 1920 and 1366, all
  eight Settings pages, the welcome steps, About, logbook, memories,
  shortcuts and the second display: identical to `main` at every step
  bar a few pixels of the FT8 slot-progress bar that differ between any
  two runs of `main` itself.
- **Sim (step 5).** `ohscore.devices.simcore` holds `Presence`, `Station`,
  `FT8Activity` and `SimCore(Device)` (real-time pacing, the noise bank,
  the transmit FIFO and delayed loopback). The three QO-100 points became
  `SimCore` hooks: `_noise_density`, `_loopback_amp`, `_loopback_shift`.
  The RNG is drawn in the same order: a seeded run hashes identically.
- **Config (step 7).** `ohscore.config.Config(AppId, Registry, repair)`;
  `repair` is the app's cross-key fix-up on load (NB: gain ceiling, 2.7
  kHz). `host.conf_dir(app)` / `host.data_dir(app)` take the folder name.
  `ui.json` follows the app's Config and `$<ENV>_UI_CONF`.
- **Engine (8b).** Hooks are methods, not objects (§2.4). Log records and
  memories keep a per-app frequency key (`FREQ_KEY`: NB `"dl"`, HAM
  `"rf"`), so NB's existing logs and configs read unchanged.
- **The UI's Face.** §2.2 proposed a provider per widget (plan provider,
  secondary-line provider, guard text). They are one object,
  `ohscore.ui.face.Face`, given to the Bridge and reached by every widget
  through it, because the answers belong together: the band the scope
  draws is the band the readout parses and the logbook labels. It holds
  the app's name and icon, the band plan the scope shows (segments,
  markers, wide extent, axis labels), the readout's digit grouping,
  tuning cap, second line and frequency parser, the log's frequency
  heading, the second display's big frequency and status, and the
  sentences the voice panel and Settings show. Methods with no
  app-neutral answer raise NotImplementedError. NB's is
  `ohsnb/ui/face.py` (`Qo100Face`). **HAM will need more of the readout
  than the Face gives today**: NB's digits are a fixed 11-digit
  "10 489.540 000"; HAM's run from 1.8 MHz to 5.8 GHz, so its
  `digit_groups` will vary with the band, and the readout's fixed cell
  layout may need to follow.
- **Transmit card.** Stays NB (`ohsnb/ui/rail.py`), not a core card with
  a slot: everything on it is NB's vocabulary (Pluto gain in dB under its
  ceiling, the beacon meter, the level guard). HAM builds its own (drive,
  watts, SWR) from the core's Card, Slider and BarMeter. The rest of the
  rail (mode grid, receive card) is core.
- **Window.** `ohscore/ui/window.py` `BaseWindow`; NB's `MainWindow` fills
  `_header_status` (lock badges), `_transmit_card`, `MODE_KEYS`,
  `SHORTCUTS`, `TAGLINE`, `status_items` and the three dialogs. Settings
  pages are named builder methods in `PAGES`; NB adds `page_lnb` and
  `_transmit_limits` and its words for its keys. Welcome and About take
  their text from class attributes of NB's subclasses.
- **Stayed NB on purpose.** `bench.py` (its only scenario is NB's),
  `screenshots.py` and `uibench.py` (NB scenes; the generic part is a
  dozen lines), `ohsnb/dsp/lock.py`, `bandplan.py`, the lock badges and
  the beacon meter.
- **Moved that the tables did not mention.** `ohscore/ui/qtapp.py`
  (`make_app`, and `shutdown`, the Windows exit-crash fix);
  `ohscore/ui/appicon.py` (the icon search; the artwork stays per app).
- **Logger names** in moved modules still say `ohsnb.*` (`ohsnb.audio`,
  `ohsnb.modes_glue`, `ohsnb.ui`); the engine's logger is the app's
  (`LOGGER`). Renaming the rest is a visible change to log lines, left
  for a commit of its own.
- **Windows build.** `packaging/windows/openhamshack-nb.spec` names the
  lazily imported drivers at their new paths (`ohscore.devices.pluto`,
  `ohscore.devices.soapy`, `ohsnb.devices.sim`); `ohscore` itself is found
  by PyInstaller's analysis from `pathex=[ROOT]` like `ohsnb`. Not run on
  Windows during the split.

### 2.8 OpenHamShack Radio as built (phases A-C, 04/10/2026)

Built on the split core, every commit gated on the whole suite (both
apps), `python3 -m ohsnb --headless` locking on its sim, and the .deb
builds. What differs from sections 3-8, or was decided on the way:

- **Core hooks** HAM needed, each a no-op for NB: `_rx_dial`/`_tx_dial`
  (repeater shift, reverse), `_demodulate` (FM from its own 24 kS/s
  channel), `_rx_audio_gain` (half duplex), `_tx_chain` (FM renders at
  24 kS/s), `_mode_caps` (AM transmits); `validate=` on dict keys;
  `Config(freq_key=)` (HAM's memories are "rf"); `BaseWindow._under_header`
  (band bar), per-app `STEPS`; `Face.panel` (the FM panel).
- **FM, CTCSS, AM TX** are in the core (`ohscore/dsp/fm.py`,
  `ohscore/dsp/mod.py` AmMod), as section 2.2 planned. NR, notch and WSPR
  are not built (phase 3).
- **The receiver's centre** follows the band: a band the span holds is
  shown whole (DC off it when it fits on one side, in its middle when
  not); otherwise the span follows the dial. The "thin overview strip"
  of section 7 is not built.
- **TX offset is per device**: the Pluto's signal sits fs/4 above its
  analogue TX LO (leakage); the HL2's TX "LO" is an NCO and its 48 kS/s
  TX path passes only +-20 kHz, so its signal sits on it
  (`tx_offset_hz`, `tx_reach_hz` on the device).
- **Power**: `drive` through a per-band power chain (`bandPower`) to an
  estimated PEP; `maxDrive` (status) is the band's ceiling or the drive at
  which the estimate reaches the licence's limit, whichever is lower, and
  the drive control cannot pass it. A bigger PA lowers the drive by
  itself. Every number is labelled an estimate; the HL2's forward power
  is on a provisional curve until calibrated.
- **Licence data** was checked line by line against the PDFs before it
  was written (`licence-check.md`): no Ofcom figure was wrong, four plan
  details were. Foundation is the default class (the most restrictive;
  first run asks). `nearLondon` defaults off. Innovation bands, including
  2300-2302 MHz, are refused (no NoV setting yet).
- **The sequencer** has the `none` and `serial` (RTS/DTR by ioctl, no
  pyserial) drivers; HL2 OC, Pi GPIO and Pluto GPO are not built. Opening
  a serial port asserts RTS/DTR for an instant before they can be
  cleared; the Settings page says so.
- **The band simulator** builds each band from its plan on arrival,
  scaled by the UTC hour (`simHourUtc`), with real UK repeater pairs that
  open to the right CTCSS tone or a toneburst, IBP beacons on UTC, QRN,
  and telemetry from a simulated antenna (`simAntSwr`).
- **Two core bugs found and fixed** on the way: decoders' audio was
  stamped with each block's arrival time, which broke FT8 in real time
  (now stamped from the sample count); the simulators' UTC was anchored
  at open() rather than at the first read (NB's FT8 was 5 s late into
  its slots). Both affected NB too.
- **Not built yet**: transverters (built 07/10, see section 5.6), CW via
  the HL2's CWX, WSPR, NR/notch, the repeater-list import, Pi GPIO, the
  HL2 Settings page's discovery button, the Windows installer for HAM.

---

## 3. Frequencies — HAM vocabulary

All Hz, floats, as in NB.

| name | meaning |
| --- | --- |
| `rf` | the on-air frequency the operator sees and types; the VFO is an `rf` |
| `dev` | what the device tunes: `rf` itself, or the transverter's IF (`rf − xvLo`, or `xvLo − rf` for a high-side LO, which inverts the spectrum) |
| `ppm` | per-device reference error, measured once against a known signal (a beacon, WWV/MSF-referenced carrier, a GPSDO), applied to every `dev` tune; per transverter too when its LO is not locked |
| `xvLo` | a transverter's LO, per band (§5.6) |

Display is always `rf`; the readout's secondary line shows `dev` when a
transverter is in use, and the TX frequency when split or a repeater shift
is active. A spectrum from an inverting transverter is flipped by the
`FreqModel` before it reaches a feed, so the UI never knows.

---

## 4. Devices

### 4.1 Interface changes (core)

The NB interface ties RX and TX to one sample rate and calls the receive
tuning an "IF". Both stop being true on an HL2, whose TX IQ runs at a fixed
48 kHz whatever the RX rate (see `hl2-research.md`). Additions, all with
defaults that keep today's devices unchanged:

```python
class Device:
    tx_fs: float               # TX IQ rate; = fs for Pluto/sim, 48 000 for HL2
    caps: dict                 # rx_range, tx_range, gain ranges, duplex, telemetry list,
                               # "hw_keyer", "oc_outputs", "ptt_out", "lna", "attenuator", "pa"
    def set_rx_freq(self, hz)  # = today's set_rx_if (kept as an alias for NB)
    def set_drive(self, x)     # 0..1; Pluto maps to hardwaregain, HL2 to its drive register
    def set_outputs(self, bits)          # open-collector / GPO lines (sequencer driver)
    def telemetry(self) -> dict          # fwd/rev W, temp °C, current A, supply V; {} if none
    def cw_key(self, down: bool)         # hardware keyer/cwx path, where caps["hw_keyer"]
```

The engine's TX path renders at `tx_fs` (the filter-bank synthesis handles
any rate that is a multiple of 200 Hz — 48 kHz is), and the TX monitor and
loopback use `tx_fs` too.

### 4.2 Hermes-Lite 2 (`ohscore/devices/hl2.py`)

Pure Python, standard library + numpy: openHPSDR **Protocol 1** over UDP,
with the HL2's own extensions, exactly as documented in `hl2-research.md`.
No Quisk/SparkSDR code is copied (Quisk is GPL; OpenHamShack is not — question 11
if that is wrong); the protocol is implemented from the documentation and
checked against a packet capture of a known client **[to do on hardware]**.

- **Discovery** by UDP broadcast on port 1024 from every interface (and a
  direct probe of a configured address, for a radio on another subnet or
  behind a router), presented in Settings like Pluto *Find*: address,
  MAC, gateware version, board id. A gateware older than the minimum the
  driver is tested against is named, with the update sentence.
- **Receive**: one receiver at 48/96/192/384 kS/s (register 0x00 bits 25:24;
  setting `hl2Rate`, default 192 kS/s: covers any HF band's busy part and
  costs a Pi about a sixth of NB's 1.2 MS/s). EP6 datagrams carry 2 × 63
  samples of 24-bit big-endian IQ for one receiver; unpacked with numpy
  (`frombuffer` over many datagrams at once, one vectorised 24→32-bit sign
  extension per batch). The per-endpoint sequence number exposes a dropped
  datagram: counted in `overruns`, filled with zeros so timing stays true.
  At 384 kS/s that is ~3 050 datagrams/s — the reason 192 k is the default.
- **Transmit**: TX IQ (16-bit, **fixed 48 kHz** whatever the RX rate) in EP2
  datagrams, ~381/s, paced by the EP6 stream (one EP2 per N received, N fixed
  by the RX rate) so no host timer decides the rate. MOX is C0 bit 0 of
  every frame. The HL2 only queues TX samples while MOX is set and stops
  transmitting **~12 ms (PTT hang) after samples stop** — so the engine
  keeps EP2 flowing with zero IQ and MOX clear while unkeyed (the gateware
  watchdog would otherwise stop streaming), and keys by setting MOX on a
  stream already running.
- **Drive**: the HL2's drive register has only **16 steps over 7.5 dB** (0x09
  bits 31:28). `set_drive(x)` uses the register for the top 7.5 dB and IQ
  amplitude scaling below it, so drive is continuous from 0 to full and the
  power chain (§6) is calibrated through both.
- **Controls** mapped to settings: RX LNA gain −12…+48 dB (0x0A, direct-gain
  encoding), PA enable (0x09 bit 19; off routes to the low-level RF1 output,
  ≤ 17 dBm — the transverter case, §6 rule 8), T/R relay disable (bit 18), N2ADR
  filter selection through OC0–6 (0x00 bits 23:17, automatic per band from
  the board's published map, including the RX-only 3 MHz HPF), TX buffer
  latency and PTT hang (0x17), CW hang (0x10), CWX enable (0x0F).
- **Telemetry** (`telemetry()`): the rotating response registers carry
  temperature, forward power, reverse power and PA current as 12-bit ADC
  values. Temperature and current have formulas; **forward/reverse power
  need a calibration table** (Quisk ships a spline); HAM ships its own table
  measured on Brian's HL2 against a power meter, and treats the reading as
  "measured (calibrated)" only once that exists. SWR = (1+Γ)/(1−Γ),
  Γ = √(rev/fwd), only above a minimum forward power.
- **Receive while transmitting**: the RX stream continues while keyed; HAM
  mutes RX audio while keyed by default and uses the stream for the scope.
- **Watchdog, two layers**: the engine's watchdog clears MOX explicitly;
  independently, the HL2 drops TX ~12 ms after TX samples stop and its own
  watchdog stops everything if EP2 stops arriving. The HL2 watchdog is
  **never disabled** (register 0x39) — only RX-only use may do that.
- **Discovery** also learns: gateware major/minor, board id (0x06 = HL2),
  number of receivers, fixed-IP/DHCP flags. Port 1025 is used as the
  documented fallback; the Windows firewall sentence names both ports.

### 4.3 Pluto family on terrestrial bands

The existing `PlutoDevice` serves, with three HAM-specific facts:

1. **Tuning floor.** The ADI driver accepts an RX LO from **70 MHz** and a TX
   LO from **46.875 MHz** on an AD9361/AD9364 (`MIN_RX_CARRIER_FREQ_HZ
   70000000`, `MIN_TX_CARRIER_FREQ_HZ 46875001` in
   `drivers/iio/adc/ad9361_regs.h`), and 325 MHz–3.8 GHz when it identifies
   as AD9363 (the default; "AD9364 hack" lifts it). So, realistically:
   - **6 m (50–52 MHz): TX possible, RX not** — the receiver cannot tune
     there. (Receiving 50 MHz with the RX LO at 70 MHz and a 20 MHz offset
     would need ≥ 45 MS/s through USB 2 — not a product.) Since the HL2 has
     no 6 m either, the only ways onto 6 m with this hardware are a
     transverter on the HL2 (28 MHz IF) or **Pluto TX + an RX-only SDR for
     receive** — a "split device" band, which the engine could support
     (separate RX and TX devices, half duplex) but which is not in the MVP.
     Question 5.
   - **4 m (70.0–70.5 MHz)** sits on the RX floor: place the RX LO at
     ≥ 70.0 MHz above or inside the band (e.g. 70.6 MHz at 2.4 MS/s puts the
     band at −600…−100 kHz). Performance this close to the specified floor
     is **[unverified]**; offered as "experimental" until measured.
   - 2 m, 70 cm, 23 cm, 13 cm, 9 cm, 6 cm (5.65–5.85 GHz) are inside
     70 MHz–6 GHz with the AD9364 setting; 2 m needs it (below 325 MHz).
     3 cm and above only through a transverter. The device reports which
     identity it runs as, and HAM greys out bands it cannot reach with a
     sentence saying how to change it (`fw_setenv compatible ad9364`, as in
     ADI's "customizing" page) — it never changes firmware itself. (Reversed
     05/10/2026: it now offers to, with consent; see "Diagnostics" at the end.)
2. **Output power is ~mW** (+6.5 dBm max per kittenlabs, NB research §4; far
   less at the extremes — "very low" at 46 MHz per BATC forum reports
   **[unverified]**). Every real QSO goes through a PA or transverter, so the
   sequencer (§6.1) and the drive ceiling per band are not options.
3. **TX LO leakage and harmonics are in-band problems now.** On QO-100 the LO
   sits 30 kHz outside the uplink passband. On 2 m a 30 kHz offset puts the
   leakage carrier *on someone's channel* in the band, then amplified by the
   PA. HAM's Pluto TX LO planner therefore: places the LO a configurable
   offset from the signal (default fs/4) **and** relies on the AD9361's TX
   LO-leakage/quadrature calibration (left on); the residual carrier level
   is unknown **[unverified — bench measurement with a spectrum analyser and
   dummy load is a gate before any PA use]**. The Pluto has no output
   low-pass filter: harmonics (e.g. 2nd of 145 MHz at 290 MHz) must be
   removed by the PA's or an external LPF. The welcome page and the
   transverter/PA settings say so.

Sample rates for HAM on a Pluto: 1.2 MS/s (Pi), 2.4 MS/s (default: native
with no FIR — the Tezuka nano's preferred rate anyway — and a 2 MHz-wide
panadapter covers all of 2 m's busy part), 4.8 MS/s (laptops; 70 cm
satellite/repeater views) **[CPU to be measured with `ohscore.bench`]**.

### 4.4 Receive-only SDRs (SoapySDR)

`SoapyDevice` gains gain elements, antenna choice, the RTL's direct-sampling
and bias-tee settings, and per-device sample-rate lists read from the
driver. Status on Debian 13 (checked locally with `apt-cache`, 04/10/2026):

| radio | Soapy module in Debian 13 | note |
| --- | --- | --- |
| RTL-SDR (incl. Blog V4) | `soapysdr0.8-module-rtlsdr` 0.3.3 | the V4 covers HF through its built-in upconverter (vendor claim) **[unverified with the Debian librtlsdr: the V4 needs a librtlsdr that knows its R828D; Debian's may not]** |
| Airspy R2/Mini | `soapysdr0.8-module-airspy` | |
| Airspy HF+ | **not packaged** | SoapyAirspyHF from source |
| SDRplay | **not packaged** | vendor API + SoapySDRPlay3 from source; installers are in `~/vendor` |

Receive-only devices refuse every key-up ("This device is receive-only"),
as in NB.

### 4.5 The simulator (`ohsradio/devices/sim.py`) — the default device

As in NB the sim is the default until the operator picks a radio, and the
test suite's backbone. It simulates **a band, not a radio**, at the engine's
device interface:

- the current band's noise floor (higher at 160/80 m than at 10 m — a
  per-band atmospheric noise figure from the plan data), QSB (slow Rayleigh
  fading per station), QRN impulses (for the noise blanker), a dead carrier
  (for the notch), and a population drawn per band from its plan's activity
  centres: SSB nets, a CW segment, the band's FT8/FT4 clusters at their dial
  frequencies, PSK, RTTY, a WSPR sub-band, an SSTV frequency, an IBP beacon
  rotation on 20–10 m at the right minute of the cycle;
- on 2 m/70 cm: FM simplex on the calling channel, a repeater with an input
  and output pair, a CTCSS tone and a courtesy tone, an SSB/CW activity area;
- our own TX looped back: the sim measures what we transmit (occupied
  bandwidth, frequency, drive) and reports simulated forward/reverse power
  from a per-band simulated antenna SWR (settable — the SWR guard's test), and
  plays the repeater's output back on its output frequency when we open it
  with the right tone (the CTCSS/toneburst test).

Separately, **`hl2sim`** emulates an HL2 *at the protocol level* on
`127.0.0.1` UDP: discovery reply, start/stop, C&C register writes recorded,
an RX stream fed from the band sim, TX IQ accepted and looped back, telemetry
from the simulated antenna. It exists so `hl2.py` — the code that will meet
the real radio — runs end to end in tests, including dropped-datagram and
late-host cases. An HL2 can then be emulated for a whole UI session
(`device=hl2`, `hl2Address=127.0.0.1:…`).

---

## 5. OpenHamShack Radio features beyond NB

### 5.1 Bands, segments and the plan model

Data, not code paths, with every number sourced and dated in
`bandplan-r1-uk.md`:

```python
# ohsradio/plans/rsgb_2026.py (shape)
PLAN = {"id": "rsgb-2026", "title": "RSGB band plan", "source": "…", "effective": "…",
        "bands": [Band("20m", 14_000_000, 14_350_000, segments=[Seg(lo, hi, label, modes, max_bw, flags)],
                       centres=[Centre(f, "FT8", mode="ft8"), …], beacons=[…]), …]}
# ohsradio/licences/ofcom.py (shape)
LICENCE = {"id": "ofcom-2024", "classes": {"foundation": [Allow(lo, hi, max_pep_w, notes)], "intermediate": …, "full": …}}
```

- **Band** = a licence allocation the operator can transmit in (or listen
  to). **Segment** = a plan subdivision with allowed mode classes and a
  maximum bandwidth. **Centre** = a centre of activity (calling frequency,
  FT8 dial, QRP, SSTV, beacon) — the source of the dial-frequency presets.
- Region and plan are settings (`region` = `r1`, `plan` = `rsgb-2026` /
  `iaru-r1`), licence regime and class are settings (`licence` =
  `ofcom-2024`, `licenceClass` = `foundation` / `intermediate` / `full`).
  Adding another country is a new data file and a test of its tables.
- The bandplan strip on the scope, the segment name in the status line and
  the band bar are all drawn from this data.

### 5.2 Band stack registers and VFOs

- A band bar (160 … 6 cm, only the bands the receiver covers - since
  13/10/2026 the others are left off rather than drawn faint, except one
  the Pluto's AD9364 setting would reach; bright where the licence allows
  TX, RX-only bands dim) — click a band to recall its
  stack, click again to cycle its **three registers** (dial, mode, filter,
  AGC, repeater settings), as on most transceivers. Registers are persisted
  per band (`bandStacks`). The first visit seeds them from the mode the
  operator is in (Brian, 13/10/2026; `bands.first_register`): from a
  digital mode the band's FT8 dial (FT4's from FT4), otherwise the start of
  the plan in force's widest SSB segment in the band, LSB 3 kHz in so the
  voice is inside it (20 m from SSB: 14.125 USB, 14.074 FT8, 14.025 CW).
- VFO A/B (today's `vfo`/`txVfo`), A=B, A↔B, split; RIT and XIT exist
  already in the engine and get their HAM controls.
- Mode follows the plan's convention on band change: LSB below 10 MHz, USB
  above, unless the stack register says otherwise.

### 5.3 FM, repeaters, CTCSS, toneburst

`ohscore/dsp/fm.py`, vectorised like the rest:

- **NBFM receive**: the filter bank gives a channel at 24 kS/s (a decimation
  the bank already supports); a polar discriminator (`angle(x[n]·conj(x[n−1]))`
  — vectorised, no loop), de-emphasis, decimate to 12 kHz. Channel width
  12.5 kHz (±2.5 kHz deviation) or 25 kHz (±5 kHz) per band/plan.
- **Squelch**: noise squelch (energy above the voice band in the
  discriminator output, per 10 ms block) with hysteresis; carrier squelch
  for SSB/AM is optional (`sqlLevel`), off by default as in NB.
- **CTCSS decode**: a bank of Goertzel filters over the 50 standard tones on
  the discriminator output before the 300 Hz high-pass, 1 s windows, every
  0.25 s; reports the tone heard (`events`) and gates audio when tone squelch
  is on.
- **CTCSS encode**: the tone added to the modulating audio at ~10–15 % of
  peak deviation (setting) **[the exact UK recommended level to be sourced]**;
  the voice path high-passed at 300 Hz so the tone is clean. The tone wheel
  offers the IARU R1 35-tone list and shows UK tone *letters* (A 67.0 …
  J 118.8; Scotland mostly G 103.5 in the central belt, F 94.8 in the east —
  an indicative tally, `bandplan-r1-uk.md` §5).
- **1750 Hz toneburst**: a button and shortcut sending 1750 Hz for a set
  duration (default 500 ms) at the start of the over. Still permitted on UK
  repeaters alongside CTCSS but "being withdrawn in line with IARU-R1
  recommendations" (RSGB) — so it is a button, not a default.
- **Repeater shift**: per band from the plan (`repeaterShift` auto / − / + /
  simplex / custom, `repeaterOffsetHz`), with **reverse** (listen on the
  input) on a key. "Auto" means the plan knows the repeater sub-band: UK
  2 m RV48–RV63 −600 kHz; UK 70 cm RB0–RB15 output 433.000–433.375 with
  input **+1.6 MHz** (the reverse of the IARU R1 plan — the best argument
  for data-driven plans), RU +7.6 MHz, 9 MHz DV pairs −9 MHz; 23 cm RM
  −6 MHz; 6 m +500 kHz (or +1 MHz for the 2026 inputs); 10 m −100 kHz. The TX
  guard judges the *transmit* frequency, so a shift that would put the
  input outside the licence is refused, with that sentence.
- **Repeater channels**: the UK channel names (RV/RU, V/U) computed from the
  plan; a repeater *list* (callsign, location, tone) is an operator import
  (CSV) rather than shipped data — question 7.
- FM transmit is refused on HF below 29 MHz by the plan guard (UK plan puts
  FM at 29.6–29.7 MHz); NB refuses FM everywhere, as now.

### 5.4 AM, SSB, CW

- **AM**: TX added (carrier + DSB, modulation index capped at 90 %, peak
  envelope = PEP; power accounting in §6 rule 6 uses PEP, carrier = ¼ PEP).
- **SSB**: unchanged engine; HAM adds TX audio equaliser presets later.
- **CW**: keyboard CW and macros as in NB; plus
  - **HL2**: the standard gateware has **no iambic keyer** (only special
    CW=2 builds do; the wiki page saying otherwise is AI-generated —
    `hl2-research.md` §6). What it has: a key jack (tip = key, ring = PTT)
    that produces shaped CW in the gateware for a straight key or an
    *external* keyer, with break-in set by the CW hang register, and **CWX**,
    where the host keys the gateware's CW generator through bits of the TX
    I samples. HAM sends keyboard CW and macros through CWX (gateware-shaped
    envelope, true break-in timing) and leaves paddles to an external keyer
    on the jack. Host MOX stays clear while the gateware sends CW.
  - **Pluto**: semi-break-in only (sequencer delays make QSK unrealistic
    through relays); paddle input via serial CTS/DSR or Pi GPIO is phase 3
    and needs a latency measurement first (question 6).
  - break-in delay (`cwHangMs`), sidetone, spot.

### 5.5 Digital modes

All of NB's modes, unchanged code, plus per-band dial frequencies from the
plan (FT8/FT4/WSPR/PSK/SSTV/FreeDV centres). One click "FT8" on the band bar
puts the dial on that band's FT8 frequency. New:

- **WSPR**: `wsprd` decodes 12 kHz WAVs of each 2-minute slot (WSJT-X
  package, present on the development machine: `/usr/bin/wsprd`, `wsprcode`, `wsprsim`);
  `wsprcode` gives the 162 channel symbols for TX (4-FSK, 1.4648 Hz spacing,
  ~110.6 s) — verified locally that `wsprcode "GM4BRI IO86 37"` prints the
  symbols. TX duty cycle setting (default 20 %), band hopping later. Spots
  uploaded to WSPRnet only if the operator turns it on (network, question 9).
- The occupied-edge check NB already does (both edges of the rendered
  audio, not the dial) is what makes the awkward cases come out right: an
  FT8 signal on the UK 60 m dial of 5357 kHz must keep its audio below
  1 kHz to stay under the RSGB plan's 5358 kHz ceiling, and the guard will
  say exactly that when an operator clicks a reply at 1.5 kHz.
- **JS8Call** stays "use JS8Call itself through the loopback audio output"
  (NB's second-output design), as in NB.

### 5.6 Transverters, offsets, antennas

- **Transverter table** (setting, list): name, RF range, IF range, LO,
  inverted?, IF drive ceiling (dBm), PTT line, sequencer profile, whether
  the device's PA must be off. A band served by a transverter takes its
  device and IF from it. Uses: Pluto 2 m IF → 23 cm/13 cm/3 cm transverters;
  HL2 28 MHz IF → 2 m/4 m transverters; an **upconverter** on an RX-only SDR
  for HF.
- **As built (07/10/2026, both apps): converters.** Brian asked for SDR
  Console's Converter Definitions window, so the table above became that
  window's model, shared with OpenHamShack QO-100 NB (`ohscore/converters.py`,
  docs/converters.md): an ordered list (`converters`) of title, type
  down/up, RX only, TX only or RX/TX, RX and TX offsets in Hz, inverted, and the
  most drive in dBm - and a per-band choice of one (`bandConverters`,
  `ohsradio/xvtr.py`), set on Settings › Converters with SDR Console's
  columns, buttons and a "+ VHF/UHF/SHF" pack of sourced transverter LOs.
  Where it differs from the table above: no RF/IF range fields (the band
  is the RF range; the IF follows from the offset), no PTT-line or
  sequencer-profile fields yet (below), and "must the PA be off" is a rule
  rather than a field (rule 8). How it works:
  - the dial stays `rf`; only the device boundary converts
    (`Radio._dev_freq`, through the band's converter: `dev = rf - LO`, `rf
    + LO` or `LO - rf`). An inverting converter has the engine conjugate
    the IQ as it leaves the device and before it is written
    (`Engine.rx_invert`/`tx_invert`), so feeds, channels, modulators and
    the guard never see the mirror - as section 3 asked;
  - **the licence and band-plan guard judge the on-air signal**, as they
    always did; the device's reach is judged on the IF. Tested: Foundation
    refused 1296.2 MHz through a 144 MHz IF that it may use directly;
  - a band the radio cannot reach is offered through a converter (the band
    bar judges the IF against the device's range); 6 m's `deferred` lifts
    when it has one;
  - **TX only** (07/10/2026): a band set to one is received directly and
    transmitted through it; every transmit check below treats it as RX/TX
    (`xvtr.rx_for_band` is the receive side's lookup, `for_band` and
    `Radio._conv_at` the transmit side's by default);
  - **power (rule 8)**: an RX/TX or TX-only converter must give its most drive before
    a band can be set to transmit through it (Settings refuses), and a
    stored one without it refuses to key; `maxDrive` is the lower of the
    band's ceiling and the drive at which the device's full output at the
    IF meets the most drive (`Radio._drive_limit`) - all of it the
    **transmit** dial's band, chain and converter, so a split transmit
    dial behind a transverter is held too. "Full output" is the higher of
    the device's own figure and the band's entered `devW`; when neither is
    known the converter refuses to key ("output … is not known"). The
    guard checks the drive again at key-up for the request being keyed (a
    Tune at its share), again on the converter `_tx_key_up` picks and as
    the device keys; drive, tuneDrive, bandPower, converters and
    bandConverters re-run it while keyed; and every drive given to a
    keyed device passes `_drive_device`, which clamps it to the cap
    whatever the state says. An HL2 whose PA is on - by the saved setting
    or the running radio, whichever says on - refuses a converter that
    takes 0 dBm or less (the design's "forces the PA off", as a refusal,
    because hl2Pa needs a restart and stays the operator's). The
    measured-power licence check is off through a converter: the HL2's
    sensor then reads the transverter's input. A transverter's gain goes
    in the chain's PA gain; with none entered the transmit card says the
    power is unknown (`licenceInfo.powerUnknown`) instead of printing the
    radio's milliwatts - a warning, not a refusal. These follow the
    converter safety review of 07/10/2026;
  - a band set to a converter missing from the list refuses to transmit
    rather than going direct: the radio's output is wired to the
    transverter's IF input;
  - moving the transmit dial into another converter's band mid-over unkeys;
  - **sequencing**: the per-band/per-transverter profiles of section 6.1
    are not built - the sequencer has one output. The hook is
    `Sequencer.use(converter)`, called with the over's converter before
    `key_up`; it only records it today;
  - the band simulator puts the same converter in front of itself
    (`set_rx_converter`/`set_tx_converter`), so 144.2 MHz through a 23 cm
    transverter sounds like 23 cm, and through an inverting one it mirrors
    both ways - a USB tone keyed through it landing 1 kHz above the dial
    proves the engine undoes it.
- **Per-band antenna/filter selection**: HL2 N2ADR filters automatic (the
  board's OC map); the remaining OC outputs, Pi GPIO lines and serial lines
  drive an antenna switch or band decoder per band (an `antennaMap`), and
  Pluto RX/TX port choice per band where the board has more than one.
- **S-meter calibration** per device per band per gain setting: dBFS →
  dBm offset measured with a signal generator (a Settings page walks
  through it); IARU R1 Technical Recommendation R.1 (1981): S9 = −73 dBm on
  HF, −93 dBm on VHF, 6 dB per S unit (`bandplan-r1-uk.md` §6; secondary
  source, the R.1 text itself not read). Uncalibrated devices show dBFS and
  say so.
  **As built (05/10, both apps, `ohscore/ui/smeter.py`):** one offset per
  device and band, not per gain setting - the gain it was measured at is
  recorded and a manual change is allowed for dB for dB; under the
  receiver's own AGC the calibration is reported as not holding. Kept in
  ui.json, not the state registry, and computed in the UI: the engine's
  meter feed is still dBFS (no `sMeter`/`dbm` fields). Calibrate… (the
  meter's menu, or Settings › Radio) takes the known level of the signal in
  the passband. Units: S-units, dBm, dBFS (default), dB over noise, and in
  NB dB vs beacon; styles bar (default), analogue, digital. The R.1 text
  has since been read (`bandplan-r1-uk.md` §6, [I4]): above 30 MHz is
  −93 dBm.

### 5.7 Noise blanker, notch, NR

- **NB**: NB's impulse blanker, unchanged (now also fed by the sim's QRN).
- **Auto-notch**: FFT-domain (overlap-add at 12 kHz, ~43 ms frames): bins
  that stay ≥ N dB above their neighbours for ≥ 0.5 s are attenuated —
  vectorised per frame. The classic LMS notch is a per-sample loop, which the
  design forbids on the RX path.
- **NR**: spectral subtraction / Wiener gain per frame with a minimum-
  statistics noise estimate; one strength control. Measured CPU must fit the
  Pi budget before it ships.
- Digital modes are fed the audio *before* NR/notch (decoders do better on
  the raw passband), as NB already gives decoders a fixed wide filter.

*As built (05/10/2026), NR only - the auto-notch is still to do:*

- **NR is WDSP's NR2** (EMNR, Warren Pratt NR0V; GPL-2+, credited in
  `packaging/copyright`), ported to numpy in `ohscore/dsp/nr.py` at WDSP's
  defaults: gain method 2 (his GG/GGS tables, `ohscore/dsp/nr_tables.npz`,
  rebuilt by `tools/nr-tables.py`), Martin's minimum statistics (the
  estimator planned above), and the aepf musical-noise smoothing. Shared
  by both apps (core), not HAM-only.
- 720-point frames, 4x overlap, at 12 kHz: each 75 ms block is five whole
  hops, so it adds 45 ms of delay. Per-frame numpy over 361 bins; no
  per-sample loop.
- After the demodulator, on the speaker's audio only, in USB/LSB/CW/AM/FM;
  an exact bypass in every other mode and when off. The decoder queue gets
  the demodulated audio untouched (tests/test_nr.py checks it block by
  block in both engines). It works on the audio as it was before the AGC
  (the demodulator hands it the gain it applied): after the AGC, the noise
  in every pause is lifted and minimum statistics stops seeing it.
- Controls `nr` (off by default) and `nrStrength` (0-100 %, default 50):
  strength is an attenuation limit, 0 dB to -40 dB, applied after the
  estimator. Receive card, Shift+N (N is the noise blanker), Settings ›
  Audio. Switching crossfades over 50 ms and never touches the AGC.
- Measured: segmental SNR on the simulator's voice in in-band noise
  +3.5/+1.4/+1.0 dB (white, 0/6/12 dB) and +3.2/+1.1/+0.8 dB (pink), pauses
  13-15 dB quieter; 1.1-1.3 ms per 75 ms block on the development machine, an estimated
  10-17 % of a Pi 400 core while on (docs/PERF.md) - inside the budget.

---

## 6. Safety

NB's rules carry over verbatim where they are about the program, and are
re-cut where they were about QO-100. The engine enforces all of them; the UI
only displays them.

1. **Never transmits at start**, after a restart, a reconnect, a settings
   save, a band change or a memory recall. Nothing keys except `ptt()`,
   `send()` and `tune()`.
2. **Licence guard (hard).** Every key-up and every dial/band/split/shift
   change while keyed is checked: the whole occupied signal (both edges, as
   NB) lies inside an allocation the configured licence class has, at a
   power the class allows there. Refusal raises `TxRefused` with the sentence
   naming the class and the limit ("Foundation licence: 23 cm is not
   available", "Intermediate licence: 32 W PEP maximum on 1850–2000 kHz").
   The class is a Settings item behind `authorise=True` and the first-run
   page. Licence peculiarities the data must carry and the guard must apply
   (all in `bandplan-r1-uk.md` §1): limits per *sub-allocation*; limits in
   **ERP/EIRP** on some bands (430–432 MHz 40 W ERP, 472 kHz 5 W EIRP, 60 m
   200 W EIRP), which need the antenna gain from the power chain; 60 m only
   for Full, only in the eleven UK segments, ≤ 6 kHz; 431–432 MHz not within
   100 km of Charing Cross (a station-location fact — a setting, not
   guessable); bands not licensed at all (2350–2390 MHz, 3410–3475 MHz,
   10.125–10.225 GHz) refused for every class.
3. **Bandplan guard (configurable).** Mode/bandwidth against the plan's
   segment: `enforce` (refuse), `warn` (the transmit card's standing
   warning, key anyway) or `off`. The
   RSGB plan is a voluntary code, the licence is law, so the default is
   **warn**, except that **beacon segments (IBP 14.100 etc., VHF beacon
   sub-bands) and satellite sub-bands are refused** whatever the setting —
   the analogue of NB refusing the QO-100 beacon segments. (Question 2.)
4. **TX time-out** (default 5 min; FT8/WSPR overs are short anyway), **dead
   air** (voice, 3 s), **UI watchdog** (2 s): as NB.
5. **Drive ceiling per band**, settable only from Settings; the panel's
   power control cannot exceed it.
6. **Power vs licence.** The engine knows *drive*; the licence talks about
   *watts PEP at the antenna*. HAM keeps a per-band **power chain**: device
   output at full drive (measured by the HL2's forward-power sensor, or
   entered), PA gain or PA output at full drive (entered), feeder loss
   (entered). From it the guard computes the estimated PEP and refuses a
   drive that would exceed the class limit; where a measured forward power
   exists (HL2 alone, or a PA with a power sensor on a serial line — later),
   a measured excess unkeys too. The UI says plainly which numbers are
   estimates. A band with no power chain configured transmits only at the
   device's own (barefoot) power. *(Changed 05/10/2026, see the decisions
   at the end: the estimate now warns and does not refuse or hold the
   drive; a measured excess, where nothing entered sits between the sensor
   and the feeder, unkeys.)*
7. **HL2: SWR and temperature.** The HL2 gateware has **no ALC and no SWR
   or reflected-power fold-back**: reverse power is telemetry only
   (`hl2-research.md` §7, from the gateware source). Its one protection is a
   thermal cut-out (~55 °C off, ~50 °C on) — which is bypassed when "band
   volts" is enabled, so HAM never enables band volts. The engine therefore
   computes SWR from forward/reverse power continuously while keyed and
   **unkeys above `swrLimit`** (default 3:1, a few hundred ms average so
   SSB peaks do not trip it), refuses to re-key above it until the operator
   acknowledges, and unkeys at `paTempLimit` (default 50 °C, below the
   gateware's own). It also watches the TX-inhibit and FIFO
   underflow/overflow flags the response registers carry. A `tune()`
   carrier runs at reduced drive (default 25 %) so an ATU sees a low-power
   signal.
8. **Transverters and PAs.** A band whose transverter needs ≤ 0 dBm IF drive
   forces the HL2's PA **off** (output then on RF1, ≤ 17 dBm — still enough
   to destroy a 0 dBm transverter input) and caps drive at the transverter's
   IF ceiling — the one configuration where a wrong number destroys hardware
   in a second, so the transverter page asks for the IF limit explicitly and
   refuses to save without it. The HL2's minimum hardware gain is only
   7.5 dB below maximum, so the low levels come from IQ scaling; the cap is
   applied there and re-checked against measured output on the first key-up
   into a dummy load.
9. **Sequencing** (§6.1): RF never starts before the sequencer has finished
   key-up; relays never release before RF has stopped and the device's TX
   buffer has drained. Every PTT output is defined so that **process death
   leaves it unkeyed**: serial RTS/DTR drop when the port closes, Pi GPIO
   lines are released (the hardware must have a pull-down — written on the
   Settings page), HL2 MOX is cleared by the engine and the gateware's own
   behaviour on a silent host is the second line (§4.2).
10. Receive-only devices refuse; a band the device cannot tune refuses with
    the reason (§4.3).

### 6.1 The sequencer (`ohsradio/sequencer.py`)

```
key-up:   [mute RX] → out1 (antenna relay / preamp bypass) → wait t1 → out2 (PA on) → wait t2
          → device TX start at zero drive → ramp drive over 5 ms → RF
key-down: wait for the TX queue to go out (device.tx_queued(), a normal end only) → drive → 0 → device TX stop
          → out2 off → wait t2' → out1 off → wait t1' → unmute RX
```

- Outputs are named per station (e.g. "preamp bypass", "PA PTT", "6 cm
  relay") and mapped to drivers: `hl2_exttr` (the rear EXTTR open-collector,
  pulled low whenever the HL2 is transmitting, 28 V / 1 W max), `hl2_oc:7`
  (the one OC bit the N2ADR board leaves free) and `hl2_io:<n>` (the eight
  outputs of N2ADR's newer I/O board, over the HL2's I2C), `serial:<port>:
  rts|dtr`, `gpio:<chip>:<line>`, `pluto_gpo:<n>` (the GPO lines F5OEO's
  firmware exposes **[unverified on stock firmware]**), `none`.
- **HL2 timing is partly in the gateware**: EXTTR follows the radio's TX
  state, and RF is delayed by the TX buffer latency (default 20 ms) after
  MOX — a built-in key-up delay **[derived from the gateware source; to be
  measured on a scope]**. For an HL2 driving a PA directly from EXTTR, HAM
  sets the buffer latency to the PA's required delay rather than running its
  own wait; for anything else (a mast-head preamp, a relay box) the host
  sequence runs first and sets MOX last.
- Profiles per band/transverter: which outputs, delays (default 25 ms each,
  setting range 0–500 ms), and whether CW break-in may hold the sequence
  up between characters (hang time).
- The sequence runs on the TX thread with monotonic-clock waits; its state
  is published (`seq` in `meter`), so the UI can show "PA ON" before "ON
  AIR".
- Tested against a fake output driver recording timestamps: ordering,
  minimum delays, unkey from every intermediate step (watchdog firing during
  t1, device failing during ramp) always walks back down in the reverse
  order.

---

## 7. User interface

NB's UI quality is the bar: hand-painted QPainter, cached images, dark
instrument look with a light theme, no stock plots, nothing fetched.

**Carries over unchanged**: panadapter + waterfall with plan strip, decode
labels, zoom scope, frequency readout, meters, PTT button and on-air frame,
mode panels (FT8 sequencer, terminals, FreeDV, SSTV), logbook, memories,
settings framework, first-run, second display, shortcuts overlay, toasts.

**Goes**: beacon-lock and TX-lock badges, the own-signal-vs-beacon meter,
the uplink line, the LNB page.

**New or changed**:

- **Band bar** under the readout: 160 80 60 40 30 20 17 15 12 10 6 4 2 70 23
  13 9 6cm (and transverter bands), brightness by reachability and licence.
- **Readout**: VFO A large, VFO B small, split/RIT/XIT tags; secondary line
  for TX frequency, repeater shift (↑ −0.600) and transverter IF.
- **Licence chip** where NB's lock badges were: "Full · 400 W PEP · CW/narrow
  digital" for the segment under the dial (class, limit, segment), turning
  amber in a warned segment and red where TX is refused, with the reason as
  its tooltip. Next to it a **sequencer chip** (RX / SEQ / PA / ON AIR).
- **Panadapter spans**: wide view = the device's full rate (HL2 up to 384
  kHz; Pluto 1.2–4.8 MHz); click-drag and wheel zoom as now. Bands wider
  than the span scroll with the VFO; the plan strip shows the whole band
  in a thin overview above the scope with the visible window marked.
- **Meters** (TransmitCard slot): S-meter in S-units/dBm when calibrated;
  while keyed, forward power (W), SWR, ALC/TX peak, PA temperature and
  current (HL2), all hand-painted like NB's BarMeter.
- **FM panel** (the mode panel for `fm`): squelch, CTCSS TX/RX tone wheel,
  tone heard, shift (− / + / simplex / custom), reverse, 1750 Hz button,
  channel name, repeater list lookup.
- **Settings pages**: Licence (class, plan, bandplan guard), Bands & antennas
  (power chain, drive ceilings, antenna map), Transverters, Sequencer (with
  a "test outputs" button that toggles each line with RF **off**), HL2
  (address, rate, LNA, filter board, keyer), S-meter calibration.
- **First run**: device choice (sim default), licence class and callsign,
  the PA/harmonics warning for Pluto users, and the same "I hold a licence"
  acknowledgement NB has, worded for terrestrial bands.

---

## 8. Phased build plan

**Phase 0 — core split** (§2.5, steps 0–12). Exit: NB bit-for-bit
behaviourally the same (suite, headless run, deb install, pixel-identical
screenshots); `ohsradio` skeleton receives on the sim.

**Phase 1 — MVP: HL2 + Pluto, SSB/CW/FM/FT8.**
1. `ohsradio` state, plans (RSGB + Ofcom data with table tests), licence and
   bandplan guards, band bar, band stacks.
2. HAM band sim (HF + 2 m/70 cm) and `hl2sim`.
3. `hl2.py`: discovery, RX at 48–384 kS/s, TX at 48 kHz, MOX, drive, LNA,
   N2ADR OC map, telemetry, SWR/temperature guards — against `hl2sim` first,
   then the real radio receive-only, then into a dummy load.
4. Pluto on 2 m / 70 cm with the AD9364 identity check, LO planner, drive
   ceiling.
5. Sequencer with serial RTS/DTR and HL2 OC drivers.
6. FM (NBFM RX/TX, squelch, CTCSS encode/decode, toneburst, shift/reverse).
7. FT8/FT4 with per-band dials; SSB; CW (keyboard, HL2 hardware keyer).
8. Packaging: `openhamshack-ham` .deb.

**Phase 2** — AM TX, split/RIT/XIT controls, transverters (Pluto 23 cm+
via 2 m IF, HL2 28 MHz IF), S-meter calibration, power chain, Pi GPIO
driver, Pluto 23/13/9/6 cm direct.

**Phase 3** — PSK/RTTY/SSTV/FreeDV on all bands (code exists; per-band
centres and UI only), WSPR, NR and auto-notch, SoapySDR RX-only (RTL v4,
Airspy HF+, SDRplay), repeater list import, Windows installer.

**Later / not now** — CAT-out (a rigctld-compatible socket so loggers and
WSJT-X can follow the dial), a second HL2 receiver, CW paddles on Pluto,
other regions' plans, rigs via CAT.

### 8.1 Test strategy

- Everything runs on the sim by default; no test needs hardware or an
  antenna. Tests run behaviour, never source text (house rule).
- **Guard tables**: for each licence class and every band edge, a key-up just
  inside and just outside, SSB both sidebands, FM with shift, CW at the
  pitch — generated from the plan data *and* cross-checked against a few
  hand-written cases quoted from the Ofcom schedule (so a data typo in both
  places is unlikely to agree).
- **End to end on the sim**: FT8 rendered on 20 m decodes at the right dial;
  a CTCSS-gated repeater opens with the right tone and not the wrong one;
  toneburst opens a toneburst repeater; SWR guard unkeys with the simulated
  3.5:1 antenna and not with 1.5:1; licence class change flips a 4 m key-up
  from allowed to refused.
- **HL2 driver vs `hl2sim`**: discovery, register writes captured and
  compared with the documented C&C values for a given band/drive/LNA, RX
  sample continuity across injected datagram loss, TX pacing (no underrun
  over 60 s), MOX cleared on watchdog, on `stop()` and on exception.
- **Sequencer** with a recording fake driver (§6.1).
- **NB regression**: the whole NB suite on every commit, screenshots compared
  through Phase 0.
- **Hardware checklist** (manual, with Brian; never key real hardware
  without him): HL2 RX on each band; HL2 TX into a dummy load with a power
  meter — drive vs watts per band (fills the power chain); SWR guard with a
  deliberately mismatched load; Pluto 2 m/70 cm TX into a spectrum
  analyser — LO leakage, image, harmonics, at the planned LO offset — before
  any PA; sequencer timing on a scope.

---

## 9. Risks and unknowns

| risk | why it matters | mitigation |
| --- | --- | --- |
| HL2 drive has only 7.5 dB of hardware range | low power (transverter IF, QRP) depends on IQ scaling, so DAC resolution and carrier suppression at low drive matter | measure output and spurs at low drive into a dummy load before any transverter use |
| Python keeping up with HL2 UDP at 384 kS/s (~3 000 datagrams/s each way at the top rate, see research) | a GIL stall drops datagrams; TX underruns click | default 192 kS/s; `recvfrom_into` a preallocated buffer, batch-unpack many datagrams per numpy call; a dedicated socket thread; measure on a Pi before promising 384 k there |
| HL2 gateware variations | registers/telemetry differ by version | record version at discovery; tested-version list; refuse unknown-major with a sentence |
| Pluto LO leakage / image / harmonics in-band | spurious emissions amplified by a PA | bench gate (§8.1); LO offset; no PA use until measured |
| No native 6 m anywhere (HL2 stops at 38.4 MHz, Pluto RX at 70 MHz); Pluto 4 m on its RX floor | a band Brian expected | transverter or split-device band (question 5); 4 m "experimental" |
| Power ≠ drive | licence limit enforcement is only as good as the power chain | measured HL2 power; explicit "estimated" labels; barefoot-only without a chain |
| RTL-SDR V4 with Debian's librtlsdr | V4 needs newer driver | detect and say so; document the build |
| SDRplay / Airspy HF+ unpackaged | install friction | sentence + INSTALL notes; not MVP |
| Pi CPU at 2.4–4.8 MS/s | NB measured 1.2 MS/s only | `bench` on the Pi; 1.2 MS/s Pi default |
| Plan/licence data errors | a wrong edge refuses a legal QSO or allows an illegal one | sourced, dated data; table tests; the chip shows the class and limit so the operator can see the rule being applied |
| The refactor regressing NB | NB is released and public | §2.5 rules: one move per commit, full suite + screenshot diff each step |
| Windows UDP broadcast / firewall for HL2 discovery | discovery silently fails | direct-address probe always; firewall sentence (port 1024) |

---

## 10. What this design deliberately does not do

- No CAT control of existing rigs (Brian: out of scope for now).
- No satellite operation in HAM (QO-100 is NB's; LEO satellites with Doppler
  are a different program).
- No automatic firmware changes on any radio (Pluto identity, HL2 gateware):
  the program says what to do.
- No shipped third-party data that may not be ours to ship (repeater lists).
- No network use by default (WSPRnet/PSKReporter uploads are opt-in).

---

## 11. Open questions for Brian

Listed in the hand-off report; kept here so the document is complete.

1. **Repository name**: keep `openhamshack-nb` as the monorepo, or rename (e.g.
   `openhamshack-radio`) before the split, with the gitsync/hub/release-path
   changes that implies?
2. **Bandplan guard default**: `warn` (licence hard, plan advisory — this
   design) or `enforce` like NB?
3. **Your station**: which licence class to default (Full for GM4BRI?), and
   which PAs, transverters, preamps and relays on which bands, keyed how
   (HL2 OC, USB-serial RTS/DTR, Pi GPIO, Pluto GPO)? This sets the MVP
   sequencer drivers.
4. **Your HL2**: N2ADR filter board or the newer I/O board; gateware
   version (74.2 is current stable); any external PA/ATU on it; a paddle
   with an external keyer on the key jack, or keyboard CW only?
5. **6 m**: neither the HL2 (no 6 m at all) nor the Pluto (cannot receive
   below 70 MHz) covers it natively. Which do you want — a 6 m transverter on
   the HL2's 28 MHz IF, a "split device" band (Pluto TX + RTL/Airspy RX), or
   6 m deferred? And 4 m on the Pluto as experimental (right on its 70 MHz RX
   floor)? Which Pluto(s) for which bands — the Tezuka nano (2.4 MS/s only)
   or a stock Pluto/Pluto+?
6. **CW paddles**: HL2 key jack only, or also paddles for the Pluto
   (serial/GPIO input, semi-break-in)?
7. **Repeater data**: operator CSV import (this design) or ship a UK list
   (needs ukrepeater.net's permission)?
8. **Power**: is "estimated PEP from an entered power chain" an acceptable
   basis for the licence power guard, or should power limits be advisory
   until measured?
9. **Network features**: WSPRnet / PSKReporter spotting wanted (opt-in)?
10. **Release and site**: `openhamshack-ham` from 0.1.0 with its own page
    (e.g. openhamshackham.brian-henderson.co.uk), and testers (Ray?)?
11. **Licence of the code**: Quisk, piHPSDR, linHPSDR and the HL2 gateware
    are GPL; the HL2's own `hermeslite.py` has no licence at all. This
    design implements Protocol 1 from the wiki and TAPR documents and copies
    no client source. Confirm that is the policy (or that OpenHamShack Radio may be
    GPL, which would let us borrow e.g. Quisk's power calibration table).
12. **Station location for 431–432 MHz**: the licence excludes it within
    100 km of Charing Cross. Irrelevant in Scotland, but the guard needs a
    "station location" setting to apply it honestly — default "outside", or
    derive from the locator?

## Decisions taken 04/10/2026 (Brian)

- **Hardware order: Pluto first.** Brian has no Hermes-Lite 2. The MVP is proven on
  real kit with the Pluto (2 m / 70 cm / 23 cm); the HL2 driver is built against
  the emulator and proven when one is bought.
- **6 m is deferred.** Neither radio receives it natively; a transverter on the
  HL2's 28 MHz IF is the likely later route.
- **GPL is acceptable.** The repository is already GPLv3, so code from Quisk or
  piHPSDR (GPLv3-compatible) may be borrowed into either `ohsradio` or `ohscore`,
  with attribution in the file and in NOTICES. The HL2 driver need not be a
  clean-room write from the protocol documents after all.
- **Band-plan guard warns by default.** Licence-class limits are always
  enforced; beacon and satellite segments are always refused.
- Repository keeps the name `openhamshack-nb` for now; a rename is cosmetic and
  touches gitsync and the release paths, so it waits until there is a reason.

## Decisions taken 05/10/2026 (Brian)

These answer §11's questions 3, 7, 8, 9, 10 and 12. Questions 4 and 6 (the
HL2's boards and paddles) wait until an HL2 is bought.

- **Licence class: no default.** Transmit stays locked until the operator
  picks a class. Foundation used to be the default, but a default that is
  wrong for most people is worse than a one-time choice: a Full licensee
  would be refused for no reason, and anyone who skips Welcome would
  silently inherit a class they may not hold.
- **Repeaters: CSV import only.** No list is shipped. Shipping one needs
  ukrepeater.net's permission and goes stale between releases. Import works
  anywhere.
- **Spotting: WSPRnet and PSKReporter, both opt-in.** Off by default, and
  nothing leaves the machine until the operator turns it on.
- **Power: advisory until measured.** The power chain's estimated PEP warns
  but does not refuse. Where the radio measures forward power (the HL2), the
  licence limit is enforced on the measurement. This reverses phase B's
  hard limit on an estimate: an estimate can be wrong in either direction,
  and Brian would rather see a warning than be refused by a guess. Licence
  *frequency* limits stay hard.
- **Station: bare radio for now.** No PAs, preamps or transverters, and
  keying is undecided, so the sequencer's hardware outputs wait. It stays
  simulated with its status chip.
- **Testers: Brian only for now.** It stays a preview until he has tried it
  on his own Pluto. Ray is not asked yet.
- **431–432 MHz exclusion: a setting, defaulting to outside.** A "Station
  within 100 km of Charing Cross" box, unticked by default. It is not worked
  out from the locator, because a four-character square is too coarse near
  the 100 km boundary.

## Added to the plan 05/10/2026 (Brian)

Chosen from a list of what a UK operator with a Pluto on 2 m / 70 cm would
miss. None is designed in detail yet. Each needs its own short design note
before it is built. They are listed in the suggested order.

1. **CAT-out: a rigctld-compatible socket.** WSJT-X, fldigi, JTDX and loggers
   then tune and key OpenHamShack Radio as if it were a rig, so it works alongside
   the operator's other programs instead of replacing them. This moves the
   item out of "later". Every key-up from it passes the same guards as the TX
   button; an external program must never be a way round the licence.
2. **Scanning.** Memory scan, band scan and a priority channel; it stops on
   squelch and resumes after a hold or when the carrier drops. Receive only:
   a scan never keys.
3. **APRS, receive and transmit.** 1200 baud AFSK (Bell 202, AX.25) on
   144.800 MHz. Decoded stations go to a list and a map relative to the
   locator. Position beacons are opt-in, with an interval and path
   (WIDE1-1,WIDE2-1); each beacon is an ordinary keyed transmission under
   the guards.
4. **Log upload.** QRZ and Clublog directly, each with its own API key
   stored as a secret, never logged. LoTW through TQSL, which does the
   signing; OpenHamShack Radio hands it the ADIF rather than handling the
   certificate.
5. **DX cluster.** A telnet client (with a configurable node) that shows
   spots on the waterfall and the band map; clicking one tunes to it. It
   connects only once switched on.
6. **Recording and playback.** IQ and audio recording, with playback through
   the same decoders and scopes as live signals. Some recording code already
   exists in ohscore; find out what it covers before designing.
   *IQ recording built 07/10/2026, in ohscore for both apps* (there was no
   earlier recording code: "record" in ohscore meant the HL2 emulator's
   register log): `ohscore/sigmf.py`, File › Record receive IQ…. It keeps
   the device's own stream (before the converter mirror) and a capture
   per retune, so playback can be a "file" device that replays it through
   the device interface - not built yet. Audio recording is not planned.
7. **Propagation panel.** Solar flux, K and A indices from a public feed,
   fetched only once switched on and cached; nothing fails without it.

**Not chosen:** FM satellites and the ISS with Doppler correction (offered,
not picked this time). DMR, D-STAR and Fusion stay out: their codecs are
encumbered or closed. M17 is the open route if digital voice is ever wanted.


## Diagnostics (05/10/2026)

Why: testers hit problems nobody else can see. The first, on 05/10: a
Windows tester's stock Pluto worked in NB and not in HAM - almost certainly
the AD9363 identity (§4.3), which keeps it off 2 m. Brian asked for the
program to find problems like this itself and offer to fix them. HAM only
for now; NB later (below).

**As built:**

- **Log file and report: the shared ones.** The always-on log
  (`<data>/logs/openhamshack-ham.log`) and Help › Save diagnostics… landed in
  `ohscore/diag.py` the same day from another session, for both apps. A
  HAM-only log and report were built first on this branch and dropped in
  favour of them: two log files and two report menus would only confuse a
  tester. The shared log already records device open/close, keyed
  transitions and every toast (so the guards' refusals).
- **HAM's findings in the report** (`ohsradio/diagnostics.py`): a fresh Find
  and, for a Pluto, reachable or why not, model, serial, firmware,
  identity, range, FIR and whether the fix can run on that firmware -
  asked afresh when the radio would not open, which is when the report
  matters most. Each probe has a deadline and records its failure as a
  sentence, on a worker thread before the shared dialog opens. ohscore
  gained the hook (`gather(more=)`) and redaction by shape (key blocks,
  common API-token prefixes) beside its by-name rule, ready for the
  QRZ/Clublog keys; not "any long random string", because a Pluto's
  hw_serial is 34 hex digits.
- **Chip check** (`ohsradio/plutofix.py`, `ohsradio/ui/diagnostics.py`): an
  AD9363-identified Pluto asked for a band outside 325 MHz-3.8 GHz (2 m,
  4 m, 6 cm), on a band pick (the greyed band-bar button included) or at
  start, gets a dialog instead of a bare error, offering **Apply the
  AD9364 setting…**, **Save diagnostics…** and **Close**; a failed start
  gets one with **Save diagnostics…** and **Check radio…**. Help › Check
  radio… lists reachable, model, serial, firmware, identity, FIR/sample
  rate and each licensed VHF/UHF band's reach, and offers the fix or its
  Undo.
- **The fix reverses §4.3's "it never changes firmware itself"** (Brian,
  05/10). It still never changes the firmware image: it sets the U-Boot
  environment ADI documents for this, shows the exact commands and what
  each does, runs nothing until the operator agrees, and Undo restores the
  factory state. Commands, firmware versions and sources are in
  `docs/ham/pluto-identity.md`: `fw_setenv compatible ad9364` on v0.32+,
  `attr_name`/`attr_val` before, ADI firmware v0.26-v0.39 only; anything
  else (Tezuka, newer ADI, clones' own firmware) and `usb:`-only radios
  get manual steps and nothing is run. The engine is stopped before the
  first command and started again at the end whatever happened.
- **SSH through paramiko**, not the system `ssh`: OpenSSH takes a password
  only from a terminal, and the Windows build has none. In Debian
  (`python3-paramiko`, a Depends of the HAM `.deb`), bundled in the Windows
  build. Host keys are accepted for that one connection and never written
  (the Pluto regenerates them; many share 192.168.2.1). Password `analog`
  first, then asked once and never kept.
- **Tests**: a pretend Pluto whose IIO context reports what its U-Boot
  environment says and whose shell edits it and reboots
  (`tests/pluto_fakes.py`), plus a real paramiko server on loopback for the
  SSH client itself. Success, wrong-then-right password, the radio not
  coming back, unsupported firmware (nothing run), `usb:` only, undo, and
  the window's dialogs end to end. **Nothing has run against a real Pluto.**

**Later, in roughly this order:**

1. Audio checks: input and output devices open, the microphone level moves,
   the test tone plays; in the report and in Check radio.
2. A loopback transmit self-test through the Pluto's internal digital
   loopback (the AD9361's BIST/loopback, `loopback` attribute on the
   ad9361-phy): key into nothing, receive our own signal, check its level
   and sideband, with no RF leaving the radio.
3. Decoder checks: `jt9`, `ft8code`, codec2/FreeDV present and runnable;
   and the clock - FT8 fails silently with the system clock more than a
   second or two out (NTP status, or the decode DT spread).
4. Windows prerequisites: libiio 0.26 (not 1.0) and its location, ADI's
   PlutoSDR USB drivers, Smart App Control, the HL2's firewall rule.
5. Moving the Pluto findings and the chip check to `ohscore` so OpenHamShack QO-100 NB
   gets them too (the log and report are already shared; NB's Pluto is the
   same radio, and it needs the findings more than the fix).
