# Copilot Instructions for QuakeBlend

## Build & Test

```powershell
# Run all pure-Python tests
python -m pytest

# Run a single test file
python -m pytest tests/test_map_q1.py

# Run a single test by name
python -m pytest tests/test_map_q1.py -k "test_name"

# Build the Blender extension zip
pwsh ./scripts/build_extension.ps1
```

No linter is configured. Tests use plain pytest with `addopts = "-q"` and `pythonpath = ["."]`.

## Architecture

The codebase has a strict two-layer separation:

- **`quakeblend/formats/`** — Pure Python parsers for Quake file formats (MAP, BSP, WAD, WAL, patches). **Must never import `bpy`, `bmesh`, or `mathutils`.** This layer is tested with pytest under a standard Python interpreter.
- **`quakeblend/blender/`** — Blender operators, mesh/material builders, UI, and preferences. Imports `bpy` and depends on the formats layer.
- **`quakeblend/utils/`** — Shared constants and logging. No `bpy` imports; safe for both layers.

This separation exists so parsers remain testable without a Blender runtime.

### Import pipeline flow

1. **Operator** (`blender/importer_*.py`) — registers the Blender file-browser operator and collects user options.
2. **Runner** (`blender/import_runner_*.py`) — orchestrates the import: calls the parser, then the builders.
3. **Parser** (`formats/*.py`) — reads the file and returns dataclasses (brushes, entities, faces, etc.).
4. **Builders** (`blender/builder_*.py`) — convert parsed data into Blender objects/materials/lights.

### Export pipeline

The MAP exporter (`blender/exporter_map.py`) re-parses the original `.map` file (path stored on collection as `qb_source_map`) and rewrites it with optional cross-game conversion via `formats/map_convert.py` and `formats/map_writer.py`.

## Key Conventions

- **`from __future__ import annotations`** is used at the top of every module.
- **Frozen dataclasses** for parsed data structures (see `formats/common.py` `Vec3`).
- **`Vec3`** is a hand-rolled vector type (not `mathutils.Vector`) so parsers stay bpy-free.
- Custom properties on Blender objects use the `qb_` prefix (e.g., `qb_source_map`, `qb_entity_index`, `qb_patch_control_grid`, `qb_prop_<key>`).
- Constants live in `quakeblend/utils/constants.py`; add new project-wide constants there.
- The extension targets **Blender 5.0+** and uses the extension manifest format (`blender_manifest.toml`), not the legacy `bl_info` dict.
- Python 3.11+ is required.
