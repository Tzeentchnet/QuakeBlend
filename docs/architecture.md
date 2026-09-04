# Architecture and Contributing

QuakeBlend separates file-format logic from Blender integration so parsing,
conversion, and serialization remain testable in a standard Python runtime.

## Repository layers

### `quakeblend/formats/`

This is the pure-Python format layer. It contains MAP, BSP, WAD, WAL, palette,
entity, patch, CSG, conversion, and serialization code. It must not import
`bpy`, `bmesh`, or `mathutils`.

Parsed values use standard Python types and frozen dataclasses. For example,
`Vec3` is a small project-owned vector type rather than
`mathutils.Vector`. This keeps parser output usable outside Blender.

### `quakeblend/blender/`

This is the Blender integration layer. It contains file-browser operators,
import runners, the MAP exporter, mesh and material builders, entity builders,
preferences, transactions, and UI registration. Modules here may import
`bpy` and consume values returned by the format layer.

### `quakeblend/utils/`

This layer contains constants, logging, and path helpers shared by both other
layers. It follows the same no-Blender-import rule as the format layer.

### Supporting directories

- `quakeblend/data/` contains the bundled Q1 and Q2 palettes.
- `tests/` contains tests that run under a standard Python interpreter.
- `scripts/` contains extension packaging and installed-Blender smoke tools.
- `.github/workflows/` defines continuous integration.

## Import pipeline

An import follows four primary stages:

1. An operator in `quakeblend/blender/importer_*.py` registers the file
   browser and gathers user options.
2. A runner in `quakeblend/blender/import_runner_*.py` chooses the format,
   calls parsers, resolves assets, and coordinates object creation.
3. A parser in `quakeblend/formats/` reads the source and returns ordinary
   Python values and dataclasses.
4. Builders in `quakeblend/blender/builder_*.py` turn parsed geometry,
   materials, and entities into Blender datablocks.

Each operator wraps its runner in `ImportTransaction`. If the runner raises,
the transaction removes datablocks created during that import and leaves
pre-existing Blender data intact.

## Export pipeline

MAP export intentionally does not reconstruct source brushes from Blender
meshes. Instead it:

1. Finds the selected import root through its `qb_source_map` property.
2. Re-parses the original MAP file with the format layer.
3. Optionally overlays supported entity properties and origins from scene
   anchors.
4. Applies cross-game conversion through `formats/map_convert.py`.
5. Serializes the result through `formats/map_writer.py`.

See [Exporting MAP files](exporting.md) for user-facing behavior and
limitations.

## Blender data contracts

QuakeBlend custom properties use the `qb_` prefix. These properties retain
source identity and metadata needed across modules without mixing project
keys with Blender's own names. Examples include:

- `qb_source_map`, `qb_source_game`, and `qb_import_scale` on MAP roots
- `qb_entity_index` and `qb_prop_<key>` on entity anchors
- `qb_bsp_model_index` on BSP geometry
- `qb_patch_control_grid` and `qb_patch_size` on imported patches

When extending these contracts, preserve existing property meanings so saved
Blender files remain usable by later versions.

## Registration and packaging

The package root imports Blender-facing modules lazily during `register()`.
This allows `quakeblend.formats` and `quakeblend.utils` to be imported by
pytest without a Blender runtime. Modules are unregistered in reverse order.

QuakeBlend targets Blender 5.0+ and uses the Blender extension manifest in
`blender_manifest.toml`. It does not use the legacy `bl_info` add-on format.
The manifest and `quakeblend/__init__.py` become siblings at the root of the
built archive.

Implementation modules that define annotations use
`from __future__ import annotations`. Project-wide constants belong in
`quakeblend/utils/constants.py`, provided that doing so does not introduce a
Blender dependency.

## Enforced boundaries

`tests/test_architecture.py` parses every Python file directly under
`quakeblend/formats/` and `quakeblend/utils/`. It reports imports of `bpy`,
`bmesh`, or `mathutils` as architecture violations.

Run this check with:

```powershell
python -m pytest tests/test_architecture.py -v
```

Broader commands and the Blender smoke workflow are documented in
[Testing and validation](testing.md).

## Contributing

Issues and pull requests are welcome at the
[QuakeBlend repository](https://github.com/Tzeentchnet/QuakeBlend).

When changing the project:

- Keep parsing, validation, conversion, and serialization independent of
  Blender whenever they do not require Blender state.
- Do not import Blender modules from `quakeblend/formats/` or
  `quakeblend/utils/`.
- Add focused pure-Python tests for format behavior and update the installed
  Blender smoke test when a user workflow crosses the integration boundary.
- Use the existing operator, runner, parser, and builder responsibilities
  instead of bypassing layers for convenience.
- Prefix new Blender custom properties with `qb_` and document persistent
  data-contract changes.

## See also

- [Testing and validation](testing.md)
- [Importing Quake files](importing.md)
- [Project overview](../README.md)