# Testing and Validation

QuakeBlend combines pure-Python tests, package validation, a headless Blender
smoke test, and manual viewport checks. Each layer catches a different class
of problem.

## Development setup

Use Python 3.11 or newer from the repository root:

```powershell
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

The development extra installs pytest and Ruff.

## Python tests

Run the complete suite:

```powershell
python -m pytest
```

Run one file or select tests by name:

```powershell
python -m pytest tests/test_map_q1.py
python -m pytest tests/test_map_q1.py -k "test_name"
```

The suite covers the pure-Python format parsers, conversion and serialization,
CSG and patch operations, palettes and texture containers, shared utilities,
packaging, and Blender-facing transaction behavior through test doubles.

The low-level brush transform and serialization probes can be run separately:

```powershell
python -m pytest tests/test_geometry_export_feasibility.py -s
```

They exercise affine brush geometry and texture locking through serialization
and CSG reconstruction. One passing test intentionally reproduces
large-coordinate UV precision loss. The supported production contract and
rejection rules are documented under
[Apply brush transforms](exporting.md#apply-brush-transforms-experimental).

The MAP writer and production transform validator have separate coverage in
[tests/test_map_writer.py](../tests/test_map_writer.py) and
[tests/test_map_transform.py](../tests/test_map_transform.py), including atomic
destination preservation and cleanup, oblique brushes, unsupported transforms,
serialized UV precision loss, strict Latin-1 round-trips, and rejection of
characters outside Latin-1.

The architecture test can be run independently:

```powershell
python -m pytest tests/test_architecture.py -v
```

It parses modules under `quakeblend/formats/` and `quakeblend/utils/` and
fails if they import `bpy`, `bmesh`, or `mathutils`.

Run the same static check used by CI with:

```powershell
ruff check .
```

The Q3 shader parser, asset-preparation tests, and installed shader smoke are
documented in [Quake 3 shader materials](q3-shaders.md). The deferred sky probe
demonstrates a known far-depth mismatch and is intentionally not a non-sky gate.

## Build validation

Exercise the PowerShell fallback build without requiring Blender:

```powershell
pwsh ./scripts/build_extension.ps1 -BlenderExe ""
```

The command should create `dist/quakeblend-<version>.zip`. CI expands this
archive and checks that the manifest, extension package, bundled palettes,
transaction module, and license are present at the expected paths. It rejects
Python caches and source-only content such as `docs/`, `scripts/`, `tests/`,
`.private/`, virtual environments, egg-info, and documentation images.

See [Installing QuakeBlend](installation.md) for Blender-backed builds and
normal installation.

## Headless Blender smoke test

The smoke workflow must run against an installed extension, not directly
against the source package. Use `scripts/blender_acceptance.py` with an explicit
isolated profile and existing config directory. It enables the packaged extension
without writing normal preferences and checks the exact executable version before
running the smoke script. Use a matching `--version` when testing another Blender
runtime. GUI preference tests must not be run in background mode, which bypasses
operator invocation.

The script exercises:

- extension registration and operator availability
- image and material creation
- transaction rollback
- bounded import progress and cleanup after success and rollback failure
- opt-in MAP and Q1/Q2/Q3 BSP replacement, including default duplicates,
  exact-one preflight errors, rollback with the old root intact, orphan ownership
  cleanup, shared materials/images, root-name restoration, merged-world transform
  rejection, and explicit GoldSrc rejection
- synthetic Q1, Q2, and Q3 MAP workflows
- texture-name casing and Q2 face metadata
- BSP and WAD imports, including BSP submodels
- BSP brush-model/material option combinations for Q1/Q2/Q3, including Q3
  submodel patches and Q2 UV dimensions without materials
- GoldSrc v30 dispatch, embedded/WAD3/image texture precedence, masked pixels,
  source-scoped materials, path containment, and BSP-based UV dimensions
- GoldSrc brush origins, light color/energy, camera angles, source metadata,
  material-free world-only imports, and rollback after geometry allocation
- GoldSrc landmark chains, source-local parenting, idempotent placement,
  entity-independent matching, explicit target selection, ambiguous imports,
  incompatible transforms/scales, and rollback after assembly placement
- WAD3 palette colors, masked transparency, and no Quake fullbright emission
  through standalone WAD and MAP imports
- camera forward/up vectors, horizontal FOV, malformed-angle fallbacks, and
  MAP/BSP camera filtering
- MAP export
- Experimental Q1/Q2 brush-transform export with parent transforms, geometry/UV
  comparisons, entity overlays and unchanged default source replay; rejected
  mesh/UV/material edits, missing/duplicate brushes, modifiers, reflections,
  zero scale, shear, changed provenance and precision loss preserve destination bytes
- unregister and re-register behavior

A successful run ends with:

```text
QUAKEBLEND_SMOKE_OK registration materials transaction map progress rollback replacement textures bsp submodels wad export unregister
```

## Large MAP import benchmark

Run `scripts/blender_large_map_benchmark.py` before optimizing the MAP builders.
It generates a deterministic, material-free Quake 1 worldspawn in a unique
temporary directory, imports it through the installed extension, verifies the
operator result and the mode-specific mesh count, then removes the generated
MAP when Blender exits the temporary-directory context. The default is 3,441
disjoint box brushes in `PER_BRUSH` mode; pass `--brushes` for a quicker sanity
run or `--geometry-mode MERGED_WORLD` for the merged comparison. Merged runs
also validate the root's geometry mode, brush list, and face-provenance
attributes.

Use the same isolated, existing profile requirements as the acceptance launcher.
The profile must already contain the extension installed from the archive being
measured. From the repository root, the exact 3,441-brush command is:

```powershell
$blender = "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
$profile = Join-Path $env:TEMP "quakeblend-benchmark-profile"
$config = Join-Path $profile "config"
New-Item -ItemType Directory -Force $config | Out-Null
$env:BLENDER_USER_RESOURCES = $profile
$env:BLENDER_USER_CONFIG = $config
foreach ($geometryMode in @("PER_BRUSH", "MERGED_WORLD")) {
  & $blender --background --factory-startup --python-exit-code 1 `
    --python .\scripts\blender_acceptance.py -- `
    --version 5.0.0 .\scripts\blender_large_map_benchmark.py `
    --brushes 3441 --geometry-mode $geometryMode
  if ($LASTEXITCODE -ne 0) {
    throw "Large MAP benchmark failed for $geometryMode"
  }
}
```

Each successful run emits one `QUAKEBLEND_LARGE_MAP_BENCHMARK` line followed by
a JSON object. `elapsed_import_seconds` times only the synchronous
`bpy.ops.quakeblend.import_map` call; generation, extension enablement, and
validation are outside the interval. `object_count`, `mesh_object_count`, and
`mesh_datablock_count` describe the imported root. The peak-memory value is the
operating system's process-lifetime resident-memory high-water mark after import
(`PeakWorkingSetSize` on Windows or `ru_maxrss` on POSIX), not the import's
incremental allocation. `peak_process_memory_before_import_bytes` helps show
whether import raised that high-water mark.

Treat results as local comparison baselines, not universal performance claims.
Compare runs made with the same Blender build, installed extension build, host,
brush count, and import options. The JSON includes that context plus a hash and
byte count for the generated MAP; `import_options.geometry_mode` distinguishes
the two modes. Factory startup and a fresh Blender process remain important
because the memory high-water mark covers the entire process.

### Observed pre-optimization baseline

The following local observations were recorded on 2026-10-05. They are evidence
that the benchmark completed on this machine, not performance targets for other
systems:

- Blender 5.0.0 release build `a37564c4df7a`, Python 3.11.13
- locally built QuakeBlend 1.3.0 extension from this worktree, installed in an
  isolated profile
- `Windows-10-10.0.26200-SP0`, AMD64 Family 26 Model 68 Stepping 0
  (`AuthenticAMD`), 16 logical CPUs
- Q1 source override, scale `0.03125`, worldspawn only, and material creation
  disabled

| Brushes | Import seconds | Objects | Mesh objects | Mesh datablocks | Peak process bytes | Pre-import peak bytes |
| ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| 16 | 0.126476 | 16 | 16 | 16 | 156,868,608 | 150,753,280 |
| 3,441 | 1.774319 | 3,441 | 3,441 | 3,441 | 436,994,048 | 155,545,600 |

The 16-brush sanity MAP was 6,183 bytes with SHA-256
`d080b6c58c4a759bcb7f92c41abdc29314f7184bf9c9f449b02713634f261499`.
The 3,441-brush baseline MAP was 1,500,944 bytes with SHA-256
`e928aeed9b6fb4e50a9a242e699a9b3fac7f476175f2b5dc8b9d882190669076`.
Both operator results were `FINISHED`.

### Observed merged-world comparison

The following single-run comparison was recorded on 2026-10-05. Both modes used
separate factory-startup processes, the same officially built and installed
QuakeBlend 1.3.0 archive, and the same generated MAP:

- Blender 5.2.2 LTS release build `d13f752e3b9c`, Python 3.13.13
- `Windows-11-10.0.26200-SP0`, AMD64 Family 26 Model 68 Stepping 0
  (`AuthenticAMD`), 16 logical CPUs
- Q1 source override, scale `0.03125`, worldspawn only, material creation
  disabled, and an explicit geometry mode
- 3,441 brushes, 1,500,944 bytes, SHA-256
  `e928aeed9b6fb4e50a9a242e699a9b3fac7f476175f2b5dc8b9d882190669076`

| Geometry mode | Import seconds | Objects | Mesh objects | Mesh datablocks | Peak process bytes | Pre-import peak bytes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `PER_BRUSH` | 1.733040 | 3,441 | 3,441 | 3,441 | 455,110,656 | 181,563,392 |
| `MERGED_WORLD` | 1.115577 | 1 | 1 | 1 | 256,864,256 | 182,652,928 |

On this host, merged worldspawn geometry reduced each object/mesh count by
99.9709% (3,441 to 1). The single observed import was 35.63% faster, the
process-lifetime peak was 43.56% lower, and the increase from each run's
pre-import peak was 72.87% lower (273,547,264 versus 74,211,328 bytes). Both
operator results were `FINISHED`; these timing and memory percentages are local
observations, not performance guarantees.

## Import-option acceptance

`scripts/blender_import_preferences_smoke.py` checks global defaults through actual
RNA operator invocations, explicit overrides, stale last-used options, and unchanged
direct execution. It needs GUI Blender because background mode bypasses `invoke`.
The file selector is intercepted, and no map is imported. Optional `--output-dir`
captures the installed extension's native Preferences panel.

Persistence testing uses `--persist write`, then a separate launch without
`--factory-startup` and with `--persist read`. Both require `BLENDER_USER_CONFIG`
to point to an **existing isolated directory**; the script verifies Blender's
resolved CONFIG path before any save. Set `BLENDER_USER_RESOURCES` to an existing
isolated extension profile as well. Do not rely on that variable alone: a missing
directory can fall back to the normal user configuration. These tests must never
save to the normal Blender profile.

Run these scripts against the rebuilt, installed extension in an isolated profile.
Each output directory must be new. Source-package runs with `--extension-root
quakeblend` are useful during development but do not replace installed acceptance.

```powershell
& $blender --background --factory-startup --python-exit-code 1 --python scripts/blender_import_options_smoke.py -- --output-dir '<new-options-output>'
& $blender --background --factory-startup --python-exit-code 1 --python scripts/blender_q3_shader_smoke.py -- --output-dir '<new-shader-output>'
```

The option matrix covers material-free WAD/WAL/Q3 projection, brushes and patches,
collection organization, content precedence, viewport visibility and persistence,
all BSP variants, GoldSrc parenting, source replay after Skip, and rejection of
incomplete transform exports. Shader checks render Fullbright/Baked/Blender Lighting
against dark baked inputs and controlled lights, preserve vertex alpha, and cross
animation/deformation switches with evaluated fields and rendered animation frames.

The native GUI check opens and closes a separate Blender process. `--presets`
requires an explicitly isolated `BLENDER_USER_RESOURCES` because it writes a native
operator preset. It captures both halves of the actual BSP file-browser sidebar:

```powershell
& $blender --factory-startup --python-exit-code 1 --python scripts/blender_import_options_ui.py -- --extension-root bl_ext.user_default.quakeblend --output-dir '<new-ui-output>' --publication
```

Publication mode creates a minimal synthetic IBSP46 selector input and avoids
user paths, recent files, and privately owned assets. Raw captures should be
written outside the repository; only reviewed documentation images belong in
`docs/images/`.

## Continuous integration

The Windows CI workflow performs two dependent jobs.

The first job uses Python 3.11 to install development dependencies, run Ruff,
run pytest, build the fallback extension archive, validate its contents, and
upload it as an artifact.

The second job installs Blender 5.0.0, downloads and installs that exact
archive, and runs the general and merged-world headless smoke scripts. The job
fails if Blender exits with an error or if either success marker is missing.

The workflow definition is in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml). The smoke entry
points are [`scripts/blender_smoke.py`](../scripts/blender_smoke.py) and
[`scripts/blender_merged_world_smoke.py`](../scripts/blender_merged_world_smoke.py).

