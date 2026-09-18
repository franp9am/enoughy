# release.ps1 -- zip the client files, sign the zip, tag the commit and publish
# both as a GitHub release, where every launcher fetches them.
#
#   .\release.ps1 v0.6.0 [-KeyFile ...]
#
# Needs the private key (a PFX; release_key.cer is its public half) and a
# logged-in gh. Lose the key and no installed machine updates without a visit.
param(
    [Parameter(Mandatory)][string]$Tag,
    [Parameter(Mandatory)][string]$Notes,   # the tag's message and the release's notes, shown on GitHub
    [string]$KeyFile = (Join-Path $HOME ".enoughy\release_key.pfx")
)
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot

if (-not (Test-Path $KeyFile)) { throw "No signing key at $KeyFile." }
if (git status --porcelain) { throw "The working tree is not clean; commit first." }

# The launcher compares the version in the zip, so config.py must agree with the tag.
$version = $Tag -replace '^v', ''
$pinned = [regex]::Match((Get-Content -Raw "$src\config.py"), 'MONITOR_VERSION\s*=\s*"([^"]+)"').Groups[1].Value
if ($pinned -ne $version) { throw "config.py says MONITOR_VERSION = $pinned, the tag says $version." }

$password = Read-Host "Password for $KeyFile" -AsSecureString
$cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($KeyFile, $password, [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
$public = New-Object Security.Cryptography.X509Certificates.X509Certificate2("$src\release_key.cer")
if ($cert.Thumbprint -ne $public.Thumbprint) { throw "release_key.cer is not the public half of $KeyFile; no machine would accept the release." }
$key = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)

# Two folders, as the launcher expects: monitor\ and shared\. The files
# install.ps1 copies, plus VERSION.
$stage = Join-Path $env:TEMP "enoughy-release"
if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory "$stage\files\monitor", "$stage\files\shared" | Out-Null
Copy-Item "$src\monitor.py", "$src\os_tooling.py", "$src\remote_sync.py", "$src\config.py", "$src\settings.py" "$stage\files\monitor"
Copy-Item "$src\remaining_time_widget.py" "$stage\files\shared"
Set-Content "$stage\files\monitor\VERSION" $version -NoNewline

# .NET rather than Compress-Archive. Both write backslashes into entry names under
# Windows PowerShell; Expand-Archive, which the launcher uses, reads them as folders.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = "$stage\enoughy.zip"
[IO.Compression.ZipFile]::CreateFromDirectory("$stage\files", $zip)

# One signature over the whole zip.
$signature = $key.SignData([IO.File]::ReadAllBytes($zip), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
[IO.File]::WriteAllBytes("$zip.sig", $signature)

# A tag is never moved; a fix is a new tag. Annotated, so the notes live in git
# and the release shows them rather than the last commit's message.
git tag -a $Tag -m $Notes
if ($LASTEXITCODE -ne 0) { throw "Could not tag; does $Tag exist already?" }
git push origin $Tag
if ($LASTEXITCODE -ne 0) { throw "Could not push the tag." }
gh release create $Tag $zip "$zip.sig" --title $Tag --notes-from-tag
if ($LASTEXITCODE -ne 0) { throw "gh release create failed; the tag is pushed, delete it before retrying." }
Write-Host "Released $Tag."
