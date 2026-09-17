# release.ps1 -- one-step release: zip the client files, sign the zip, tag the
# commit and publish zip and signature as the assets of a GitHub release.
#
#   .\release.ps1 v0.6.0 [-KeyFile ...]
#
# The launcher on every child's machine fetches the two assets from
# releases/latest/download/ and checks them against release_key.cer, so the
# asset names and the key never change. The private key is a password
# protected PFX, release_key.cer its certificate; making them is not this
# script's business. Losing the key means no installed machine updates again
# without a visit. The GitHub CLI must be logged in (gh auth login).
param(
    [Parameter(Mandatory)][string]$Tag,
    [string]$KeyFile = (Join-Path $HOME ".enoughy\release_key.pfx")
)
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot

if (-not (Test-Path $KeyFile)) { throw "No signing key at $KeyFile." }
if (git status --porcelain) { throw "The working tree is not clean; commit first." }

# The version inside the zip is what the launcher compares, so it is the tag's,
# and config.py must agree until the monitor reads it from the file instead.
$version = $Tag -replace '^v', ''
$pinned = [regex]::Match((Get-Content -Raw "$src\config.py"), 'MONITOR_VERSION\s*=\s*"([^"]+)"').Groups[1].Value
if ($pinned -ne $version) { throw "config.py says MONITOR_VERSION = $pinned, the tag says $version." }

$password = Read-Host "Password for $KeyFile" -AsSecureString
$cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($KeyFile, $password, [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
$public = New-Object Security.Cryptography.X509Certificates.X509Certificate2("$src\release_key.cer")
if ($cert.Thumbprint -ne $public.Thumbprint) { throw "release_key.cer is not the public half of $KeyFile; no machine would accept the release." }
$key = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)

# The zip has two folders, and the launcher copies the contents of each: monitor\
# into the locked monitor folder, shared\ into the folder the child can see.
# The same files install.ps1 copies, plus the version.
$stage = Join-Path $env:TEMP "enoughy-release"
if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory "$stage\files\monitor", "$stage\files\shared" | Out-Null
Copy-Item "$src\monitor.py", "$src\os_tooling.py", "$src\remote_sync.py", "$src\config.py" "$stage\files\monitor"
Copy-Item "$src\remaining_time_widget.py" "$stage\files\shared"
Set-Content "$stage\files\monitor\VERSION" $version -NoNewline

# .NET rather than Compress-Archive, which writes backslashes into entry names.
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = "$stage\enoughy.zip"
[IO.Compression.ZipFile]::CreateFromDirectory("$stage\files", $zip)

# The signature covers the whole zip, so nothing inside needs a hash of its own.
$signature = $key.SignData([IO.File]::ReadAllBytes($zip), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
[IO.File]::WriteAllBytes("$zip.sig", $signature)

# A tag is never moved: a fix is a new tag, so a machine never sees two zips of one version.
git tag $Tag
if ($LASTEXITCODE -ne 0) { throw "Could not tag; does $Tag exist already?" }
git push origin $Tag
if ($LASTEXITCODE -ne 0) { throw "Could not push the tag." }
gh release create $Tag $zip "$zip.sig" --title $Tag --notes ""
if ($LASTEXITCODE -ne 0) { throw "gh release create failed; the tag is pushed, delete it before retrying." }
Write-Host "Released $Tag."