## Compiler-produced fixtures

Original Q1 and Q2 fixtures qualify bounded transform-export cases against
independent compiler output. A real LibreQuake follow-up qualifies one translated
detail brush from a 3,441-brush source map using `-notex` placeholder texture
records. A separate LibreQuake visual check imports the full map through
QuakeBlend 1.3.0 and renders its seven source cameras in an extension-disabled
Blender 5.0 process. The GoldSrc connected pair qualifies
embedded/external WAD3 import, nonzero brush origins, palette masking, landmark
stitching, separate-process saved-scene checks, and controlled Blender 5.0 room
and material renders. `scripts/blender_goldsrc_visual.py` checks extension-disabled
scene loading, lit/dark response, masked pixels, repeatability, and embedded versus
external render parity. These use a pinned external compiler and explicit isolated
Blender profiles; they are not run by ordinary pytest and do not require retail
game data. The corresponding public scripts and offline validators contain the
reproducible entry points and bounded assertions.

## Manual viewport checks

The Blender 5.0 test workflow covers the public synthetic workflows, GUI defaults,
and licensed LibreQuake structural import. It does not replace broader manual
checks on assets a user is authorized to inspect.

Headless tests validate structure and behavior, but they do not establish
that real levels look correct. Before publishing a release, import these real
assets and inspect them in the Blender viewport. Retail BSP files do not include
their original editable MAP sources. Use independently licensed source maps for
MAP tests, and keep privately owned game data outside the repository. Public
candidates must be checked for per-asset licensing and texture dependencies;
an engine or compiler license does not automatically cover its sample assets.

