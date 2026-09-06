# Public Test Assets

QuakeBlend's default test suite is offline. External fixtures are opt-in, remain
outside the repository, and are never bundled with the Blender extension. The
public catalogs are [tests/assets/manifest.json](../tests/assets/manifest.json)
and [tests/assets/librequake-textures.json](../tests/assets/librequake-textures.json).

## Licensed LibreQuake fixture

The admitted real-map fixture is **LibreQuake e3m4, Hounds of The Depths**,
credited to **Nolcoz** in the map. The unmodified Q1 Valve220 source is mirrored
in [ericw-tools revision 4f9cb6c2](https://github.com/ericwa/ericw-tools/tree/4f9cb6c2e0e9a3dbe5617d161501b25b1e08436e/testmaps/LibreQuake).

The catalogs identify the upstream BSD-3-Clause terms and required notices. The
downloader stores and verifies those notices beside each optional fixture in the
external cache. This repository does not redistribute the fixture payloads or
copied notices. Keep the cataloged notices with any redistributed fixture.

Verified source properties:

| Property | Result |
|---|---:|
| Source size | 3,161,251 bytes |
| Entities | 1,301 |
| Brushes | 3,441 |
| Faces | 22,180, all Valve220 |
| SHA-256 | `a827f8a4f6e011d8c1b81c25b16e43b086bbdec97a82f8327057ae2dc0f3f2cf` |

This is an authored map, not a synthetic fixture. Its admission does not imply
engine-rendering parity, gameplay certification, or permission for unrelated
Quake assets.

## Acquire and verify

Use an external cache from the repository root:

```powershell
$cache = Join-Path $env:LOCALAPPDATA "QuakeBlend\test-assets"
pwsh ./scripts/fetch_test_assets.ps1 -CacheRoot $cache
$previousAssetRoot = $env:QB_TEST_ASSET_ROOT
try {
    $env:QB_TEST_ASSET_ROOT = $cache
    python -m pytest tests/test_external_assets.py -v
} finally {
    $env:QB_TEST_ASSET_ROOT = $previousAssetRoot
}
```

The downloader fetches only pinned catalog entries, verifies lengths and SHA-256
digests before publishing them to the external cache, and retains required
notices there. Existing mismatched files fail verification instead of being
silently replaced. No pytest test performs a download.

## Partial texture subset

A separate catalog selects 71 exact PNG basename matches from
[LibreQuake revision 3a7d9f1e](https://github.com/lavenderdotpet/LibreQuake/tree/3a7d9f1e3845839747efb666b787f26a0565b1ba/texture-wads).
The files total 1,079,289 bytes. Their paths, dimensions, Git blob identities, and
SHA-256 digests are recorded in the catalog alongside five required notices.

```powershell
pwsh ./scripts/fetch_test_assets.ps1 -CacheRoot $cache `
    -AssetId librequake-e3m4-textures `
    -ManifestPath ./tests/assets/librequake-textures.json
$previousAssetRoot = $env:QB_TEST_ASSET_ROOT
try {
    $env:QB_TEST_ASSET_ROOT = $cache
    python -m pytest tests/test_external_assets.py tests/test_texture_assets.py -v
} finally {
    $env:QB_TEST_ASSET_ROOT = $previousAssetRoot
}
```

The texture revision is newer than the map snapshot. Matching names do not prove
that its art or dimensions match the map's original WADs. Twelve names remain
unresolved, including tool textures and encoded animation or liquid names. The
subset does not establish indexed-palette, fullbright, sky, animation, or compiled
WAD equivalence.

[scripts/blender_asset_images.py](../scripts/blender_asset_images.py) can check
that Blender decodes all cataloged PNGs. [scripts/blender_asset_map.py](../scripts/blender_asset_map.py)
imports the full map through an installed extension and verifies source hashes,
closed brush geometry, source-face provenance, material coverage, and same-process
save/reopen persistence. Both require explicit inputs and isolated output paths.

## Authored compiler fixtures

The repository contains original synthetic Q1, Q2, and GoldSrc fixtures. Their
source generators, WAD/WAL payloads, and deterministic offline validators are
public test tooling, but generated compiler outputs and external executables stay
outside Git and the extension archive.

The optional compiler workflows use
[ericw-tools 2.0.0-alpha11](https://github.com/ericwa/ericw-tools/releases/tag/2.0.0-alpha11).
The validators pin the selected executable and require explicit asset roots. They
do not download or install it. Preserve the compiler distribution's bundled
licenses and notices. See [Testing and validation](testing.md) for the bounded
coverage and public entry points.

## Asset boundary

Do not add retail game payloads, user-supplied maps, generated Blender scenes,
compiler outputs, or raw captures to this repository. Public candidates require
an exact source revision, reviewed redistribution terms, retained notices,
pinned bytes, and a narrow stated purpose before they enter an acquisition
catalog. A tool or engine license does not automatically license its sample data.

For normal development, leave `QB_TEST_ASSET_ROOT` unset and run
`python -m pytest`. See [Testing and validation](testing.md) for the complete
public test workflow.
