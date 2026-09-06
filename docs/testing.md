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

The production transform validator has separate coverage in
[tests/test_map_transform.py](../tests/test_map_transform.py), including oblique
brushes, unsupported transforms, serialized UV precision loss and encoding
round-trip rejection.

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
QUAKEBLEND_SMOKE_OK registration materials transaction map rollback textures bsp submodels wad export unregister
```

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
archive, and runs the headless smoke script. The job fails if Blender exits
with an error or if the success marker is missing.

The workflow definition is in
[`.github/workflows/ci.yml`](../.github/workflows/ci.yml), and the smoke test
is in [`scripts/blender_smoke.py`](../scripts/blender_smoke.py).

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
