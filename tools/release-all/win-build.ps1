# release-all's Windows build, on the Windows build VM, in the folder
# win-prep.ps1 made: tools/build-windows.ps1 from the release commit's own
# tree, SIGNED (its signing configuration and secret are this machine's
# and are used where they are). -NoTests: the suite already passed once,
# on Linux, for this tree; the build's own smoke tests on the frozen
# program (simulator, libiio, ohsdigi, signature self-test, pad, cty.dat,
# an FT8 decode) still run, and are what caught HAM 0.1.18.
#
#   win-build.ps1 -Root C:/ohsnb-build -App nb|ham -V <version>
param([string]$Root, [string]$App, [string]$V)
$W = Join-Path $Root "$V-$App"
$Pkg = @{nb = "openhamshack-nb"; ham = "openhamshack-radio"}[$App]
Set-Location "$W\repo"
cmd /c "powershell -NoProfile -ExecutionPolicy Bypass -File `"$W\repo\tools\build-windows.ps1`" -App $App -Work `"$W`" -Ohsdigi `"$W\ohsdigi\ohsdigi.pyd`" -NoTests > `"$W\build-$App.log`" 2>&1"
$rc = $LASTEXITCODE
Get-Content "$W\build-$App.log" -Tail 12
$exe = Join-Path $W "out\$Pkg-$V-setup.exe"
if ($rc -eq 0 -and (Test-Path -LiteralPath $exe) -and (Test-Path -LiteralPath "$exe.sha256")) {
    "BUILD PASS $exe"
} else {
    "BUILD FAIL: exit $rc"
    exit 1
}
