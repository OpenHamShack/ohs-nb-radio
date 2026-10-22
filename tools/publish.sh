#!/usr/bin/env bash
# Upload a release folder to 20i in one command - the recipe that was run
# by hand for NB 0.1.8 on 07/10/2026 (HANDOVER.md "Live now"), and before
# that for OpenHamShack DATV (~/control360-handover-2026-10-04.md), scripted so
# the steps cannot be done out of order or left half finished.
#
#   tools/publish.sh nb|ham|source [--dry-run] [--version V]
#                     [--remove PATH]... [--remove-list FILE]
#   tools/publish.sh nb|ham --prune-only [--dry-run]
#
# nb/ham/source each map to one local release folder and one folder of
# openhamshack.com (20i package PACKAGE_ID, user@ssh.example-host):
#   nb      /srv/openhamshack-nb-releases   -> public_html/desktop/nb  https://openhamshack.com/desktop/nb/
#   ham     /srv/openhamshack-ham-releases  -> public_html/desktop/ham https://openhamshack.com/desktop/ham/
#   source  /srv/source-site           -> public_html/source      https://openhamshack.com/source/
# Until 0.1.15 these were openhamshacknb., openhamshackham. and source.brian-henderson
# .co.uk (package 2703870). Brian had those hosts deleted on 09/10/2026 and
# decided on 12/10 that they are not coming back, so from 0.1.16 the apps'
# feeds and source link name these folders (docs/update-feed.md). The rest
# of openhamshack.com is the website's (~/openhamshack-site, uploaded by
# openhamshack-os tools/publish-web.sh, which leaves these folders alone,
# as this leaves the site and /feeds/ alone: each run touches only its own
# folder). robots.txt and sitemap.xml are never uploaded: crawlers read
# only the docroot's, which are the website's, and the release folders'
# copies still name the old hosts.
#
# nb and ham upload only what the feed offers: the files update.json names,
# their .sha256, the feed and its signature, and .htaccess (types, and
# no-cache on the feed). The rest of a release folder - every old .deb, the
# Mac preview, and the product pages site-build.py writes - stays behind.
# The pages name people (the user guide's examples, the release notes'
# commit subjects, the publisher's address), and openhamshack.com publishes
# no personal name (BETA-PLAN decision 5); the website's downloads page and
# guides stand in for them. Old packages were never on openhamshack.com and
# poll the deleted hosts, so offering them would only strand whoever took
# one. The source target uploads its whole folder: the archive page is the
# GPL's "clear directions" to the source.
#
# The upload key. Brian's first rule was no standing key at all; on 09/10
# he relaxed it for openhamshack.com to one key with an end date (2026-11-08),
# kept only on shack in ~/.config/openhamshack/20i/ and removed from 20i by
# a timer on that date (openhamshack-os publish-web.sh key-month). While it
# is valid for at least another hour this uses it: no lab session and no
# wait. Otherwise every run - dry or not - mints a temporary ed25519
# keypair, adds the public half through the Control360 API
# (a lab session stands in for an operator's own login - see
# ~/.claude/jobs/e0b9840c/tmp/lab-session.sh), waits for 20i to accept it
# (about half an hour, 09/10), uses it over SSH, then removes the key and
# the lab session again. "touches nothing remote" for --dry-run means no
# upload, delete or verify - reaching the remote at all to list what would
# change still needs a key.
#
# Order (upload_order() in tools/release.sh says the same thing):
#   1. back up what is about to change or be removed
#   2. the payload (never --delete - a removal is only ever the explicit
#      list below, never rsync's own idea of "not present locally")
#   3. the pages, index.html last of those
#   4. update.json.sig, then update.json - the feed always last, so a
#      client never sees a manifest before what it points at exists
#   5. delete what release.sh's own "remove from the remote site:" list
#      named (one path per line, relative to the docroot; --remove-list
#      FILE accepts exactly that block of a release.sh run's own stdout,
#      a blank line or one starting with "#" ignored, so it can be piped
#      straight through)
#   5b. nb/ham: prune the packages the feed no longer names (below)
#   6. verify every uploaded file over HTTPS against its local sha256,
#      with a ?v=<random> cache-buster (20i's StackCDN serves stale
#      copies of replaced files at the edge for a while - HANDOVER.md),
#      and that every pruned file is now a 404
#
# Pruning (nb/ham only, from 19/10/2026). Step 5's list names only what
# release.sh moved out of the release folder - older installers and
# images - and .debs never move, so every superseded .deb stayed on the
# site for good: after NB 0.1.23 / Radio 0.1.22, /desktop/nb and
# /desktop/ham still served NB 0.1.22 and Radio 0.1.21's .debs and the
# openhamshack-nb/openhamshack-ham .debs of the hand releases. So after the feed is
# up, every package (.deb, .exe, .dmg, and its .sha256) at the top of the
# release folder or the remote folder that the feed does NOT name is
# moved into the release folder's archive (${local_dir}-archive, flat, as
# release.sh archives installers; copied down from the site first when
# only the site has it) and deleted from both. Never pruned: anything the
# feed names, any file of a version the feed or --version names (a
# platform held back still has its own files), source tarballs, and
# anything below the top level (source/, shots/). An archive that already
# holds a different file of the same name keeps both copies in place and
# fails the run, as release.sh's archive_to does. A feed that names no
# package at all prunes nothing. --prune-only does just this against what
# is already live: it uploads nothing, and refuses unless every file the
# feed offers - the feed and its signature included - is byte-identical
# on the site already, so the feed it prunes by is the live one.
# Cleanup (the key, the lab session, the temp dir) runs in a trap, so it
# happens whether the run above succeeded or not - never left behind for
# "a stolen session holds a list of verbs rather than a machine" to stay
# true, and never the unscoped "revoke every lab session" call, which
# would end every other lab session on the box along with this one.
#
# Nothing here is a secret by itself (the package ID and docroots are
# already in HANDOVER.md) but the cookie/CSRF a lab session mints are
# capability-bearing for as long as the key and session exist - neither is
# ever echoed, logged, or put in a URL/command line another process on
# this box could read from ps.
#
# This script has not been run for real: tests/test_publish.py stubs
# ssh/curl/rsync on PATH (and the lab-session helper itself) and checks
# argument handling, step order and the cleanup trap only - never the
# real endpoints.
set -euo pipefail

