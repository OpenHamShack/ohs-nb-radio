How to publish source on openhamshack.com/source/
=====================================================

(This text is docs/source-site.md in the OpenHamShack QO-100 NB repository, ~/openhamshack-nb,
and is copied onto the site as HOW-TO-PUBLISH.txt every time it is built.)

What the site is
----------------

https://openhamshack.com/source/ holds the source of the third-party
GPL and LGPL code inside the OpenHamShack installers - OpenHamShack QO-100 NB and Radio now;
OpenHamShack DATV, Desktop and ATV as they join - and, from 06/10/2026, each
project's own source, one tarball per release, for the projects that
publish it (NB and HAM do: they are PyQt6 programs, GPL, whose Windows
installers carry only bytecode, and from NB 0.1.5 / HAM 0.1.6 they ship
ohsdigi, compiled from a port of WSJT-X). Repositories stay private; only
release tarballs are published. See "A project's own source" below.

GPL-3 section 6(d) and the LGPL let us offer that source from a different
server than the binaries, on two conditions, and both are yours to keep
for your project:

  1. every page that offers an installer gives clear directions to the
     source - a link to https://openhamshack.com/source/#<project>,
     saying which licences require it - and so does the THIRD-PARTY (or
     equivalent) file inside the installer;
  2. the source stays on the site for as long as the installer is offered.
     Change your manifest only when the installer it describes is about to
     replace the one on offer, never before.

The same two hold for your own source: every download page says where it
is, and a release's tarball stays for as long as any binary of that
release is offered - for a project that keeps every old .deb up, for ever.

The folder /srv/source-site on the release host is the site; it is uploaded to 20i
(by whichever session does uploads, as the product sites are). Nothing
here is ever deleted: files that leave the site go to /srv/source-site-archive.

    files/<tarball>            each tarball once, whichever projects need it
    manifests/<project>.txt    one per project: its own source, and what its installers carry
    SHA256SUMS                 every file under files/
    index.html                 a section per project, anchored #<project>
    HOW-TO-PUBLISH.txt         this text

The manifest
------------

One text file per project, manifests/<project>.txt. <project> is
lower-case letters, digits and hyphens (openhamshack-nb, openhamshack-datv); it is
also the page anchor your download page links to. NB's and Radio's were
openhamshack-nb and openhamshack-ham (and -macos) until the OpenHamShack rename of
17/10/2026; their releases from then on are filed under openhamshack-nb and
openhamshack-radio, and the old sections stay for the releases they cover
(the .debs of those stay on offer, and so must their source).

  - Blank lines and lines starting "#" are ignored.
  - "@title <name>" - the project's name as the page shows it (OpenHamShack DATV).
  - "@home <url>" - its download site.
  - A line starting ">" is prose shown under the project's list (a blank
    ">" line starts a new paragraph; "> - item" lines make a list).
  - A line starting "@own " is one release of the project's own source,
    in the six fields below with url "local". publish-own writes these
    (see "A project's own source"); a list given to publish must not
    contain them.
  - Every other line is one tarball, six fields separated by "|" (spaces
    around them are trimmed):

    file | sha256 | licence | installers that carry it | what it is the source of | url [fallback url ...]

    file       the name it is stored and served under: letters, digits and
               . _ + - only; the upstream release's own name, unrenamed
    sha256     64 lower-case hex digits; take it from the publisher's own
               checksum where they publish one, and say so in a comment
    licence    the licence that requires the source (GPL-3.0, LGPL-2.1-or-later)
    installers which of your installers carry it ("DATV 1.2 onward")
    source of  which files in your installer it is the source of
    url        where the publisher keeps it; more than one, space-separated,
               are tried in order. file:// works, for a tarball you hold
               and upstream no longer serves.

A file another project already lists is stored once - but only if your line
has the same name AND the same SHA-256. The same name with a different hash
is refused for both projects until one of you is corrected: one name on the
site cannot be two files.

Example:

    @title OpenHamShack DATV
    @home https://openhamshack.brian-henderson.co.uk/

    ffmpeg-6.1.1.tar.xz | 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef | LGPL-2.1-or-later | DATV 1.4 onward | ffmpeg.dll and avcodec-60.dll (FFmpeg 6.1.1) | https://ffmpeg.org/releases/ffmpeg-6.1.1.tar.xz

    > Each tarball is the unmodified upstream release.

