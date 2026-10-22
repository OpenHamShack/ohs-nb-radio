# release-all's checks of a built installer, on the Windows build VM: what
# was run by hand as wincheck.ps1 for NB 0.1.19-0.1.22, now ending in a
# verdict. The installer goes in silently, per user, OVER whatever release
# is installed (so the upgrade is what is tested: one Apps & features
# entry, the old folders gone), then the installed console program runs
# headless on the simulator, receive-only - nothing here can transmit,
# and the VM has no radio - and its own read-only reports.
#
#   win-check.ps1 -Root C:/ohsnb-build -App nb|ham -V <version>
param([string]$Root, [string]$App, [string]$V)
$W = Join-Path $Root "$V-$App"
$C = "$W\checks"; New-Item -ItemType Directory -Force -Path $C | Out-Null
$a = @{nb = @{p = "openhamshack-nb"; e = "OHS_NB"}; ham = @{p = "openhamshack-radio"; e = "OHS_RADIO"}}[$App]
$Pkg = $a.p
$bad = @()
function Entries { @(Get-ItemProperty HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\* -ErrorAction SilentlyContinue |
    Where-Object { $_.DisplayName -like "*OpenHamShack*" -or $_.DisplayName -like "OpenHamShack*" }) }
"== Apps & features before"
Entries | Select-Object DisplayName, DisplayVersion | Format-Table -AutoSize | Out-String -Width 200
"== install $App $V"
$p = Start-Process -FilePath "$W\out\$Pkg-$V-setup.exe" -ArgumentList "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CURRENTUSER",
    "/MERGETASKS=""!plutodrivers""", "/LOG=$C\install-$App.log" -Wait -PassThru
"installer exit $($p.ExitCode)"
if ($p.ExitCode -ne 0) { $bad += "installer exit $($p.ExitCode)" }
"== Apps & features after"
$after = Entries
$after | Select-Object DisplayName, DisplayVersion | Format-Table -AutoSize | Out-String -Width 200
$mine = @($after | Where-Object { $_.DisplayVersion -eq $V })
if ($mine.Count -ne 1) { $bad += "Apps & features has $($mine.Count) entries at $V, not one" }
$programs = Join-Path $env:LOCALAPPDATA "Programs"
$I = Get-ChildItem $programs -Directory | Where-Object { Test-Path (Join-Path $_.FullName "$Pkg-console.exe") } | Select-Object -First 1
if (-not $I) { "no installed $Pkg-console.exe under $programs"; "WINCHECK FAIL: not installed"; exit 1 }
"installed in $($I.FullName)"
$signer = (Get-AuthenticodeSignature "$($I.FullName)\$Pkg.exe").SignerCertificate.Subject
"signer $signer"
if ($signer -notmatch "O=360 Technology") { $bad += "the installed $Pkg.exe is not signed by 360 Technology" }

"== headless on the simulator, receive-only, 8 s"
Set-Item "Env:$($a.e)_CONF" "$C\$($App)conf\config.json"; Set-Item "Env:$($a.e)_DATA" "$C\$($App)data"
$o = & "$($I.FullName)\$Pkg-console.exe" --headless --device sim --receive-only --seconds 8 -v 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
"exit $rc"
$o | Select-String -Pattern "Ed25519|Traceback|Error|version|update|receive-only" | Select-Object -First 12 | ForEach-Object { $_.Line }
if ($rc -ne 0) { $bad += "headless run exit $rc" }
if ($o -match "Traceback") { $bad += "headless run printed a Traceback" }
if (-not ($o -match [regex]::Escape($V))) { $bad += "headless run never named version $V" }
Remove-Item "Env:$($a.e)_CONF", "Env:$($a.e)_DATA"

"== --pad-report (no pad attached)"
$o = & "$($I.FullName)\$Pkg-console.exe" --pad-report 2>&1 | ForEach-Object { "$_" }
$rc = $LASTEXITCODE
"exit $rc"; $o | Select-Object -First 8
if ($rc -ne 0) { $bad += "--pad-report exit $rc" }

if ($App -eq "nb") {
    # Read-only: it lists serial ports and asks a radio what it is; it
    # never sets anything, and there is no radio here.
    "== --rig-diagnostic (no radio attached), 180 s limit"
    Set-Item "Env:$($a.e)_CONF" "$C\$($App)conf\config.json"; Set-Item "Env:$($a.e)_DATA" "$C\$($App)data"
    $rp = Start-Process -FilePath "$($I.FullName)\$Pkg-console.exe" -ArgumentList "--rig-diagnostic", "$C\rigdiag.txt" -NoNewWindow -PassThru `
        -RedirectStandardOutput "$C\rigdiag.out" -RedirectStandardError "$C\rigdiag.err"
    if (-not $rp.WaitForExit(180000)) { "rig-diagnostic HUNG; killing"; Stop-Process -Id $rp.Id -Force; $bad += "--rig-diagnostic hung" }
    Remove-Item "Env:$($a.e)_CONF", "Env:$($a.e)_DATA"
    if (-not (Test-Path "$C\rigdiag.txt")) { $bad += "--rig-diagnostic wrote no report" }
    Get-Content "$C\rigdiag.txt" -ErrorAction SilentlyContinue | Select-Object -First 12
}
if ($App -eq "ham") {
    "== --cw-skim-selftest"
    $o = & "$($I.FullName)\$Pkg-console.exe" --cw-skim-selftest 2>&1 | ForEach-Object { "$_" }
    $rc = $LASTEXITCODE
    "exit $rc"; $o | Select-Object -Last 4
    if ($rc -ne 0 -or -not ($o -match "PASS")) { $bad += "--cw-skim-selftest did not pass" }
}
$left = @(Get-Process | Where-Object { $_.Name -like "*openhamshack*" -or $_.Name -like "*openhamshack*" })
if ($left.Count) { "still running: " + (($left | ForEach-Object { "$($_.Name) $($_.Id)" }) -join ", "); $bad += "a program was left running" }
if ($bad.Count) { "WINCHECK FAIL: " + ($bad -join "; "); exit 1 }
"WINCHECK PASS"
