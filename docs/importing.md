# Importing Quake Files

QuakeBlend imports Quake 1, Quake 2, and Quake 3 level data and textures into
Blender. After installation, its operators are available under
**File > Import**.

## Quake MAP

Use **Quake MAP (.map)** to import text-based Q1, Q2, or Q3 MAP files. Brushes
are converted from CSG planes into Blender meshes.

### Options

- **Scale** controls the world-unit conversion. The default is `1/32`, so 32
  Quake units become one Blender meter.
- **Source game** selects `Auto`, `Quake 1`, `Quake 2`, or `Quake 3`. Auto
  detects Q2 face trailers, Q3 `brushDef3` and `patchDef2` blocks, and
  path-like Q3 shader names. Ambiguous files fall back to Q1 behavior.
- **Texture root** selects a folder searched recursively for external Q2 WAL
  and Q3 image textures. When blank, QuakeBlend uses the default texture root
  from its add-on preferences.
- **WAD files** accepts a semicolon-separated list of Q1 WAD2/WAD3 archives.
  When blank, QuakeBlend uses the default WAD from its add-on preferences.
- **Import entities** creates Blender objects for MAP entities in addition to
  importing their brush geometry. It is enabled by default.
- **Import lights** controls entities whose classname begins with `light`. It
  is enabled by default and only applies when entity import is enabled.
- **Light energy multiplier** scales converted point-light wattage. Its
  default is `1.0`.
- **Patch tessellation level** controls Q3 `patchDef2` subdivision from 1 to
  16 segments per Bezier span. Its default is `5`.

Standard and Valve220 texture projection are detected independently for each
face. The root collection records the file summary as `qb_source_projection`,
whose value is `standard`, `valve220`, or `mixed`. It also stores the source
path, detected game, and import scale as `qb_source_map`, `qb_source_game`,
and `qb_import_scale` for later MAP export.

When **Source game** is Auto, external texture lookup probes both WAL and
image formats because an otherwise ordinary Q3 MAP can be syntactically
ambiguous. Selecting Q2 or Q3 explicitly restricts lookup to that game's
texture format.

### Q2 face metadata

Quake 2 MAP `contents flags value` trailers are parsed and retained for
export. Brush objects expose values in source-face order through:

- `qb_face_textures`, a newline-separated texture-name list
- `qb_face_contents`, an integer array
- `qb_face_flags`, an integer array
- `qb_face_value`, an integer array

These arrays follow source brush faces, not generated mesh polygons. CSG can
discard a source face when it is clipped away, so the two orders are not
interchangeable.

### Q3 brushes and patches

Q3 `brushDef3` brushes are converted to mesh geometry. Their texture matrices
are decomposed into Standard projection parameters for UV generation.

Q3 `patchDef2` surfaces are tessellated into meshes at the selected level.
Each patch object stores its original data for future round-trip work:

- `qb_patch_texture` contains the source texture name.
- `qb_patch_size` contains the control-grid width and height.
- `qb_patch_control_grid` contains one `[x, y, z, u, v]` array per control
  point in row-major order.

## Quake BSP

Use **Quake BSP (.bsp)** for compiled levels. QuakeBlend detects the format
from its header:

- Quake 1 BSP version 29
- Quake 2 IBSP version 38
- Quake 3 IBSP version 46

The BSP operator provides **Scale**, **Texture root**, **Import entities**,
**Import lights**, **Light energy multiplier**, and **Patch tessellation
level**. Their defaults and behavior match the MAP importer. Q2 and Q3 BSP
imports use the texture root for `.wal`, `.tga`, `.jpg`, `.jpeg`, and `.png`
files.

The BSP models lump is honored. World geometry and entity-owned submodels are
created separately, so moving brushes such as `func_door`, `func_plat`, and
trigger models are not welded into the world mesh. Each generated object is
tagged with `qb_bsp_model_index`; an entity-owned model also receives the
owner's `qb_prop_<key>` values.

Q3 triangle soups, mesh vertices, and curved patch faces are converted to
Blender geometry. Patch faces use the operator's tessellation level.

## Quake textures

Use **Import Quake textures** to load either a WAD2/WAD3 archive (`.wad`) or
one Quake 2 WAL texture (`.wal`).

The **Create materials** option is enabled by default. It creates one Blender
material per imported texture. Disable it to import only the decoded images.
WAD2 textures use QuakeBlend's bundled Q1 palette; WAD3 textures can use an
embedded palette. WAL textures use the bundled Q2 palette.

## Texture resolution and materials

MAP texture names are matched case-insensitively, including names whose case
does not match the entry in a WAD. External texture folders are indexed once
per import and searched recursively.

QuakeBlend supports these material behaviors:

- Q1 and Q2 indexed-color fullbright pixels contribute emission.
- Q2 light, sky, and transparency surface flags affect generated materials.
- Q2 warp and flowing flags are parsed but are not currently applied to
  Blender materials.
- Missing or unreadable textures use a packed magenta placeholder material
  instead of borrowing an unrelated material slot.

Materials and images carry stable source keys. Importing the same assets again
reuses them rather than creating duplicate datablocks.

## Entities and lights

Entities with valid origins become native Blender objects:

- Classnames beginning with `light` become point lights. `_color` supplies
  their color when valid.
- Player starts, deathmatch starts, cooperative starts, and intermission
  points become cameras.
- Other point entities become empties.

Every imported entity key/value pair is retained as a `qb_prop_<key>` custom
property. MAP entity anchors are also tagged with `qb_entity_role` and
`qb_entity_index` so supported changes can be applied during
[MAP export](exporting.md).

Quake light values represent intensity in Quake-unit space. QuakeBlend
converts them to Blender point-light watts using:

```text
watts = light * 4 * pi * scale^2 * light_energy_multiplier
```

A missing or invalid light value defaults to `300`. At the default `1/32`
scale and `1.0` multiplier, that becomes approximately `3.7 W`.

## Collections, re-imports, and failures

Each import creates a new root collection. Importing `e1m1` twice therefore
creates collections such as `e1m1` and `e1m1.001`; it does not replace the
first import. Existing materials and images are reused when their source keys
match.

Imports run inside a transaction. If an import raises an error, QuakeBlend
removes the collections, objects, meshes, materials, images, lights, and
cameras created by that operation. Datablocks that existed before the import
are left untouched.

## See also

- [Exporting MAP files](exporting.md)
- [Installing QuakeBlend](installation.md)
- [Project overview](../README.md)