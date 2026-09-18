# release.ps1 -- zip everything a child's machine receives, sign it, tag the
# commit v<VERSION> and publish both as a GitHub release, which a fresh install
# runs from and every launcher updates from.
#
#   .\release.ps1 "What changed, in a sentence for the parent." [-KeyFile ...]
#
# Needs the private key (release_key.cer is its public half) and a logged-in gh.
# Lose the key and no installed machine updates without a visit.
param(
    [Parameter(Mandatory)][string]$Notes,   # the tag's message and the release's notes
    [string]$KeyFile = (Join-Path $HOME ".enoughy\release_key.pfx")
)
$ErrorActionPreference = "Stop"
$src = $PSScriptRoot

if (-not (Test-Path $KeyFile)) { throw "No signing key at $KeyFile." }
if (git status --porcelain) { throw "The working tree is not clean; commit first." }
$Tag = "v" + (Get-Content "$src\VERSION").Trim()
if (git ls-remote --tags origin $Tag) { throw "$Tag is released already; bump VERSION first." }   # on origin: a local tag may be gone

$password = Read-Host "Password for $KeyFile" -AsSecureString
$cert = New-Object Security.Cryptography.X509Certificates.X509Certificate2($KeyFile, $password, [Security.Cryptography.X509Certificates.X509KeyStorageFlags]::EphemeralKeySet)
$public = New-Object Security.Cryptography.X509Certificates.X509Certificate2("$src\release_key.cer")
if ($cert.Thumbprint -ne $public.Thumbprint) { throw "release_key.cer is not the public half of $KeyFile; no machine would accept the release." }
$key = [Security.Cryptography.X509Certificates.RSACertificateExtensions]::GetRSAPrivateKey($cert)

# Flat, like the repo: what install.ps1 copies, and the installer itself.
$stage = Join-Path $env:TEMP "enoughy-release"
if (Test-Path $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory "$stage\files" | Out-Null
Copy-Item "$src\monitor.py", "$src\os_tooling.py", "$src\remote_sync.py", "$src\config.py", "$src\settings.py", "$src\VERSION", "$src\remaining_time_widget.py",
          "$src\launcher.ps1", "$src\release_key.cer", "$src\install.ps1", "$src\install.cmd", "$src\uninstall.ps1", "$src\uninstall.cmd" "$stage\files"
Add-Type -AssemblyName System.IO.Compression.FileSystem   # Compress-Archive would do the same; both write backslashes, which Expand-Archive reads
$zip = "$stage\enoughy.zip"
[IO.Compression.ZipFile]::CreateFromDirectory("$stage\files", $zip)
$signature = $key.SignData([IO.File]::ReadAllBytes($zip), [Security.Cryptography.HashAlgorithmName]::SHA256, [Security.Cryptography.RSASignaturePadding]::Pkcs1)
[IO.File]::WriteAllBytes("$zip.sig", $signature)

# Annotated, so the notes live in git and GitHub shows them for the tag too.
git tag -a $Tag -m $Notes
if ($LASTEXITCODE -ne 0) { throw "Could not tag." }
git push origin $Tag
if ($LASTEXITCODE -ne 0) { throw "Could not push the tag." }
gh release create $Tag $zip "$zip.sig" --title $Tag --notes-from-tag
if ($LASTEXITCODE -ne 0) { throw "gh release create failed; the tag is pushed, delete it before retrying." }
Write-Host "Released $Tag."