prog=$(basename "$0")
usage() {
    cat >&2 <<EOF
Usage: $prog nb|ham|source [--dry-run] [--version V] [--remove PATH]... [--remove-list FILE]
       $prog nb|ham --prune-only [--dry-run]
EOF
}

# --- site mapping (env overrides are for the test suite only: the real
# run always gets the defaults below) ----------------------------------
site=${1:-}
case "$site" in
    nb)     default_local=/srv/openhamshack-nb-releases;  default_remote=public_html/desktop/nb;  default_base=https://openhamshack.com/desktop/nb ;;
    ham)    default_local=/srv/openhamshack-ham-releases; default_remote=public_html/desktop/ham; default_base=https://openhamshack.com/desktop/ham ;;
    source) default_local=/srv/source-site;          default_remote=public_html/source;      default_base=https://openhamshack.com/source ;;
    *) usage; exit 2 ;;
esac
shift

local_dir=${PUBLISH_LOCAL_DIR:-$default_local}
remote_subdir=${PUBLISH_REMOTE_SUBDIR:-$default_remote}
public_base=${PUBLISH_PUBLIC_BASE:-$default_base}
remote_host=${PUBLISH_REMOTE_HOST:user@ssh.example-host}
api_base=${PUBLISH_API_BASE:-https://control360.co.uk/api/v1}
package_id=${PUBLISH_PACKAGE_ID:-PACKAGE_ID}
confirm_header=${PUBLISH_CONFIRM_HEADER:-openhamshack.com}
standing_dir=${PUBLISH_STANDING_DIR:-$HOME/.config/openhamshack/20i}
lab_session_helper=${PUBLISH_LAB_SESSION_HELPER:-$HOME/.claude/jobs/e0b9840c/tmp/lab-session.sh}
control_a_host=${PUBLISH_CONTROL_A_HOST:-control-a}
backup_root=${PUBLISH_BACKUP_ROOT:-$HOME/backups}

dry_run=0
prune_only=0
version=""
remove_paths=()

while [ $# -gt 0 ]; do
    case "$1" in
        --dry-run) dry_run=1; shift ;;
        --prune-only) prune_only=1; shift ;;
        --version) version=${2:?--version needs a value}; shift 2 ;;
        --remove) remove_paths+=("${2:?--remove needs a path}"); shift 2 ;;
        --remove-list)
            file=${2:?--remove-list needs a file path}
            shift 2
            [ -f "$file" ] || { echo "$prog: --remove-list $file: no such file" >&2; exit 2; }
            while IFS= read -r line || [ -n "$line" ]; do
                # Tolerates release.sh's own "remove from the remote
                # site:" block verbatim: its paths are the only lines
                # indented with two spaces; everything else here (blank,
                # "#"-commented, or any other line) is ignored rather
                # than rejected, so the whole block can be piped through
                # without editing it down to just the paths by hand.
                case "$line" in
                    "  "*) remove_paths+=("${line#  }") ;;
                    ""|"#"*) ;;
                esac
            done < "$file"
            ;;
        -h|--help) usage; exit 0 ;;
        --) shift; break ;;
        -*) echo "$prog: unknown option $1" >&2; usage; exit 2 ;;
        *) break ;;
    esac
