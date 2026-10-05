[CmdletBinding()]
param(
    [Parameter()]
    [string]$OutputDirectory = (Join-Path ([Environment]::GetFolderPath('MyDocuments')) 'Stewardence')
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$releaseDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$profilePath = Join-Path $releaseDirectory 'collector-profile.json'
$signaturePath = Join-Path $releaseDirectory 'collector-profile.sig'
$publicKeyPath = Join-Path $releaseDirectory 'collector-profile-public.pem'
$manifestPath = Join-Path $releaseDirectory 'collector-modules.json'

$profileBytes = [IO.File]::ReadAllBytes($profilePath)
$signature = [Convert]::FromBase64String(
    ([IO.File]::ReadAllText($signaturePath)).Trim()
)
$publicKey = [IO.File]::ReadAllText($publicKeyPath)
$rsa = [Security.Cryptography.RSA]::Create()
try {
    $rsa.ImportFromPem($publicKey)
    $signatureValid = $rsa.VerifyData(
        $profileBytes,
        $signature,
        [Security.Cryptography.HashAlgorithmName]::SHA256,
        [Security.Cryptography.RSASignaturePadding]::Pkcs1
    )
}
finally {
    $rsa.Dispose()
}
if (-not $signatureValid) {
    throw 'The Stewardence installation profile signature is invalid.'
}

$profile = [Text.Encoding]::UTF8.GetString($profileBytes) | ConvertFrom-Json
if ($profile.profile_schema_version -ne 1) {
    throw 'The Stewardence installation profile version is unsupported.'
}
if ($profile.enabled_modules.Count -ne 1 -or $profile.enabled_modules[0] -ne 'windows.installed_programs') {
    throw 'The installation profile requests unsupported Collector modules.'
}

$artifactPath = Join-Path $releaseDirectory $profile.artifact.name
$artifactHash = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($artifactHash -ne $profile.artifact.sha256) {
    throw 'The Stewardence Collector executable hash does not match its signed profile.'
}
$manifestHash = (Get-FileHash -LiteralPath $manifestPath -Algorithm SHA256).Hash.ToLowerInvariant()
if ($manifestHash -ne $profile.module_manifest.sha256) {
    throw 'The Stewardence Collector module manifest hash does not match its signed profile.'
}

$manifest = [Text.Encoding]::UTF8.GetString(
    [IO.File]::ReadAllBytes($manifestPath)
) | ConvertFrom-Json
$activeModule = $manifest.modules | Where-Object {
    $_.id -eq 'windows.installed_programs' -and $_.available -eq $true
}
if ($null -eq $activeModule) {
    throw 'The signed Collector module is unavailable in this release.'
}

$identityDirectory = Join-Path ([Environment]::GetFolderPath('LocalApplicationData')) 'Stewardence'
$identityPath = Join-Path $identityDirectory 'collector-device-id.txt'
New-Item -ItemType Directory -Force -Path $identityDirectory | Out-Null
$deviceId = $null
if (Test-Path -LiteralPath $identityPath) {
    $deviceId = [Guid]::Parse(([IO.File]::ReadAllText($identityPath)).Trim())
}
if ($null -eq $deviceId) {
    $deviceId = [Guid]::NewGuid()
    [IO.File]::WriteAllText($identityPath, $deviceId.ToString())
}

New-Item -ItemType Directory -Force -Path $OutputDirectory | Out-Null
$timestamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssZ')
$outputPath = Join-Path $OutputDirectory "stewardence-evidence-$timestamp.json"

& $artifactPath --device-id $deviceId --output $outputPath
if ($LASTEXITCODE -ne 0) {
    throw "The Stewardence Collector exited with code $LASTEXITCODE."
}

$bundleHash = (Get-FileHash -LiteralPath $outputPath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Host "Evidence bundle: $outputPath"
Write-Host "Bundle SHA-256: $bundleHash"
Write-Host 'Review the JSON bundle, then upload it from Inventory > Collector evidence.'
