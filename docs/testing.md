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

## Build validation

Exercise the PowerShell fallback build without requiring Blender:

```powershell
pwsh ./scripts/build_extension.ps1 -BlenderExe ""
```

The command should create `dist/quakeblend-<version>.zip`. CI expands this
archive and checks that the manifest, extension package, bundled palettes,
transaction module, and license are present at the expected paths. It also
rejects `__pycache__` directories and `.pyc` files.

See [Installing QuakeBlend](installation.md) for Blender-backed builds and
normal installation.

## Headless Blender smoke test

The smoke workflow must run against an installed extension, not directly
against the source package. Set the path for an installed Blender 5.x build,
build the archive with that executable, install it, and run the script:

```powershell
$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
pwsh ./scripts/build_extension.ps1 -BlenderExe $blender
$zip = (Get-ChildItem ./dist/quakeblend-*.zip |
  Sort-Object LastWriteTime -Descending |
  Select-Object -First 1).FullName
& $blender --command extension install-file -r user_default -e $zip
& $blender --background --python scripts/blender_smoke.py -- `
  --extension-root bl_ext.user_default.quakeblend
```

The script exercises:

- extension registration and operator availability
- image and material creation
- transaction rollback
- synthetic Q1, Q2, and Q3 MAP workflows
- texture-name casing and Q2 face metadata
- BSP and WAD imports, including BSP submodels
- MAP export
- unregister and re-register behavior

A successful run ends with:

```text
QUAKEBLEND_SMOKE_OK registration materials transaction map rollback textures bsp submodels wad export unregister
```

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

## Manual viewport checks

Headless tests validate structure and behavior, but they do not establish
that real levels look correct. Before publishing a release, import these real
assets and inspect them in the Blender viewport:

| Test | Sample | What to check |
|---|---|---|
| Q1 MAP | `e1m1.map` (id1) | Brushes are solid, faces are UV-aligned, and lights are placed correctly |
| Q1 BSP | `start.bsp` | The world mesh is visible, submodels are separate, and entities and lights are objects |
| Q1 WAD | `quake.wad` (id1) | All textures appear as materials |
| Q2 MAP | `base1.map` | Brushes render correctly and `qb_face_flags` is present on brush objects |
| Q2 BSP | `base1.bsp` | WAL textures load and fullbright and sky materials emit |
| Q3 MAP | `q3dm1.map` | `patchDef2` surfaces are tessellated and `brushDef3` brushes render as geometry |
| Q3 BSP | `q3dm1.bsp` | Triangle soups, patches, and mesh vertices all draw |
| Reload | Repeat any import | Materials are reused and no Python errors occur |

## See also

- [Architecture and contributing](architecture.md)
- [Installing QuakeBlend](installation.md)
- [Project overview](../README.md)