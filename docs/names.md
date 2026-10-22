# Names: OpenHamShack to OpenHamShack

The family became OpenHamShack on 09/10/2026; the windows, menus and
installer titles took the new product names then (OpenHamShack QO-100 NB,
OpenHamShack Radio, which was OpenHamShack HAM). On 17/10/2026 Brian renamed
everything else as well, hidden identifiers included - and decided then,
and again on 21/10/2026 for the family-wide rename, to keep no
compatibility with the old names: no migration code, no "former name"
handling, nothing that carries an installation across by itself. This
page is what each name is now, what it was, and what was deliberately
left alone. Read it before adding a file, a folder or a variable named
after the app.

## Renamed

| What | Now (NB / Radio) | Was |
| --- | --- | --- |
| Settings, data and log folders | `openhamshack-nb`, `openhamshack-radio` under `~/.config` and `~/.local/share` (Linux), `%APPDATA%` (Windows), `~/Library/Application Support` and `~/Library/Logs` (macOS) | `openhamshack-nb`, `openhamshack-ham` |
| Environment variables | `$OHS_NB_CONF`, `_DATA`, `_UI_CONF`, `_UPDATE_URL`, `_DIAG_URL`; `$OHS_RADIO_*`; `$OHS_PSKREPORTER`; `$OHS_RELEASE_KEY` | `$OHSNB_*`, `$OHSRADIO_*`, `$OPENHAMSHACK_PSKREPORTER`, `$OPENHAMSHACK_RELEASE_KEY` (still read when the new ones are not set: `AppId.getenv`, the one piece of compatibility kept, since it costs nothing and breaks no script) |
| Debian package, command, `/usr/lib` folder, desktop entry, icon, AppStream id, man page, udev rule | `openhamshack-nb`, `openhamshack-radio` | `openhamshack-nb`, `openhamshack-ham` |
| Release files | `openhamshack-nb_<v>_<arch>.deb`, `openhamshack-nb-<v>-setup.exe`, `openhamshack-nb-<v>-arm64.dmg`, `openhamshack-nb-<v>-src.tar.gz` | `openhamshack-nb...` |
| Windows program | `openhamshack-nb.exe` in `%LOCALAPPDATA%\Programs\OpenHamShack QO-100 NB`; Start menu "OpenHamShack QO-100 NB" | `openhamshack-nb.exe` in `...\Programs\OpenHamShack NB`; Start-menu folder "OpenHamShack NB" |
| Mac app | "OpenHamShack QO-100 NB.app", `com.openhamshack.qo100nb`; "OpenHamShack Radio.app", `com.openhamshack.radio` | "OpenHamShack NB.app", `com.openhamshack-nb` (HAM likewise) |
| Recording file names | `openhamshack-nb-<UTC>-<MHz>-<MODE>.sigmf-*` | `openhamshack-nb-...` |
| Diagnostics zip, log file | `openhamshack-nb-diagnostics-<time>.zip`, `openhamshack-nb.log` | `openhamshack-nb...` |
| Source-site sections | `#openhamshack-nb`, `#openhamshack-radio`, `-macos` | `#openhamshack-nb`, ... |
| Update request and feed `app` | `User-Agent: openhamshack-nb/<v>`, feed `"app": "openhamshack-nb"` (`"openhamshack-radio"`) | `openhamshack-nb/<v>`, `"openhamshack-ham"` |
| Simulator texts | OPENHAMSHACK NB SIMULATOR, KG-STV call OPENHAMSHACK-SIM | OPENHAMSHACK ... |

## What is not carried across

None of the above migrates itself any more. A Windows install from before
09/10/2026 (the AppId is unchanged) still upgrades in place, because that
is Inno Setup's own default behaviour, not code of ours - but it installs
into its own existing folder and keeps its own Start-menu group, rather
than being moved. A Linux package from before 17/10/2026 is a different
package name and is not replaced or conflicted with; the operator
installs the new one and removes the old by hand. A Mac app is a
different bundle id and sits beside the old one in Applications, to be
thrown away by hand. Settings, logbook, memories and recordings are not
moved between folders by the program: an operator who wants them carried
across copies the folder across themselves.

The update feed is the one place every installed copy still needs the
same words as ever, since changing them would strand live installations
polling the feed for an update that never matches: `tools/update-feed.py`
writes the feed's `app` and the files it offers under each package's own
current name, and every copy since NB/HAM 0.1.21/0.1.22 checks for exactly
that. There has been no "former" name for either app's feed since then,
so there is nothing left for a later client to carry forward.

## Kept, and why

| What | Kept as | Why |
| --- | --- | --- |
| The update feed's URL | `https://openhamshack.com/desktop/nb/update.json` | It never said OpenHamShack, and moving a feed strands every copy that polls it. |
| The Windows AppId | unchanged GUIDs | It is what makes the new installer an upgrade of the old one; Inno Setup's own default behaviour does the rest. |
| SigMF extension `openhamshack:` in recordings | `openhamshack:` | A file format, in every recording made so far, and read by other repositories (ohs-libs `shack_rec` and `shack_cw` bench, openhamshack `tools/dish-survey`). A new namespace means every reader accepting both, across those repositories at once: a follow-up of its own. |
| Bonjour `_openhamshack._tcp` | as is | The Classic box's contract with every client (GUIDE §2); not NB's to change. |
| Python packages `ohsnb`, `ohsradio`, `ohscore`, `ohsdigi` | as is | Nothing a user sees, every file in the repository and every open branch touches them, and ohsdigi is a wheel other repositories pin. Proposed as a separate change. |
| The repository `~/openhamshack-nb` and its hub | as is | gitsync, every worktree and other sessions' paths; a separate change. |
| Release folders `/srv/openhamshack-nb-releases`, `-ham-releases` | as is | The release host's, invisible outside it; publish.sh maps them to `/desktop/nb`, `/desktop/ham`. |
| The release key's file `~/.config/openhamshack-release/ed25519.key` | as is | It is the same key made on 07/10/2026; moving the file is the release host's business, not this tool's. |
| `OPENHAMSHACK_SIGNING_ACCOUNT` | as is | A variable set on the Windows build machine beside the signing credentials. |
| Maintainer address `noreply@openhamshack.com` | as is | A real mailbox; a new one is Brian's to make. |
| `.desktop` Keywords "OpenHamShack" | kept | So a search for the old name still finds the app. |
| `former_name` in the About box ("Formerly OpenHamShack NB") | kept | The one place the old name is meant to show: a one-line note for an operator who knew the app by its old name, not a migration path. |
| Historical documents (release notes, research notes, design decisions, HANDOVER) | as written | They record what was true when they were written. |
