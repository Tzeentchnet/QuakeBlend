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

# Both builders consume the same extension root: manifest and __init__.py must
# be siblings at the archive root.
$staging = Join-Path ([System.IO.Path]::GetTempPath()) ("quakeblend-build-" + [guid]::NewGuid())
New-Item -ItemType Directory -Path $staging | Out-Null
try {
    Copy-Item -Path $manifest -Destination $staging
    # Blender Extensions expect the package contents at the zip root, not
    # nested inside a subfolder. Copy quakeblend/* directly.
    Copy-Item -Path (Join-Path $root "quakeblend\*") -Destination $staging -Recurse
    if (Test-Path (Join-Path $root "LICENSE")) {
        Copy-Item -Path (Join-Path $root "LICENSE") -Destination $staging
    }
    # Strip __pycache__ before zipping.
    Get-ChildItem -Path $staging -Recurse -Force -Directory -Filter "__pycache__" |
        Remove-Item -Recurse -Force

    if ($BlenderExe -and (Test-Path $BlenderExe)) {
        Write-Host "Building via Blender CLI: $BlenderExe"
        & $BlenderExe --command extension build --output-dir $OutputDir --source-dir $staging
        if ($LASTEXITCODE -ne 0) {
            throw "Blender extension build failed with exit code $LASTEXITCODE"
        }
        return
    }

    Write-Host "Blender CLI not available; falling back to Compress-Archive"
    $version = (Select-String -Path $manifest -Pattern '^\s*version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    $zipName = "quakeblend-$version.zip"
    $zipPath = Join-Path $OutputDir $zipName

    if (Test-Path $zipPath) { Remove-Item -Force $zipPath }

    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $zipPath -Force
    Write-Host "Wrote $zipPath"
} finally {
    Remove-Item -Recurse -Force $staging
}