done
# Any remaining positional arguments are also removal paths (the task's
# "accept them as arguments or from a file" - both, not either/or).
remove_paths+=("$@")

if [ "$prune_only" = 1 ]; then
    # Only a feed site has packages a feed can stop naming, and "only"
    # means only: an explicit removal belongs to a release's own run.
    [ "$site" != source ] || { echo "$prog: --prune-only is for nb or ham" >&2; exit 2; }
    [ "${#remove_paths[@]}" -eq 0 ] || { echo "$prog: --prune-only takes no --remove" >&2; exit 2; }
fi

[ -d "$local_dir" ] || { echo "$prog: $local_dir does not exist" >&2; exit 1; }

if [ -z "$version" ]; then
    for cand in "$local_dir"/ohsnb/VERSION "$local_dir"/ohsradio/VERSION "$local_dir"/VERSION; do
        [ -f "$cand" ] && { version=$(tr -d ' \t\r\n' < "$cand"); break; }
    done
    version=${version:-unknown}
fi

today=$(date -u +%Y-%m-%d)
backup_dir="$backup_root/${site}-${today}-pre-${version}"

log() { echo "$prog: $*"; }

# --- temp dir + keypair --------------------------------------------------
tmp=$(mktemp -d)
chmod 700 "$tmp"
key="$tmp/id_ed25519"
standing_key="$standing_dir/id_ed25519"
standing_meta="$standing_dir/meta"   # handle=<20i handle>, expires=<epoch seconds>

handle=""
cookie=""
csrf=""
token_sha=""
key_added=0

cleanup() {
    local rc=$?
    # Best-effort, every step independent of the others: a failure half
    # way through the run above must not stop the rest of this from
    # running, and nothing here is allowed to mask the original exit code.
    if [ "$key_added" = 1 ] && [ -n "$handle" ]; then
        curl -sS -o /dev/null -X DELETE \
            -H "Cookie: c360_session=${cookie}" \
            -H "X-C360-Csrf: ${csrf}" \
            -H "X-C360-Reason: $prog cleanup" \
            -H "X-C360-Confirm: ${confirm_header}" \
            "${api_base}/dns/hosting/packages/${package_id}/ssh/keys/${handle}" \
            || log "could not delete the uploaded ssh key (handle ${handle}) - remove it by hand"
    fi
    if [ -n "$token_sha" ]; then
        # Scoped to this run's own session only - never the unscoped
        # revoke-everything call, which would end every other lab
        # session on the box along with this one.
        ssh "$control_a_host" \
            "sudo -u postgres psql -qtAX -d c360 -c \"DELETE FROM core.sessions WHERE token_sha256 = '${token_sha}'\"" \
            >/dev/null || log "could not delete the lab session (by its token hash) - it will expire on its own"
    fi
    rm -rf "$tmp"
    exit "$rc"
}
trap cleanup EXIT

