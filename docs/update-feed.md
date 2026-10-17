# The OpenHamShack desktop update feed

How an OpenHamShack desktop app (the family was OpenHamShack until 09/10/2026) learns that a new version exists, proves it, and
installs it. This is the contract: OpenHamShack QO-100 NB and OpenHamShack Radio follow it
first (07/10/2026), and OpenHamShack ATV, Teletext and DATV are to follow the
same one. The client code is `ohscore/update.py` (no window, standard
library plus `cryptography`, nothing else from ohscore - written to be
copied into another repository as it is) and `ohscore/ui/update.py` (the
Qt banner and timing). The feed is written by `tools/update-feed.py`,
which `tools/release.sh` runs.

Brian's decisions (07/10/2026): every app updates itself; it
checks on start-up; what it installs is signed as 360 Technology. The
reasoning behind a signed manifest, rather than HTTPS and Authenticode
alone, is in `docs/ideas-2026-10.md` and at the top of `ohscore/update.py`:
the site is one shared hosting account, and whoever controls it could
otherwise point every client at an old signed installer, or the other
app's.

## Where it lives

Each app has its own feed, in its own release folder, which is its site:

| App | Release folder | Feed |
| --- | --- | --- |
| OpenHamShack QO-100 NB | `/srv/openhamshack-nb-releases` | `https://openhamshack.com/desktop/nb/update.json` |
| OpenHamShack Radio | `/srv/openhamshack-ham-releases` | `https://openhamshack.com/desktop/ham/update.json` |

From 0.1.16 (12/10/2026) both feeds are on openhamshack.com, under
`/desktop/<app>/`. The brian-henderson.co.uk hosts that served them
(openhamshacknb., openhamshackham., source.) were deleted at Brian's request on
09/10 and are not coming back, so 0.1.15 and earlier poll an address
that no longer answers and must be reinstalled once by hand. The new
address is meant to outlive the rename: `/desktop/` keeps desktop
releases apart from the platform's `/feeds/`, and `nb`/`ham` follow the
package names, which change least. Moving it again strands every
installed copy in the same way: don't.

Two files: `update.json`, the manifest, and `update.json.sig`, its
signature. Every file the manifest names sits in the same folder.

## The app's name

On 17/10/2026 (Brian: "rename everything") the Radio package became
`openhamshack-radio`, from `openhamshack-ham` (NB's package name,
`openhamshack-nb`, did not change). Every copy out there by then was new
enough to check the feed's `app` against its own package name
(`Face.package`) and nothing else, so `tools/update-feed.py` writes
`"app"` as that same package name directly - `"openhamshack-nb"` or
`"openhamshack-radio"` - with no transitional name to carry forward and
no compatibility code to do it (`ohscore/update.py` `read_manifest`
takes one `app` name, not a choice of names). The files a feed names
follow the same rule (`openhamshack-nb_0.1.22_amd64.deb`,
`openhamshack-radio-0.1.22-setup.exe`, ...).

The URL does not change: it never said OpenHamShack (`/desktop/nb/`), and
moving a feed strands every copy that polls it.

A copy from before 17/10/2026 (Radio only; NB's package name is
unchanged) is not upgraded by apt or dpkg automatically - there is no
Conflicts, Replaces or Breaks on the old package name - so the operator
installs the new package and removes the old one themselves. On Windows
the new installer keeps the AppId, so it upgrades the old install in
place (one entry in Apps & features), into whichever folder that AppId
was last installed to. On a Mac the new .app lands beside the old one,
which the operator bins. See `docs/names.md` for the full list of what
changed and what is not carried across automatically.

Mirrors (below) add other URLs for the same feed. They combine with
this unchanged: every URL serves the same signed bytes, so the `app` a
mirror's copy names is the same, and a client checks the signature
whatever URL it came from.

## Mirrors

A feed may have more than one address (17/10/2026). Ray's checks were
answered 401 by 20i StackProtect's bot challenge, shown to his VPN's
address, which a program cannot pass. Where a feed is fetched from does
not affect trust: nothing in the manifest is believed until its
signature checks, and every file is held to the signed size and
SHA-256. So a mirror is any other host that carries **the same signed
files, byte for byte**, at the same path:

- `update.json`, `update.json.sig`, and every file `update.json` names,
  under the same path as on openhamshack.com: `/desktop/nb/` and
  `/desktop/ham/` below the mirror's base address. Copy them; never
  re-sign, re-serialise or recompress anything. A mirror that differs by
  one byte is a mirror whose clients refuse it.
