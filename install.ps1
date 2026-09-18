$ErrorActionPreference = "Stop"
$MonitorDir = "C:\ProgramData\ScreenTime"   # monitor + data; hidden from the child
$PythonDir  = "C:\ProgramData\ScreenTimePython"   # its own interpreter; readable by the child
$DefaultServerUrl = "https://marwin.pfranek.cz"   # the author's server; a child token from it is what turns syncing on

# Re-launch as administrator if we aren't already.
$admin = [Security.Principal.WindowsBuiltInRole]::Administrator
if (-not ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole($admin)) {
    Start-Process powershell "-NoProfile -ExecutionPolicy Bypass -File `"$PSCommandPath`"" -Verb RunAs
    return
}

# This window closes the moment the script ends, taking any error message with it.
trap { Write-Host "`n$_" -ForegroundColor Red; Read-Host "Press Enter to close" | Out-Null; exit 1 }

$src = $PSScriptRoot

$configText = Get-Content -Raw "$src\config.py"

# Which account is the child's. A typed name invites a typo that would leave the
# monitor watching an account nobody uses, so offer the real ones and check.
$enabledUsers = @(Get-LocalUser | Where-Object { $_.Enabled } | ForEach-Object { $_.Name })
$adminUsers = @()
try {
    $adminUsers = @(Get-LocalGroupMember -SID "S-1-5-32-544" | ForEach-Object { ($_.Name -split '\\')[-1] })   # Administrators -- the SID works in every display language
} catch { }   # an orphaned SID in the group makes this throw; then nothing is filtered out
$candidates = @($enabledUsers | Where-Object {
    $_ -notin $adminUsers -and $_ -notin @("Guest", "DefaultAccount", "WDAGUtilityAccount")
})

if ($candidates.Count -eq 1) { $defaultUser = $candidates[0] } else { $defaultUser = "" }

Write-Host "Local accounts: $($enabledUsers -join ', ')"
$userPrompt = "Which one is the child's account"
if ($defaultUser) { $userPrompt += " (Enter for $defaultUser)" }
$childUser = (Read-Host $userPrompt).Trim()
if (-not $childUser) { $childUser = $defaultUser }
if ($enabledUsers -notcontains $childUser) {
    throw "'$childUser' is not an enabled local account. Pick one of: $($enabledUsers -join ', ')"
}

# The folder the child may write in -- config.py is the single source for it.
$SharedDir = [regex]::Match($configText, 'SHARED_DIR\s*=\s*Path\(r?["'']([^"'']+)').Groups[1].Value
if (-not $SharedDir) { throw "Could not read SHARED_DIR from config.py." }

# Everything kept for a child sits in a folder named after the account: one under
# data\ (locked; every folder there is a child to the monitor) and one in the
# shared folder. The file names must match what monitor.py uses.
$DataDir        = "$MonitorDir\data"
$childDataDir   = "$DataDir\$childUser"
$childSharedDir = "$SharedDir\$childUser"
$redeemFile     = "$childSharedDir\extra_time.txt"
$remainingFile  = "$childSharedDir\remaining_time.txt"

# Before 0.5 the child's files sat in data\ itself, with the account in
# target_user.txt. Move them under the account, target_user.txt last: while it
# exists the move is not done and the next run redoes it. The earlier child
# keeps their files even when a different account is picked now; the monitor
# then watches both. (Temporary: gone once no machine before 0.5 remains.)
$oldUserFile = "$DataDir\target_user.txt"
if (Test-Path $oldUserFile) {
    $oldChild = [IO.File]::ReadAllText($oldUserFile).Trim()
    New-Item -ItemType Directory -Force "$DataDir\$oldChild", "$SharedDir\$oldChild" | Out-Null
    Get-ChildItem -LiteralPath $DataDir -File |
        Where-Object { $_.Name -notin @("target_user.txt", "crash.log") } |
        Move-Item -Destination "$DataDir\$oldChild" -Force
    if (Test-Path "$SharedDir\extra_time.txt") { Move-Item "$SharedDir\extra_time.txt" "$SharedDir\$oldChild" -Force }   # may hold a code not yet redeemed
    Remove-Item "$SharedDir\remaining_time.txt" -ErrorAction SilentlyContinue   # the monitor writes a new one
    Remove-Item -LiteralPath $oldUserFile
    Write-Host "Moved the files of the earlier install under data\$oldChild"
    if ($oldChild -ne $childUser) { Write-Host "  $oldChild stays a child of this machine; delete that folder to stop watching the account." -ForegroundColor Yellow }
}

# Both credentials go to files in the locked data folder, never into config.py,
# which git tracks. Asked for now, written only once the folder ACL is in place.
$secretFile    = "$childDataDir\secret.txt"
$tokenFile     = "$childDataDir\child_token.txt"
$serverUrlFile = "$childDataDir\server_url.txt"
$linkFile      = "$childDataDir\link_path.txt"   # so uninstall.ps1 finds a non-default choice

# A fresh install gets a random secret for signing extra-time codes; a reinstall
# keeps the one it has. To change it later, edit data\<child>\secret.txt and reboot.
$secretHex = ""
if (-not (Test-Path $secretFile)) {
    $bytes = New-Object byte[] 16
    [Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
    $secretHex = -join ($bytes | ForEach-Object { $_.ToString("x2") })   # printed at the end
}

$tokenPrompt = "Child token from add_child.py on the parent's server"
if (Test-Path $tokenFile) {
    $tokenPrompt += " (Enter keeps the current one)"
} else {
    $tokenPrompt += " (Enter to run without server syncing)"
}
$childToken = (Read-Host $tokenPrompt).Trim()

# Enter keeps the URL of an earlier install, or takes the default on a fresh one. Without
# a token the monitor never contacts the server, so the default is harmless offline.
$serverUrlDefault = $DefaultServerUrl
if (Test-Path $serverUrlFile) { $serverUrlDefault = [IO.File]::ReadAllText($serverUrlFile).Trim() }
$serverUrl = (Read-Host "Parent's server URL (Enter for $serverUrlDefault)").Trim()
if (-not $serverUrl) { $serverUrl = $serverUrlDefault }

# Where the "Extra time" shortcut goes. The shared desktop is one file every
# account sees, the parent's included; the child's own Desktop keeps it off yours.
$defaultLinkDir = "$env:PUBLIC\Desktop"
$previousLinkPath = ""
if (Test-Path $linkFile) {
    $previousLinkPath = [IO.File]::ReadAllText($linkFile).Trim()
    if ($previousLinkPath) { $defaultLinkDir = Split-Path $previousLinkPath }
}
$linkDir = (Read-Host "Folder for the 'Extra time' shortcut (Enter for $defaultLinkDir)").Trim().Trim('"')
if (-not $linkDir) { $linkDir = $defaultLinkDir }
if (-not (Test-Path $linkDir -PathType Container)) {
    throw "'$linkDir' is not an existing folder. Create it first, or press Enter for $defaultLinkDir."
}
$linkPath = Join-Path $linkDir "Extra time.lnk"

# A private Python for the two tasks, so the parent's own is neither touched nor
# trusted. These four MSIs are python.org's installer without pip, docs, tests and
# the launcher; "msiexec /a" unpacks them without registering anything. To upgrade,
# change the version and the hashes (of https://www.python.org/ftp/python/<v>/amd64/<part>.msi).
$PythonVersion = "3.13.15"
$PythonParts = [ordered]@{
    core  = "eff25b160b54a77c5953cf5803fc147a1ced084513265dfefc227583b1355484"
    exe   = "47f02452bde1f05b4d06fb93841ce380624c882ef75caddd1b1207d1a36bb4d2"
    lib   = "6d3130114d7f57eaa33d86e8366a669dfc73cfe8df772bef93ce2d9ea799f751"
    tcltk = "ec1e0fe1188969a48da63f24536183c95fc0393cf93588c646b253e91dc9b179"
}
$python = "$PythonDir\python.exe"

# tkinter is in the last MSI, so a copy that imports it at the pinned version is complete.
$installedVersion = ""
if (Test-Path $python) {
    try { $installedVersion = & $python -c "import sys, tkinter; print('%d.%d.%d' % sys.version_info[:3])" 2>$null } catch { }
}
if ($installedVersion -ne $PythonVersion) {
    Write-Host "Downloading Python $PythonVersion from python.org (about 13 MB)..."
    $downloadDir = Join-Path $env:TEMP "ScreenTimePython"
    New-Item -ItemType Directory -Force $downloadDir | Out-Null
    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower
    foreach ($part in $PythonParts.Keys) {
        $msi = Join-Path $downloadDir "$part.msi"
        Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$PythonVersion/amd64/$part.msi" -OutFile $msi
        if ((Get-FileHash -Algorithm SHA256 $msi).Hash -ne $PythonParts[$part]) { throw "$part.msi does not match its pinned SHA-256; not installing it." }
    }
    # Only now is an older copy touched, so a failed download leaves a working monitor.
    # A running one holds the DLLs open; it starts again at the next boot anyway.
    if (Test-Path $PythonDir) {
        foreach ($t in "ScreenTimeMonitor", "ScreenTimeWidget") { Stop-ScheduledTask $t -ErrorAction SilentlyContinue }
        Get-Process python, pythonw -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "$PythonDir\*" } | Stop-Process -Force
        Remove-Item -LiteralPath $PythonDir -Recurse -Force
    }
    New-Item -ItemType Directory -Force $PythonDir | Out-Null
    foreach ($part in $PythonParts.Keys) {
        $p = Start-Process msiexec.exe -ArgumentList "/a `"$downloadDir\$part.msi`" /qn TARGETDIR=`"$PythonDir`"" -Wait -PassThru
        if ($p.ExitCode -ne 0) { throw "msiexec could not unpack $part.msi (exit code $($p.ExitCode))." }
    }
    Remove-Item "$PythonDir\*.msi", $downloadDir -Recurse -Force   # /a leaves a copy of each package next to the files
    & $python -m compileall -q "$PythonDir\Lib" | Out-Null   # the child's account cannot write .pyc files here
}

# monitor.py runs as SYSTEM on this interpreter, so the child must not be able to
# write into it: a sitecustomize.py or .pth planted in Lib would run as SYSTEM at
# every boot. ProgramData would otherwise let any user create files inside it.
icacls $PythonDir /inheritance:r /grant "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-32-545:(OI)(CI)RX" | Out-Null   # SYSTEM, Administrators, BUILTIN\Users read-only
if ($LASTEXITCODE -ne 0) { throw "Could not lock $PythonDir; the child could plant code there that runs as SYSTEM." }

$pythonw = Join-Path $PythonDir pythonw.exe   # windowless twin, for the widget

# Monitor folder: copy the files, then lock it to SYSTEM + Administrators only.
# That lock is what stops the child reading data\<child>\secret.txt and forging codes.
New-Item -ItemType Directory -Force $childDataDir | Out-Null
Copy-Item "$src\monitor.py", "$src\os_tooling.py", "$src\remote_sync.py", "$src\config.py", "$src\settings.py", "$src\VERSION", "$src\launcher.ps1", "$src\release_key.cer" $MonitorDir -Force
# VERSION is what the launcher compares releases against. UPDATE_MODE says
# whether it fetches them at boot: to stop that on a machine, edit it to
# `manual`; a reinstall keeps it.
if (-not (Test-Path "$MonitorDir\UPDATE_MODE")) { Set-Content "$MonitorDir\UPDATE_MODE" auto -Encoding ascii -NoNewline }
icacls $MonitorDir /inheritance:r /grant "*S-1-5-18:(OI)(CI)F" "*S-1-5-32-544:(OI)(CI)F" | Out-Null   # S-1-5-18 = SYSTEM, S-1-5-32-544 = Administrators
# icacls signals failure only through its exit code, which $ErrorActionPreference
# does not catch -- unchecked, the secret below lands in a folder the child can read.
if ($LASTEXITCODE -ne 0) { throw "Could not lock $MonitorDir; data\$childUser\secret.txt would be readable by the child." }

# Written only now, so neither credential ever sits in a folder the child can read.
if ($secretHex)   { Set-Content -Path $secretFile -Value $secretHex   -Encoding ascii -NoNewline }
if ($childToken) { Set-Content -Path $tokenFile  -Value $childToken -Encoding ascii -NoNewline }
[IO.File]::WriteAllText($serverUrlFile, $serverUrl)

# Shared folder: every local account may write here. It holds only the overlay
# script and, per child, the number it shows and the redeem file -- nothing that
# has to be trusted, since the codes inside are signed and checked by monitor.py.
New-Item -ItemType Directory -Force $childSharedDir | Out-Null
icacls $SharedDir /grant "*S-1-5-32-545:(OI)(CI)M" | Out-Null   # *S-1-5-32-545 = BUILTIN\Users
Copy-Item "$src\remaining_time_widget.py" $SharedDir -Force
if (-not (Test-Path $redeemFile)) { New-Item -ItemType File $redeemFile | Out-Null }

# The shortcut. An earlier install may have left one in a different folder.
if ($previousLinkPath -and $previousLinkPath -ne $linkPath -and (Test-Path $previousLinkPath)) {
    Remove-Item -LiteralPath $previousLinkPath -Force
}
$link = (New-Object -ComObject WScript.Shell).CreateShortcut($linkPath)
$link.TargetPath = $redeemFile
$link.Save()
[IO.File]::WriteAllText($linkFile, $linkPath)

# Task 1 -- run the launcher as SYSTEM at every startup; it starts monitor.py
# and installs releases (see launcher.ps1).
$run  = New-ScheduledTaskAction -Execute powershell.exe -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$MonitorDir\launcher.ps1`"" -WorkingDirectory $MonitorDir
$who  = New-ScheduledTaskPrincipal -UserId SYSTEM -LogonType ServiceAccount -RunLevel Highest
$opts = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask "ScreenTimeMonitor" -Action $run -Trigger (New-ScheduledTaskTrigger -AtStartup) -Principal $who -Settings $opts -Force | Out-Null

# Task 2 -- show the overlay in the child's session when they log in.
$run = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$SharedDir\remaining_time_widget.py`" `"$remainingFile`"" -WorkingDirectory $SharedDir
$who = New-ScheduledTaskPrincipal -UserId $childUser -LogonType Interactive
# default task settings would skip the start on battery power
Register-ScheduledTask "ScreenTimeWidget" -Action $run -Trigger (New-ScheduledTaskTrigger -AtLogOn -User $childUser) -Principal $who -Settings $opts -Force | Out-Null

if ($secretHex) {
    Write-Host "`nShared secret, needed by grant_extra_time_offline.py on your own machine:" -ForegroundColor Yellow
    Write-Host "  $secretHex"
    Write-Host "  (write it to data\secret.txt there, or set CHILD_SECRET; it stays in $secretFile here)"
}
Write-Host "`nDone. Monitor starts after a reboot; the widget appears when $childUser logs in."
Read-Host "`nPress Enter to close" | Out-Null
