<#
    uninstall.ps1 -- removes what install.ps1 set up.

    Right-click -> "Run with PowerShell" (it self-elevates), or paste the line
    from the README into an administrator PowerShell. It unregisters the two
    scheduled tasks, deletes the install folders (the monitor's private Python
    included) and removes the desktop shortcut. Pass -KeepData to leave the
    data\ folder (used codes, per-day json) in place.
#>
[CmdletBinding()]
param(
    [string]$MonitorDir = "C:\ProgramData\Enoughy",
    [string]$SharedDir  = "C:\ProgramData\EnoughyShared",
    [string]$PythonDir  = "C:\ProgramData\EnoughyPython",
    [string]$MonitorTaskName = "EnoughyMonitor",
    [string]$WidgetTaskName  = "EnoughyWidget",
    [switch]$KeepData
)

$ErrorActionPreference = "Stop"

$isAdmin = ([Security.Principal.WindowsPrincipal] `
    [Security.Principal.WindowsIdentity]::GetCurrent()
).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $isAdmin) {
    # Piped into iex there is no file to re-launch, so say what to do instead.
    if (-not $PSCommandPath) { throw "Not running as administrator. Right-click PowerShell in the Start menu, choose 'Run as administrator', and paste the line again." }
    Write-Host "Re-launching with administrator rights..." -ForegroundColor Yellow
    $argList = @("-NoProfile", "-ExecutionPolicy", "Bypass", "-File", "`"$PSCommandPath`"")
    if ($KeepData) { $argList += "-KeepData" }
    Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList $argList
    return
}

foreach ($t in @($MonitorTaskName, $WidgetTaskName)) {
    if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        Unregister-ScheduledTask -TaskName $t -Confirm:$false
        Write-Host "Removed scheduled task '$t'" -ForegroundColor Green
    }
}

# Stopping the task doesn't always kill an already-running instance launched by
# a previous boot, so also kill any monitor.py/widget process directly, by
# command line or by the interpreter it runs on, before deleting their folders.
Get-CimInstance Win32_Process -Filter "Name = 'python.exe' OR Name = 'pythonw.exe'" |
    Where-Object {
        $_.CommandLine -match [regex]::Escape($MonitorDir) -or
        $_.CommandLine -match [regex]::Escape($SharedDir) -or
        $_.ExecutablePath -like "$PythonDir\*"
    } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped running process (PID $($_.ProcessId))" -ForegroundColor Green
    }

if (Test-Path $SharedDir) {
    Remove-Item -LiteralPath $SharedDir -Recurse -Force
    Write-Host "Deleted $SharedDir" -ForegroundColor Green
}

if (Test-Path $PythonDir) {
    Remove-Item -LiteralPath $PythonDir -Recurse -Force
    Write-Host "Deleted $PythonDir" -ForegroundColor Green
}

# install.ps1 records where it put the shortcut, in data\<child>\link_path.txt
# per child, or in data\ itself before 0.5; the oldest installs always used the
# shared desktop, so try all of them.
$links = @("$env:PUBLIC\Desktop\Extra time.lnk")
$linkFiles = @("$MonitorDir\data\link_path.txt")
if (Test-Path "$MonitorDir\data") {
    $linkFiles += Get-ChildItem -LiteralPath "$MonitorDir\data" -Directory | ForEach-Object { "$($_.FullName)\link_path.txt" }
}
foreach ($linkFile in $linkFiles) {
    if (Test-Path $linkFile) { $links += [IO.File]::ReadAllText($linkFile).Trim() }
}
foreach ($link in ($links | Where-Object { $_ } | Select-Object -Unique)) {
    if (Test-Path $link) {
        Remove-Item -LiteralPath $link -Force
        Write-Host "Deleted $link" -ForegroundColor Green
    }
}

if (Test-Path $MonitorDir) {
    if ($KeepData) {
        Get-ChildItem -LiteralPath $MonitorDir -Exclude "data" | Remove-Item -Recurse -Force
        Write-Host "Deleted $MonitorDir contents but kept data\ (--KeepData)" -ForegroundColor Green
    } else {
        Remove-Item -LiteralPath $MonitorDir -Recurse -Force
        Write-Host "Deleted $MonitorDir" -ForegroundColor Green
    }
}

Write-Host "`nDone. Reboot to be sure the monitor is no longer running." -ForegroundColor Green
