# Publishing a release to 20i: tools/publish.sh

What used to be a by-hand recipe (first done for NB 0.1.8, 07/10/2026 -
HANDOVER.md "Live now"; the same recipe as the OpenHamShack DATV site before it,
~/control360-handover-2026-10-04.md) is now one command:

```
tools/publish.sh nb|ham|source [--dry-run] [--version V]
                  [--remove PATH]... [--remove-list FILE]
```

`nb`, `ham` and `source` each map to one local release folder - the folder
*is* the site (HANDOVER.md "Publishing") - and one folder of openhamshack.com,
20i package PACKAGE_ID on `user@ssh.example-host`:

| site     | local folder                | remote folder              | public address |
| -------- | ---------------------------- | -------------------------- | -------------- |
| `nb`     | `/srv/openhamshack-nb-releases`   | `public_html/desktop/nb`   | https://openhamshack.com/desktop/nb/ |
| `ham`    | `/srv/openhamshack-ham-releases`  | `public_html/desktop/ham`  | https://openhamshack.com/desktop/ham/ |
| `source` | `/srv/source-site`           | `public_html/source`       | https://openhamshack.com/source/ |

The local folders keep their openhamshack- names after the OpenHamShack rename
(17/10/2026): they are this host's, and nothing outside it sees them. The
files in them are named openhamshack-nb... / openhamshack-radio... from the
first release after it, beside the older openhamshack-nb... ones (docs/names.md).

Until 0.1.15 these were the openhamshacknb., openhamshackham. and source.
brian-henderson.co.uk hosts on package 2703870. Brian had them deleted on
09/10/2026 and decided on 12/10 that they are not coming back. From 0.1.16
the apps' update feeds and About-box source link name the folders above,
so an older copy has to be reinstalled once by hand. The rest of
openhamshack.com (the website, and the platform's `/feeds/`) belongs to
openhamshack-os `tools/publish-web.sh`. Each tool touches only its own
folders. `robots.txt` and `sitemap.xml` are never uploaded from here:
crawlers read only the docroot's, which belong to the website.

**`nb` and `ham` upload only what the feed offers:** the files `update.json`
names, their `.sha256`, the feed and its signature, and `.htaccess`. The
product pages that `site-build.py` writes into the release folder stay
behind, because they name people (the user guide's examples, the release
notes' commit subjects, the publisher's address) and openhamshack.com
publishes no personal name (BETA-PLAN decision 5). The website's downloads
page and guides stand in for them. For the same reason the feed carries no
`notesUrl` any more. Old packages stay behind too. `source` uploads its
whole folder, because its page is the GPL's directions to the source.

## The update mirror (not set up yet)

From 0.1.22 the apps can fall back to a second address for their feed
when openhamshack.com refuses them - 20i StackProtect's bot challenge
answers some VPN addresses 401, and a program cannot pass it
(`docs/update-feed.md`, "Mirrors"). No mirror exists yet:
`MIRROR_BASE` in `ohscore/update.py` is empty, so no client asks one.
To bring one up:

1. Pick the host (Cloudflare is the likely one: R2 or Pages) and give
   it an address of ours, e.g. `https://updates.<domain>`. Turn off its
   own bot protection for that address (Bot Fight Mode, challenges,
   "under attack") - a mirror that challenges is no mirror.
2. Copy each feed folder's uploaded files to the same path there:
   `desktop/nb/` and `desktop/ham/` with `update.json`,
   `update.json.sig`, every file `update.json` names and their
   `.sha256`. Byte for byte: never re-sign, re-serialise or recompress.
   Order as for the site: payloads, then `update.json.sig`, then
   `update.json`.
3. Serve `update.json` and `update.json.sig` with
   `Cache-Control: no-cache` (or a TTL of a few minutes).
4. Verify as step 6 below does: fetch each file back with a
   `?v=<random>` and compare its sha256 with the local copy;
   `curl -A openhamshack-nb/0.1.21 https://updates.<domain>/desktop/nb/update.json`
   must give JSON, not a page.
5. Set `MIRROR_BASE = "https://updates.<domain>"` and release. Only
   copies from that release on know the mirror; Ray still needs 0.1.22
   installed by hand once (or from a network the challenge lets through).

From then on every release uploads to the mirror after the site, in the
same order. `publish.sh` does not do that yet: it is a step to add once
the host, and its upload route, are chosen.

## The upload key

**The month key first.** On 09/10 Brian allowed one openhamshack.com key
with an end date (2026-11-08). It is kept on shack only, in
`~/.config/openhamshack/20i/` (`id_ed25519`, plus `meta` holding
`handle=`/`expires=`), and a timer removes it from 20i on that date.
`publish-web.sh key-month` makes a new one. While the key is good for at
least another hour, `publish.sh` simply uses it: no lab session and no
wait.

**Otherwise a key per run.** The original rule (HANDOVER.md "Publishing")
was no standing upload route at all. Without a valid month key, every run
of `publish.sh` (`--dry-run` or not) does the same things around the real
work:

1. makes a fresh ed25519 keypair in a `mktemp -d`, `chmod 700` directory;
2. mints a lab session that stands in for an operator's own login
   (`~/.claude/jobs/e0b9840c/tmp/lab-session.sh` - a real `core.operators`
   row and a real, time-limited `core.sessions` row, the same fixture the
   auth test suite uses, not a bypass of anything past the login step
   itself) and adds the public half of the key through the Control360 API:
   `POST /api/v1/dns/hosting/packages/PACKAGE_ID/ssh/keys` with the session's
   cookie and CSRF token, `X-C360-Reason` saying why, and
   `X-C360-Confirm: openhamshack.com`;
3. waits for 20i to accept the key (about half an hour; at most 40 minutes),
   then does the actual work over SSH with it;
4. in a trap, always - success or failure - deletes the key by the handle
   it was added under, deletes *only this run's own* lab session (by the
   SHA-256 of its cookie, never the unscoped "revoke everything" call,
   which would end every other lab session on the box too), and removes
   the temp directory.

