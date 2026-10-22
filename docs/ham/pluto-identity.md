# The Pluto's chip identity (AD9363 / AD9364)

Research notes behind `ohsradio/plutofix.py`, checked 5 October 2026.

## The problem

Every Pluto-family radio is an AD936x behind ADI's IIO driver. ADI ships the
ADALM-Pluto telling the driver it is an **AD9363**, and the driver then keeps
both LOs inside **325 MHz–3.8 GHz** (`docs/ham/DESIGN-HAM.md` §4.3; the
limits are in the driver, `drivers/iio/adc/ad9361_regs.h`). Told it is an
**AD9364**, the same radio receives from 70 MHz and transmits from
46.875 MHz, to 6 GHz.

OpenHamShack QO-100 NB never notices: 739 MHz and 2.4 GHz are inside either range.
OpenHamShack Radio does: **2 m, 4 m and 6 cm are outside the AD9363 range**. On
5 October a tester's stock Pluto worked in NB and did nothing useful in
HAM, which is this.

The firmware reports which it runs as in the IIO context attribute
`ad9361-phy,model` (`ad9363`, `ad9364`, or `ad9361` in 2R2T mode); the
release notes for v0.32 are where ADI started telling users which. Older
firmware may not report it at all.

## The commands

From ADI, *Customizing the PlutoSDR*, section "Updating to the AD9364"
(https://wiki.analog.com/university/tools/pluto/users/customizing). Log in
over SSH as `root`, password `analog` (the factory default).

| Firmware | Set AD9364 | Back to the default (AD9363) |
| --- | --- | --- |
| v0.32 and later | `fw_setenv compatible ad9364`, `reboot` | `fw_setenv compatible`, `reboot` |
| before v0.32 | `fw_setenv attr_name compatible`, `fw_setenv attr_val ad9364`, `reboot` | `fw_setenv attr_name`, `fw_setenv attr_val`, `reboot` |

ADI's page documents only the setting. The undo is ours: the page shows the
default state as the variables being *undefined* (`fw_printenv attr_name`
answers `## Error: "attr_name" not defined`), and `fw_setenv <name>` with no
value deletes a variable (U-Boot's environment tools). So Undo deletes them
rather than writing `ad9363`, which restores exactly the factory state. On
v0.32+ it clears `attr_name`/`attr_val` too, in case the radio was set the
old way before a firmware update (the v0.33 notes mention a fix to
`attr_val`/`attr_name` handling, so both mechanisms are live on new
firmware).

Before changing anything the fix runs
`fw_printenv attr_name attr_val compatible` and logs the answer, so the
diagnostic log shows what the environment held.

## Which firmware the program will change

From ADI's release list (https://github.com/analogdevicesinc/plutosdr-fw/releases):
v0.30 (01/2019), v0.31 and v0.32 (07/2019), … v0.38 (11/2022), v0.39
(10/2023, the newest).

- **v0.32–v0.39**: the `compatible` method.
- **v0.26–v0.31**: the `attr_name`/`attr_val` method. (The lower bound is a
  judgement, not ADI's: ADI documents no lower limit, and firmware older
  than v0.26 should be updated before anything is changed.)
- **Anything else** – a version newer than v0.39, or not numbered like
  ADI's – gets the manual steps and nothing is run. That includes
  **Tezuka** (F5OEO, https://github.com/F5OEO/tezuka_fw), whose
  `fw_version` reads `tezuka-v0.3.x`. Tezuka extends tuning to
  47.5 MHz–6 GHz by itself and is configured through its own file "based
  on standard ADI customization parameters"; what `fw_setenv` does there is
  not documented, so the program does not guess. In practice a Tezuka radio
  should not report `ad9363` at all.
- **Pluto+, LibreSDR and other clones** are handled by their firmware
  version like any other: ADI-numbered firmware gets ADI's method; anything
  else gets the manual steps.

## How it reaches the radio

Over the Pluto's own network link (its USB Ethernet, `ip:192.168.2.1` by
default, or the configured `ip:` address). A radio reached only as `usb:`
has no address to SSH to; the program says so and shows the manual steps.

**SSH client: paramiko.** OpenSSH reads a password only from a terminal:
driving it from a GUI needs `sshpass` (Linux only) or `SSH_ASKPASS` tricks
that differ per platform, and the Windows build has no console. Paramiko is
pure Python over `cryptography`, packaged in Debian (`python3-paramiko`, a
Depends of the HAM `.deb`) and on PyPI with Windows wheels (bundled by
`packaging/windows/openhamshack-radio.spec`).

**Host keys** are accepted for that one connection and never written: the
Pluto makes new keys whenever its firmware is updated and many radios share
192.168.2.1, so a stored key would only ever be wrong. Nothing is read from
or written to `~/.ssh/known_hosts`.

**Password**: `analog` first; if refused, the operator is asked once, and the
answer is used for that connection only - not saved, not logged.

## After the reboot

The program waits for the radio to drop off and come back (two minutes at
most), reads `ad9361-phy,model` again and reports the result. A radio that
never drops off is reported as not restarted; one that comes back with the
old identity is reported as not honouring the setting, with the manual
steps.

## Not verified

None of this has run against a real Pluto yet: it is tested against a
pretend radio (`tests/pluto_fakes.py`) and a real paramiko SSH server on
loopback. The first run on a stock ADALM-Pluto (ADI firmware) is the
test that matters.
