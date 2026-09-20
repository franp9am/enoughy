# build-python.ps1 -- the private Python the setup exe bundles, unpacked once
# per version into build\python (git-ignored). Run it before iscc when that
# folder is missing or the version below changes.
#
# python.org's installer is four MSIs; without pip, docs, tests and the launcher
# it is these, and "msiexec /a" unpacks them without registering anything. To
# upgrade, change the version and the hashes (of
# https://www.python.org/ftp/python/<v>/amd64/<part>.msi).
$ErrorActionPreference = "Stop"
$PythonVersion = "3.13.15"
$Parts = [ordered]@{
    core  = "eff25b160b54a77c5953cf5803fc147a1ced084513265dfefc227583b1355484"
    exe   = "47f02452bde1f05b4d06fb93841ce380624c882ef75caddd1b1207d1a36bb4d2"
    lib   = "6d3130114d7f57eaa33d86e8366a669dfc73cfe8df772bef93ce2d9ea799f751"
    tcltk = "ec1e0fe1188969a48da63f24536183c95fc0393cf93588c646b253e91dc9b179"
}
$Dir = "$PSScriptRoot\build\python"

if ((Test-Path "$Dir\PYTHON_VERSION") -and ((Get-Content "$Dir\PYTHON_VERSION") -eq $PythonVersion)) {
    Write-Host "build\python is Python $PythonVersion already"
    return
}

Write-Host "Downloading Python $PythonVersion from python.org (about 13 MB)..."
$download = Join-Path $env:TEMP "EnoughyPython"
New-Item -ItemType Directory -Force $download | Out-Null
[Net.ServicePointManager]::SecurityProtocol = [Net.ServicePointManager]::SecurityProtocol -bor [Net.SecurityProtocolType]::Tls12
$ProgressPreference = "SilentlyContinue"   # the progress bar makes Invoke-WebRequest many times slower
foreach ($part in $Parts.Keys) {
    $msi = Join-Path $download "$part.msi"
    Invoke-WebRequest -UseBasicParsing -Uri "https://www.python.org/ftp/python/$PythonVersion/amd64/$part.msi" -OutFile $msi
    if ((Get-FileHash -Algorithm SHA256 $msi).Hash -ne $Parts[$part]) { throw "$part.msi does not match its pinned SHA-256." }
}

if (Test-Path $Dir) { Remove-Item -LiteralPath $Dir -Recurse -Force }
New-Item -ItemType Directory -Force $Dir | Out-Null
foreach ($part in $Parts.Keys) {
    $p = Start-Process msiexec.exe -ArgumentList "/a `"$download\$part.msi`" /qn TARGETDIR=`"$Dir`"" -Wait -PassThru
    if ($p.ExitCode -ne 0) { throw "msiexec could not unpack $part.msi (exit code $($p.ExitCode))." }
}
Remove-Item "$Dir\*.msi", $download -Recurse -Force   # /a leaves a copy of each package next to the files
& "$Dir\python.exe" -m compileall -q "$Dir\Lib" | Out-Null   # on the child's machine nobody may write .pyc files there
Set-Content "$Dir\PYTHON_VERSION" $PythonVersion -Encoding ascii -NoNewline
Write-Host "build\python is Python $PythonVersion"
