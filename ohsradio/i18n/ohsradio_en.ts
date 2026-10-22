<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE TS>
<TS version="2.1" language="en" sourcelanguage="en">
<context>
    <name>About</name>
    <message>
        <location filename="../ui/welcome.py" line="77" />
        <source>An all-amateur-bands transceiver: SSB, CW, AM, FM with CTCSS and repeaters, FT8/FT4, PSK, RTTY, FreeDV and SSTV, holding every transmission to the licence of the country it is in.</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>BandBar</name>
    <message>
        <location filename="../ui/widgets.py" line="170" />
        <source>This band's FT8 dial</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/widgets.py" line="170" />
        <source>This band's FT4 dial</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/widgets.py" line="172" />
        <source>This band's FT8 dial, {freq}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/widgets.py" line="173" />
        <source>This band's FT4 dial, {freq}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/widgets.py" line="186" />
        <source>VFO B (the split transmit dial) = A</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/widgets.py" line="186" />
        <source>Swap VFO A and B</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>CheckRadioDialog</name>
    <message>
        <location filename="../ui/diagnostics.py" line="180" />
        <source>Check radio</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="184" />
        <source>Checking {uri}…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="190" />
        <source>Apply the AD9364 setting…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="192" />
        <source>Undo (back to AD9363)…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="194" />
        <source>Save diagnostics…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="195" />
        <source>Close</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="203" />
        <source>The check itself failed: {error}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="206" />
        <source>Radio at {uri}:</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>ChipModeDialog</name>
    <message>
        <location filename="../ui/diagnostics.py" line="156" />
        <source>This Pluto cannot reach {band}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="157" />
        <source>This Pluto is running as an AD9363, which tunes 325 MHz–3.8 GHz. {band} needs the AD9364 setting.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="160" />
        <source>The radio itself covers 70 MHz–6 GHz; the AD9363 setting is only what ADI's firmware tells the driver to allow. OpenHamShack Radio can change it for you over the Pluto's network link: it shows the commands first and asks before running them, and it can undo the change the same way.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="165" />
        <source>Apply the AD9364 setting…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="166" />
        <source>Save diagnostics…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="167" />
        <source>Close</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>DeviceErrorDialog</name>
    <message>
        <location filename="../ui/diagnostics.py" line="141" />
        <source>The radio did not start</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="143" />
        <source>Save diagnostics… collects what is needed to work out why. It is saved where you choose and nothing is sent anywhere.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="145" />
        <source>Save diagnostics…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="146" />
        <source>Check radio…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="147" />
        <source>Close</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>FixFlow</name>
    <message>
        <location filename="../ui/diagnostics.py" line="304" />
        <source>The radio could not be checked: {error}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="313" />
        <source>Change it by hand</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="323" />
        <source>OpenHamShack Radio will log in to the Pluto at {host} (SSH, as root) and run the commands below to set it to AD9363 (ADI's default). {reason} They change two settings the radio reads when it starts, not its firmware. The radio then restarts: receiving stops for about half a minute and OpenHamShack Radio reconnects when it is back.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="329" />
        <source>OpenHamShack Radio will log in to the Pluto at {host} (SSH, as root) and run the commands below to set it to AD9364. {reason} They change two settings the radio reads when it starts, not its firmware, and can be undone the same way. The radio then restarts: receiving stops for about half a minute and OpenHamShack Radio reconnects when it is back.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="335" />
        <source>Set the Pluto to {chip}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="337" />
        <source>Run these commands</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="338" />
        <source>Cancel</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="349" />
        <source>Changing the Pluto</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="350" />
        <source>Working…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="351" />
        <source>Hide</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="388" />
        <source>The change failed: {error}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="397" />
        <source>{message}

Restarting the radio: {error}</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="405" />
        <source>Done</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="406" />
        <source>Not changed</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="407" />
        <source>Check the radio</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>FmPanel</name>
    <message>
        <location filename="../ui/fm.py" line="179" />
        <source>Repeater</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="182" />
        <source>Auto</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="182" />
        <source>Simplex</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="192" />
        <source>Offset for − and +</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="199" />
        <source>The repeater offset − and + use, in MHz (e.g. 0.6, 1.6, 5, 6). It is set to the band's usual split in your country's plan when you arrive in a band; Auto ignores it.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="203" />
        <source>MHz</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="211" />
        <source>Reverse</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="213" />
        <source>1750 Hz</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="214" />
        <source>Toneburst: 1750 Hz for the time set in Settings. Still accepted by many UK repeaters, but being withdrawn in favour of CTCSS (RSGB).</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="224" />
        <source>CTCSS</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="228" />
        <source>Send</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="230" />
        <source>Tone squelch</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="237" />
        <source>Send the tone heard</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="243" />
        <source>Receive &amp; audio</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="245" />
        <source>Squelch</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="246" />
        <source>open</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="251" />
        <source>Mic gain</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="254" />
        <source>Channel and deviation</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="265" />
        <source>Voice keyer</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="275" />
        <source>Transmit is locked until the licence box is ticked (Settings › Station)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="287" />
        <source>{text} is not an offset in MHz (e.g. 1.6)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/fm.py" line="305" />
        <source>No CTCSS tone heard on this channel yet</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>MainWindow</name>
    <message>
        <location filename="../ui/mainwindow.py" line="105" />
        <source>OpenHamShack Radio</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="136" />
        <source>Check radio…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="144" />
        <source>Licence</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="145" />
        <source>PTT sequence</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="263" />
        <source>No {mode} dial is listed for this band</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="268" />
        <source>VFO B = A</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>PasswordDialog</name>
    <message>
        <location filename="../ui/diagnostics.py" line="245" />
        <source>Pluto password</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="247" />
        <source>The radio at {host} did not accept ADI's default password (analog). Type the root password you set on it. It is used for this one connection and not saved.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="253" />
        <source>Connect</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="254" />
        <source>Cancel</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>ReportJob</name>
    <message>
        <location filename="../ui/diagnostics.py" line="112" />
        <source>Collecting diagnostics (finding radios takes a few seconds)…</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/diagnostics.py" line="124" />
        <source>Diagnostics could not be collected: {error}</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>SettingsDialog</name>
    <message>
        <location filename="../ui/settings.py" line="62" />
        <source>real time</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="78" />
        <source>CW skimmer</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="94" />
        <source>Hermes-Lite 2</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="95" />
        <source>Empty: found by broadcast when the radio starts. Find lists what answers now; pick one to fix its address. A radio on another subnet: type its address, and Find asks it directly.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="99" />
        <source>Find</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="113" />
        <source>Calibration</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="135" />
        <source>No Hermes-Lite 2 answered the broadcast on UDP port 1024 or {address}. Check it is powered and on this network (a radio with no DHCP server falls back to 169.254.19.221), and that no firewall drops UDP 1024 and 1025. Leaving the address empty still finds it by broadcast when the radio starts.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="140" />
        <source>No Hermes-Lite 2 answered the broadcast on UDP port 1024. Check it is powered and on this network (a radio with no DHCP server falls back to 169.254.19.221), and that no firewall drops UDP 1024 and 1025. Leaving the address empty still finds it by broadcast when the radio starts.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="162" />
        <source>Licence &amp; plan</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="162" />
        <source>What the transmit guard enforces. The licence is law and is always enforced; the band plan is a code of practice.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="166" />
        <source>Band plan</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="168" />
        <source>Warn: a transmission outside what its segment is for goes ahead with a warning. Enforce: it is refused. Beacon and satellite sub-bands are refused whatever this says.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="175" />
        <source>Bands &amp; power</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="175" />
        <source>Per band, what turns drive into watts at the antenna. An estimate over your class's limit there is a warning, not a refusal; where the radio measures its own output and no PA gain is entered, the measurement is held to the limit.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="183" />
        <source>Band</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="183" />
        <source>Device W</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="183" />
        <source>PA gain dB</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="183" />
        <source>Feeder loss dB</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="184" />
        <source>Antenna dBi</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="184" />
        <source>Ceiling %</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="184" />
        <source>At full drive</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="216" />
        <source>Device W empty: the device's own figure (a Pluto about 4.5 mW, the Hermes-Lite 2 about 5 W). A Pluto has no output filter: check its output into a dummy load on a spectrum analyser before it drives any PA, and never connect it straight to an antenna. Whether a PA's own filter is then enough is what that check shows.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="256" />
        <source>Bands</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="257" />
        <source>Direct: the radio tunes the band itself. Through a converter, the band is on the band bar whenever the radio reaches the converter's IF for it (6 m included), and transmits only through an RX/TX or TX only one with its most drive given. A TX only one is transmitted through and the band received directly.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="271" />
        <source>Direct</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="282" />
        <source>PTT sequencer</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="282" />
        <source>The line that keys a PA, a preamp's bypass relay or a transverter: on before RF, off after it.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/settings.py" line="288" />
        <source>Opening a serial port raises RTS and DTR for an instant before OpenHamShack Radio can clear them (Linux does this, not the program); a relay does not follow it and no RF is ever sent then. If your PA keys on the slightest glitch, drive it through an inverter with a pull-down. When the program stops for any reason the port closes and both lines drop.</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>Shortcuts</name>
    <message>
        <location filename="../ui/mainwindow.py" line="28" />
        <source>Tuning &amp; bands</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="29" />
        <source>Tune down / up one step</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="30" />
        <source>Ten steps</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="31" />
        <source>1 Hz</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="32" />
        <source>Smaller / larger step</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="33" />
        <source>Step (over a digit: that digit)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="34" />
        <source>Type a frequency</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="35" />
        <source>Tune to the click</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="36" />
        <source>Zoom a scope</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="37" />
        <source>Next / previous band</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="38" />
        <source>Next register of this band</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="39" />
        <source>Transmit</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="40" />
        <source>PTT (hold, or toggle - Settings)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="41" />
        <source>Unkey, stop queue / CQ loop</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="42" />
        <source>1750 Hz toneburst (FM)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="43" />
        <source>Send macro or voice memory n</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="46" />
        <source>Modes &amp; filter</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="47" />
        <source>Mode menu: type a name (JS8, PSK63, SSTV…)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="48" />
        <source>USB, LSB, CW, AM, FM</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="49" />
        <source>FT8, FT4, PSK31, RTTY, FreeDV</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="50" />
        <source>Filter narrower / wider</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="51" />
        <source>RIT / XIT / split</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="52" />
        <source>Noise blanker / mute</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="53" />
        <source>Noise reduction</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="54" />
        <source>Auto-tune onto the SSB station on the dial</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="55" />
        <source>Best audio for the station on the dial</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="56" />
        <source>Auto-tune there (scopes, USB and LSB)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="57" />
        <source>Views</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="58" />
        <source>Next workspace: Digital, Voice, Watch</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="59" />
        <source>Workspace follows the mode (Auto)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="60" />
        <source>Signal labels on the scopes on / off</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="61" />
        <source>Recall memory 1 … 9</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="62" />
        <source>Operate</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="63" />
        <source>Logbook</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="64" />
        <source>Memories</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="65" />
        <source>CW Activity</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="66" />
        <source>Second display</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="67" />
        <source>Settings</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="68" />
        <source>Record receive IQ / stop</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="69" />
        <source>Play an IQ recording / back to the radio</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="70" />
        <source>Light / dark theme</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="71" />
        <source>Full screen</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="72" />
        <source>This list</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/mainwindow.py" line="73" />
        <source>Quit</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>TextDialog</name>
    <message>
        <location filename="../ui/diagnostics.py" line="239" />
        <source>Close</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>ToneHeard</name>
    <message>
        <location filename="../ui/fm.py" line="125" />
        <source>Heard</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>ToneWheel</name>
    <message>
        <location filename="../ui/fm.py" line="95" />
        <source>{tone} Hz</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>TransmitCard</name>
    <message>
        <location filename="../ui/rail.py" line="29" />
        <source>Transmit</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="31" />
        <source>Drive</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="37" />
        <source>Transmit drive. The amber mark is this band's ceiling (Settings › Bands &amp; power). An estimated power over your licence's limit warns below; where the radio measures its output, a measured excess unkeys.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="50" />
        <source>ALC / peak</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="53" />
        <source>Forward</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="54" />
        <source>SWR</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="64" />
        <source>PA temperature</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="69" />
        <source>Tune</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="70" />
        <source>A steady carrier for an ATU or a PA, at the tune drive (Settings) times Drive - 25 % of 40 % is 10 %. The licence guard applies as to any transmission.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="73" />
        <source>SWR tripped: acknowledge</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="91" />
        <source>Transmit is locked until the licence box is ticked (Settings › Station)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="127" />
        <source>Power at the antenna unknown</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="128" />
        <source>≈ {power} PEP at the antenna (estimate)</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="130" />
        <source>{power} at full drive</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/rail.py" line="132" />
        <source>licence {limit:g} W {kind}</source>
        <translation type="unfinished" />
    </message>
</context><context>
    <name>Welcome</name>
    <message>
        <location filename="../ui/welcome.py" line="16" />
        <source>Your licence class - none is chosen for you: until you pick one, OpenHamShack Radio receives but will not transmit.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="20" />
        <source>No licence for {country} is written into OpenHamShack yet, so there is no class to pick here. OpenHamShack Radio will receive; to transmit, choose a licence or enter your own in Settings › Licence &amp; plan.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="41" />
        <source>An all-band amateur transceiver</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="42" />
        <source>&lt;ul style='margin-left:-18px; line-height:150%'&gt;&lt;li&gt;OpenHamShack Radio holds every transmission inside &lt;b&gt;what your licence class allows&lt;/b&gt;. Power is advisory until measured: it warns when the power chain you enter in Settings estimates more than your class's limit, and unkeys when a radio that measures its output goes over it.&lt;/li&gt;&lt;li&gt;It warns when you leave what the &lt;b&gt;band plan&lt;/b&gt; of your country (or IARU region) intends, and never transmits on the beacon or satellite sub-bands.&lt;/li&gt;&lt;li&gt;A Pluto has &lt;b&gt;no output filter&lt;/b&gt;: check its output into a dummy load on a spectrum analyser before it drives any PA, and never connect it straight to an antenna.&lt;/li&gt;&lt;li&gt;Space or the TX button keys; &lt;b&gt;Esc always stops&lt;/b&gt;. A time-out and a watchdog stop it too.&lt;/li&gt;&lt;/ul&gt;</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="54" />
        <source>I understand, and I hold an amateur licence of the class I have chosen above.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="55" />
        <source>Start with the simulator to learn the controls on busy simulated bands - no radio needed. You can switch in Settings at any time.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="59" />
        <source>Simulator</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="60" />
        <source>Simulated bands, 160 m to 6 cm: SSB, CW, FT8, FM repeaters.</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="61" />
        <source>ADALM-Pluto family</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="62" />
        <source>2 m to 6 cm (Pluto, Pluto+, LibreSDR, nano).</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="63" />
        <source>Hermes-Lite 2</source>
        <translation type="unfinished" />
    </message>
    <message>
        <location filename="../ui/welcome.py" line="64" />
        <source>160 m to 10 m over Ethernet.</source>
        <translation type="unfinished" />
    </message>
</context></TS>
