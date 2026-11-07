#!/bin/bash
# Install the scheduled IQ captures: the script, decimate.py, the capture
# units and their timers on the controller, and the fetch timers here.
#
#   tools/iq-capture/deploy.sh            # both
#   tools/iq-capture/deploy.sh --box      # the controller only
#   tools/iq-capture/deploy.sh --fetch    # this host's fetch timers only
#   tools/iq-capture/deploy.sh --remove   # disable and remove both
#
# On the controller (BOX_HOST in ~/.config/openhamshack/box-update.conf;
# sudo is passwordless there):
#   /usr/local/sbin/ohs-iq-capture                      0755
#   /usr/local/lib/ohs-iq-capture/decimate.py           0644 (dock360's podman mounts it read-only)
#   /etc/ohs-iq-capture/<name>.env                      0644
#   /etc/systemd/system/ohs-iq-capture@.service and ohs-iq-capture-<name>.timer, enabled
# Real unit files rather than systemd-run, so they survive a reboot.
#
# Here (user units; they fire only while this account lingers, which the
# script checks):
#   ~/.local/lib/ohs-iq-capture/fetch.sh
#   ~/.config/systemd/user/ohs-iq-fetch@.service and ohs-iq-fetch-<name>.timer, enabled
#
# Installing only schedules: nothing touches the receiver until a timer
# fires. Run again after a change; it replaces what is there.
set -euo pipefail

HERE=$(cd "$(dirname "$0")" && pwd)
WHAT=${1:-all}
case $WHAT in all|--box|--fetch|--remove) ;; *) echo "usage: $0 [--box|--fetch|--remove]" >&2; exit 2 ;; esac

NAMES=()
for f in "$HERE"/units/box/*.env; do NAMES+=("$(basename "$f" .env)"); done

box_part() {
    local conf=${BOX_UPDATE_CONF:-$HOME/.config/openhamshack/box-update.conf}
    # shellcheck disable=SC1090
    source "$conf"
    : "${BOX_HOST:?$conf must set BOX_HOST}"
    local stage=/var/tmp/ohs-iq-deploy-$$
    if [ "$WHAT" = --remove ]; then
        ssh -T "$BOX_HOST" sudo sh -s <<EOF
set -e
for n in ${NAMES[*]}; do systemctl disable --now ohs-iq-capture-\$n.timer 2>/dev/null || true; done
rm -f /etc/systemd/system/ohs-iq-capture@.service /etc/systemd/system/ohs-iq-capture-*.timer
rm -rf /etc/ohs-iq-capture /usr/local/lib/ohs-iq-capture /usr/local/sbin/ohs-iq-capture
systemctl daemon-reload
echo "removed from the controller (recordings in /var/lib/ohs-iq and logs in /var/log/ohs-iq-capture kept)"
EOF
        return
    fi
    ssh -T "$BOX_HOST" "mkdir -m 700 $stage && tar -x -C $stage" < <(
        tar -c -C "$HERE" ohs-iq-capture decimate.py -C "$HERE/units/box" .)
    ssh -T "$BOX_HOST" sudo sh -s <<EOF
set -e
for t in python3 runuser flock podman; do command -v \$t >/dev/null || echo "WARNING: no \$t on the controller"; done
install -o root -g root -m 0755 $stage/ohs-iq-capture /usr/local/sbin/ohs-iq-capture
install -d -o root -g root -m 0755 /usr/local/lib/ohs-iq-capture /etc/ohs-iq-capture
install -o root -g root -m 0644 $stage/decimate.py /usr/local/lib/ohs-iq-capture/decimate.py
install -o root -g root -m 0644 $stage/*.env /etc/ohs-iq-capture/
install -o root -g root -m 0644 $stage/*.service $stage/*.timer /etc/systemd/system/
rm -rf $stage
systemctl daemon-reload
for n in ${NAMES[*]}; do systemctl enable --now ohs-iq-capture-\$n.timer; done
systemctl list-timers --all 'ohs-iq-capture-*' --no-pager
EOF
}

fetch_part() {
    local lib=$HOME/.local/lib/ohs-iq-capture units=$HOME/.config/systemd/user
    if [ "$WHAT" = --remove ]; then
        for n in "${NAMES[@]}"; do systemctl --user disable --now "ohs-iq-fetch-$n.timer" 2>/dev/null || true; done
        rm -f "$units"/ohs-iq-fetch@.service "$units"/ohs-iq-fetch-*.timer
        rm -rf "$lib"
        systemctl --user daemon-reload
        echo "removed the fetch timers here (~/naughtcade-private kept)"
        return
    fi
    install -d -m 0700 "$lib"
    install -d "$units"
    install -m 0700 "$HERE/fetch.sh" "$lib/fetch.sh"
    install -m 0644 "$HERE"/units/user/*.service "$HERE"/units/user/*.timer "$units/"
    systemctl --user daemon-reload
    for n in "${NAMES[@]}"; do systemctl --user enable --now "ohs-iq-fetch-$n.timer"; done
    systemctl --user list-timers --all 'ohs-iq-fetch-*' --no-pager
    [ "$(loginctl show-user "$USER" -p Linger --value 2>/dev/null)" = yes ] \
        || echo "WARNING: $USER does not linger, so the fetch timers fire only while logged in (sudo loginctl enable-linger $USER)"
}

case $WHAT in
    --box) box_part ;;
    --fetch) fetch_part ;;
    *) box_part; fetch_part ;;
esac