- Served as plain GETs with no challenge of its own (no bot check, no
  JavaScript test, no cookie wall), and with `Cache-Control: no-cache`
  (or a TTL of minutes) on `update.json` and `update.json.sig`, so it
  does not keep handing out an old manifest after a release.
- Updated in the same order as the site: payloads, then
  `update.json.sig`, then `update.json`.

The client side:

- A face lists its addresses in order (`update_feeds`: its own site
  first, then `update.with_mirrors()`, which puts the same path under
  each base in `MIRROR_BASE`). An address is tried when the one before
  it fails in any way: 401, 403, 429, 5xx, a timeout, no connection, or
  a body that is not a validly signed feed (a challenge page can come
  back as a 200 of HTML). The first that proves itself answers; the log
  names it. A failure the next address recovers from is only logged.
- When every address fails, the check reports the first refusal if
  there was one, otherwise the first address's own failure.
- Payload names are bare file names, so they resolve against the
  address that answered. The offer also carries the same name beside
  every other address, and the download falls through to those in turn,
  each copy proved the same way. `notesUrl` resolves against the first
  address, the canonical site: it opens in a browser, and a mirror
  carries no pages.
- `OHSNB_UPDATE_URL` / `OHSRADIO_UPDATE_URL`, when set, is the only address
  tried: a copy pointed at a test feed never falls back to the real one.
- `MIRROR_BASE` in `ohscore/update.py` is empty until a mirror host is
  chosen, and an empty base adds no address: no client sends a request
  to a host that does not exist. Setting it takes a release, and only
  copies from that release on know the mirror.
- The `Seen` rule holds across addresses: a mirror serving an older
  manifest than one already accepted is refused like a stale CDN copy,
  and the next address is tried.

## The manifest (schema 1)

UTF-8 JSON, one object:

| Field | Required | Meaning |
| --- | --- | --- |
| `schema` | yes | `1`. A client refuses any other number. |
| `app` | yes | The app's own package name: `openhamshack-nb` or `openhamshack-radio` (see "The app's name" above). A client refuses a manifest for another app. |
| `key` | yes | The id of the key that signed it (below). |
| `published` | yes | When it was signed, UTC, `YYYY-MM-DDTHH:MM:SSZ`. Only ever moves forward. |
| `recommended` | no | A version clients may go *back* to (a withdrawn release). Absent: never backwards. |
| `notesUrl` | no | "What's new": a page of the same site, as a relative reference (`index.html#notes`). Not written since 0.1.16: the openhamshack.com folders carry no pages (see tools/update-feed.py). |
| `files` | yes | One entry per platform and architecture, below. |

Each entry of `files`:

