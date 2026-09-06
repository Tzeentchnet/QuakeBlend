# Importing Quake Files

QuakeBlend imports Quake 1, Quake 2, and Quake 3 level data and textures, plus
GoldSrc BSP v30 levels, into Blender. Its operators are available under
**File > Import**.

## Global defaults

Open **Edit > Preferences > Add-ons**, expand **QuakeBlend**, and configure
**Import Defaults**, **Tool Geometry**, **Quake 3**, and **GoldSrc BSP** beneath
the existing texture/WAD paths. These settings initialize new MAP/BSP file-browser
imports. Save Preferences if Blender's automatic preference saving is disabled.

MAP and BSP lighting have separate defaults: Blender Lighting for MAP, Fullbright
for BSP. The MAP lighting selector does not offer Baked. Clip/hint defaults apply
only to MAP; landmark stitching applies only to GoldSrc BSP. Source-game selection
and the scene-specific stitch target remain per-import choices.

Explicit arguments supplied to an interactive invocation override preferences.
After the dialog opens, per-import edits and loaded operator presets take
precedence and do not change global defaults. Reopening the importer uses the
global defaults again, not its previous unsaved option values. Direct scripted
`bpy.ops.quakeblend.import_map(...)` / `import_bsp(...)` execution retains the
operator's built-in defaults and explicit arguments; asset-path fallback behavior
is unchanged. Preferences never alter existing imported scenes.

## Content and visibility

MAP and BSP dialogs group options into Source, Content, Materials, Tool Geometry,
and applicable game-specific panels. Native Blender operator presets retain the
new settings. Disabled controls retain their values.

- **Worldspawn Only** is off by default. It excludes non-world brush geometry
  and all entity objects, including lights and cameras.
- **Collections** is on by default. It organizes objects in subcollections.
  Turning it off links objects directly to the import root without changing
  transforms or parenting. GoldSrc assembly roots are preserved.
- **Brush Entities** is on by default and controls non-world brush geometry,
  independently of **Entity Objects**. Lights and cameras remain subordinate
  to Entity Objects. These switches are overridden by Worldspawn Only.
- **Create materials** is on by default. Disabling it creates no materials or
  images, including placeholders, while retaining source geometry and UVs.
  Texture and WAD paths remain available for projection sizes and tool metadata.
- **Triggers** offers Visible, Hidden in Viewport, and Skip for MAP and BSP.
  MAP additionally offers **Clip Brushes** and **Hint Brushes**. All default to
  **Hidden in Viewport**, using the Outliner eye state without changing render
  visibility. Reveal these objects in the Outliner when needed.

Tool classification uses entity ownership, game-specific contents/shader metadata,
and exact tool texture names. Mixed ordinary/tool textures, conflicting semantics,
and failed metadata reads remain visible with diagnostics. Sky, liquids and
ordinary names containing `clip` or `hint` are not hidden by these filters.
Brushes are handled whole; individual CSG planes are never removed. BSP imports
do not reconstruct source clip/hint brushes or trigger volumes absent from draw
geometry. Worldspawn/content exclusions take precedence over tool visibility.

Import roots record settings in `qb_import_options` and tool-object counts in
`qb_tool_counts`. Imported tools carry `qb_tool_categories` and `qb_tool_handling`.
Skip differs from hiding: [transform export](exporting.md) requires a complete
brush import, while normal source-based export still retains skipped source data.

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
- **WAD files** accepts a semicolon-separated list of Quake WAD2 or Half-Life
  WAD3 archives.
  When blank, QuakeBlend uses the default WAD from its add-on preferences.
- **Entity Objects** creates Blender objects for MAP entities in addition to
  importing their brush geometry. It is enabled by default.
- **Lights** controls entities whose classname begins with `light`. It
  is enabled by default and only applies when entity import is enabled.
- **Cameras** controls player-start and intermission camera entities.
  It is enabled by default and only applies when entity import is enabled.
  Disabling it skips those entities rather than replacing them with empties.
- **Light Energy** scales converted point-light wattage. Its
  default is `1.0`.
- **Patch Detail** controls Q3 `patchDef2` subdivision from 1 to
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

Synthetic parser, importer, exporter, and compiler-fixture tests cover retained
Q2 trailers and polygon-to-source association. Texture dimensions and appearance
still depend on the corresponding WAL files.