(The hash above is a placeholder; pin the real one.)

Publishing, for another project
-------------------------------

The tool is tools/source-site.py in the OpenHamShack QO-100 NB repository. Call it by
path from any up-to-date checkout of it (git -C ~/openhamshack-nb pull first, or
a worktree of main); it needs only Python 3 and curl. Nothing in your
repository needs to change but your own release script.

  1. Keep your list in your own repository, in the format above (a
     "@title" and "@home" in it, or given as options below).
  2. When - and only when - you publish an installer, publish the list
     first, as part of that release:

         python3 ~/openhamshack-nb/tools/source-site.py publish <project> <your list> \
             --title "OpenHamShack DATV" --home https://openhamshack.brian-henderson.co.uk/

     It fetches every tarball the list names that the site does not hold
     yet, checks every file's SHA-256 (all projects', every time), and
     only then writes manifests/<project>.txt, SHA256SUMS and index.html.
     It exits non-zero, writing no manifest, if any file cannot be had
     with the pinned hash: your release script must then refuse to
     publish the installer. It moves nothing off the site.
     (--carried-by WORD keeps only the lines whose installers field names
     WORD: one list serving two programs, as NB and HAM's does.)
  3. Put the installer on its own site.
  4. Then let the old set go:

         python3 ~/openhamshack-nb/tools/source-site.py build

     Anything no manifest lists any more moves to /srv/source-site-archive
     (never deleted), and the run ends with a "remove from the remote
     source site:" list.
  5. Upload /srv/source-site (files/ and manifests/ first, index.html
     last), and delete on 20i whatever step 4 listed: an upload adds files
     and never removes any.
  6. Your download page links to
     https://openhamshack.com/source/#<project>; your installer's
     third-party notice gives the same address.

A project's own source
----------------------

Your own program's source, one tarball per release, goes in your section
under its own heading ("OpenHamShack QO-100 NB's own source, per release"), apart from
the third-party list. Two steps, in your release script, after the
release commit and before any binary of it is put on offer:

  1. Make the tarball:

         python3 ~/openhamshack-nb/tools/source-site.py tarball <repo> <release commit> \
             <project>-<version> --out <a build folder>

     It writes <project>-<version>-src.tar.gz there and prints its path:
     the commit's whole tree under <project>-<version>/, by git archive,
     every member stamped with the commit's time, compressed with gzip -n.
     The same commit always gives the same bytes, so anyone can check a
     tarball against the commit, and a lost copy can be made again and
     still match its pinned hash. Paths marked export-ignore in the
     checkout's .gitattributes are left out - for internal notes only: the
     GPL's corresponding source is everything needed to rebuild what you
     ship, so nothing the build reads may be excluded. Run it from a clean
     checkout of the release commit, as release.sh does: the attributes are
     read from the checkout, which is also how releases made before the
     .gitattributes existed are backfilled with the same exclusions.
     Before your first release, search the tree for credentials, internal
     addresses and personal data: the tarball is public, the repository
     is not.

     What history already holds - a host name in an old commit's comment -
     cannot be edited out of it, so the tarball can carry a scrub list:
     packaging/source-scrub.txt in the checkout (read from the checkout,
     like the attributes, so it reaches old commits too), or --scrub
     <file>; --no-scrub makes the plain archive. One rule a line:

         old text => new text      literal, applied in order to every text
                                   file; "\n" is a line break; "old =>"
                                   replaces with nothing
         @forbid <regex>           must not be left in any text file after
                                   the replacements, or no tarball is made
         > prose                   copied into the tarball's notes

     The tool refuses any replacement that would change how the tree
     builds or runs: Rust, Cargo and other compiled sources and any file
     that is not text are never changed, and a Python file may change only
     in comments and docstrings (under tests/, string constants too: test
     data). Everything else it changes - documentation, scripts - is the
     list's reviewer's to vouch for. A scrubbed tarball holds a
     SOURCE-NOTES.txt at its top saying what export-ignore left out, which
     files the list changed, and that none of it affects the build. The
     list names everything it hides, so it must be export-ignore itself;
     the tool refuses otherwise. With no list the tarball is git archive's
     tar exactly, as before.

  2. Publish it:

         python3 ~/openhamshack-nb/tools/source-site.py publish-own <project> <tarball> \
             --licence GPL-3.0-or-later --carried "DATV 1.4: every package of it" \
             --covers "OpenHamShack DATV 1.4 itself, release commit <sha>" \
             --title "OpenHamShack DATV" --home https://openhamshack.brian-henderson.co.uk/

     It copies the tarball into files/, adds an "@own" line at the top of
     your manifest (creating the manifest if you have none yet), checks
     every file on the site as publish does, and exits non-zero if
     anything is wrong: your release script must then not publish the
     binaries. Publishing the same file again changes nothing; the same
     name with other bytes is refused - a release's source is never
     replaced; a fix is a new version. Own lines are never dropped:
     neither publish-own nor publish (which rewrites only the third-party
     lines) takes one away, and build keeps every file a manifest names.
     To stop offering an old release's source, every binary of that
     release must be gone first; then edit the manifest by hand and run
     build.

     The one exception: a tarball that never left this folder has nobody
     holding it, and can be made again (say, with a scrub list added) and
     put in its place with --replace-unpublished [<public url>]. It is
     refused unless the public site's SHA256SUMS can be read and does not
     list the name, and the file itself is not served there; the replaced
     file goes to the archive and the manifest line keeps its place. Once
     uploaded, never.

The site's copy is the original: url "local" means there is no upstream to
fetch it from again. If it is ever lost or damaged, build fails and says
so; make it again with tarball from the same commit and run publish-own.

To see whether everything your installers need is in place, without
fetching anything:

    python3 ~/openhamshack-nb/tools/source-site.py check <project>          # this folder
    python3 ~/openhamshack-nb/tools/source-site.py check <project> --live   # and the public site

--live compares the public manifest with the local one, finds each file's
line in the public SHA256SUMS and asks for each file's size; use it before
taking anything that relied on the old location away.

A project that stops offering installers altogether:

    python3 ~/openhamshack-nb/tools/source-site.py withdraw <project>

Its manifest goes to the archive, the files only it needed follow, and the
removal list says what to delete on 20i.

Runs are locked against each other, so two sessions publishing at once
take turns. SOURCE_SITE and SOURCE_SITE_ARCHIVE (or --site and --archive)
point the tool elsewhere, for a test.

How OpenHamShack QO-100 NB and HAM do it
----------------------------

Their list is packaging/windows/sources.txt; tools/release.sh [nb|ham]
--windows runs publish with --carried-by NB or HAM before it copies the
installer, refuses if that fails, and runs build afterwards.
Their Mac preview (from 07/10/2026) has a section of its own,
openhamshack-nb-macos and openhamshack-radio-macos: tools/release.sh [nb|ham] --macos
<dmg> --commit <sha> runs publish-own with the scrubbed tree of the commit
the image was built from (openhamshack-nb-0.1.9-mac-preview.1-src.tar.gz), then
publish with packaging/macos/sources.txt as that commit had it, and copies
the image only if both succeed. Separate from the Windows section because
the two sets of third-party code differ, and each must stay as long as
its own download is offered.
tools/release.sh [nb|ham] <version> makes <package>-<version>-src.tar.gz
in the release's build folder right after the release commit, runs
publish-own with it before building any package, and stops there if that
fails. Every earlier release of both was backfilled on 06/10/2026, and
the page's #openhamshack-nb and #openhamshack-radio sections list them all.
HANDOVER.md (internal working notes) and the guides' screenshots (about 28 MB
from 0.1.3 on, rendered from the simulator by ohsnb.ui.screenshots and
ohsradio.ui.screenshots, and read only by the product sites' build) are left
out; .gitattributes says why. packaging/source-scrub.txt replaces the
internal host names, addresses and account names that commits up to NB
0.1.5 and HAM 0.1.6 carried, and stands guard over every later one; the
backfilled tarballs were made again with both on 06/10/2026, before any
had been uploaded.
Until 06/10/2026 each product site had its own source/ folder;
tools/release.sh [nb|ham] --retire-product-source moves it into that
site's archive once the shared site is live (it runs check --live first,
and refuses otherwise), leaving source/index.html as a pointer here for the
installers already out there whose notices give the old address.