| Field | Meaning |
| --- | --- |
| `platform` | `linux`, `windows` or `macos` |
| `arch` | `amd64`, `arm64` or `all` (Linux: Debian's names; `all` is pure Python and runs anywhere). Windows: `amd64`. macOS: `arm64` (Apple Silicon; there is no Intel build). |
| `kind` | `deb` on Linux, `exe` (an Inno Setup installer) on Windows, `dmg` (a disk image holding the .app) on macOS |
| `version` | This file's version, e.g. `0.1.9`: numbers and dots, compared as numbers. Entries may differ (the installer of a release arrives a day after its `.deb`s). |
| `url` | The file's name, in the manifest's own folder. A bare name - no `/`, no scheme, no `..` - since the client also saves it under that name. |
| `size` | Bytes. |
| `sha256` | Lower-case hex. |
| `date` | The release date, `YYYY-MM-DD`. |
| `notes` | One line, at most 300 characters, for the banner's tooltip and Help › Check for updates…: docs/release-notes/<app>-<version>.txt, written for users (empty without one). |

At most one entry per (platform, arch). A client passes over an entry
whose `platform` or `arch` it has no word for (it is for some later
client) and reads the rest: `macos` was added on 07/10/2026, and refusing
the whole manifest would have stopped every older copy from ever seeing
another update once a feed offered a Mac build. An entry for a platform
it does know is still checked in full. Example:

```json
{
  "schema": 1,
  "app": "openhamshack-nb",
  "key": "ed25519:cc306e8e9b62d0f1",
  "published": "2026-10-09T18:20:11Z",
  "notesUrl": "index.html#notes",
  "files": [
    {"platform": "linux", "arch": "amd64", "kind": "deb", "version": "0.1.9",
     "url": "openhamshack-nb_0.1.9_amd64.deb", "size": 412334,
     "sha256": "5fa77e1c0a7d...", "date": "2026-10-09", "notes": "IQ playback; Q65"},
    {"platform": "linux", "arch": "arm64", "kind": "deb", "version": "0.1.9", "...": "..."},
    {"platform": "linux", "arch": "all", "kind": "deb", "version": "0.1.9", "...": "..."},
    {"platform": "windows", "arch": "amd64", "kind": "exe", "version": "0.1.8",
     "url": "openhamshack-nb-0.1.8-setup.exe", "size": 98123456,
     "sha256": "7deaf154...", "date": "2026-10-07", "notes": "IQ recording; hairline scope pens"}
  ]
}
```

(Here 0.1.9's `.deb`s are out and its installer is not yet: Windows is
still offered 0.1.8's, which is still on the site.)

## The signature

`update.json.sig` is the raw 64-byte Ed25519 signature (RFC 8032, pure
Ed25519, no prehash) of the exact bytes of `update.json` - not of a
parsed or re-serialised copy. Nothing else is in the file. It can be
checked without any of our code:

```
openssl pkey -in ed25519.key -pubout -out release.pub      # on the release host; or from the hex below
openssl pkeyutl -verify -pubin -inkey release.pub -rawin -in update.json -sigfile update.json.sig
```

## Keys

- **The key:** "360 Technology OpenHamShack release key" (made on
  07/10/2026), Ed25519, made and kept only on the release host at
  `~/.config/openhamshack-release/ed25519.key` (PKCS#8 PEM, unencrypted,
  mode 0600 in a 0700 folder); `$OHS_RELEASE_KEY` or `$OPENHAMSHACK_RELEASE_KEY`
  names another place. One key signs every app's feed; the `app` field
  keeps one app's feed from passing as another's. Separate from the
  Authenticode identity on purpose: the feed is signed every release from
  the release host, the installers on the Windows build machine through
  Azure.
- **Making it:** `tools/update-feed.py keygen`. It refuses to overwrite a
  key, writes it 0600 from the first byte, and prints the line to add to
  `RELEASE_KEYS` in `ohscore/update.py`. Back the file up offline.
- **Key id:** `"ed25519:" + sha256(raw 32-byte public key)[:16 hex]`.
  Derived from the key, so it cannot be claimed for another one.
- **Trust:** a client trusts exactly the public keys compiled into it
  (`RELEASE_KEYS`: name and hex of the raw public key). It reads `key`
  from the manifest only to pick which one to check with; a key it does
  not list is refused by name. With no key listed, every manifest is
  refused.
- **Rotation:** make the next key; add its line beside the current one;
  release (signed with the current key) - clients now trust both; once
  installed copies have that release, point `$OHS_RELEASE_KEY` at the
  next key; a later release drops the old line. A copy that missed the
  middle release can only be updated by hand once.
- **Compromise:** the same steps, as fast as releases go out. A copy that
  never updates keeps trusting the old key, which can then only offer it
  something properly built and signed by someone holding that key - the
  Authenticode check (Windows) and the version rules still apply.

## What a client does

1. GET `update.json` and `update.json.sig` from the first address, or
   the next after a failure at any step to 4 (Mirrors, above) - plain GETs, no query string,
   no cookie, with `User-Agent: <app>/<version>` and nothing else about
   the machine. Up to 64 KiB and exactly 64 bytes.
2. Parse the JSON only to read `key`. Refuse if the key is not trusted;
   check the signature over the exact bytes; refuse if it fails.
3. Refuse unless `schema` is 1 and `app` is this app; check every field
   above, including that each `url` is a bare file name.
4. Refuse a manifest whose `published` is older than the newest one this
   installation has accepted (kept beside its config, as
   `update-seen.json`): a stale CDN copy or a replayed manifest must not
   undo a newer one. Record a newer one.
5. Choose the entry: Windows, the `windows`/`amd64` one; Linux, this
   machine's architecture (`dpkg --print-architecture`), else `all`;
   macOS, the `macos` entry of this machine's architecture only (an
   Intel Mac is offered nothing rather than an app it cannot run).
6. Offer it if its version is newer than the installed one, or if it is
   older and equals `recommended` (offered as going back). Otherwise
   nothing.
7. On the operator's click, download `url` (resolved against the
   address that answered, then beside each other address in turn if
   that fails) to `<data folder>/updates/`, stopping past `size`;
   refuse unless size and SHA-256 match; only then give it its real name.
