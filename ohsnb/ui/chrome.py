"""QO-100 NB's entries in the shared window chrome (ohscore/ui/chrome.py):
its shortcut list, and the corrections it shows in the status strip."""
from __future__ import annotations

from PyQt6.QtCore import QT_TRANSLATE_NOOP

# The "?" sheet (ohscore/ui/chrome.py ShortcutOverlay). Keys are written as
# they are, never translated; what they do is, through the "Shortcuts"
# context (QT_TRANSLATE_NOOP marks a string for the catalog, the sheet
# translates it as it draws).
SHORTCUTS = [
    (QT_TRANSLATE_NOOP("Shortcuts", "Tuning"), [
        ("← / →", QT_TRANSLATE_NOOP("Shortcuts", "Tune down / up one step")),
        ("Shift + ← / →", QT_TRANSLATE_NOOP("Shortcuts", "Ten steps")),
        ("Ctrl + ← / →", QT_TRANSLATE_NOOP("Shortcuts", "1 Hz")),
        ("[ / ]", QT_TRANSLATE_NOOP("Shortcuts", "Smaller / larger step")),
        ("Wheel", QT_TRANSLATE_NOOP("Shortcuts", "Step (over a digit: that digit)")),
        ("F or Enter", QT_TRANSLATE_NOOP("Shortcuts", "Type a frequency")),
        ("Click", QT_TRANSLATE_NOOP("Shortcuts", "Tune to the click")),
        ("Drag passband", QT_TRANSLATE_NOOP("Shortcuts", "Tune by dragging")),
        ("Ctrl + wheel", QT_TRANSLATE_NOOP("Shortcuts", "Zoom a scope")),
        ("Z / Shift + Z", QT_TRANSLATE_NOOP("Shortcuts", "Zoom scope span in / out"))]),
    (QT_TRANSLATE_NOOP("Shortcuts", "Transmit"), [
        ("Space", QT_TRANSLATE_NOOP("Shortcuts", "PTT (hold, or toggle - Settings)")),
        ("Esc", QT_TRANSLATE_NOOP("Shortcuts", "Unkey, stop queue / CQ loop")),
        ("Enter", QT_TRANSLATE_NOOP("Shortcuts", "Send the typed line (text modes)")),
        ("F1 … F8", QT_TRANSLATE_NOOP("Shortcuts", "Send macro or voice memory n"))]),
    # Ctrl + E is the only key for Q65, JS8, PSK63, PSK125 and HSmodem
    # (Mac test FINDINGS 13), so it comes first and names some of them.
    (QT_TRANSLATE_NOOP("Shortcuts", "Modes & filter"), [
        ("Ctrl + E", QT_TRANSLATE_NOOP("Shortcuts", "Mode menu: type a name (Q65, JS8, HSmodem…)")),
        ("Ctrl + 1 … 4", QT_TRANSLATE_NOOP("Shortcuts", "USB, LSB, CW, AM")),
        ("Ctrl + 5 … 8", QT_TRANSLATE_NOOP("Shortcuts", "FT8, FT4, PSK31, RTTY")),
        ("Ctrl + 9 / 0", QT_TRANSLATE_NOOP("Shortcuts", "FreeDV, SSTV")),
        (", / .", QT_TRANSLATE_NOOP("Shortcuts", "Filter narrower / wider")),
        ("R", QT_TRANSLATE_NOOP("Shortcuts", "RIT on / off")),
        ("X", QT_TRANSLATE_NOOP("Shortcuts", "XIT on / off")),
        ("S", QT_TRANSLATE_NOOP("Shortcuts", "Split on / off")),
        ("N", QT_TRANSLATE_NOOP("Shortcuts", "Noise blanker")),
        ("Shift + N", QT_TRANSLATE_NOOP("Shortcuts", "Noise reduction")),
        ("M", QT_TRANSLATE_NOOP("Shortcuts", "Mute")),
        ("A", QT_TRANSLATE_NOOP("Shortcuts", "Auto-tune onto the SSB station on the dial")),
        ("Shift + A", QT_TRANSLATE_NOOP("Shortcuts", "Best audio for the station on the dial"))]),
    (QT_TRANSLATE_NOOP("Shortcuts", "Views"), [
        ("W", QT_TRANSLATE_NOOP("Shortcuts", "Next workspace: Digital, Voice, Watch")),
        ("Shift + W", QT_TRANSLATE_NOOP("Shortcuts", "Workspace follows the mode (Auto)")),
        ("L", QT_TRANSLATE_NOOP("Shortcuts", "Signal labels on the scopes on / off")),
        ("Alt + 1 … 9", QT_TRANSLATE_NOOP("Shortcuts", "Recall memory 1 … 9")),
        ("Ctrl + J", QT_TRANSLATE_NOOP("Shortcuts", "Operate")),
        ("Ctrl + L", QT_TRANSLATE_NOOP("Shortcuts", "Logbook")),
        ("Ctrl + B", QT_TRANSLATE_NOOP("Shortcuts", "Memories")),
        ("Ctrl + M", QT_TRANSLATE_NOOP("Shortcuts", "Multimedia beacon")),
        ("Ctrl + K", QT_TRANSLATE_NOOP("Shortcuts", "Band skimmer")),
        ("Ctrl + D", QT_TRANSLATE_NOOP("Shortcuts", "Second display")),
        ("Ctrl + ,", QT_TRANSLATE_NOOP("Shortcuts", "Settings")),
        ("Ctrl + Shift + R", QT_TRANSLATE_NOOP("Shortcuts", "Record receive IQ / stop")),
        ("Ctrl + Shift + P", QT_TRANSLATE_NOOP("Shortcuts", "Play an IQ recording / back to the radio")),
        ("Ctrl + T", QT_TRANSLATE_NOOP("Shortcuts", "Light / dark theme")),
        ("F11", QT_TRANSLATE_NOOP("Shortcuts", "Full screen")),
        ("?", QT_TRANSLATE_NOOP("Shortcuts", "This list")),
        ("Ctrl + Q", QT_TRANSLATE_NOOP("Shortcuts", "Quit"))]),
    # H was free in NB (HAM's B, V and T are HAM's own); "hold" is the word.
    (QT_TRANSLATE_NOOP("Shortcuts", "Beacon lock"), [
        ("H", QT_TRANSLATE_NOOP("Shortcuts", "Hold / back to Auto")),
        ("Right-click", QT_TRANSLATE_NOOP("Shortcuts", "Lock to this beacon, or auto-tune (scopes)")),
        ("Wheel on RX", QT_TRANSLATE_NOOP("Shortcuts", "rxCorr ±10 Hz (Shift 1), Manual"))]),
]


