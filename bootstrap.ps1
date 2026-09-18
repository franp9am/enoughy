# bootstrap.ps1 -- install straight from GitHub, no manual download. From any PowerShell:
#
#   irm https://raw.githubusercontent.com/franp9am/enoughy/main/bootstrap.ps1 | iex
#
# That URL never changes. It fetches the latest release, the same zip every
# launcher updates from, into a temp folder and runs install.ps1 from it, which
# asks its questions and re-launches itself as administrator.
# Piped into iex it has no location of its own, so nothing here may use
# $PSScriptRoot. The braces keep its variables out of the caller's session.
& {
    $ErrorActionPreference = "Stop"
    $Url = "https://github.com/franp9am/enoughy/releases/latest/download/enoughy.zip"
    if ($env:ENOUGHY_ZIP) { $Url = $env:ENOUGHY_ZIP }   # any zip built by release.ps1, for testing before a release

    $dir = Join-Path $env:TEMP "ScreenTimeInstall"
    if (Test-Path $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
    New-Item -ItemType Directory $dir | Out-Null
    $zip = Join-Path $dir "enoughy.zip"

    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower
    Write-Host "Downloading the latest enoughy release from GitHub..."
    Invoke-WebRequest -UseBasicParsing -Uri $Url -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $dir

    # -File sets $PSCommandPath, which install.ps1 needs to re-launch itself elevated.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$dir\install.ps1"
}
