# launcher.ps1 -- the boot task: install a release staged at an earlier boot,
# start the monitor, then fetch the latest release and stage it for the next
# boot. A failure is logged and the monitor runs as it is.
#
# An update takes the .py files, the widget and VERSION out of the zip; this
# file, the installer and Python change only with a reinstall. Next to it:
# release_key.cer, UPDATE_MODE (`auto` or `manual`) and VERSION.
# -Url and -Wait are for the test, which serves a release locally.
param(
    [string]$Url = "https://github.com/franp9am/enoughy/releases/latest/download",
    [int]$Wait = 60   # at boot the network comes up after this task starts
)
$ErrorActionPreference = "Stop"

$MonitorDir = $PSScriptRoot
$SharedDir  = Join-Path (Split-Path $MonitorDir) "ScreenTimeShared"
$python     = Join-Path (Split-Path $MonitorDir) "ScreenTimePython\python.exe"
$Staged     = "$MonitorDir\update"   # inside the locked folder, so only the launcher writes there

function Log($message) {   # called from catches, so it must not throw
    try { Add-Content "$MonitorDir\data\crash.log" "--- $(Get-Date -Format s) launcher: $message" } catch { }
}

function Install-Staged {
    $new = [version](Get-Content "$Staged\VERSION")
    $current = if (Test-Path "$MonitorDir\VERSION") { [version](Get-Content "$MonitorDir\VERSION") } else { [version]"0.0.0" }
    if ($new -le $current) { return }   # never downgrades: a rollback is a new version
    Copy-Item "$Staged\remaining_time_widget.py" $SharedDir -Force
    Copy-Item "$Staged\*.py" $MonitorDir -Force -Exclude remaining_time_widget.py
    Remove-Item "$MonitorDir\__pycache__" -Recurse -Force -ErrorAction SilentlyContinue   # stale bytecode
    Copy-Item "$Staged\VERSION" $MonitorDir -Force   # last: until it lands, the next boot redoes the copy
    Log "updated $current to $new"
}

function Fetch {
    $zip = "$MonitorDir\enoughy.zip"
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower
    Start-Sleep $Wait   # one try; a miss costs one boot
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri "$Url/enoughy.zip" -OutFile $zip
    Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 -Uri "$Url/enoughy.zip.sig" -OutFile "$zip.sig"

    $cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2("$MonitorDir\release_key.cer")
    $key = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPublicKey($cert)
    if (-not $key.VerifyData([IO.File]::ReadAllBytes($zip), [IO.File]::ReadAllBytes("$zip.sig"),
            [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)) {
        throw "the downloaded zip does not match its signature"
    }
    # Unpacked under another name and renamed last, so a staged folder is always whole.
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
