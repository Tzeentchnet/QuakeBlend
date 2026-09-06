# Exporting MAP Files

QuakeBlend registers **Quake MAP (.map)** under **File > Export**. It rewrites
a previously imported MAP file and can convert between Quake 1, Quake 2, and
Quake 3 MAP dialects.

## Select the source

Select an object or collection inside the imported MAP that you want to
export. QuakeBlend walks up to the nearest collection containing
`qb_source_map`. If the scene contains exactly one imported MAP collection,
it can use that collection without an explicit selection. When several are
present, select content inside the intended import before exporting.

BSP imports cannot be used as export sources because they do not carry an
original MAP path.

## Source of truth

The exporter re-parses the original `.map` file whose path is stored in the
root collection's `qb_source_map` property. The source game and import scale
come from `qb_source_game` and `qb_import_scale`.

By default, edits to Blender brush or patch geometry and object transforms
are not written to the exported MAP. The exporter converts the original MAP
text, not the generated Blender meshes. An experimental transform-only option
is described below; it does not export vertex or topology edits.

Keep the original MAP available at its recorded path. Export fails if the
file can no longer be read or parsed.

Import visibility does not remove source data. Normal source-based export retains
brushes omitted by Worldspawn Only, Brush Entities, or tool Skip settings, subject
to the explicit export conversion options. Hidden in Viewport keeps the brush
objects and remains eligible for supported transform export. Intentionally
incomplete brush imports are rejected by transform export with a request to
reimport all brushes; partial-transform export is not supported.

## Options

### Target game

**Target game** chooses the output dialect:

- **Auto (source)** uses the game detected or selected when the MAP was
  imported.
- **Quake 1** writes Standard or Valve220 faces without Q2 trailing fields.
  Q3 `brushDef3` brushes are converted to Standard faces.
- **Quake 2** writes Standard or Valve220 faces and always emits
  `contents flags value` for every face. Q3 `brushDef3` brushes are converted
  to Standard faces.
- **Quake 3** permits `brushDef3`, `patchDef2`, and `patchDef3` content.
  Standard faces can also be written unchanged.

For Q1 and Q2 targets, `patchDef3` blocks cannot be converted and are dropped
with a warning. For Q3 targets, they are retained as opaque source blocks.

### Texture projection

**Texture projection** controls serialized brush faces:

- **Auto (per-face)** preserves each parsed face's Standard or Valve220
  syntax.
- **Standard** converts every face to Standard projection.
- **Valve220** converts every face to Valve220 projection.

Some Valve220 axes contain shear or independent rotation that Standard
projection cannot represent exactly. A forced Standard export approximates
those faces and reports warnings identifying the affected source faces.

### Q3 patches

**Q3 patches** controls `patchDef2` output independently of the target game:

- **Tessellate to brushes** is the default. Each tessellated quad becomes a
  thin six-sided brush, with the source texture on top and `skip` on the
  other faces.
- **Drop with warning** omits each patch and reports it.
- **Keep verbatim** retains the original block and is valid only for a Q3
  target. For Q1 or Q2, QuakeBlend warns and falls back to tessellation.

**Patch tessellation level** ranges from 1 to 16 and defaults to `5`.
**Patch extrusion thickness** controls the generated brush depth in Quake
units, ranges from `0.0625` to `64.0`, and defaults to `1.0`.

### Texture map

**Texture map (JSON)** accepts an optional JSON object whose string keys and
values map source texture names to destination names:

```json
{
  "BRICK1": "textures/base_wall/brick1",
  "*": "textures/common/caulk"
}
```

An exact key takes precedence. The optional `"*"` entry is the fallback for
names that are not listed. This is useful when converting short Q1 or Q2
texture names to Q3-style paths. Non-string entries are skipped with a
warning.

Texture remapping inside opaque `patchDef3` blocks is not supported. Such a
block remains unchanged for Q3 output.

### Apply brush transforms (experimental)

This option is off by default. It applies object transforms to source-backed
Q1/Q2 brushes, with textures locked to each brush. It is a restricted prototype,
not an arbitrary Blender-mesh exporter. Original sealed Q1 and Q2 fixtures have
passed independent compiler acceptance after actual Blender transform exports.
The Q2 case also verifies compiled contents, flags, and value. One translated
detail brush in a real 3,441-brush LibreQuake map has also passed BSP29 geometry
and UV checks. Broader transforms, submodels, textured real-map builds, and
real-map viewport acceptance remain unverified.

