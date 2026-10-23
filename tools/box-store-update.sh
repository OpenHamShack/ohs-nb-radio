#!/bin/bash
# Update a signed store module on the box from a package already built and
# signed elsewhere, after first making a signed rollback of what is
# installed - Dock360 refuses to "update" to an older version, so the
# installed tree is relabelled <new>.rollback and signed where the modules
# key lives before the new package ever touches the box.
#
# Usage:
#   tools/box-store-update.sh [--force-rollback] <module> <new-version> <host:path-of-.d360mod> <sha256>
#   tools/box-store-update.sh --check <module> <new-version> <host:path-of-.d360mod> <sha256>
#
# <module> is the module id (store/<app>/module.yaml "id:", e.g.
# shack-radio or shack-qo100nb) - not the app's folder name, and used as
# both the catalogue path and the podman image tag on the box.
# <host:path> names wherever the new, already-built .d360mod sits (usually
# the signing host, but any host this account can scp from). <sha256> is
# checked against the fetched file before anything on the box changes.
#
# Host names, the dock360 source checkout used to sign the rollback, its
# venv and the modules key's path are read from
# ~/.config/openhamshack/box-update.conf (BOX_HOST, SIGN_HOST, DOCK360_SRC,
# DOCK360_VENV, MODULES_KEY; shell syntax, read with `source` - see
# ~/.config/openhamshack/packet-release.conf for the house style) rather
# than hard-coded here, because this repository's source is public.
# DOCK360_SRC, DOCK360_VENV and MODULES_KEY are paths on SIGN_HOST: keep
# any leading ~ single-quoted in the conf file so this script does not
# expand it against the wrong (local) home before the remote shell sees it.
#
# --check validates the arguments and the config file only - no ssh, no
# scp, nothing on either host touched - so a test can run it with no
# network. --force-rollback replaces an existing <new>.rollback package
# instead of refusing (the default): a second attempt at the same version
# after a failed run part-way through is the normal reason to pass it.
#
# Safety kept from the working draft this replaces
# (tools/.box-radio-update.draft.sh, hard-coded to shack-radio and ohs-box/
# ohs-dev, used by hand before this existed): refuses outright if the
# installed version cannot be read; a config backup is taken before
# install; an existing rollback package is never overwritten without
# --force-rollback; the sha256 of the fetched new package is checked before
# upload.
set -euo pipefail

usage() {
    echo "usage: $0 [--check] [--force-rollback] <module> <new-version> <host:path-of-.d360mod> <sha256>" >&2
    exit 2
}

CHECK=0
FORCE_ROLLBACK=0
while [ $# -gt 0 ]; do
    case "$1" in
        --check) CHECK=1; shift ;;
        --force-rollback) FORCE_ROLLBACK=1; shift ;;
        -h|--help) usage ;;
        --) shift; break ;;
        -*) usage ;;
        *) break ;;
    esac
done
[ $# -eq 4 ] || usage
MODULE=$1 NEW=$2 FROM=$3 SHA=$4

# Validate before touching anything: a typo in the module id or version
# must not reach a sed/grep built from it on the box.
[[ $MODULE =~ ^[a-z0-9][a-z0-9-]*$ ]] || { echo "bad module id: $MODULE" >&2; exit 2; }
[[ $NEW =~ ^[A-Za-z0-9][A-Za-z0-9.+_-]*$ ]] || { echo "bad version: $NEW" >&2; exit 2; }
case "$FROM" in
    *:*) ;;
    *) echo "expected host:path, got: $FROM" >&2; exit 2 ;;