### Q3 brushes and patches

**Q3 materials** defaults to **Shaders** for both MAP and BSP imports. Set
**Texture root** to a prepared folder containing `scripts/`, `textures/`, and
any referenced model image directories, retaining original resource paths.
The [asset-preparation tool](../scripts/prepare_q3_assets.py) can create a selective
subset from a local package set that you are authorized to use. PK3 browsing is
not part of the importer.

Shader mode resolves definitions before same-name images, supports packed
animation frames, UV motion, vertex waves, ordered blending and alpha tests.
MAP projection dimensions use the editor image, or first runtime image, even
with materials disabled. WAD/WAL and loose-image dimensions are likewise retained;
missing or invalid dimensions produce a warning and the 64x64 fallback.

**Lighting** in shader mode offers:

- **Fullbright**, the Q3 BSP default: composed unlit shader colors without baked
  lightmap or vertex-RGB darkening. No lightmap images are created and no scene
  lights are needed. Texture/vertex alpha and supported glow remain intact.
- **Blender Lighting**, the Q3 MAP default: removes the same baked inputs, but
  lets scene lights illuminate lit stages. Additive/unlit stages retain their
  shader behavior. This mode can be dark without suitable Blender lights.
- **Baked**, BSP only: retains the previous lightmap and vertex-color appearance
  without applying additional scene lighting to the composed result.

**Animation** controls texture frames, UV motion and stage color/alpha waves.
Disabling it freezes stage time at zero, including the first animation frame,
while retaining static UV transforms. **Deformation** independently controls
supported vertex waves. Both are on by default; disabling deformation leaves
the original mesh unchanged and does not disable UV animation.

**Direct images** retains legacy same-name-image behavior; shader lighting and
effect controls are inactive there. Explicitly select **Source game: Quake 3**
for ambiguous MAP files. New defaults affect new imports, not existing materials
or saved scenes. The importer never changes the World, exposure or view transform.

Sky rendering is deferred and remains a labeled placeholder. Unsupported shader
features also produce warnings and diagnostic placeholders. The current shader
pipeline does not reproduce Q3 hardware gamma/overbright settings; Baked may look
darker than the game. See [Quake 3 shader materials](q3-shaders.md) for supported
stages, animation behavior, asset preparation, and remaining limitations.

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
- GoldSrc BSP version 30

The BSP operator provides **Scale**, **Texture root**, **Entity Objects**,
**Lights**, **Cameras**, **Light Energy**, and **Patch Detail**. Their defaults
and behavior match the MAP importer. Q2 and Q3 BSP
imports use the texture root for `.wal`, `.tga`, `.jpg`, `.jpeg`, and `.png`
files.

The shared geometry/material controls also apply to BSP:

- **Brush Entities** includes all submodels beyond worldspawn. Disable
  it to import only world geometry, including only world-owned Q3 patches.
  This does not disable separately enabled point entities, lights or cameras.
- **Create materials** builds texture images and materials. Disable it to
  import geometry and UVs without creating image or material datablocks.
  Q2 still reads available WAL textures to determine UV dimensions; missing
  dimensions use the existing 64-by-64 fallback.

The BSP models lump is honored. World geometry and entity-owned submodels are
created separately, so moving brushes such as `func_door`, `func_plat`, and
trigger models are not welded into the world mesh. Each generated object is
tagged with `qb_bsp_model_index`; an entity-owned model also receives the
owner's `qb_prop_<key>` values.

Q3 triangle soups, mesh vertices, and curved patch faces are converted to
Blender geometry. Patch faces use the operator's tessellation level.

### GoldSrc BSP

Use the same **Quake BSP (.bsp)** operator for GoldSrc v30 files. Texture
resolution follows this order:

1. Embedded BSP miptexture and palette.
2. **GoldSrc WAD files**, a semicolon-separated list of WAD3 archives searched
  in order, with case-insensitive texture names. A blank field uses the
  default WAD preference; WAD2 archives are rejected for this path.
3. Images under **Texture root**, including `.tga`, `.jpg`, `.jpeg`, and `.png`.
4. Source-scoped magenta placeholders for unresolved texture slots.

