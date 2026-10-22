# release-all's Windows build folder, on the Windows build VM (windows.sh
# copies this script, the source tarball and ohsdigi.pyd to <Root>\release-all).
#
#   win-prep.ps1 -Root C:/ohsnb-build -App nb|ham -V <version> [-Keep 2]
#
# <Root>\<V>-<App> is the build folder. It starts with the download cache
# of the newest earlier folder of the same app (as NB 0.1.19-0.1.22 were
# seeded by hand), or, if it exists already (this version run again), is
# reused with its source, ohsdigi and checks replaced. Older folders of the
# app go, so that only -Keep remain once this one is built: the VM's disk
# had 11 GB free on 18/10 with four folders on it. Only folders named
# <digits...>-<App> are ever touched.
param([string]$Root, [string]$App, [string]$V, [int]$Keep = 2)
$ErrorActionPreference = "Stop"
$In = Join-Path $Root "release-all"
$W = Join-Path $Root "$V-$App"
$PyDir = @{nb = "ohsnb"; ham = "ohsradio"}[$App]
if (-not $PyDir) { throw "-App is nb or ham" }

$others = @(Get-ChildItem $Root -Directory | Where-Object {
    $_.Name -match "^\d+\.\d+.*-$App$" -and $_.FullName -ne (Get-Item -LiteralPath $W -ErrorAction SilentlyContinue).FullName
} | Sort-Object LastWriteTime -Descending)
$seed = $others | Select-Object -First 1
foreach ($old in ($others | Select-Object -Skip ([math]::Max($Keep - 1, 1)))) {
    "removing an older build folder, $($old.Name) (keeping the newest $Keep of $App)"
    Remove-Item -LiteralPath $old.FullName -Recurse -Force
}

if (Test-Path -LiteralPath $W) {
    "reusing $W (this version was built here before)"
    foreach ($d in "repo", "ohsdigi", "checks") {
        if (Test-Path -LiteralPath "$W\$d") { Remove-Item -LiteralPath "$W\$d" -Recurse -Force }
    }
    Get-ChildItem -LiteralPath "$W\out" -Filter "*-$V-setup.exe*" -ErrorAction SilentlyContinue | Remove-Item -Force
} else {
    New-Item -ItemType Directory -Path $W | Out-Null
    if ($seed -and (Test-Path -LiteralPath "$($seed.FullName)\cache")) {
        "download cache from $($seed.Name)"
        Copy-Item -Recurse -LiteralPath "$($seed.FullName)\cache" -Destination "$W\cache"
    } else {
        "no earlier $App folder: build-windows.ps1 downloads everything"
    }
}
New-Item -ItemType Directory -Path "$W\repo", "$W\ohsdigi" | Out-Null
tar -xzf "$In\rel-$V-$App-src.tar.gz" -C "$W\repo"
if ($LASTEXITCODE -ne 0) { throw "tar failed" }
Move-Item -LiteralPath "$In\rel-$V-$App-ohsdigi.pyd" -Destination "$W\ohsdigi\ohsdigi.pyd" -Force
Move-Item -LiteralPath "$In\rel-$V-$App-SHA256SUMS" -Destination "$W\ohsdigi\SHA256SUMS" -Force
Remove-Item -LiteralPath "$In\rel-$V-$App-src.tar.gz"
$have = (Get-Content "$W\repo\$PyDir\VERSION" -Raw).Trim()
if ($have -ne $V) { throw "$PyDir\VERSION in the source is $have, not $V" }
"$App $have, ohsdigi.pyd " + (Get-FileHash "$W\ohsdigi\ohsdigi.pyd").Hash.ToLower()
"free GB " + [math]::Round((Get-PSDrive C).Free / 1GB, 1)
"PREP PASS"
