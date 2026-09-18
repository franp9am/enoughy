# bootstrap.ps1 -- install straight from GitHub, no manual download. From any PowerShell:
#
#   irm https://raw.githubusercontent.com/franp9am/enoughy/main/bootstrap.ps1 | iex
#
# That URL never changes; the release it installs is pinned below. It fetches
# that release into a temp folder and runs install.ps1 from there, which asks
# its questions and re-launches itself as administrator.
# Piped into iex it has no location of its own, so nothing here may use
# $PSScriptRoot. The braces keep its variables out of the caller's session.
& {
    $ErrorActionPreference = "Stop"
    $Repo = "franp9am/enoughy"
    $Ref  = "v0.6.0"   # a tag, so every install gets the same files; bump it on release
    if ($env:SCREENTIME_REF) { $Ref = $env:SCREENTIME_REF }   # any branch or tag, for testing before a release

    $dir = Join-Path $env:TEMP "ScreenTimeInstall"
    if (Test-Path $dir) { Remove-Item -LiteralPath $dir -Recurse -Force }
    New-Item -ItemType Directory $dir | Out-Null
    $zip = Join-Path $dir "src.zip"

    [Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
    $ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower
    Write-Host "Downloading $Repo $Ref from GitHub..."
    Invoke-WebRequest -UseBasicParsing -Uri "https://github.com/$Repo/archive/$Ref.zip" -OutFile $zip
    Expand-Archive -LiteralPath $zip -DestinationPath $dir
    $src = (Get-ChildItem -LiteralPath $dir -Directory | Select-Object -First 1).FullName   # GitHub names it <repo>-<ref>

    # -File sets $PSCommandPath, which install.ps1 needs to re-launch itself elevated.
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "$src\install.ps1"
}