esac
FROM_HOST=${FROM%%:*}
FROM_PATH=${FROM#*:}
[ -n "$FROM_HOST" ] && [ -n "$FROM_PATH" ] || { echo "expected host:path, got: $FROM" >&2; exit 2; }
[[ $SHA =~ ^[0-9a-f]{64}$ ]] || { echo "sha256 must be 64 lower-case hex characters, got: $SHA" >&2; exit 2; }

CONF=${BOX_UPDATE_CONF:-$HOME/.config/openhamshack/box-update.conf}
[ -r "$CONF" ] || { echo "no config at $CONF (see this script's own header)" >&2; exit 2; }
# shellcheck disable=SC1090
source "$CONF"
for v in BOX_HOST SIGN_HOST DOCK360_SRC DOCK360_VENV MODULES_KEY; do
    [ -n "${!v:-}" ] || { echo "$CONF: $v is not set" >&2; exit 2; }
done

if [ "$CHECK" -eq 1 ]; then
    echo "ok: module=$MODULE new=$NEW from=$FROM_HOST:$FROM_PATH sha256=$SHA"
    echo "ok: config box=$BOX_HOST sign=$SIGN_HOST src=$DOCK360_SRC venv=$DOCK360_VENV key=$MODULES_KEY"
    exit 0
fi

B="/var/backups/ohs-store-rollback/$MODULE"
S=$(mktemp -d "$HOME/build/tmp/box-update.XXXXXX")
trap 'rm -rf "$S"' EXIT

# Read with 2>/dev/null and `|| true`: a missing module on the box makes
# the remote grep (and so this whole pipeline, under pipefail) fail, and
# without the guard that would abort here with ssh's bare exit status
# instead of the clear message below - this was the draft's own bug.
OLD=$(ssh "$BOX_HOST" "sudo grep '^version:' /var/lib/dock360/catalogue/uploaded/modules/$MODULE/module.yaml | cut -d' ' -f2" 2>/dev/null) || true
[ -n "$OLD" ] || { echo "could not read the installed version of $MODULE on $BOX_HOST" >&2; exit 1; }
RB="$NEW.rollback"
echo "installed $OLD -> new $NEW (rollback labelled $RB)"

if ssh "$BOX_HOST" "sudo test -e $B/$MODULE-$RB.d360mod"; then
    if [ "$FORCE_ROLLBACK" -eq 0 ]; then
        echo "$B/$MODULE-$RB.d360mod already exists on $BOX_HOST; pass --force-rollback to replace it" >&2
        exit 1
    fi
fi

# 1. rollback package of the installed version, with its image
ssh "$BOX_HOST" "set -e; W=/tmp/rb-$MODULE-$NEW; sudo rm -rf \$W /tmp/rbout-$MODULE-$NEW
  sudo cp -a /var/lib/dock360/catalogue/uploaded/modules/$MODULE \$W
  sudo sed -i 's/^version: $OLD\$/version: $RB/' \$W/module.yaml
  sudo rm -f \$W/checksums.txt \$W/checksums.txt.sig \$W/image.tar.gz \$W/d360mod.json
  U=\$(id -u dock360)
  sudo -u dock360 env XDG_RUNTIME_DIR=/run/user/\$U podman tag localhost/dock360-$MODULE:$OLD localhost/dock360-$MODULE:$RB
  sudo mkdir -p /tmp/rbout-$MODULE-$NEW; sudo chown dock360 /tmp/rbout-$MODULE-$NEW; sudo chown -R dock360 \$W
  cd /tmp; sudo -u dock360 env HOME=/var/lib/dock360 XDG_RUNTIME_DIR=/run/user/\$U /usr/local/bin/dock360ctl module package --allow-dirty --with-image -o /tmp/rbout-$MODULE-$NEW/rb.d360mod \$W | head -1" 2>&1 | { grep -v chdir || true; }
ssh "$BOX_HOST" "sudo cat /tmp/rbout-$MODULE-$NEW/rb.d360mod" > "$S/rb.d360mod" 2>/dev/null
scp -q "$S/rb.d360mod" "$SIGN_HOST:/tmp/$MODULE-$RB.d360mod"
ssh "$SIGN_HOST" "cd $DOCK360_SRC && PYTHONPATH=. $DOCK360_VENV -m dock360.cli module sign /tmp/$MODULE-$RB.d360mod --key $MODULES_KEY | head -1"
scp -q "$SIGN_HOST:/tmp/$MODULE-$RB.d360mod" "$S/rb-signed.d360mod"
ssh "$SIGN_HOST" "rm -f /tmp/$MODULE-$RB.d360mod"
scp -q "$S/rb-signed.d360mod" "$BOX_HOST:/tmp/$MODULE-$RB.d360mod"
ssh "$BOX_HOST" "set -e; sudo mkdir -p $B; sudo mv /tmp/$MODULE-$RB.d360mod $B/$MODULE-$RB.d360mod
  printf '#!/bin/sh\n# Back to $OLD, relabelled so Dock360 accepts it over $NEW.\nset -eu\ndock360ctl catalogue upload $B/$MODULE-$RB.d360mod\ndock360ctl update $MODULE\ndock360ctl status | grep $MODULE\n' | sudo tee $B/rollback-$MODULE-$NEW.sh >/dev/null
  sudo chmod 755 $B/rollback-$MODULE-$NEW.sh; sudo rm -rf /tmp/rb-$MODULE-$NEW /tmp/rbout-$MODULE-$NEW" 2>&1 | { grep -v chdir || true; }
echo "rollback ready: ssh $BOX_HOST sudo $B/rollback-$MODULE-$NEW.sh"

# 2. the new package, checked, then installed
scp -q "$FROM_HOST:$FROM_PATH" "$S/new.d360mod"
got=$(sha256sum "$S/new.d360mod" | cut -d' ' -f1)
[ "$got" = "$SHA" ] || { echo "sha256 mismatch: $got" >&2; exit 1; }
scp -q "$S/new.d360mod" "$BOX_HOST:/tmp/$MODULE-$NEW.d360mod"
ssh "$BOX_HOST" "set -e; sudo mkdir -p $B
  if [ -e /var/lib/dock360/modules/$MODULE/data/config.json ]; then
    sudo cp -p /var/lib/dock360/modules/$MODULE/data/config.json $B/config.json.before-$NEW-\$(date +%Y%m%d%H%M)
  fi
  sudo dock360ctl catalogue upload /tmp/$MODULE-$NEW.d360mod | tail -1
  sudo dock360ctl update $MODULE | tail -3
  rm -f /tmp/$MODULE-$NEW.d360mod
  sudo dock360ctl module list | grep $MODULE || echo '$MODULE not seen in module list after update' >&2" 2>&1 | { grep -v chdir || true; }
echo DONE