Only explicitly configured paths are searched. The worldspawn `wad` property
is retained as metadata, not followed automatically. Image lookup cannot escape
the configured texture root. UV projection always uses the BSP texture header's
dimensions, even when replacement textures have different sizes.

Embedded and WAD3 palettes have no Quake fullbright emission. Texture names
beginning with `{` use masked transparency; palette index 255 is transparent.
Brush-owned models receive their entity origin once, without adding the model
lump origin again. Brush owners do not also create duplicate point empties.
Brush rotations, movement, and render effects are not simulated.

GoldSrc point lights decode `_light` as a scalar intensity, three RGB
intensities, or RGB bytes plus a fourth intensity. Three-component values use
their maximum component as intensity and normalize the color accordingly.
The scale-aware watt conversion below is an approximation, not a reproduction
of compiler radiosity or engine lighting. Unsupported directional/targeted
lights become tagged empties with a warning. Render modes and effects are
metadata only. GoldSrc cameras prefer `angles` over `mangle` and yaw `angle`.

Root collections retain `qb_source_bsp`, `qb_source_game`, `qb_import_scale`,
`qb_import_id`, `qb_map_name`, and the raw `qb_bsp_entities` string. Entity
metadata remains available when visible entity import is disabled.

This support does not include rendered BSP lightmaps, texture animation,
MDL/sprite assets, BSP export, or GoldSrc MAP export.
Imported BSP collections are not eligible for the source-backed MAP exporter.

### GoldSrc landmark stitching

Each GoldSrc import has an Assembly Empty that parents its geometry and entity
objects. Child coordinates remain local to the source map, including brush
origins. Move the Assembly Empty to place a whole map together.

1. Import an anchor GoldSrc map normally. Its Assembly Empty may be translated
  to the desired scene location.
2. Import a connected map with **Stitch Landmarks** enabled. This
  option is off by default and applies only to GoldSrc BSP imports.
3. Leave **Stitch target** set to **Automatic** for unambiguous connections,
  or choose a specific imported collection when several instances match.

Matching uses stored `trigger_changelevel` map/landmark keys and corresponding
named `info_landmark` origins. A connection in either direction is sufficient.
Map names are case-insensitive, with an optional `.bsp` suffix; landmark names
must match exactly. Renaming a collection does not change its source identity.
Matching works with visible entities, lights, cameras, or brush models disabled.

Only the new Assembly Empty is translated. Existing maps are not moved. Multiple
connections must agree within `0.0001` game units on each axis. Missing or
duplicate landmarks, conflicting offsets, or ambiguous imported instances cause
a warning and leave the new map at its unstitched position. Selecting an explicit
target restricts matching to that instance. No connection is guessed from import
order or collection display names.

Connected maps must use the same import scale. Assembly roots must have an
identity world rotation/scale, no parent, constraints or animation, and no delta
translation. Stitching uses root translation, not manual edits to child objects.
Imports made before assembly-root support should be reimported before stitching.
Only imported collections in the current scene are considered.

Successful imports record the absolute scene translation in `qb_stitch_offset`
and newline-separated target import IDs in `qb_stitch_targets`. Source metadata
stays unchanged, and stitching does not enable MAP export. This is translation
alignment only, not geometry merging or simulation of level transitions.

## Quake textures

Use **Import Quake textures** to load either a WAD2/WAD3 archive (`.wad`) or
one Quake 2 WAL texture (`.wal`).

The **Create materials** option is enabled by default. It creates one Blender
material per imported texture. Disable it to import only the decoded images.
WAD2 textures use QuakeBlend's bundled Q1 palette; WAD3 textures can use an
embedded palette without Quake fullbright indices. WAD2 and WAD3 miptexture
directory types are decoded separately. WAL textures use the bundled Q2 palette.

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

- Quake classnames beginning with `light` become point lights. `_color`
  supplies their color when valid. GoldSrc uses the rules above.
- Player starts, deathmatch starts, cooperative starts, and intermission
  points become cameras with a 90-degree horizontal field of view.
- Other point entities become empties.

Camera orientation uses `mangle` pitch/yaw/roll when present, otherwise
`angle` yaw. Positive pitch looks downward; roll is applied around the
viewing axis. Invalid `mangle` values produce a warning and fall back to
`angle`; an invalid yaw falls back to zero. Importing cameras does not
change the active scene camera.

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