# The month key, if it is there and good for at least another hour (a
# whole upload, setup.exe and all, fits in that comfortably).
standing_expires=$(sed -n 's/^expires=//p' "$standing_meta" 2>/dev/null || true)
if [ -f "$standing_key" ] && [ -n "$(sed -n 's/^handle=//p' "$standing_meta" 2>/dev/null || true)" ] \
        && [ "${standing_expires:-0}" -gt $(( $(date +%s) + 3600 )) ] 2>/dev/null; then
    log "using the month upload key (until $(date -d @"$standing_expires" +%F))"
    key=$standing_key
else
ssh-keygen -q -t ed25519 -N "" -f "$key" -C "publish.sh ${site} $(date -u +%FT%TZ)"

# --- a lab session stands in for an operator's own login -----------------
# Run with bash, not exec'd: the helper is a job's scratch file, not
# marked executable. control-a is the live management host; the helper's
# own default address is an older one.
lab_out=$(C360_HOST="${C360_HOST:-control-a}" bash "$lab_session_helper" owner)
cookie=$(sed -n 's/^COOKIE=//p' <<< "$lab_out")
csrf=$(sed -n 's/^CSRF=//p' <<< "$lab_out")
[ -n "$cookie" ] && [ -n "$csrf" ] || { log "lab session helper did not print COOKIE=/CSRF="; exit 1; }
token_sha=$(printf '%s' "$cookie" | sha256sum | cut -d' ' -f1)

handle="publish-${site}-$(date -u +%Y%m%d%H%M%S)-$$"
pubkey=$(cat "$key.pub")
body=$(python3 -c 'import json, sys; print(json.dumps({"handle": sys.argv[1], "publicKey": sys.argv[2]}))' "$handle" "$pubkey")
curl -sS -f -X POST \
    -H "Cookie: c360_session=${cookie}" \
    -H "X-C360-Csrf: ${csrf}" \
    -H "X-C360-Reason: $prog ${site} release upload" \
    -H "X-C360-Confirm: ${confirm_header}" \
    -H "Content-Type: application/json" \
    --data "$body" \
    "${api_base}/dns/hosting/packages/${package_id}/ssh/keys" >/dev/null
key_added=1
fi

ssh_cmd=(ssh -i "$key" -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new -o BatchMode=yes -o ConnectTimeout=20)
rsync_ssh="${ssh_cmd[*]}"

# A fresh key can take about half an hour before 20i's SSH host accepts it
# (09/10: refused at 4 minutes, accepted at 31); the month key is accepted
# at once. Without this wait the first rsync below failed outright.
accepted=0
for i in $(seq 1 "${PUBLISH_KEY_WAIT_TRIES:-80}"); do
    if "${ssh_cmd[@]}" "$remote_host" true 2>/dev/null; then accepted=1; break; fi
    [ "$i" = 1 ] && log "waiting for 20i to accept the key (often ~30 minutes)"
    sleep "${PUBLISH_KEY_WAIT_SECONDS:-30}"
done
[ "$accepted" = 1 ] || { log "20i never accepted the key; nothing uploaded"; exit 1; }

remote() { "${ssh_cmd[@]}" "$remote_host" "$@"; }

# `printf '%s\n' "${arr[@]}"` on a zero-element array still prints one
# blank line (printf recycles its format string for a format with no
# arguments left, same as it does for too few) - every array built by
# filtering another one below would otherwise pick up one phantom empty
# path, with `"${#arr[@]}" -gt 0` then wrongly true and an rsync call
# uploading "nothing" as if it were a real file. lines_of is the guard.
lines_of() { [ "$#" -eq 0 ] || printf '%s\n' "$@"; }

