# PyInstaller spec for QO-100 NB's and Radio's AppImages, through the
# shared kit (ohs-libs packaging/appimage, `[pyinstaller] spec`): the kit's
# own spec is for web-UI apps and leaves Qt out.
#
# Everything comes from the kit's stage ($SHACK_STAGE): src/ holds ohscore,
# the app's package and the pinned shared libraries (tools/build-appimage.sh
# put them there), app.json says which app, launcher.py is the entry.
# As the Windows and macOS specs do: every data file the packages carry
# (cty.dat, the noise reduction's tables, the catalogs, the pad files, the
# band-plan dataset...), every module named (several are imported lazily,
# by name, when the operator picks a device or a mode), no Qt PDF
# (packaging/windows/bundle_prune.py says why) and nothing from tkinter.
import json
import os
import sys
from pathlib import Path

stage = Path(os.environ["SHACK_STAGE"]).resolve()
src = stage / "src"
sys.path.insert(0, str(src))
app = json.loads((stage / "app.json").read_text())

datas, hidden = [], []
for pkg in sorted(p.name for p in src.iterdir() if p.is_dir()):
    for p in sorted((src / pkg).rglob("*")):
        if p.is_file() and p.suffix not in (".py", ".pyc") and "__pycache__" not in p.parts \
                and not p.name.endswith(("_en_XA.ts", "_en_XA.qm")):
            datas.append((str(p), str(p.parent.relative_to(src))))
    # Named from the files, not by importing them as collect_submodules
    # does: in the build container a window module cannot import (no
    # libGL), and a module that fails to import is silently left out -
    # which left ohsnb.analyse out of the first build.
    for p in sorted((src / pkg).rglob("*.py")):
        parts = list(p.relative_to(src).with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        if "tests" not in parts and parts[-1] not in ("screenshots", "uibench"):
            hidden.append(".".join(parts))
hidden += ["iio", "pyaudio", "serial", "serial.tools.list_ports",
           "cryptography.hazmat.primitives.asymmetric.ed25519"]

a = Analysis(  # noqa: F821
    [str(stage / "launcher.py")],
    pathex=[str(src)],
    datas=datas,
    hiddenimports=hidden,
    excludes=["tkinter", "SoapySDR", "PIL", "scipy", "matplotlib", "IPython", "webview", "gi"],
    noarchive=False,
)
# No Qt PDF: 15 MB of a module nothing imports (bundle_prune.py).
a.binaries = [b for b in a.binaries if "Qt6Pdf" not in b[0] and "qpdf" not in b[0].lower()]
a.datas = [d for d in a.datas if "Qt6Pdf" not in d[0] and "qpdf" not in d[0].lower()]
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name=app["executable"], console=False,  # noqa: F821
          upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name=app["executable"], upx=False)  # noqa: F821
