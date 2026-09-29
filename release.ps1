# release.ps1 -- write the version into monitor\VERSION, zip what every launcher
# updates from, sign it, build the setup exe and sign that too, commit VERSION,
# tag the commit v<version> and publish the three files as a GitHub release.
#
#   powershell -ExecutionPolicy Bypass -File .\release.ps1 0.9.0 "What changed, in a sentence for the parent." [-NoSign] [-KeyFile ...]
#
# The bypass is for a window whose policy refuses scripts.
#
# Needs the private key (release_key.cer is its public half), a logged-in gh,
# Inno Setup's iscc on the PATH and, for the exe's signature, SimplySign Desktop
# connected. Lose the key and no installed machine updates without a visit.
param(
    [Parameter(Mandatory)][version]$Version,
    [Parameter(Mandatory)][string]$Notes,   # the tag's message and the release's notes
    [switch]$NoSign,                        # leave the setup exe unsigned; SmartScreen warns about it
    [string]$KeyFile = (Join-Path $HOME ".enoughy\release_key.pfx")
)
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot
$SignTool = "C:\Program Files (x86)\Windows Kits\10\bin\10.0.28000.0\x64\signtool.exe"   # x64 as the SimplySign provider is; the arm64 one finds no certificate
$Thumbprint = "EC442E0D7C1D47B8F530D3E799C468A173BE2268"   # the Certum certificate, valid to 2027-09-22

if (-not (Test-Path $KeyFile)) { throw "No signing key at $KeyFile." }
$VersionFile = "$src\monitor\VERSION"
if (git status --porcelain | Where-Object { $_ -notmatch "monitor/VERSION$" }) { throw "The working tree is not clean; commit first." }   # VERSION may be left changed by a run that failed
if ($Version -lt [version](git show HEAD:monitor/VERSION)) { throw "$Version is lower than the committed version; no launcher would take it." }
$Tag = "v$Version"
if (git ls-remote --tags origin $Tag) { throw "$Tag is released already." }   # on origin: a local tag may be gone
Set-Content $VersionFile $Version -Encoding ascii -NoNewline

$password = Read-Host "Password for $KeyFile" -AsSecureString
$cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($KeyFile, $password, [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
$public = New-Object Security.Cryptography.X509Certificates.X509Certificate2("$src\monitor\release_key.cer")
if ($cert.Thumbprint -ne $public.Thumbprint) { throw "release_key.cer is not the public half of $KeyFile; no machine would accept the release." }
$key = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)

# Flat, whatever the repo's folders: the files a child's machine runs.
$stage = Join-Path $env:TEMP "enoughy-release"
if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory "$stage\files" | Out-Null
Copy-Item "$src\monitor\monitor.py", "$src\monitor\os_tooling.py", "$src\monitor\remote_sync.py", "$src\monitor\config.py", "$src\monitor\settings.py",
          $VersionFile, "$src\monitor\launcher.ps1", "$src\monitor\release_key.cer", "$src\widget\remaining_time_widget.py" "$stage\files"
Add-Type -AssemblyName System.IO.Compression.FileSystem   # Compress-Archive would do the same; both write backslashes, which Expand-Archive reads
$zip = "$stage\enoughy.zip"
[IO.Compression.ZipFile]::CreateFromDirectory("$stage\files", $zip)
$signature = $key.SignData([IO.File]::ReadAllBytes($zip), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
[IO.File]::WriteAllBytes("$zip.sig", $signature)

# The setup exe, before the commit, so that a failed build leaves nothing pushed.
& "$src\installer\build-python.ps1"
iscc /Q "$src\installer\installer.iss"
if ($LASTEXITCODE -ne 0) { throw "iscc could not build the setup exe." }
$exe = "$src\installer\dist\enoughy-setup.exe"
if (-not $NoSign) {
    & $SignTool sign /sha1 $Thumbprint /fd SHA256 /tr http://time.certum.pl /td SHA256 $exe
    if ($LASTEXITCODE -ne 0) { throw "Could not sign the setup exe; connect SimplySign Desktop, or pass -NoSign." }
}

if (git status --porcelain) {   # nothing to commit when VERSION held the number already
    git commit -q -m "VERSION $Version" -- monitor/VERSION
    if ($LASTEXITCODE -ne 0) { throw "Could not commit VERSION." }
}
# Annotated, so the notes live in git and GitHub shows them for the tag too.
git tag -a $Tag -m $Notes
if ($LASTEXITCODE -ne 0) { throw "Could not tag." }
git push --atomic origin HEAD $Tag
if ($LASTEXITCODE -ne 0) { throw "Could not push; the commit and the tag $Tag are local, delete the tag before retrying." }
gh release create $Tag $zip "$zip.sig" $exe --title $Tag --notes-from-tag
if ($LASTEXITCODE -ne 0) { throw "gh release create failed; the tag is pushed, delete it before retrying." }
Write-Host "Released $Tag."
