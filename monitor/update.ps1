# update.ps1 -- run by the launcher every ten minutes, from the latest release
# folder: once a day it fetches the latest release and, when it is newer, unpacks
# it beside this folder and renames it to v<version>. From that folder the
# launcher restarts the monitor. -Url is for the test.
param([string]$Url = "https://github.com/franp9am/enoughy/releases/latest/download")
$ErrorActionPreference = "Stop"

$Root      = Split-Path $PSScriptRoot   # the release folders, the data and what outlives a release
$SharedDir = Join-Path (Split-Path $Root) "EnoughyShared"
$zip       = "$Root\enoughy.zip"
$unpacked  = "$Root\update.tmp"   # inside the locked folder, so no child writes there
$today     = Get-Date -Format yyyy-MM-dd

function Log($text) { Add-Content "$Root\data\crash.log" "--- $(Get-Date -Format s) update: $text" }
trap { Log $_; Set-Content "$Root\FETCHED" $today; exit 1 }   # a failure is logged once and waits for tomorrow

$current = [version](Get-Content "$PSScriptRoot\VERSION")
# The releases before this one: the monitor has left them. What is still held, the next run removes.
Get-ChildItem $Root -Directory | Where-Object { $_.Name -match '^v\d+(\.\d+){1,3}$' -and [version]$_.Name.Substring(1) -lt $current } |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue

if ((Get-Content "$Root\UPDATE_MODE" -ErrorAction SilentlyContinue) -eq "manual") { exit }
if ((Get-Content "$Root\FETCHED" -ErrorAction SilentlyContinue) -eq $today) { exit }

[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower
try {
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri "$Url/enoughy.zip" -OutFile $zip
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri "$Url/enoughy.zip.sig" -OutFile "$zip.sig"
} catch { exit }   # no network, as at boot: quietly, the next run tries again

$cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2("$PSScriptRoot\release_key.cer")
$key = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey($cert)
if (-not $key.VerifyData([IO.File]::ReadAllBytes($zip), [IO.File]::ReadAllBytes("$zip.sig"),
        [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)) {
    throw "the downloaded zip does not match its signature"
}
if (Test-Path $unpacked) { Remove-Item -LiteralPath $unpacked -Recurse -Force }   # what a run cut off left
Expand-Archive -LiteralPath $zip -DestinationPath $unpacked

$new = [version](Get-Content "$unpacked\VERSION")
if ($new -gt $current) {   # never downgrades: a rollback is a new version
    Copy-Item "$unpacked\remaining_time_widget.py" $SharedDir -Force   # a copy, so it takes that folder's permissions
    Remove-Item "$unpacked\remaining_time_widget.py"   # the widget runs from the shared folder only: none is left in the release
    Rename-Item $unpacked "v$new"   # last and at once: only now is it a release, and it is whole
    Log "updated $current to $new"
} else {
    Remove-Item -LiteralPath $unpacked -Recurse -Force
}
Remove-Item $zip, "$zip.sig"
Set-Content "$Root\FETCHED" $today   # the day's work is done; a run cut off before this line is done again by the next