def status_items(st: dict) -> list[tuple[str, str]]:
    """The status strip's QO-100 items: the receive and transmit
    corrections beacon lock and TX lock maintain - the transmit one being
    the IC-9700's (rigTxCorr) when that is the transmitter, with its link.
    A receive correction nothing is tracking says so, in the accent colour
    the badge uses for Hold and Manual."""
    mode = st.get("beaconMode", "auto")
    held = {"hold": " (held)", "manual": " (manual)"}.get(mode, "")
    items = [(f"rxCorr {float(st.get('rxCorr') or 0):+.1f} Hz{held}", "accent" if held else "text2")]
    # The multimedia beacon, while it decodes: the one figure that says the
    # receive chain is healthy end to end.
    if st.get("mmbState") == "receiving":
        items.append((f"MM beacon {float(st.get('mmbMer') or 0):.0f} dB", "text2"))
    if st.get("txRadio", "sdr") == "sdr":
        items.append((f"txCorr {float(st.get('txCorr') or 0):+.1f} Hz ({float(st.get('txPpm') or 0):+.3f} ppm)",
                      "text2"))
        return items
    items.append((f"rigTxCorr {float(st.get('rigTxCorr') or 0):+.1f} Hz", "text2"))
    link = st.get("rigLink", "off")
    items.append((f"IC-9700 {'TX' if st.get('rigKeyed') else 'RX'}" if link == "ok" else f"IC-9700 {link}",
                  "err" if st.get("rigKeyed") else ("text2" if link == "ok" else "warn")))
    return items
