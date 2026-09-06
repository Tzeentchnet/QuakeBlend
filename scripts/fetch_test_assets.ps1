[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string] $CacheRoot,
    [string] $AssetId = "librequake-e3m4",
    [string] $ManifestPath = (Join-Path $PSScriptRoot "..\tests\assets\manifest.json")
)

$ErrorActionPreference = "Stop"
$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
if ($manifest.schema_version -ne 1) {
    throw "Unsupported asset manifest version"
}
$matches = @($manifest.assets | Where-Object { $_.id -eq $AssetId })
if ($matches.Count -ne 1) {
    throw "Expected exactly one catalog entry for asset: $AssetId"
}
$asset = $matches[0]
if ($asset.cache_directory -cnotmatch '^[a-z0-9-]+$' -or
    $asset.revision -cnotmatch '^[0-9a-f]{40}$') {
    throw "Invalid asset cache directory or revision"
}
$repository = if ($asset.repository) { $asset.repository } else { "ericwa/ericw-tools" }
if ($repository -cnotin @("ericwa/ericw-tools", "lavenderdotpet/LibreQuake")) {
    throw "Asset repository is not approved"
}
$expectedPrefix = "https://raw.githubusercontent.com/$repository/$($asset.revision)/"
if (-not $asset.source_base_url.StartsWith($expectedPrefix, [StringComparison]::Ordinal) -or
    -not $asset.source_base_url.EndsWith('/')) {
    throw "Asset source must be pinned to the catalog's GitHub revision"
}
$cache = [System.IO.Path]::GetFullPath($CacheRoot)
$destinationRoot = Join-Path $cache $asset.cache_directory

function Test-AssetFile {
    param([string] $Path, [object] $Entry)
    $item = Get-Item -LiteralPath $Path
    if ($item.PSIsContainer -or $item.Length -ne $Entry.bytes) {
        throw "Asset size mismatch: $Path"
    }
    $hash = (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
    if ($hash -ine $Entry.sha256) {
        throw "Asset SHA256 mismatch: $Path"
    }
}

foreach ($entry in $asset.files) {
    if ($entry.path -cnotmatch '^[A-Za-z0-9_./-]+$' -or
        $entry.path.StartsWith('/') -or
        ($entry.path.Split('/') -contains '..') -or
        $entry.bytes -le 0 -or
        $entry.sha256 -cnotmatch '^[0-9a-f]{64}$') {
        throw "Invalid file entry in asset catalog"
    }
    $destination = Join-Path $destinationRoot $entry.path
    if (Test-Path -LiteralPath $destination) {
        Test-AssetFile -Path $destination -Entry $entry
        Write-Host "Verified existing $($entry.path)"
        continue
    }
    $parent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Force -Path $parent | Out-Null
    $temporary = Join-Path $parent (".download-" + [guid]::NewGuid())
    try {
        Invoke-WebRequest -Uri ($asset.source_base_url + $entry.path) `
            -OutFile $temporary -TimeoutSec 120
        Test-AssetFile -Path $temporary -Entry $entry
        [System.IO.File]::Move($temporary, $destination)
        Write-Host "Downloaded and verified $($entry.path)"
    } finally {
        if (Test-Path -LiteralPath $temporary) {
            Remove-Item -LiteralPath $temporary -Force
        }
    }
}
Write-Host "Asset files verified: $destinationRoot"