1. Import the original Q1 or Q2 MAP using this version of QuakeBlend. Older
  imports need reimporting to capture source hashes and mesh baselines.
2. In Object Mode, translate, rotate or positively scale brush objects. Plain
  object parenting is supported when the resulting world matrix has no shear
  or reflection. Moving an entity anchor does not move its brush geometry.
3. Export to a different file, keep the target game the same as the source,
  choose **Valve220** explicitly, and enable **Apply brush transforms
  (experimental)**. Texture remapping is not supported in this mode.

The source file's content hash, recorded scale, import identity, brush ownership,
source-face IDs and baseline mesh signature must still match. Missing, duplicate,
foreign or added mesh objects are rejected. The mode also rejects changed mesh
vertices, topology, loop UVs, material-slot names/assignments, or source face
metadata; modifiers, shape keys, animation, constraints, non-object parenting,
singular transforms, shear and reflections are unsupported. Reimport after
editing the source MAP rather than replacing its provenance properties.

Material shader-node changes do not author MAP texture changes. Original MAP
texture identifiers are retained. The importer records `qb_source_face`,
`qb_texture_width` and `qb_texture_height` face attributes, while the original
projection and face flags are recovered from the fingerprint-matched source.
Do not edit these provenance records manually.

Before writing, the exporter serializes and re-parses the proposed output,
checks brush reconstruction within `0.0001` game units, and checks UV agreement
within `0.001` texture pixels. Large-coordinate edits can fail because of the
writer's numeric precision. Output that changes names/properties under the
current UTF-8 writer and Latin-1 reader is also rejected, including non-ASCII
text that would not round-trip. These checks do not replace compiler validation.

All brushes must pass before the existing atomic writer replaces the destination.
A rejected export leaves existing destination contents and the Blender scene
untouched. This mode refuses to overwrite its source MAP. It does not support
Q3 brushes/patches, BSP sources, new brushes, brush deletion or edit-mode geometry.

Entity edits may be enabled separately. In this mode their anchors must be
unique, unparented, unconstrained and unanimated. Brush transforms and entity
origins are exported independently, without adding an entity origin twice.

### Apply entity edits from scene

**Apply entity edits from scene** is disabled by default. When enabled, the
exporter finds entity anchor objects tagged with `qb_entity_role = "ENTITY"`
and `qb_entity_index`.

For each matching source entity:

- Custom properties named `qb_prop_<key>` replace the corresponding MAP
  property, including `classname`.
- An anchor that had a valid source origin contributes its Blender location,
  divided by the saved import scale, as the new `origin`.
- Location overlays do not apply to `worldspawn` or to entities that did not
  have a valid origin when imported.

Entity overlays do not change the source collection or original MAP file.
They are applied to the in-memory copy being exported.

## Conversion summary

Conversion proceeds in this order:

1. Normalize Q3 `brushDef3` brushes when the target is Q1 or Q2.
2. Keep, tessellate, or drop Q3 patch content according to the selected
   target and patch handling.
3. Apply texture-name remapping.
4. Strip Q2 trailers for Q1, or emit them for Q2.
5. Serialize each face using the selected projection mode.

Warnings and conversion counts are reported in Blender when export finishes.
Errors in brush conversion, patch conversion, source parsing, entity
coordinates, or output writing cancel the export.

## Limitations

- BSP-to-MAP export is not supported.
- Mesh vertex/topology edits and patch edits are not exported. Only the explicit
  experimental mode exports supported brush object transforms.
- The exporter writes MAP text only. It does not write lightmaps, Q3 shader
  files, WAD archives, WAL textures, or image textures.
- Q3 `patchDef3` blocks are not interpreted. They are preserved only for Q3
  output and dropped with a warning for Q1 or Q2.
- Keeping `patchDef2` verbatim is available only for Q3 output.

## See also

- [Importing Quake files](importing.md)
- [Testing and validation](testing.md)
- [Architecture and contributing](architecture.md)
- [Project overview](../README.md)