# --- what rsync is about to touch, for the backup and the verify step ----
# Only files whose CONTENT differs from the remote copy (--checksum, no
# times or permissions compared): a release folder keeps every old package,
# and comparing times made the first real run (0.1.9) want to re-upload,
# back up and re-download every old tarball whose bytes had not changed.
# The folder may not exist yet (desktop/ did not, the first time); a dry
# run creates nothing, and rsync -n lists every file as new without it.
[ "$dry_run" = 1 ] || remote mkdir -p "$remote_subdir"
only=()
if [ "$site" != source ]; then
    # What the feed offers (module docstring), listed before anything is
    # compared, so a feed that cannot be read stops the run here.
    python3 - "$local_dir" > "$tmp/offer" <<'PY' || { log "cannot read $local_dir/update.json; nothing uploaded"; exit 1; }
import json, os, sys
d = sys.argv[1]
names = [f["url"] for f in json.load(open(os.path.join(d, "update.json"), encoding="utf-8"))["files"]]
for n in names:
    if "/" in n or n.startswith("."):
        sys.exit(f"update.json names {n!r}, not a file beside it")
    print(n)
    if os.path.isfile(os.path.join(d, n + ".sha256")):
        print(n + ".sha256")
for n in (".htaccess", "update.json.sig", "update.json"):
    if os.path.isfile(os.path.join(d, n)):
        print(n)
PY
    only=(--files-from="$tmp/offer")
fi
mapfile -t all_files < <(rsync -rcn --out-format='%n' --exclude=/robots.txt --exclude=/sitemap.xml "${only[@]}" \
    -e "$rsync_ssh" "$local_dir/" "${remote_host}:${remote_subdir}/" | grep -v '/$' | sort || true)
mapfile -t html_files < <(lines_of "${all_files[@]}" | grep -E '\.html$' || true)
mapfile -t non_index_html < <(lines_of "${html_files[@]}" | grep -vE '(^|/)index\.html$' || true)
mapfile -t index_html < <(lines_of "${html_files[@]}" | grep -E '(^|/)index\.html$' || true)
mapfile -t payload_files < <(lines_of "${all_files[@]}" \
    | grep -vE '\.html$' | grep -vE '^update\.json(\.sig)?$' || true)

# --- what the feed no longer names (module docstring, "Pruning") ---------
# Listed here, before anything changes, so a dry run shows it and a feed
# that cannot be read stops the run with nothing touched; carried out in
# step 5b, once the feed that no longer names these files is up.
archive_dir=${local_dir%/}-archive
prune_names=() prune_local=() prune_remote=()
if [ "$site" != source ]; then
    if [ "$prune_only" = 1 ] && [ "${#all_files[@]}" -gt 0 ]; then
        log "--prune-only: the site does not yet serve this folder's feed and what it offers byte for byte:"
        lines_of "${all_files[@]}" | sed 's/^/  differs: /'
        log "publish it first (without --prune-only); nothing pruned"
        exit 1
    fi
    # Top-level regular files only: source/ and shots/ are never pruned.
    # The folder may not exist yet in a dry run, which is an empty list;
    # in a real run it was just made, so a listing that fails is a fault.
    if ! remote find "$remote_subdir" -maxdepth 1 -type f -printf '%f\\n' > "$tmp/remote-files" 2>/dev/null; then
        [ "$dry_run" = 1 ] || { log "cannot list ${remote_subdir}; nothing uploaded"; exit 1; }
        : > "$tmp/remote-files"
    fi
    lines_of "${remove_paths[@]}" > "$tmp/removing"
    python3 - "$local_dir" "$version" "$tmp/offer" "$tmp/remote-files" "$tmp/removing" > "$tmp/prune" <<'PY' \
        || { log "cannot work out what to prune; nothing uploaded"; exit 1; }
