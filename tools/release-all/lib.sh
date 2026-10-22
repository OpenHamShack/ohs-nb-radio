# Shared by tools/release-all.sh and its stage drivers (sourced, not run).
#
# Hosts are never named here: the release tarball of this repository is
# public, and packaging/source-scrub.txt refuses internal names. They come
# from the configuration file (RA_CONF, default
# ~/.config/openhamshack/nb-release.conf on the machine that runs the
# release), which release-all.sh copies into each run's run.env.

# SSH that never asks: a release runs unattended, so a host that wants a
# password or a new host key fails the stage instead of hanging it.
# RA_SSH / RA_SCP name stand-ins for the tests.
ra_ssh() { ${RA_SSH:-ssh} -o BatchMode=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=10 "$@"; }
ra_scp() { ${RA_SCP:-scp} -q -o BatchMode=yes "$@"; }

# Each stage prints "== step <what>" before each step: when a stage fails,
# release-all.sh names the last such line as the step that failed, in the
# summary and in the one notification.
step() { echo "== step $*"; }
die() { echo "FAIL: $*" >&2; exit 1; }

# Every app this script knows: package, VERSION folder, release commit
# subject (tools/release.sh's marker), the website's product name, the
# app's name on a Mac, and its update feed.
app_pkg()    { case $1 in nb) echo openhamshack-nb ;; ham) echo openhamshack-radio ;; esac; }
app_pydir()  { case $1 in nb) echo ohsnb ;; ham) echo ohsradio ;; esac; }
app_marker() { case $1 in nb) echo "Release" ;; ham) echo "Release HAM" ;; esac; }
app_site()   { case $1 in nb) echo QO-100-NB ;; ham) echo Radio ;; esac; }
app_macname() { case $1 in nb) echo "OpenHamShack QO-100 NB" ;; ham) echo "OpenHamShack Radio" ;; esac; }
app_feed()   { case $1 in nb) echo https://openhamshack.com/desktop/nb/update.json ;;
                          ham) echo https://openhamshack.com/desktop/ham/update.json ;; esac; }

# A run's facts, written once by release-all.sh: APPS, VER_<app>,
# COMMIT_<app>, BASE, SUITE_TREE, PLATFORMS, DRY, RUN, and the
# configuration's hosts and folders.
load_run() {
    RUN_DIR=$1
    [[ -f $RUN_DIR/run.env ]] || die "no $RUN_DIR/run.env"
    # shellcheck disable=SC1091
    source "$RUN_DIR/run.env"
}
ver_of()    { local v="VER_$1"; echo "${!v}"; }
commit_of() { local v="COMMIT_$1"; echo "${!v}"; }
wants()     { [[ ,$PLATFORMS, == *",$1,"* ]]; }
