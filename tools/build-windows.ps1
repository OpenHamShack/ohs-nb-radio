<#
.SYNOPSIS
Build openhamshack-nb-<version>-setup.exe or openhamshack-radio-<version>-setup.exe
(and its .sha256) on Windows.

.DESCRIPTION
Run on a Windows 10/11 x64 machine, from a checkout of the repository:

    powershell -ExecutionPolicy Bypass -File tools\build-windows.ps1 [-App nb|ham] [-Work C:\ohsnb-build] [-Ohsdigi <path>\ohsdigi.pyd] [-RtlSdr <path>\rtlsdr.dll] [-NoTests] [-NoSign]

-App picks the program: nb (OpenHamShack QO-100 NB, the default, as the script has
always built) or ham (OpenHamShack Radio). The two differ only in their package,
PyInstaller spec and Inno Setup script (packaging\windows\<package>.*);
the Python, the vendored libraries and the checks are the same, so one -Work
folder can build both, one after the other, and each installer goes into
out\ under its own name.

Everything it downloads or builds goes under -Work (default C:\ohsnb-build):
a private Python (python.org's NuGet package, unpacked, not installed), a
virtualenv, a download cache, PyInstaller's work folders, and out\ with the
installer. Nothing is installed machine-wide and PATH is not touched, so a
developer's own PC is left as it was: delete the folder and it is gone.
Inno Setup, if not already installed, is unpacked into the same folder in
its portable mode.

Version comes from ohsnb\VERSION or ohsradio\VERSION, as the .deb's does. The test suite runs
under the build's own Python first (skip with -NoTests), and the frozen
console .exe is started headless on the simulator before the installer is
made, so a bundle missing a module fails here rather than on someone's PC.

What a Pluto needs is inside the installer too: libiio 0.26's DLLs in the
bundle (_internal\libiio), and ADI's PlutoSDR USB driver installer, which
the setup program runs as an option (packaging\windows\pluto-drivers.iss).
Radio's carries librtlsdr for an RTL-SDR (_internal\rtlsdr), cross-built
on Linux by tools/build-rtlsdr-windows.sh and passed as -RtlSdr. Neither
carries SDRplay's API, which is the operator's own install, ever.
The Country column's cty.dat is ohscore's own (ohscore\data, from the
repository). The licences for all of these are in
packaging\windows\THIRD-PARTY.txt. WSJT-X is not carried (since
17/10/2026; until then jt9, ft8code and their DLLs were, in
_internal\wsjtx, as ohsdigi's fallback and shadow): ohsdigi decodes and
encodes, and a WSJT-X the operator installs is still found.

FT8 and FT4 are encoded by ohsdigi, our own Rust encoder (rust\ohsdigi),
which is not built here: tools/build-ohsdigi.sh cross-builds ohsdigi.pyd on
Linux, and release.sh builds it from the release commit and says where it
put it. Copy that file (and the SHA256SUMS beside it) to this machine and
name it with -Ohsdigi, or leave it at -Work\ohsdigi\ohsdigi.pyd. The build
refuses to run without it: it is the only decoder and encoder the
installer carries, so without it there would be no digital modes at all.

Everything of ours in the installer, and the installer and its uninstaller,
is Authenticode-signed as 360 Technology through Azure Artifact Signing
(packaging\windows\sign.ps1 says how, where the credential lives and how
to rotate it): the two .exes and ohsdigi.pyd before Inno Setup packs them,
the uninstaller and setup.exe by Inno Setup's own SignTool, and every
signature is checked (signer, chain, timestamp) before the .sha256 is
written. Third-party binaries keep their own publishers' signatures, or
none. A build that cannot sign fails; -NoSign makes an unsigned build for
local testing, and says so loudly.

Every download that ends up inside the installer is pinned by SHA-256: a
changed upstream file stops the build instead of shipping. Windows
PowerShell 5.1 compatible (no ?? and no -NoNewline): that is what a fresh
Windows has.
#>
param(
    [ValidateSet("nb", "ham")]
    [string]$App = "nb",
    [string]$Work = "C:\ohsnb-build",
    [string]$Ohsdigi = "",
    # Radio only: rtlsdr.dll from tools/build-rtlsdr-windows.sh (default
    # <Work>\rtlsdr\rtlsdr.dll), its SHA256SUMS beside it.
    [string]$RtlSdr = "",
    [switch]$NoTests,
    # An unsigned build, for trying something locally. Never for release:
    # tools/release.sh --windows refuses an installer that is not signed.
    [switch]$NoSign
)

$ErrorActionPreference = "Stop"
# Invoke-WebRequest in 5.1 is tens of times slower while drawing its progress bar.
$ProgressPreference = "SilentlyContinue"
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12

$Repo = Split-Path -Parent $PSScriptRoot
# Everything that differs between the two programs. Env is each one's
# environment-variable prefix ($OHS_NB_CONF / $OHS_RADIO_CONF), used to keep the
# smoke test off a developer's real settings. Ft8Conf/Ft8Args put each
# simulator on a dial where it plays FT8 (NB: 10489.540; HAM: 20 m), for
# the FT8 smoke test.
$Apps = @{
    nb  = @{ Pkg = "openhamshack-nb";    PyDir = "ohsnb";  Env = "OHS_NB"
             Ft8Conf = '{"mode": "ft8", "vfo": 10489540000.0}'; Ft8Args = @() }
    ham = @{ Pkg = "openhamshack-radio"; PyDir = "ohsradio"; Env = "OHS_RADIO"
             Ft8Conf = '{}'; Ft8Args = @("--band", "20m", "--mode", "ft8") }
}
$Pkg = $Apps[$App].Pkg
$Version = (Get-Content (Join-Path $Repo "$($Apps[$App].PyDir)\VERSION") -Raw).Trim()
$Cache = Join-Path $Work "cache"
$Vendor = Join-Path $Work "vendor"
$Out = Join-Path $Work "out"
New-Item -ItemType Directory -Force -Path $Work, $Cache, $Vendor, $Out | Out-Null

$Pins = @{
    # Python 3.13, the full interpreter as a zip (tools\ inside): venv and pip
    # work, nothing is registered with Windows.
    python   = @{ url  = "https://api.nuget.org/v3-flatcontainer/python/3.13.16/python.3.13.16.nupkg"
                  file = "python.3.13.16.zip"
                  sha  = "95fad176338f1d6a799e45946488063f4aa61764e6cff2f132ddeffbf7a04c34" }
    # The last FreeDV-GUI release that ships codec2 as a DLL (2.x links it in).
    freedv   = @{ url  = "https://github.com/drowe67/freedv-gui/releases/download/v1.9.9.2/FreeDV-1.9.9.2-windows-x86_64.exe"
                  file = "FreeDV-1.9.9.2-windows-x86_64.exe"
                  sha  = "d7f9b2a11248ea83c2e51c5525c7729b913dd0a430f68d1db12a6eafdf5b6995" }
    # ADI's libiio 0.26 Windows binaries: the pure-Python iio.py, and
    # libiio.dll with the DLLs it links against, all shipped unmodified.
    # 0.26, not 1.0: the program is written against the 0.2x interface.
    libiio   = @{ url  = "https://github.com/analogdevicesinc/libiio/releases/download/v0.26/Windows.zip"
                  file = "libiio-0.26-Windows.zip"
                  sha  = "4ad4a8c6b3f7145922c122dcfc51d693f0d3f9a0054fb2228814ce58c538a6ca" }
    # ADI's PlutoSDR/M2k USB driver package (an Inno Setup installer around
    # DPInst and four signed INFs). Shipped unmodified inside our installer,
    # which runs it, elevated, only when the drivers are not already in the
    # driver store (packaging\windows\pluto-drivers.iss). v0.9 is the newest
    # release (2022) and the one the guides have always named.
    plutodrivers = @{ url = "https://github.com/analogdevicesinc/plutosdr-m2k-drivers-win/releases/download/v0.9/PlutoSDR-M2k-USB-Drivers.exe"
                  file = "PlutoSDR-M2k-USB-Drivers-0.9.exe"
                  sha  = "c53dac79be6af8e268b2b5460856d46501f3a61c7b820cbfc3fe24288960550d" }
    # The licence of each of those, from the exact tag the binaries were
    # built from, for the licences\ folder (packaging\windows\THIRD-PARTY.txt
    # says which is which). libxml2 2.9.12 and libusb 1.0.24 are the versions
    # the DLLs in ADI's zip report; libserialport is 0.1.1.
    libiio_copying = @{ url = "https://raw.githubusercontent.com/analogdevicesinc/libiio/v0.26/COPYING.txt"
                  file = "libiio-COPYING.txt"
                  sha  = "102900208eef27b766380135906d431dba87edaa7ec6aa72e6ebd3dd67f3a97b" }
    libusb_copying = @{ url = "https://raw.githubusercontent.com/libusb/libusb/v1.0.24/COPYING"
                  file = "libusb-COPYING"
                  sha  = "5df07007198989c622f5d41de8d703e7bef3d0e79d62e24332ee739a452af62a" }
    libserialport_copying = @{ url = "https://raw.githubusercontent.com/sigrokproject/libserialport/libserialport-0.1.1/COPYING"
                  file = "libserialport-COPYING"
                  sha  = "da7eabb7bafdf7d3ae5e9f223aa5bdc1eece45ac569dc21b3b037520b4464768" }
    # pySerial 3.5's wheel carries no licence text, unlike the other
    # packages the specs collect theirs from (bundle_licences.py), so its
    # BSD text comes from the v3.5 tag.
    pyserial_license = @{ url = "https://raw.githubusercontent.com/pyserial/pyserial/v3.5/LICENSE.txt"
                  file = "pyserial-LICENSE.txt"
                  sha  = "f91cb9813de6a5b142b8f7f2dede630b5134160aedaeaf55f4d6a7e2593ca3f3" }
    libxml2_copyright = @{ url = "https://raw.githubusercontent.com/GNOME/libxml2/v2.9.12/Copyright"
                  file = "libxml2-Copyright"
                  sha  = "c5c63674f8a83c4d2e385d96d1c670a03cb871ba2927755467017317878574bd" }
    plutodrivers_license = @{ url = "https://raw.githubusercontent.com/analogdevicesinc/plutosdr-m2k-drivers-win/v0.9/LICENSE"
                  file = "plutosdr-m2k-drivers-LICENSE"
                  sha  = "a914058ac8f4eb858e93c0050d29f1a95bb7a7abe6e3f4d4d1189b46daa7d888" }
    # 7-Zip, unpacked with msiexec /a (an administrative image: files only,
    # nothing installed), to open FreeDV's NSIS installer.
    sevenzip = @{ url  = "https://www.7-zip.org/a/7z2301-x64.msi"
                  file = "7z2301-x64.msi"
                  sha  = "0ba639b6dacdf573d847c911bd147c6384381a54dac082b1e8c77bc73d58958b" }
    # Licence texts for what the MinGW-w64 toolchain links into ohsdigi.pyd
    # (THIRD-PARTY.txt, ohsdigi): the GCC runtime exception (libgcc) and
    # mingw-w64 winpthreads' MIT-style notice for its start-up code. (Until
    # 17/10/2026 these also covered WSJT-X's DLLs, with libquadmath's,
    # FFTW's and Qt 5's texts beside them.)
    gcc_runtime = @{ url = "https://raw.githubusercontent.com/gcc-mirror/gcc/releases/gcc-13.2.0/COPYING.RUNTIME"
                  file = "gcc-COPYING.RUNTIME"
                  sha  = "9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74" }
    winpthreads_copying = @{ url = "https://raw.githubusercontent.com/mingw-w64/mingw-w64/v11.0.1/mingw-w64-libraries/winpthreads/COPYING"
                  file = "winpthreads-COPYING"
                  sha  = "63263614cdd29f2f93cba85e992f041b31f9fc7b4033692f31269489a8a1b177" }
    innosetup = @{ url = "https://github.com/jrsoftware/issrc/releases/download/is-6_7_3/innosetup-6.7.3.exe"
                  file = "innosetup-6.7.3.exe"
                  sha  = "9c73c3bae7ed48d44112a0f48e66742c00090bdb5bef71d9d3c056c66e97b732" }
    # The licence of Radio's rtlsdr.dll (built from the RTL-SDR Blog's v1.3.6
    # source by tools/build-rtlsdr-windows.sh; below), from that tag.
    rtlsdr_copying = @{ url = "https://raw.githubusercontent.com/rtlsdrblog/rtl-sdr-blog/v1.3.6/COPYING"
                  file = "rtl-sdr-COPYING"
                  sha  = "ab15fd526bd8dd18a9e77ebc139656bf4d33e97fc7238cd11bf60e2b9b8666c6" }
    codec2_copying = @{ url = "https://raw.githubusercontent.com/drowe67/codec2/1.2.0/COPYING"
                  file = "codec2-COPYING"
                  sha  = "9ebb6f82b7380a62ac74c5f0322c88e6744dedf2ebe1f54d6f088282b39844bf" }
    lpcnet_copying = @{ url = "https://raw.githubusercontent.com/drowe67/LPCNet/master/COPYING"
                  file = "lpcnet-COPYING"
                  sha  = "4463ce6b7229bd39dcded6169b17b7f3736fce4af72e90f7e5166beb482134ad" }
    # Signing tools (packaging\windows\sign.ps1), used on this machine and
    # never shipped. signtool.exe from Microsoft's Windows SDK build tools
    # NuGet package (a zip: unpacked, not installed). Microsoft's Artifact
    # Signing docs want a recent one and name the 20348 SDK as not working;
    # 10.0.28000 signed on the Windows build machine (06/10/2026), and so did 10.0.26100.
    signtool = @{ url  = "https://api.nuget.org/v3-flatcontainer/microsoft.windows.sdk.buildtools/10.0.28000.2705/microsoft.windows.sdk.buildtools.10.0.28000.2705.nupkg"
                  file = "microsoft.windows.sdk.buildtools.10.0.28000.2705.zip"
                  sha  = "8bfdfb6ca2633f531cf80b5fa22512ba61a394d7988f0970db83baadc67929ed" }
    # Microsoft's Artifact Signing plugin for signtool (the "dlib"), which
    # was Microsoft.Trusted.Signing.Client until the service was renamed.
    # It carries its own VC++ runtime DLLs.
    signclient = @{ url = "https://api.nuget.org/v3-flatcontainer/microsoft.artifactsigning.client/1.0.128/microsoft.artifactsigning.client.1.0.128.nupkg"
                  file = "microsoft.artifactsigning.client.1.0.128.zip"
                  sha  = "74bd7d27e6ce1051409c38d9b46bc8df0400ecd643d51ffbf2ac00869061e40b" }
    # The .NET runtime the dlib is written for (its runtimeconfig asks for
    # 8.0, rolling forward to a newer major if that is all there is). The
    # zip, unpacked under -Work and found through DOTNET_ROOT, rather than
    # Microsoft's installer: nothing machine-wide, as for everything else.
    dotnet8 = @{ url  = "https://builds.dotnet.microsoft.com/dotnet/Runtime/8.0.31/dotnet-runtime-8.0.31-win-x64.zip"
                  file = "dotnet-runtime-8.0.31-win-x64.zip"
                  sha  = "7deabbefdc83e378b343c551fe447b86002680eea91355b1f6f81d0c9ab0dcaa" }
}

function Step([string]$what) { Write-Host ""; Write-Host "== $what" }

function Fetch([string]$name) {
    $p = $Pins[$name]
    $dest = Join-Path $Cache $p.file
    if (Test-Path $dest) {
        if ((Get-FileHash $dest -Algorithm SHA256).Hash -eq $p.sha.ToUpper()) { return $dest }
        Remove-Item $dest
    }
    Write-Host "   fetching $($p.url)"
    # A plain tool's user agent: SourceForge answers PowerShell's default
    # one, which names Windows, with its "your download will start" HTML
    # page instead of the file (the SHA check below caught it).
    Invoke-WebRequest -Uri $p.url -OutFile $dest -UseBasicParsing -UserAgent "Wget/1.21"
    $got = (Get-FileHash $dest -Algorithm SHA256).Hash
    if ($got -ne $p.sha.ToUpper()) {
        Remove-Item $dest
        throw "$($p.file): SHA-256 $got, expected $($p.sha). Upstream changed the file; check it and update the pin."
    }
    return $dest
}

function Run([string]$exe) {
    # Native commands do not throw in 5.1; their exit code is the only signal.
    & $exe @args
    if ($LASTEXITCODE -ne 0) { throw "$exe $args exited $LASTEXITCODE" }
}

# ---------------------------------------------------------------- signing tools
# First, before anything slow: a build that is going to fail for want of a
# credential should say so in seconds, not after the test suite.
$SignCfg = $null
$SignTool = $null
if ($NoSign) {
    Step "Signing: OFF (-NoSign). This build is UNSIGNED and must not be released."
} else {
    Step "Signing tools: signtool, the Artifact Signing dlib, .NET 8"
    # OPENHAMSHACK_SIGNING_ACCOUNT is the Artifact Signing account's name, for
    # metadata.json below. It was a literal there until the source was
    # published: not a secret, but an internal resource's name, so it now
    # sits beside the credential in the build account's environment and is
    # checked with it - missing, the build fails here in seconds rather
    # than at its first signature (sign.ps1, "The account").
    foreach ($n in @("AZURE_TENANT_ID", "AZURE_CLIENT_ID", "AZURE_CLIENT_SECRET", "OPENHAMSHACK_SIGNING_ACCOUNT")) {
        # Present or not, never the value.
        if (-not [Environment]::GetEnvironmentVariable($n, "User")) {
            throw "$n is not set for this account, so nothing can be signed (packaging\windows\sign.ps1 says what it is). " +
                  "Use -NoSign for an unsigned local test build."
        }
    }
    $SignDir = Join-Path $Work "signing"
    foreach ($t in @(@("signtool", "sdk-buildtools"), @("signclient", "artifactsigning-client"), @("dotnet8", "dotnet"))) {
        $dest = Join-Path $SignDir $t[1]
        # Unpacked once per pin: a stamp names the zip it came from, so a
        # new pin replaces the folder rather than mixing with it.
        $stamp = Join-Path $dest ".from-$($Pins[$t[0]].file)"
        if (-not (Test-Path $stamp)) {
            if (Test-Path $dest) { Remove-Item -Recurse -Force $dest }
            Expand-Archive -Path (Fetch $t[0]) -DestinationPath $dest -Force
            Set-Content -Path $stamp -Value $Pins[$t[0]].sha
        }
    }
    $SignTool = Get-ChildItem (Join-Path $SignDir "sdk-buildtools\bin\*\x64\signtool.exe") | Select-Object -First 1 -ExpandProperty FullName
    $Dlib = Join-Path $SignDir "artifactsigning-client\bin\x64\Azure.CodeSigning.Dlib.dll"
    if (-not $SignTool -or -not (Test-Path $Dlib)) { throw "signtool.exe or Azure.CodeSigning.Dlib.dll is not where the packages put them" }
    # The account and profile, for the dlib. Only the environment's client
    # secret may sign: every other credential DefaultAzureCredential would
    # try is off, so a build never opens a browser or signs with whoever
    # happens to be logged in to the Azure CLI.
    $meta = [ordered]@{
        Endpoint = "https://weu.codesigning.azure.net/"
        CodeSigningAccountName = [Environment]::GetEnvironmentVariable("OPENHAMSHACK_SIGNING_ACCOUNT", "User")
        CertificateProfileName = "Default"
        CorrelationId = "$Pkg-$Version"
        ExcludeCredentials = @("ManagedIdentityCredential", "WorkloadIdentityCredential", "SharedTokenCacheCredential",
                               "VisualStudioCredential", "VisualStudioCodeCredential", "AzureCliCredential",
                               "AzurePowerShellCredential", "AzureDeveloperCliCredential", "InteractiveBrowserCredential")
    }
    $Metadata = Join-Path $SignDir "metadata.json"
    [IO.File]::WriteAllText($Metadata, ($meta | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    $SignCfg = Join-Path $SignDir "signing.json"
    $cfg = [ordered]@{ SignTool = $SignTool; Dlib = $Dlib; Metadata = $Metadata
                       DotnetRoot = (Join-Path $SignDir "dotnet"); TimestampUrl = "http://timestamp.acs.microsoft.com" }
    [IO.File]::WriteAllText($SignCfg, ($cfg | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    Write-Host "   $SignTool"
    Write-Host "   $Dlib"
}
$SignPs1 = Join-Path $Repo "packaging\windows\sign.ps1"

function Sign([string[]]$paths) {
    # In a powershell of its own: sign.ps1 ends with exit, and it is what
    # Inno Setup runs too, so both callers use it the same way.
    & powershell.exe -NoProfile -ExecutionPolicy Bypass -File $SignPs1 -Config $SignCfg @paths
    if ($LASTEXITCODE -ne 0) { throw "signing $($paths -join ', ') failed; not building an unsigned installer" }
}

function AssertSigned([string]$path) {
    # Signed by 360 Technology, chaining to a root Windows trusts (/pa, the
    # Authenticode policy a user's PC applies), and timestamped: the
    # certificate lives three days, and only the timestamp keeps the
    # signature valid after that. Each is checked, and the lines that show
    # it are printed for the build log.
    $out = (cmd /c "`"$SignTool`" verify /pa /v `"$path`" 2>&1") | Out-String
    $code = $LASTEXITCODE
    $s = Get-AuthenticodeSignature -LiteralPath $path
    $name = Split-Path -Leaf $path
    if ($code -ne 0 -or $s.Status -ne "Valid") {
        throw "$name does not verify (signtool verify exit $code, Authenticode $($s.Status)):`n$out"
    }
    if ($s.SignerCertificate.Subject -notmatch '(^|, )O=360 Technology(,|$)' -or $out -notmatch "Issued to: 360 Technology") {
        throw "$name is signed, but not by 360 Technology ($($s.SignerCertificate.Subject))"
    }
    if (-not $s.TimeStamperCertificate -or $out -notmatch "The signature is timestamped: (.+)") {
        throw "$name is signed without a timestamp; it would stop verifying when the 3-day certificate expires"
    }
    $when = $Matches[1].Trim()
    Write-Host "   $name : $($s.Status), signer $($s.SignerCertificate.Subject)"
    Write-Host "      issued by $($s.SignerCertificate.Issuer)"
    Write-Host "      timestamped $when by $($s.TimeStamperCertificate.Subject)"
}

# ---------------------------------------------------------------- Python
Step "Python"
$PyHome = Join-Path $Work "python"
$Py = Join-Path $PyHome "tools\python.exe"
if (-not (Test-Path $Py)) {
    $zip = Fetch "python"
    Expand-Archive -Path $zip -DestinationPath $PyHome -Force
}
$Venv = Join-Path $Work "venv"
$VPy = Join-Path $Venv "Scripts\python.exe"
if (-not (Test-Path $VPy)) { Run $Py -m venv $Venv }
Run $VPy -m pip install --disable-pip-version-check --quiet -r (Join-Path $Repo "packaging\windows\requirements.txt")
Run $VPy -c "import sys, numpy, PyQt6.QtCore, pyaudio, serial, cryptography, hid, PIL; print('   python', sys.version.split()[0], 'numpy', numpy.__version__, 'Qt', PyQt6.QtCore.QT_VERSION_STR, 'cryptography', cryptography.__version__, 'hidapi', hid.version_str(), 'Pillow', PIL.__version__)"

# ---------------------------------------------------------------- libiio
Step "libiio 0.26: Python bindings and DLLs"
$PyDir = Join-Path $Vendor "py"
$IioDir = Join-Path $Vendor "libiio"
# libiio.dll and exactly what it imports beyond Windows itself (read from
# its import table): libxml2 for the XML context description, libusb-1.0
# for usb: URIs, libserialport for serial: ones. The VS-2022 build, as the
# bindings are; its other import, vcruntime140.dll, is Python's own and is
# already in the bundle and in the process, so ADI's copy is not taken.
# Shipped in a folder of their own rather than beside the .exe, so the
# bundle's libusb and libxml2 can never be picked up by anything else that
# searches the program's folder, and host.bundled_libiio() can name the
# folder precisely.
$IioDlls = @("libiio.dll", "libxml2.dll", "libusb-1.0.dll", "libserialport-0.dll")
if (-not (Test-Path (Join-Path $PyDir "iio.py")) -or -not (Test-Path (Join-Path $IioDir "libiio.dll"))) {
    $zip = Fetch "libiio"
    $tmp = Join-Path $Work "tmp-libiio"
    if (Test-Path $tmp) { Remove-Item -Recurse -Force $tmp }
    Expand-Archive -Path $zip -DestinationPath $tmp -Force
    $vs = Join-Path $tmp "Windows-VS-2022-x64"
    $tgz = Join-Path $vs "libiio-py39-amd64.tar.gz"
    # Not pip-installed: its setup.py refuses to install where libiio.dll is
    # not already on the system. iio.py is the whole binding; it finds the
    # DLL itself at run time (host.bundled_libiio() steers it to ours).
    Run tar -xzf $tgz -C $tmp
    New-Item -ItemType Directory -Force -Path $PyDir, $IioDir | Out-Null
    Copy-Item (Join-Path $tmp "pylibiio-0.26\iio.py") $PyDir
    foreach ($dll in $IioDlls) { Copy-Item (Join-Path $vs $dll) $IioDir }
    Remove-Item -Recurse -Force $tmp
}
# The set must load on its own and be the 0.26 the bindings speak: loaded
# by full path from $IioDir, as the frozen program will, with $IioDir first
# on PATH the way host.bundled_libiio() puts it. A DLL left out of
# $IioDlls fails here, not on a user's PC - unless the build machine has a
# copy in System32 (ADI's libiio installer leaves one), which is why the
# frozen smoke test below also counts and why a clean machine is the real
# proof (docs/INSTALL.md).
$oldPath = $env:PATH
$env:PATH = "$IioDir;$env:PATH"
try {
    Run $VPy -c "import sys; sys.path.insert(0, sys.argv[1]); import iio, os; d = os.path.dirname(iio._lib._name); print('   libiio', '.'.join(map(str, iio.version[:2])), iio.version[2], 'from', d); assert iio.version[:2] == (0, 26), iio.version; assert os.path.samefile(d, sys.argv[2]), d" $PyDir $IioDir
} finally { $env:PATH = $oldPath }

$Lic = Join-Path $Vendor "licences"
New-Item -ItemType Directory -Force -Path $Lic | Out-Null
foreach ($l in @("libiio_copying", "libusb_copying", "libserialport_copying", "libxml2_copyright", "plutodrivers_license", "pyserial_license")) {
    Copy-Item (Fetch $l) (Join-Path $Lic $Pins[$l].file)
}

# ---------------------------------------------------------------- PlutoSDR USB drivers
Step "PlutoSDR USB drivers (ADI v0.9, run by the installer)"
# Not unpacked or changed: the installer carries ADI's own setup .exe and
# runs it. Its path goes to ISCC as /DPlutoDrivers.
$PlutoDrivers = Fetch "plutodrivers"
Write-Host "   $PlutoDrivers"

# ---------------------------------------------------------------- codec2
function SevenZip {
    # 7-Zip opens the NSIS installer FreeDV ships as; unpacked on
    # first use only, so a work folder seeded with vendor\ never needs it.
    $SevenDir = Join-Path $Work "7zip"
    $seven = Join-Path $SevenDir "Files\7-Zip\7z.exe"
    if (-not (Test-Path $seven)) {
        $msi = Fetch "sevenzip"
        $p = Start-Process msiexec.exe -ArgumentList "/a `"$msi`" /qn TARGETDIR=`"$SevenDir`"" -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "msiexec /a 7-Zip exited $($p.ExitCode)" }
    }
    return $seven
}

Step "libcodec2 from FreeDV-GUI 1.9.9.2"
$C2 = Join-Path $Vendor "codec2"
if (-not (Test-Path (Join-Path $C2 "libcodec2.dll"))) {
    $Seven = SevenZip
    $fdv = Fetch "freedv"
    New-Item -ItemType Directory -Force -Path $C2 | Out-Null
    # 7-Zip prints "Headers Error" for this NSIS installer and still exits 0
    # with both files intact (their hashes match a Linux 7z extraction).
    Run $Seven e -y "-o$C2" $fdv "bin\libcodec2.dll" "bin\liblpcnetfreedv.dll"
}
Copy-Item (Fetch "codec2_copying") (Join-Path $Lic "codec2-COPYING")
Copy-Item (Fetch "lpcnet_copying") (Join-Path $Lic "lpcnet-COPYING")

# ---------------------------------------------------------------- librtlsdr
if ($App -eq "ham") {
    Step "librtlsdr, cross-built on Linux"
    # Radio's RTL-SDR receiver (shack_sdr.sources.rtlsdr, over ctypes).
    # Built from the RTL-SDR Blog's v1.3.6 source with libusb 1.0.26 linked
    # in, against the UCRT (tools/build-rtlsdr-windows.sh), not taken from
    # their Release.zip, whose DLL needs the VC++ 2010 runtime (no security
    # updates for years). Not built here, as ohsdigi.pyd is not: the
    # cross toolchain is Linux's. The dongle also needs the WinUSB driver in
    # place of Windows' own DVB-T one, once (Zadig); nothing here installs a
    # driver.
    if (-not $RtlSdr) { $RtlSdr = Join-Path $Work "rtlsdr\rtlsdr.dll" }
    if (-not (Test-Path $RtlSdr)) {
        throw "no rtlsdr.dll at $RtlSdr. Build it on Linux from this same commit (tools/build-rtlsdr-windows.sh), " +
              "copy it here with its SHA256SUMS and pass -RtlSdr. Without it Radio cannot open an RTL-SDR."
    }
    $sums = Join-Path (Split-Path -Parent $RtlSdr) "SHA256SUMS"
    if (Test-Path $sums) {
        $want = (Get-Content $sums | Where-Object { $_ -match "\srtlsdr\.dll$" } | Select-Object -First 1) -split "\s+" | Select-Object -First 1
        $got = (Get-FileHash $RtlSdr -Algorithm SHA256).Hash.ToLower()
        if ($want -ne $got) { throw "$RtlSdr does not match its SHA256SUMS (got $got, expected $want): damaged on the way here?" }
        Write-Host "   SHA-256 $got matches SHA256SUMS"
    } else {
        Write-Host "   (no SHA256SUMS beside it to check against)"
    }
    $Rtl = Join-Path $Vendor "rtlsdr"
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue $Rtl     # an older build's Release.zip copy, msvcr100.dll with it
    New-Item -ItemType Directory -Force -Path $Rtl | Out-Null
    Copy-Item $RtlSdr (Join-Path $Rtl "rtlsdr.dll")
    Copy-Item (Fetch "rtlsdr_copying") (Join-Path $Lic "rtl-sdr-COPYING")
    # Loaded by full path from its own folder, as the frozen program will:
    # the binding's own probe (no dongle needed) must find every function.
    Push-Location $Repo
    try {
        Run $VPy -c "import sys; from ohscore import shacklibs; shacklibs.sdr(); from shack_sdr.sources import rtlsdr; a = rtlsdr.availability(search=[sys.argv[1]]); print('   librtlsdr', a); assert a['available'], a" $Rtl
    } finally { Pop-Location }
}

# ---------------------------------------------------------------- licence texts
Step "Licence texts: cty.dat's notice, the GCC runtime's and winpthreads'"
# Under the name in licences\ that WSJT-X's copy of it had; the file itself
# is ohscore\data's, which the spec collects. A work folder from a build
# before 17/10/2026 still has WSJT-X's tools and licence texts: none of it
# may reach the installer.
Copy-Item (Join-Path $Repo "ohscore\data\cty.dat-copyright.txt") (Join-Path $Lic "cty.dat-copyright.txt")
Remove-Item -Recurse -Force -ErrorAction SilentlyContinue (Join-Path $Vendor "wsjtx")
foreach ($f in @("wsjtx-COPYING", "libquadmath-COPYING.LIB", "fftw-COPYING", "qt5-LICENSE.LGPL3")) {
    Remove-Item -Force -ErrorAction SilentlyContinue (Join-Path $Lic $f)
}
foreach ($l in @("gcc_runtime", "winpthreads_copying")) {
    Copy-Item (Fetch $l) (Join-Path $Lic $Pins[$l].file)
}

# ---------------------------------------------------------------- ohsdigi
Step "ohsdigi: the FT8/FT4 encoder, cross-built on Linux"
if (-not $Ohsdigi) { $Ohsdigi = Join-Path $Work "ohsdigi\ohsdigi.pyd" }
if (-not (Test-Path $Ohsdigi)) {
    throw "no ohsdigi.pyd at $Ohsdigi. Build it on Linux from this same commit (tools/build-ohsdigi.sh windows-amd64, " +
          "or the one release.sh made), copy it here with its SHA256SUMS and pass -Ohsdigi. Without it FT4 cannot be sent."
}
$sums = Join-Path (Split-Path -Parent $Ohsdigi) "SHA256SUMS"
if (Test-Path $sums) {
    $want = (Get-Content $sums | Where-Object { $_ -match "\sohsdigi\.pyd$" } | Select-Object -First 1) -split "\s+" | Select-Object -First 1
    $got = (Get-FileHash $Ohsdigi -Algorithm SHA256).Hash.ToLower()
    if ($want -ne $got) { throw "$Ohsdigi does not match its SHA256SUMS (got $got, expected $want): damaged on the way here?" }
    Write-Host "   SHA-256 $got matches SHA256SUMS"
} else {
    Write-Host "   (no SHA256SUMS beside it to check against)"
}
# Into the source tree as ohscore\ohsdigi.pyd, where a run from source on
# Windows imports it, the test suite below exercises it, and PyInstaller
# collects it as the extension module ohscore.ohsdigi (the specs name it).
Copy-Item $Ohsdigi (Join-Path $Repo "ohscore\ohsdigi.pyd") -Force
Copy-Item (Join-Path $Repo "rust\ohsdigi\LICENSE-THIRD-PARTY") (Join-Path $Lic "ohsdigi-LICENSE-THIRD-PARTY.txt")
# It must load into this Python and encode FT4 exactly as WSJT-X's ft4code
# would (the symbols of WSJT-X's own example, from ft4code on Linux).
Push-Location $Repo
try {
    Run $VPy -c "from ohscore import ohsdigi; e = ohsdigi.encode('ft4', 'CQ G4XYZ IO91'); assert ''.join(map(str, e.tones)) == '0132103311233031311022300030202121023133023323031212322012213001002310012202210103011011112103311313201', e.tones; print('   ohsdigi', ohsdigi.__version__, 'loads and encodes FT4 here')"
} finally { Pop-Location }

# ---------------------------------------------------------------- Inno Setup
Step "Inno Setup"
$Iscc = $null
foreach ($c in @("${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe",
                 "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", (Join-Path $Work "innosetup\ISCC.exe"))) {
    if ($c -and (Test-Path $c)) { $Iscc = $c; break }
}
if (-not $Iscc) {
    # /PORTABLE=1: files only - no uninstaller, no registry, no Start menu.
    $is = Fetch "innosetup"
    $dir = Join-Path $Work "innosetup"
    $p = Start-Process $is -ArgumentList "/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /CURRENTUSER /PORTABLE=1 /DIR=`"$dir`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "Inno Setup unpack exited $($p.ExitCode)" }
    $Iscc = Join-Path $dir "ISCC.exe"
}
Write-Host "   $Iscc"

# ---------------------------------------------------------------- icon
Step "Icon"
$Ico = Join-Path $Vendor "$Pkg.ico"
Run $VPy (Join-Path $Repo "tools\make-ico.py") --app $App $Ico

# ---------------------------------------------------------------- tests
if (-not $NoTests) {
    Step "Test suite under Windows Python"
    # The FreeDV tests run against the codec2 DLLs being shipped, found the
    # way a source run on Windows finds a library: on PATH.
    $oldPath = $env:PATH
    $env:PATH = "$C2;$env:PATH"
    Push-Location $Repo
    try { Run $VPy -m unittest discover -s tests } finally { Pop-Location; $env:PATH = $oldPath }
}

# ---------------------------------------------------------------- freeze
Step "PyInstaller"
$env:OHSNB_VENDOR = $Vendor
$env:OHSNB_ICO = $Ico
$Dist = Join-Path $Work "dist"
Run $VPy -m PyInstaller --noconfirm --log-level WARN --distpath $Dist --workpath (Join-Path $Work "pyi-work") (Join-Path $Repo "packaging\windows\$Pkg.spec")
$Bundle = Join-Path $Dist $Pkg

Step "No Qt PDF in the bundle"
# The specs take Qt6Pdf.dll and the qpdf image-format plugin out
# (packaging\windows\bundle_prune.py says why): neither program uses them,
# and carrying them obliges us to host Qt WebEngine's 580 MB source beside
# the installer. A PyInstaller or PyQt6 upgrade could bring them back by
# another route without any error, so look at what was actually collected.
$pdf = @(Get-ChildItem -Path $Bundle -Recurse -File | Where-Object { $_.Name -like "Qt6Pdf*.dll" -or $_.Name -ieq "qpdf.dll" })
if ($pdf.Count -gt 0) {
    throw "Qt PDF is in the bundle again ($(($pdf | ForEach-Object { $_.FullName }) -join ', ')); " +
          "packaging\windows\bundle_prune.py no longer catches it - fix that, or its source must be published (sources.txt)"
}
Write-Host "   neither Qt6Pdf*.dll nor qpdf.dll in $Bundle"

Step "Nothing encumbered in the bundle"
# No AAC or AMBE codec and no SDRplay API carried, linked or defined by
# anything in the bundle (RADIO-SDR-PLAN 5.5): ohs-libs' own check,
# vendored in tools\vendor\encumbered and hash-checked before it runs.
Run $VPy (Join-Path $Repo "packaging\shack_vendor.py") --check-encumbered $Bundle

Step "ohsdigi in the bundle"
# The spec names ohscore.ohsdigi as a hidden import (ft8.py imports it by
# name at run time, which the analysis cannot follow); check it landed.
$pyd = Join-Path $Bundle "_internal\ohscore\ohsdigi.pyd"
if (-not (Test-Path $pyd)) { throw "ohsdigi.pyd is not in the bundle at $pyd" }
if ((Get-FileHash $pyd).Hash -ne (Get-FileHash $Ohsdigi).Hash) { throw "the bundle's ohsdigi.pyd is not the one given" }
Write-Host "   $pyd"

if (-not $NoSign) {
    Step "Sign our own binaries: $Pkg.exe, $Pkg-console.exe, ohsdigi.pyd (and Radio's rtlsdr.dll)"
    # Before the smoke tests, so the program they run is byte for byte the
    # one that ships (a signature is appended to the file, and PyInstaller's
    # bootloader must still find its archive past it). Only these three: the
    # rest of the bundle is Python's, Qt's, libiio's or codec2's,
    # and keeps whatever signature its publisher gave it. ohsdigi.pyd was
    # checked against SHA256SUMS above; signed, it no longer matches that
    # file, which describes the unsigned build output.
    $ours = @((Join-Path $Bundle "$Pkg.exe"), (Join-Path $Bundle "$Pkg-console.exe"), $pyd)
    # Radio's rtlsdr.dll is our own build too (tools/build-rtlsdr-windows.sh),
    # so it is signed with the rest: Smart App Control and Defender treat an
    # unsigned DLL loaded by a signed program with suspicion.
    $rtlBundled = Join-Path $Bundle "_internal\rtlsdr\rtlsdr.dll"
    if (Test-Path $rtlBundled) { $ours += $rtlBundled }
    Sign $ours
    foreach ($f in $ours) { AssertSigned $f }
}

Step "Smoke test: the frozen console build, headless, on the simulator"
# Its own config and data folders, so a developer's real settings are never
# read or written by the build.
$smoke = Join-Path $Work "smoke"
if (Test-Path $smoke) { Remove-Item -Recurse -Force $smoke }
$EnvConf = "$($Apps[$App].Env)_CONF"
$EnvData = "$($Apps[$App].Env)_DATA"
Set-Item "Env:$EnvConf" (Join-Path $smoke "config.json")
Set-Item "Env:$EnvData" (Join-Path $smoke "data")
try {
    Run (Join-Path $Bundle "$Pkg-console.exe") --headless --device sim --no-audio --seconds 3

    Step "Smoke test: the frozen build loads its own libiio"
    # The Pluto at an address where nothing listens: "No Pluto at" can only
    # be said after libiio.dll loaded and refused the connection, so it
    # proves the bundled DLL set loads in the frozen program; "libiio could
    # not be loaded" or "not the 0.2x series" means it did not. The exit
    # code is not the signal (a radio that will not open is not a crash),
    # and cmd merges stderr so PowerShell 5.1 does not turn it into errors.
    if (Test-Path (Join-Path $smoke "config.json")) { Remove-Item (Join-Path $smoke "config.json") }
    New-Item -ItemType Directory -Force -Path $smoke | Out-Null
    [IO.File]::WriteAllText((Join-Path $smoke "config.json"), '{"device": "pluto", "plutoUri": "ip:127.0.0.1"}', [Text.Encoding]::ASCII)
    $exe = Join-Path $Bundle "$Pkg-console.exe"
    $said = (cmd /c "`"$exe`" --headless --no-audio --seconds 2 2>&1") | Out-String
    Write-Host ($said.Trim() -replace '(?m)^', '   ')
    if ($said -notmatch "No Pluto at ip:127\.0\.0\.1" -or $said -match "could not be loaded|not the 0\.2x series") {
        throw "the frozen build did not reach libiio through its bundled libiio.dll"
    }

    Step "Smoke test: the frozen build encodes FT8 and FT4 with ohsdigi"
    # The start-up facts name the encoder and the file it was loaded from:
    # it must be ohsdigi, from inside the bundle. A frozen build that could
    # not load it would have no FT8 or FT4 at all, unless this machine has
    # a WSJT-X of its own.
    $said = (cmd /c "`"$exe`" --headless --device sim --no-audio --seconds 1 -v 2>&1") | Out-String
    $enc = @($said -split "`n" | Where-Object { $_ -match "ft8/ft4 encoder: " }) | Select-Object -First 1
    if ($enc) { Write-Host "   $($enc.Trim())" }
    if (-not $enc -or $enc -notmatch "ft8/ft4 encoder: ohsdigi " -or $enc -notmatch [regex]::Escape("_internal\ohscore\ohsdigi.pyd")) {
        throw "the frozen build does not encode with its own ohsdigi:`n$said"
    }

    Step "Smoke test: the frozen build can check an update's signature"
    # Self-update trusts nothing until an Ed25519 signature checks
    # (ohscore/update.py), and the check needs cryptography and its cffi
    # module inside the bundle. The start-up facts carry the result of
    # checking RFC 8032's test vector: a bundle that lost either says
    # "unavailable" there, and would otherwise only show it by never
    # offering an update.
    $upd = @($said -split "`n" | Where-Object { $_ -match "update signatures: " }) | Select-Object -First 1
    if ($upd) { Write-Host "   $($upd.Trim())" }
    if (-not $upd -or $upd -notmatch "self-test passed") {
        throw "the frozen build cannot check update signatures:`n$said"
    }

    Step "Smoke test: the frozen build can reach the controller pad"
    # The AKP03E needs hidapi (how Windows reaches a HID device) and Pillow
    # (its key pictures) inside the bundle; until 12/10/2026 the specs
    # excluded Pillow and nothing carried hidapi, so the pad could not work
    # on Windows and nothing said so. The start-up facts name both, and
    # --pad-report must enumerate HID devices through the bundled hidapi
    # (this machine has no pad: "no Ajazz/Mirabox device found" is the
    # healthy answer here).
    $padl = @($said -split "`n" | Where-Object { $_ -match "controller pad: " }) | Select-Object -First 1
    if ($padl) { Write-Host "   $($padl.Trim())" }
    if (-not $padl -or $padl -notmatch "hidapi \d" -or $padl -notmatch "Pillow \d") {
        throw "the frozen build has no hidapi or no Pillow for the controller pad:`n$said"
    }
    $rep = (cmd /c "`"$exe`" --pad-report 2>&1") | Out-String
    $rep.Trim() -split "`n" | Select-Object -First 12 | ForEach-Object { Write-Host "   $($_.TrimEnd())" }
    if ($rep -notmatch "OpenHamShack controller report" -or $rep -notmatch "hidapi: \d" -or $rep -match "could not be loaded") {
        throw "the frozen build's --pad-report did not run through its own hidapi:`n$rep"
    }

    Step "Smoke test: the frozen build reads its own cty.dat"
    # The FT8 Country column's file is ohscore\data\cty.dat inside the
    # bundle (ohscore/dxcc.py), named in the start-up facts. A spec that
    # lost it would fall back to an installed WSJT-X's - on this machine,
    # perhaps, and on a user's PC to no column at all.
    $cty = @($said -split "`n" | Where-Object { $_ -match "cty\.dat: " }) | Select-Object -First 1
    if ($cty) { Write-Host "   $($cty.Trim())" }
    if (-not $cty -or $cty -notmatch [regex]::Escape("_internal\ohscore\data\cty.dat")) {
        throw "the frozen build does not read its own cty.dat:`n$said"
    }

    if ($App -eq "ham") {
        Step "Smoke test: the CW skimmer's worker process"
        # Radio's CW skimmer decodes in a spawned child process, which in a
        # frozen build is this .exe started again: it works only with
        # multiprocessing.freeze_support() in launch-ham.py and shack_cw.skim
        # and cty.dat in the bundle. The self-test decodes a synthetic band
        # in that child and names each station's country.
        $sk = (cmd /c "`"$exe`" --cw-skim-selftest 2>&1") | Out-String
        $sk.Trim() -split "`n" | ForEach-Object { Write-Host "   $($_.TrimEnd())" }
        if ($sk -notmatch "worker process pid" -or $sk -notmatch "cw-skim-selftest: PASS") {
            throw "the frozen build's --cw-skim-selftest did not pass in a worker process:`n$sk"
        }
    }

    Step "Smoke test: the frozen build decodes FT8 with ohsdigi alone"
    # The simulator's FT8 stations are encoded and decoded by ohsdigi: two
    # 15 s slots on a dial with FT8 must print at least one "decode:" line.
    # SHACK_NO_WSJTX hides any WSJT-X this machine has (ohscore/host.py
    # find_tool), so the bundle is tested on its own.
    Remove-Item -Recurse -Force $smoke
    New-Item -ItemType Directory -Force -Path $smoke | Out-Null
    [IO.File]::WriteAllText((Join-Path $smoke "config.json"), $Apps[$App].Ft8Conf, [Text.Encoding]::ASCII)
    $extra = $Apps[$App].Ft8Args -join " "
    $env:SHACK_NO_WSJTX = "1"
    try {
        $said = (cmd /c "`"$exe`" --headless --device sim --no-audio --seconds 40 $extra 2>&1") | Out-String
    } finally { Remove-Item Env:SHACK_NO_WSJTX }
    $decodes = @($said -split "`n" | Where-Object { $_ -match "^decode: .*'mode': 'ft8'" })
    $decodes | Select-Object -First 3 | ForEach-Object { Write-Host "   $($_.Trim())" }
    if ($decodes.Count -lt 1) {
        throw "the frozen build decoded no FT8 in 40 s on the simulator:`n$said"
    }
} finally {
    Remove-Item "Env:$EnvConf", "Env:$EnvData"
}

# ---------------------------------------------------------------- installer
Step "Installer"
$isccArgs = @("/Q", "/DAppVersion=$Version", "/DDistDir=$Bundle", "/DIconFile=$Ico", "/DRepo=$Repo", "/DOutDir=$Out", "/DPlutoDrivers=$PlutoDrivers")
if (-not $NoSign) {
    # Inno Setup signs the uninstaller it generates (before embedding it)
    # and then setup.exe, by running the "ohssign" tool defined here; the
    # .iss turns it on when Sign is defined. $q is Inno's quote and $f the
    # quoted file name, so no quote characters pass through 5.1's argument
    # handling, which mangles them.
    $isccArgs += @("/DSign=1", "/Sohssign=powershell.exe -NoProfile -ExecutionPolicy Bypass -File `$q$SignPs1`$q -Config `$q$SignCfg`$q `$f")
}
$isccArgs += @(Join-Path $Repo "packaging\windows\$Pkg.iss")
Run $Iscc @isccArgs
$Setup = Join-Path $Out "$Pkg-$Version-setup.exe"
if (-not $NoSign) {
    Step "Installer signature"
    AssertSigned $Setup
}
$hash = (Get-FileHash $Setup -Algorithm SHA256).Hash.ToLower()
# Only now, with every signature in place: signing changes the bytes, so a
# hash taken earlier would describe a file nobody downloads.
# The same "<hash>  <name>" line sha256sum writes for the .deb, ASCII and no
# BOM, so `sha256sum -c` and tools/site-build.py read both alike.
[IO.File]::WriteAllText("$Setup.sha256", "$hash  $Pkg-$Version-setup.exe`n", [Text.Encoding]::ASCII)
Write-Host ""
Write-Host "built $Setup"
Write-Host "sha256 $hash"
if ($NoSign) { Write-Host "UNSIGNED (-NoSign): for local testing only; release.sh --windows refuses it" }
else { Write-Host "signed by 360 Technology and timestamped" }
exit 0