See [Public test assets](test-assets.md) for the pinned LibreQuake source fixture,
its partial 71-image texture subset, opt-in acquisition and validation commands,
and the remaining texture/compiler qualification gaps. Ordinary pytest runs do
not download or require these assets.

| Test | Sample | What to check |
|---|---|---|
| Q1 MAP | A licensed Q1 source map, such as a qualified LibreQuake map | Brushes are solid, faces are UV-aligned, and lights are placed correctly |
| Q1 BSP | A lawfully obtained BSP29 level | The world mesh is visible, submodels are separate, and entities and lights are objects |
| Q1 WAD | A lawfully obtained WAD2 archive | Expected textures appear as materials |
| Q2 MAP | A licensed Q2 source map with explicit face metadata | Brushes render correctly and `qb_face_flags` is present on brush objects |
| Q2 BSP | A lawfully obtained IBSP38 level and its WAL tree | WAL textures load and documented material rules apply |
| Q3 MAP | Licensed source fixtures containing each supported primitive | `patchDef2` surfaces are tessellated and `brushDef3` brushes render as geometry |
| Q3 BSP | A lawfully obtained IBSP46 level and prepared dependencies | Triangle soups, patches, and mesh vertices all draw |
| GoldSrc BSP | A lawfully obtained v30 map with embedded and external textures | WAD3 colors, masked surfaces, UVs, and brush origins agree with the source; unsupported rendering features remain documented |
| GoldSrc stitching | Two lawfully obtained connected v30 maps | Matching landmarks coincide; geometry, lights and cameras translate together; duplicate imports require an explicit target |
| Reload | Repeat any import | Materials are reused and no Python errors occur |

## See also

- [Architecture and contributing](architecture.md)
- [Installing QuakeBlend](installation.md)
- [Project overview](../README.md)