`--dry-run` still does steps 1, 2 and 4 - there is no other way to reach
the remote host at all to list anything - but step 3 is read-only (an
`rsync -n` listing) and never uploads, deletes or verifies anything.

## What a real run does, in order

(`tools/release.sh`'s own `upload_order()` says the same thing, since both
exist to make sure a client never sees a manifest before what it points
at, or a page before the files it links to.)

1. **Back up** what is about to change or be deleted. Every local file
   about to be uploaded, plus every path named for removal, is pulled from
   the remote site as it stands *now* into
   `~/backups/<site>-<date>-pre-<version>/` - `--version` names it
   explicitly, or it is read from `ohsnb/VERSION` / `ohsradio/VERSION` inside
   the release folder, or `unknown` if neither exists (the `source` site
   has no single version).
2. **The payload** - everything that is not a page and not the update
   feed - rsynced up, never with `--delete`: a removal is only ever the
   explicit list in step 5, never rsync's own idea of what is "not present
   locally" (losing a file nobody meant to touch, by shipping from an
   incomplete working copy, is the failure mode this avoids).
3. **The pages** - every `*.html` file, `index.html` last of them, at
   whatever depth it is found at (so `index.html` and `source/index.html`
   are each last within their own directory's pages, not merely last of
   the whole run - an operator still mid-page-load sees either the old
   page throughout or the new one, never a half-linked mix of both).
4. **The update feed** - `update.json.sig`, then `update.json` - signature
   before manifest, manifest always last of all the uploads, so a client
   checking for updates never sees one before what it signs exists.
5. **Removal.** Whatever `--remove PATH` or `--remove-list FILE` named,
   deleted from the remote site now, only now - after everything above is
   already in place, never before. `--remove-list` reads release.sh's own
   "remove from the remote site:" stdout block exactly as it prints it:
   only the two-space-indented lines are paths, so the whole block can be
   piped straight into a file and passed through, header line, blank line
   and all, with nothing to edit out by hand.
6. **Verify.** Every file just uploaded is fetched back over HTTPS with a
   `?v=<random>` cache-buster (20i's StackCDN serves stale copies of
   replaced files at the edge for a while - HANDOVER.md) and its sha256
   checked against the local copy. Any mismatch is reported and the run
   exits non-zero - cleanup (above) still happens, but the operator is
   told to check the site by hand before calling it live.

## What it will not do

Never prints the cookie, the CSRF token, or the private half of the key -
not to stdout, not to stderr, not anywhere a `ps` of this box could read
it from. A `--dry-run` touches nothing on the remote site itself (reaching
it at all for the listing still needs the same temporary key, which is
removed just as it would be for a real run).

## Testing

**This script has not been run for real** - not against the live
Control360 API, not against 20i. `tests/test_publish.py` runs the real
script with `ssh`, `curl` and `rsync` replaced by small logging stubs on
`PATH` (and the lab-session helper itself replaced by one that prints a
fixed cookie/CSRF, so no real database row is ever touched by a test
either), and checks argument handling, the upload order above, and that
the cleanup trap fires - the key is deleted, the session is deleted,
whether the run succeeded or a step part way through failed on purpose.
Run it like any other test file:

```
python3 -m unittest discover -s tests -p test_publish.py
```

Before this is ever run for real: confirm the lab-session helper's target
host and the `sudo -u postgres psql` cleanup command still match
whichever host actually holds `core.sessions` (`control-a` by name here;
`PUBLISH_CONTROL_A_HOST` overrides it), and read the script itself once
more end to end - it was written and tested, but, per the task it was
built from, deliberately never run for real.
