"""The controller report: what an operator pastes to the developers when the
AKP03E pad does not work, from Settings › Control pad's "Copy controller
report" or from the command line:

    openhamshack-nb --pad-report     (Windows: openhamshack-nb-console.exe --pad-report)

The command-line form needs no window and no radio, so it also proves a
frozen build can find hidapi and enumerate HID devices at all
(tools/build-windows.ps1 runs it on the build machine).

shack_pad.diagnose does the looking; this adds the app's own lines - its
name and version, and when the window is running, what its pad link says
(state, last errors, whether the pad may transmit). No secrets: no
callsign, locator, tokens or serial numbers; paths and ids only.

No Qt: the command-line form runs without a display.
"""
from __future__ import annotations

from . import diag, shacklibs


def text(app_name: str, package: str, extra: list[str] | None = None, survey: dict | None = None) -> str:
    """The report. `extra`: the pad link's lines; `survey`: a ready-made
    diagnose.survey() (tests), else one is taken now."""
    lines = [f"app: {app_name} {diag.app_version(package)}"] + list(extra or [])
    try:
        shacklibs.pad()
        from shack_pad import diagnose
    except Exception as e:  # noqa: BLE001 - the report must say this rather than fail
        return "\n".join(["OpenHamShack controller report", ""] + lines +
                         ["", f"shack_pad could not be loaded: {e}", ""])
    return diagnose.report(survey if survey is not None else diagnose.survey(), lines)