import json, os, re, sys
d, version, offer, remote, removing = sys.argv[1:]
files = json.load(open(os.path.join(d, "update.json"), encoding="utf-8"))["files"]
named = set(open(offer, encoding="utf-8").read().split())
package = re.compile(r"\.(deb|exe|dmg)(\.sha256)?$")
if not any(package.search(n) for n in named):
    sys.exit("update.json names no package")      # never "prune everything"
# Every version the feed offers anywhere, and this run's: a platform held
# back on an older version keeps its own files, and so does this version.
keep = {f.get("version") for f in files} | {version}
keep -= {None, "", "unknown"}
kept = [re.compile(rf"[_-]{re.escape(v)}[_-]") for v in keep]
local = {n for n in os.listdir(d) if os.path.isfile(os.path.join(d, n))}
here = set(open(remote, encoding="utf-8").read().split())
gone = set(open(removing, encoding="utf-8").read().split())   # step 5 deletes these already
for n in sorted(local | here):
    if not package.search(n) or n in named or n in gone or ".tar" in n or n.startswith("."):
        continue
    if any(k.search(n) for k in kept):
        continue
    print(f"{n}\t{int(n in local)}\t{int(n in here)}")
PY
    while IFS=$'\t' read -r n l r; do
        prune_names+=("$n"); prune_local+=("$l"); prune_remote+=("$r")
    done < "$tmp/prune"
fi

if [ "$dry_run" = 1 ]; then
    # A read-only rsync listing - still over the key just added, since
    # there is no other way to reach the remote at all (module docstring),
    # but nothing here can change or delete anything on it.
    log "dry run: would upload from $local_dir to ${remote_host}:${remote_subdir}/"
    lines_of "${all_files[@]}" | sed 's/^/would change: /'
    for p in "${remove_paths[@]}"; do
        log "would remove: $p"
    done
    for i in "${!prune_names[@]}"; do
        case "${prune_local[$i]}${prune_remote[$i]}" in
            11) where="the release folder and the site" ;;
            10) where="the release folder" ;;
            *)  where="the site" ;;
        esac
        log "would prune: ${prune_names[$i]} (from $where, into $archive_dir)"
    done
    log "dry run only: nothing uploaded, nothing removed, nothing verified"
    exit 0
fi

# --prune-only reaches here only when nothing differs (above), so steps 1-4
# have nothing to send; only the backup would still run, and the archive is
# where whatever is pruned is kept.
# --- 1. back up what is about to change or be removed ---------------------
if [ "$prune_only" = 0 ]; then
mkdir -p "$backup_dir"
backup_list="$tmp/backup-list"
{ lines_of "${all_files[@]}"; lines_of "${remove_paths[@]}"; } | sort -u > "$backup_list"
rsync -az --ignore-missing-args --files-from="$backup_list" -e "$rsync_ssh" \
    "${remote_host}:${remote_subdir}/" "$backup_dir/"
log "backed up what is about to change to $backup_dir"
fi

# --- 2. the payload, never --delete ----------------------------------------
if [ "${#payload_files[@]}" -gt 0 ]; then
    rsync -rz --chmod=D755,F644 --files-from=<(printf '%s\n' "${payload_files[@]}") -e "$rsync_ssh" \
        "$local_dir/" "${remote_host}:${remote_subdir}/"
fi

# --- 3. the pages, index.html last of those --------------------------------
if [ "${#non_index_html[@]}" -gt 0 ]; then
    rsync -rz --chmod=D755,F644 --files-from=<(printf '%s\n' "${non_index_html[@]}") -e "$rsync_ssh" \
        "$local_dir/" "${remote_host}:${remote_subdir}/"
fi
if [ "${#index_html[@]}" -gt 0 ]; then
    rsync -rz --chmod=D755,F644 --files-from=<(printf '%s\n' "${index_html[@]}") -e "$rsync_ssh" \
        "$local_dir/" "${remote_host}:${remote_subdir}/"
fi

