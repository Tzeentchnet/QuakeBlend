# Build the QuakeBlend extension zip.
# Prefers `blender --command extension build`; falls back to Compress-Archive.

[CmdletBinding()]
param(
    [string] $OutputDir = (Join-Path $PSScriptRoot "..\dist"),
    [string] $BlenderExe = $env:BLENDER_EXE
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
$manifest = Join-Path $root "blender_manifest.toml"

if (-not (Test-Path $manifest)) {
    throw "blender_manifest.toml not found at $manifest"
}

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$OutputDir = (Resolve-Path $OutputDir).Path

if ($BlenderExe -and (Test-Path $BlenderExe)) {
    Write-Host "Building via Blender CLI: $BlenderExe"
    Push-Location $root
    try {
        & $BlenderExe --command extension build --output-dir $OutputDir --source-dir $root
    } finally {
        Pop-Location
    }
    return
}

Write-Host "Blender CLI not available; falling back to Compress-Archive"
$version = (Select-String -Path $manifest -Pattern '^\s*version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
$zipName = "quakeblend-$version.zip"
$zipPath = Join-Path $OutputDir $zipName

if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

# Stage to a temp dir so the zip root contains the extension folder structure.
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("quakeblend-build-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    Copy-Item -Path $manifest -Destination $staging
    Copy-Item -Path (Join-Path $root "quakeblend") -Destination $staging -Recurse
    if (Test-Path (Join-Path $root "LICENSE")) {
        Copy-Item -Path (Join-Path $root "LICENSE") -Destination $staging
    }
    # Strip __pycache__ before zipping.
    Get-ChildItem -Path $staging -Recurse -Force -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force
    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force
    Write-Host "Wrote $zipPath"
} finally {
    Remove-Item -Recurse -Force $staging
}
