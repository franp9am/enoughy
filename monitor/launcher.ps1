# launcher.ps1 -- the boot task: keeps the monitor running from the newest release
# folder, v<version> beside this file, and every ten minutes runs that folder's
# update.ps1; when that brought a newer folder, it restarts the monitor from it.
# No release replaces this file. -Every is for the test.
param([int]$Every = 600)

$python = Join-Path (Split-Path $PSScriptRoot) "EnoughyPython\python.exe"

function Get-LatestReleaseFolder {   # the updater renames a folder to its version only once it is whole
    Get-ChildItem $PSScriptRoot -Directory -Filter v* |
        Sort-Object { [version]$_.Name.Substring(1) } | Select-Object -Last 1 -ExpandProperty FullName
}

function Start-Monitor {
    $process = Start-Process $python "`"$release\monitor.py`"" -WorkingDirectory $PSScriptRoot -NoNewWindow -PassThru
    $null = $process.Handle   # held, so Windows gives its id to no other process: only the monitor is ever stopped
    $process
}

$release = Get-LatestReleaseFolder
$monitor = Start-Monitor
while ($true) {
    $before = $release
    powershell -NoProfile -ExecutionPolicy Bypass -File "$release\update.ps1"   # a process of its own: nothing in it ends this one
    $release = Get-LatestReleaseFolder
    $updated = $release -ne $before
    if ($updated) { $monitor | Stop-Process -Force }   # it runs the old release
    if ($updated -or -not $monitor -or $monitor.HasExited) { $monitor = Start-Monitor }
    Start-Sleep $Every
}
