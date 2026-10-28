#!/bin/sh
# Vendor a shack-sdr wheel build made by ohs-libs' tools/build-wheels-safe.sh:
# copy its wheels into tools/vendor/ and pin them in tools/vendor/shack-sdr.lock.
#
#   tools/vendor-shack-sdr.sh [--why "what changed"] <folder>
#
# Why a script: the lock's hashes and its header (which ohs-libs commit,
# which folder, what changed, and every build before it) were edited by
# hand, and a wheel folder overwritten by another agent's build went
# unnoticed until the hashes stopped matching. Paired with
# build-wheels-safe.sh, which never reuses a folder, the folder named here
# is exactly what that build made.
#
# It refuses a folder whose BUILD-INFO does not say status=built, whose
# SHA256SUMS does not match its wheels, or that lacks a wheel for a
# platform the lock pins (a partial build would silently drop one). Then
# it deletes the old shack_sdr wheels from tools/vendor/, copies the new,
# rewrites each "shack-sdr==<v> --hash=sha256:..." line (by the platform
# tag in its comment; a platform the lock lacks, macOS's first, is added
# after the others), and rewrites the header: the sentence "Built by
# ohs-libs tools/... at ohs-libs main <commit> (<date>; ...; SHA256SUMS in
# ~/build/ohs-dist/<folder> match the lines below): <what changed>" names
# the new build, and the build it replaces moves down as the newest
# "<commit> before it (<folder>): ..." entry. "What changed" is --why, or
# else the ohs-libs commit's subject (from OHS_LIBS, default ~/ohs-libs).
# The same commit built again (a lost folder, a new platform) replaces the
# sentence's folder and date and keeps what it said changed, with no new
# "before it" entry.
#
# It changes files only; review `git diff` and commit the wheels and the
# lock together (REPO-LAYOUT 4: a bump is a commit of its own).
set -eu
cd "$(dirname "$0")/.."
WHY=
if [ "${1:-}" = --why ]; then WHY=${2:-}; shift 2; fi
[ $# -eq 1 ] || { echo "usage: $0 [--why \"what changed\"] <folder>" >&2; exit 2; }
DIR=${1%/}
[ -d "$DIR" ] || { echo "vendor-shack-sdr: no folder $DIR" >&2; exit 1; }
grep -qx 'status=built' "$DIR/BUILD-INFO" 2>/dev/null \
    || { echo "vendor-shack-sdr: $DIR/BUILD-INFO does not say status=built (build it with ohs-libs tools/build-wheels-safe.sh)" >&2; exit 1; }
(cd "$DIR" && sha256sum --quiet -c SHA256SUMS) || { echo "vendor-shack-sdr: $DIR's wheels do not match its SHA256SUMS" >&2; exit 1; }
LIBS=${OHS_LIBS:-$HOME/ohs-libs}
exec python3 - "$DIR" "$WHY" "$LIBS" <<'PY'
import re, shutil, subprocess, sys, textwrap
from pathlib import Path

folder, why, libs = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
lock_path = Path("tools/vendor/shack-sdr.lock")
info = dict(l.split("=", 1) for l in (folder / "BUILD-INFO").read_text().split() if "=" in l)
commit = info["commit"]
y, m, d = info["built"][:10].split("-")
date = f"{d}/{m}/{y}"

def die(msg):
    print("vendor-shack-sdr: " + msg, file=sys.stderr)
    sys.exit(1)

wheels = {}
for w in sorted(folder.glob("shack_sdr-*.whl")):
    mt = re.fullmatch(r"shack_sdr-([^-]+)-cp\d+-abi3-(.+)\.whl", w.name)
    if not mt:
        die(f"cannot read the platform from {w.name}")
    wheels[mt.group(2)] = (mt.group(1), w)
versions = {v for v, _ in wheels.values()}
if len(versions) != 1:
    die(f"the folder holds more than one version: {sorted(versions)}")
version = versions.pop()
sums = dict(reversed(l.split()) for l in (folder / "SHA256SUMS").read_text().splitlines() if l.strip())

lines = lock_path.read_text().splitlines()
pin = re.compile(r"^shack-sdr==\S+ --hash=sha256:[0-9a-f]{64}  # (\S+)$")
pinned = [pin.match(l).group(1) for l in lines if pin.match(l)]
missing = [t for t in pinned if t not in wheels]
if missing:
    die(f"{folder} has no wheel for {', '.join(missing)}, which the lock pins")
out, last_pin = [], None
for l in lines:
    mt = pin.match(l)
    if mt:
        tag = mt.group(1)
        out.append(f"shack-sdr=={version} --hash=sha256:{sums[wheels[tag][1].name]}  # {tag}")
        last_pin = len(out)
    else:
        out.append(l)
for tag in wheels:
    if tag not in pinned:
        out.insert(last_pin, f"shack-sdr=={version} --hash=sha256:{sums[wheels[tag][1].name]}  # {tag}")
        last_pin += 1

# The header: from the line holding "Built by ohs-libs" to the first
# "<commit> before it" entry is one sentence, reflowed as one.
start = next((i for i, l in enumerate(out) if "Built by ohs-libs tools/" in l), None)
if start is None:
    die("the lock has no 'Built by ohs-libs tools/...' sentence to rewrite")
end = next(i for i in range(start + 1, len(out)) if re.match(r"^# [0-9a-f]{7,40} before it", out[i]))
text = " ".join(l[2:] if l.startswith("# ") else l.lstrip("#") for l in out[start:end])
lead, built = text.split("Built by ", 1)
mt = re.fullmatch(r"ohs-libs tools/\S+ at ohs-libs main ([0-9a-f]{7,40}) \(([^)]*)\): (.*)", built, re.S)
if not mt:
    die("cannot read the lock's 'Built by' sentence")
old_commit, old_paren, old_why = mt.groups()
old_folder = (re.search(r"shack-sdr-[A-Za-z0-9_-]*[A-Za-z0-9]", old_paren) or [None])[0]
same = commit.startswith(old_commit) or old_commit.startswith(commit[:7])
if not why and same:
    why = old_why          # the same commit built again: what it changed has not
elif not why:
    try:
        why = subprocess.run(["git", "-C", libs, "log", "-1", "--format=%s", commit], check=True,
                             capture_output=True, text=True).stdout.strip()
    except (subprocess.CalledProcessError, OSError):
        die(f"commit {commit[:7]} is not in {libs}: say what changed with --why")
why = why.rstrip(".") + "."
short = commit[:7]
new = (f"{lead}Built by ohs-libs tools/build-wheels-safe.sh at ohs-libs main {short} ({date}; shack-sdr "
       f"{version}; SHA256SUMS in ~/build/ohs-dist/{folder.name} match the lines below): {why}")
wrap = lambda t: textwrap.wrap(t, 74, break_on_hyphens=False, break_long_words=False)
header = ["# " + l for l in wrap(new)]
if not same:
    header += ["# " + l for l in wrap(f"{old_commit[:7]} before it ({old_folder or 'folder not named'}): {old_why}")]
out[start:end] = header
lock_path.write_text("\n".join(out) + "\n")

for w in Path("tools/vendor").glob("shack_sdr-*.whl"):
    w.unlink()
for _, w in wheels.values():
    shutil.copy2(w, Path("tools/vendor") / w.name)
print(f"vendored shack-sdr {version} from ohs-libs {short} ({folder.name}): {', '.join(wheels)}")
print("review `git diff tools/vendor`, then commit the wheels and the lock together")
PY