8. Windows: refuse unless Windows calls the installer's Authenticode
   signature `Valid` and the signer's organisation is `360 Technology`.
9. Install - never while transmitting or recording:
   - **Linux (.deb):** `pkexec apt-get install -y <absolute path>` (the
     desktop's password prompt; apt brings in new dependencies). No
     pkexec: show `sudo apt-get install -y '<path>'` instead. Then offer
     Restart now.
   - **Windows (.exe):** after this process exits, run
     `<installer> /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /MERGETASKS=!plutodrivers /RELAUNCH=1`.
     The installer's `[Run]` entry starts the program again only when
     given `/RELAUNCH=1` (`packaging/windows/self-update.iss`).
   - **macOS (.dmg):** not installed - `open <dmg>`, which mounts it and
     shows the new app beside a link to Applications in Finder, and the
     banner tells the operator to quit, drag it across and start it
     again. The button reads "Download", not "Install and restart".
     While the Mac build is unsigned (ad-hoc only, `docs/macos.md`) there
     is no second signature to check as Authenticode is on Windows; a
     file the program downloads carries no quarantine flag, so Gatekeeper
     would never look at a silent replacement; and the microphone
     permission is tied to the app's code signature, which for an ad-hoc
     signature changes with every build, so a silent swap would leave
     transmit audio silent until the operator granted it again. With a
     Developer ID and notarisation this can become a real install: check
     the signer's Team ID, replace the .app, relaunch.

Every failure in steps 1-8 is the same as "no update": logged, and shown
in Help › Check for updates…, never put to the operator as a decision.

## When

On start-up, a few seconds after the window shows (never delaying it),
then once a day while running, by the wall clock; an hour after a check
that could not reach the site. Never while transmitting or recording
(put off until the over ends). A setting (`checkUpdates`, default on)
turns the automatic check off; Help › Check for updates… always works.
Only an installed copy checks by itself - a run from source never does.

## Publishing

`tools/release.sh` does it:

- Before the release commit, `update-feed.py pubkey` must find the key
  and see it in `RELEASE_KEYS`, or nothing is released.
- After the `.deb`s and the site: `update-feed.py write` measures each
  file (cross-checked with its `.sha256`), keeps the previous Windows
  entry while its installer is still in the folder, signs, and checks
  the result as a client would. A `<package>-<version>-arm64.dmg` (and
  its `.sha256`) in the folder becomes the `macos` entry the same way;
  nothing puts one there yet - the Mac build is unsigned, and
  `release.sh --macos` publishes previews only, named
  `<package>-<release>-<label>-arm64.dmg`, which never match, so the feed
  offers a Mac nothing until a signed release exists.
- `release.sh --windows` writes and signs it again with the installer,
  before the older installers leave the folder.
- **Upload the feed last**: packages and installers, then the pages,
  then `update.json.sig`, then `update.json`. A client that sees a new
  manifest before its files are there finds them missing and says
  nothing until the next check. (In the moment between the two feed
  files, a client may fetch a mismatched pair; that is a refused check,
  tried again later.)
- The sites serve both with `Cache-Control: no-cache`
  (`site/htaccess`, `site/ham/htaccess`), so 20i's CDN edge does not sit
  on an old feed. Verify after uploading with `curl` and a `?v=<random>`.
- **A mirror** (once `MIRROR_BASE` is set) gets the same files after
  the site, copied byte for byte in the same order, and is verified the
  same way: each file's sha256 on the mirror equal to the local copy's.
  Nothing uploads to a mirror yet; see `docs/publishing.md`.

`tools/update-feed.py verify [--app ham]` checks a folder as a client
would. `tools/update-feed.py write --version <older> --recommended`
writes a feed that sends clients back to `<older>` (its files must be in
the folder; an archived installer must be put back first).

## Taking this into another OpenHamShack repository

Copy `ohscore/update.py` as it is (keep `RELEASE_KEYS` the same: one key
for every app, and `MIRROR_BASE` the same: one mirror for every feed,
each under its own path). Write the feed with a copy of
`tools/update-feed.py`, changing `APPS` to that project's package names,
file names and folders. Give the installer the `/RELAUNCH=1` entry. The
window half is Qt-specific to NB and HAM; another app needs the same
behaviour: a quiet check after start-up and daily, nothing during a
transmission, the banner, and Help › Check for updates….
