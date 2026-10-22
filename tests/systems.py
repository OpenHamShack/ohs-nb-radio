"""Run a test as if on another system, as far as ohscore.host can tell.

host.WINDOWS and host.MACOS are what every Linux/Windows/macOS difference
turns on, and Linux is the case where neither is true. Before macOS
arrived (07/10/2026) a test patched WINDOWS to False to mean "Linux"; run
on a Mac, that left MACOS true and the test checked macOS's answer against
Linux's. Patching both, by name, keeps each test meaning the system it
says, wherever the suite runs.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)

import contextlib
from unittest import mock

from ohscore import host

SYSTEMS = ("linux", "windows", "macos")


@contextlib.contextmanager
def system(name: str):
    """ohscore.host behaving as on `name` ("linux", "windows" or "macos")
    for the length of the with-block."""
    if name not in SYSTEMS:
        raise ValueError(name)
    with mock.patch.object(host, "WINDOWS", name == "windows"), mock.patch.object(host, "MACOS", name == "macos"):
        yield
