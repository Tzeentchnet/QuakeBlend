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

This has an important consequence: edits to Blender brush or patch geometry
are not written to the exported MAP. The exporter converts the original MAP
text, not the generated Blender meshes.

Keep the original MAP available at its recorded path. Export fails if the
file can no longer be read or parsed.

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
- Blender-side brush and patch geometry edits are not exported.
- The exporter writes MAP text only. It does not write lightmaps, Q3 shader
  files, WAD archives, WAL textures, or image textures.
- Q3 `patchDef3` blocks are not interpreted. They are preserved only for Q3
  output and dropped with a warning for Q1 or Q2.
- Keeping `patchDef2` verbatim is available only for Q3 output.

## See also

- [Importing Quake files](importing.md)
- [Architecture and contributing](architecture.md)
- [Project overview](../README.md)