# --- 4. update.json.sig, then update.json - the feed always last -----------
for feed_file in update.json.sig update.json; do
    if lines_of "${all_files[@]}" | grep -qx "$feed_file"; then
        rsync -z --chmod=F644 -e "$rsync_ssh" "$local_dir/$feed_file" "${remote_host}:${remote_subdir}/$feed_file"
    fi
done

# --- 5. delete what release.sh's own list named ----------------------------
for p in "${remove_paths[@]}"; do
    [ -n "$p" ] || continue
    remote rm -f -- "${remote_subdir}/${p}"
    log "removed $p from the remote site"
done

# --- 5b. prune what the feed no longer names, archived first ---------------
# release.sh's archive_to, the same rule: the same bytes already archived
# lose nothing by dropping this copy; different bytes keep both where they
# are and fail the run. Archived before either copy is deleted, so a run
# that stops part way leaves every file in at least one place, and running
# it again finishes the job.
archive_to() {
    local f=$1 name=${1##*/}
    mkdir -p "$archive_dir"
    if [ -e "$archive_dir/$name" ]; then
        if ! cmp -s "$f" "$archive_dir/$name"; then
            log "prune: $archive_dir already holds a different $name; left in place on the site and here"
            return 1
        fi
        rm -f -- "$f"
    else
        mv -- "$f" "$archive_dir/$name"
    fi
}
prune_fail=0
pruned_remote=()
mkdir -p "$tmp/pulled"
for i in "${!prune_names[@]}"; do
    n=${prune_names[$i]}
    if [ "${prune_local[$i]}" = 1 ]; then
        src="$local_dir/$n"
    else
        # Only the site has it (a hand release's): its copy is the one kept.
        rsync -a -e "$rsync_ssh" "${remote_host}:${remote_subdir}/$n" "$tmp/pulled/"
        src="$tmp/pulled/$n"
    fi
    archive_to "$src" || { prune_fail=1; continue; }
    if [ "${prune_remote[$i]}" = 1 ]; then
        remote rm -f -- "${remote_subdir}/${n}"
        pruned_remote+=("$n")
    fi
    log "pruned $n (no longer in the feed; kept in $archive_dir)"
done

# --- 6. verify every uploaded file over HTTPS, cache-busted -----------------
verify_fail=0
for f in "${all_files[@]}"; do
    [ -f "$local_dir/$f" ] || continue
    # Dotfiles (.htaccess) are never served - a 403 is the server working.
    case "${f##*/}" in .*) continue ;; esac
    local_sha=$(sha256sum "$local_dir/$f" | cut -d' ' -f1)
    v=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
    remote_sha=$(curl -sS -f "${public_base}/${f}?v=${v}" | sha256sum | cut -d' ' -f1)
    if [ "$local_sha" != "$remote_sha" ]; then
        log "verify FAILED: $f does not match what ${public_base}/${f} now serves"
        verify_fail=1
    fi
done
for n in "${pruned_remote[@]}"; do
    v=$(od -An -N8 -tx1 /dev/urandom | tr -d ' \n')
    code=$(curl -sS -o /dev/null -w '%{http_code}' "${public_base}/${n}?v=${v}" || true)
    if [ "$code" != 404 ]; then
        log "verify FAILED: pruned $n, but ${public_base}/${n} answers ${code:-nothing}, not 404"
        verify_fail=1
    fi
done
[ "${#pruned_remote[@]}" -eq 0 ] || [ "$verify_fail" = 1 ] || log "every pruned file (${#pruned_remote[@]}) is a 404 on the site"
if [ "$prune_fail" = 1 ]; then
    log "one or more packages could not be archived (above), so they were not pruned"
    verify_fail=1
fi
if [ "$verify_fail" = 0 ]; then
    log "verified ${#all_files[@]} files byte-identical over HTTPS"
else
    log "one or more files did not verify (above) - check the site before telling anyone it is live"
    exit 1
fi

if [ "$prune_only" = 1 ]; then
    log "pruned $site: ${#prune_names[@]} files the live feed no longer names, nothing uploaded"
else
    log "published $site from $local_dir to ${remote_host}:${remote_subdir}/"
fi
