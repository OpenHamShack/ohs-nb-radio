"""ohscore never imports an app (ohsnb or ohsradio).

The rule is what lets one repository hold a shared core and two apps
without the core quietly growing a dependency on whichever app a change was
made for (docs/ham/DESIGN-HAM.md section 2.1). It is checked by doing it:
every ohscore module is imported in a fresh interpreter in which importing
ohsnb or ohsradio raises, so an import buried in a function body that runs at
import time, a re-export, or a dotted string handed to importlib all fail
here exactly as they would on a machine with only the core installed. A
grep for "ohsnb" would pass a `__import__("lb" + "nb")` and fail on a
comment; this does neither.
"""
import scratch_home  # noqa: F401  first: no test may touch the real config (see scratch_home.py)
import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Runs in the child. The blocker is a meta-path finder placed first, so it
# sees every import of an app package before the normal path machinery
# could find the one sitting next to ohscore in this repository.
_CHILD = r"""
import importlib, json, pkgutil, sys

class Blocker:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("ohsnb", "ohsradio"):
            raise ModuleNotFoundError(f"ohscore imported the app package {name!r}")
        return None

sys.meta_path.insert(0, Blocker())
import ohscore

names = ["ohscore"] + [m.name for m in pkgutil.walk_packages(ohscore.__path__, "ohscore.")]
failures = {}
for name in names:
    try:
        importlib.import_module(name)
    except Exception as e:
        failures[name] = f"{type(e).__name__}: {e}"
leaked = sorted(m for m in sys.modules if m.split(".")[0] in ("ohsnb", "ohsradio"))
print(json.dumps({"modules": names, "failures": failures, "leaked": leaked}))
"""


class CoreImportsNoApp(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(REPO_ROOT)
        # Qt modules in ohscore.ui must import without a display.
        env.setdefault("QT_QPA_PLATFORM", "offscreen")
        res = subprocess.run([sys.executable, "-c", _CHILD], cwd=str(REPO_ROOT), env=env,
                             capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            raise AssertionError(f"import probe crashed:\n{res.stderr}")
        cls.result = json.loads(res.stdout.strip().splitlines()[-1])

    def test_every_core_module_imports_with_the_apps_unimportable(self):
        self.assertEqual(self.result["failures"], {})

    def test_no_app_module_was_loaded(self):
        self.assertEqual(self.result["leaked"], [])

    def test_the_probe_saw_the_core(self):
        # Guards the test itself: a walk that found nothing would pass the
        # two checks above vacuously for ever.
        self.assertIn("ohscore", self.result["modules"])


if __name__ == "__main__":
    unittest.main()
