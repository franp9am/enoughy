# launcher.ps1 -- what the startup task runs instead of monitor.py: install a
# release staged at an earlier boot, start the monitor, then fetch the latest
# release and stage it for the next boot. Any failure is logged and the monitor
# runs as it is. Never changed by a release, only by a reinstall.
#
# Next to it: release_key.cer (the public key), UPDATE_MODE (`auto` or
# `manual`, the latter never fetches) and VERSION (what is installed).
# -Url and -Wait are for the test, which serves a release from a local server.
param(
    [string]$Url = "https://github.com/franp9am/enoughy/releases/latest/download",
    [int]$Wait = 60   # at boot the network comes up after this task starts
)
$ErrorActionPreference = "Stop"

# This folder is install.ps1's $MonitorDir; the other two are its siblings.
$MonitorDir = $PSScriptRoot
$SharedDir  = Join-Path (Split-Path $MonitorDir) "ScreenTimeShared"
$python     = Join-Path (Split-Path $MonitorDir) "ScreenTimePython\python.exe"
$Staged     = "$MonitorDir\update"   # inside the locked folder, so only the launcher writes there

# The catches below call it, so it must not throw: nothing would catch that.
function Log($message) {
    try { Add-Content "$MonitorDir\data\crash.log" "--- $(Get-Date -Format s) launcher: $message" } catch { }
}

function Install-Staged {
    $new = [version](Get-Content "$Staged\monitor\VERSION")
    $current = [version]"0.0.0"
    if (Test-Path "$MonitorDir\VERSION") { $current = [version](Get-Content "$MonitorDir\VERSION") }
    if ($new -le $current) { return }   # never downgrades: a rollback is a new tag
    # VERSION last: while the old one stands the copy is not done, and the next
    # boot redoes it from the staged folder, which only Fetch removes.
    Copy-Item "$Staged\shared\*" $SharedDir -Recurse -Force
    Copy-Item "$Staged\monitor\*" $MonitorDir -Recurse -Force -Exclude VERSION
    Remove-Item "$MonitorDir\__pycache__" -Recurse -Force -ErrorAction SilentlyContinue   # stale bytecode must not outlive its source
    Copy-Item "$Staged\monitor\VERSION" $MonitorDir -Force
    Log "updated $current to $new"
}

function Fetch {
    $zip = "$MonitorDir\enoughy.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower
    Start-Sleep $Wait   # one try; a miss costs one boot
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri "$Url/enoughy.zip" -OutFile $zip
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri "$Url/enoughy.zip.sig" -OutFile "$zip.sig"

    # The signature covers the whole zip; nothing is unpacked before it checks.
    $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2("$MonitorDir\release_key.cer")
    $key = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey($cert)
    $genuine = $key.VerifyData([IO.File]::ReadAllBytes($zip), [IO.File]::ReadAllBytes("$zip.sig"),
        [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
    if (-not $genuine) { throw "the downloaded zip does not match its signature" }
    # Unpacked under another name and renamed last, so a staged folder is always
    # whole, whenever the power goes.
    $unpacked = "$Staged.new"
    if (Test-Path $unpacked) { Remove-Item -LiteralPath $unpacked -Recurse -Force }
    Expand-Archive -LiteralPath $zip -DestinationPath $unpacked
    if (Test-Path $Staged) { Remove-Item -LiteralPath $Staged -Recurse -Force }
    Rename-Item -LiteralPath $unpacked -NewName (Split-Path $Staged -Leaf)
    Remove-Item $zip, "$zip.sig"
}

# Nothing before the monitor's start may end the script.
try { if (Test-Path $Staged) { Install-Staged } } catch { Log $_ }
$monitor = Start-Process $python "`"$MonitorDir\monitor.py`"" -WorkingDirectory $MonitorDir -NoNewWindow -PassThru
if ((Get-Content "$MonitorDir\UPDATE_MODE" -ErrorAction SilentlyContinue) -ne "manual") {
    try { Fetch } catch { Log $_ }
}
$monitor.WaitForExit()   # so the task counts as running for as long as the monitor does
