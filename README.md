# QuakeBlend

Blender 5.0+ extension for importing **Quake 1, 2, and 3** map data and textures.

Repository: <https://github.com/Tzeentchnet/QuakeBlend>

## Features

* **Import Quake 1, 2, and 3** `.map` and `.bsp` files — auto-detects the
  BSP version (v29 / IBSP v38 / IBSP v46) and the MAP texture projection
  (Standard vs Valve220) per face.
* **CSG brush → mesh conversion** for `.map` files, including Quake 3
  `brushDef3` brushes (texture matrix decomposed into Standard UV
  parameters) and `patchDef2` Bezier patches (tessellated at a configurable
  subdivision level).
* **Full texture pipeline** for all three games: Quake 1 WAD2/WAD3 archives,
  Quake 2 `.wal` textures (sky, fullbright, and transparency surface flags
  honored; warp/flowing flags are parsed but not animated), and Quake 3
  `.tga`/`.jpg`/`.png` images — resolved from a
  configurable *Texture Root* folder or add-on preference. Q2 `contents
  flags value` MAP trailing fields are parsed and propagated best-effort.
* **Entity import** as native Blender objects: point lights (energy/color
  from the `light`/`_color` keys), cameras for player starts, and empties
  for everything else, with every key/value pair preserved as a custom
  property.
* **MAP export with cross-game conversion** (Q1 ↔ Q2 ↔ Q3): re-parses the
  original source file, adds/strips trailing `contents flags value` fields,
  converts `brushDef3` faces to Standard faces, tessellates or drops
  `patchDef2` patches, remaps texture names via an optional JSON mapping,
  and can fold Blender-side entity origin/property edits back into the
  output.
* **Configurable world scale** (default 1/32 — 32 Quake units per Blender
  metre) on every import/export operator.

## Install

### From a release zip

Grab `quakeblend-*.zip` from the
[Releases](https://github.com/Tzeentchnet/QuakeBlend/releases) page (or build
your own — see below), then in Blender 5.0+ open
*Edit → Preferences → Get Extensions → ⌄ menu → Install from Disk* and pick
the zip.

### From source

```powershell
git clone https://github.com/Tzeentchnet/QuakeBlend.git
cd QuakeBlend
pwsh ./scripts/build_extension.ps1
```

The build script writes `dist/quakeblend-<version>.zip`. If the
`BLENDER_EXE` environment variable points at a Blender executable the
official `blender --command extension build` is used; otherwise it falls
back to `Compress-Archive`.

## Usage

After installing, three import operators appear under *File → Import*:

* **Quake MAP (.map)** — import any Q1/Q2/Q3 `.map` text file. Operator
  options:
  * *Scale* — world-unit scale (default `1/32`).
  * *Source game* — `Auto` detects Q2/Q3-specific syntax, or choose Q1/Q2/Q3
    explicitly for ambiguous files. Standard vs Valve220 projection is always
    detected per face.
  * *Texture root* — folder indexed recursively once per import for external
    textures. Quake 2 `.wal` and Quake 3 image textures (`.tga` / `.jpg` /
    `.jpeg` / `.png`) are matched case-insensitively by face-texture name.
    Falls back to the add-on preference when blank.
  * *WAD files* — semicolon-separated list of Quake 1 `.wad` files.
  * *Import entities* / *Import lights* — toggle non-brush entities and
    `light*` classnames respectively.
  * *Patch tessellation level* — Q3 `patchDef2` subdivision (1–16, default
    `5`). `brushDef3` brushes are converted to mesh geometry automatically
    (texture matrix decomposed to Standard UV parameters).
  Quake 3 patches are tessellated to mesh and the original control grid is
  stored in `obj["qb_patch_control_grid"]` for future round-trip.
* **Quake BSP (.bsp)** — auto-detects Q1 (v29), Q2 (IBSP v38), Q3 (IBSP v46).
  For Q2/Q3 supply a *Texture Root* folder containing the `.wal` or
  `.tga` / `.jpg` / `.png` texture files.
* **Quake WAD (.wad)** — load a WAD2/WAD3 archive as a set of materials.

If an import fails, QuakeBlend removes collections, objects, meshes, materials,
images, lights, and cameras created by that operation. Existing Blender data is
left untouched.

### Exporting MAP files

A single export operator is registered under *File → Export*: **Quake MAP
(.map)**. The exporter rewrites a previously imported `.map` file to a new
destination, optionally converting between Q1, Q2, and Q3 dialects.

**Source of truth.** The exporter re-parses the original `.map` file path
cached on the imported root collection (`obj["qb_source_map"]`). This means
brush geometry edits made in Blender after import are NOT included in the
exported file. Entity property edits (origin, classname, key/value pairs)
can optionally be folded in via the *Apply entity edits from scene* toggle:
entity anchor objects carrying `qb_entity_role = "ENTITY"` and
`qb_entity_index` contribute their location (÷ the collection's saved import
scale) as the entity's `origin`, and custom properties named `qb_prop_<key>`
overwrite the matching key.

**Cross-game conversion.** Pick a *Target game*:

* **Q1** — strips Q2 `contents flags value` trailers; converts Q3
  `brushDef3` faces into Standard faces by decomposing the texture matrix
  into `(xscale, yscale, rotation, xoffset, yoffset)`; tessellates Q3
  `patchDef2` patches into thin extruded brush quads.
* **Q2** — always emits trailing `contents flags value` ints; otherwise
  identical to Q1 export.
* **Q3** — preserves `brushDef3`, `patchDef2`, and opaque `patchDef3` blocks.
  Standard faces are passed through; *patch handling = Keep* is only legal
  here.

**Other options:**

* *Texture projection*: `Auto` (per-face Standard vs Valve220), or force
  one mode for every face.
* *Q3 patches*: `Tessellate to brushes` (default) / `Drop with warning` /
  `Keep verbatim` (Q3 target only).
* *Patch tessellation level* (1–16) and *Patch extrusion thickness* (in
  Quake units) tune the patch → brush conversion.
* *Texture map (JSON)*: optional file containing a `{"src": "dst"}`
  mapping. Use `"*"` as a fallback for any face name not explicitly
  listed. Useful for Q1 → Q3 conversions where short Q1 texture names need
  to be remapped to Q3-style `textures/<set>/<name>` paths.

**Limitations.** BSP → MAP export is not supported (the exporter rejects
collections without `qb_source_map`). Lightmap, shader, and `.wal`/image
texture files are never written; only `.map` text. Q3 `patchDef3` blocks are
preserved for Q3 output but are not interpreted and are dropped with a warning
when converting to Q1/Q2.

### Coordinate scale

Quake units are 1/32 of a Blender meter by default (configurable on the
operator panel).

## Manual smoke-test checklist

Run before publishing a release. Each test loads a sample asset and checks
both geometry and materials in the Blender viewport.

| Test | Sample | What to check |
|---|---|---|
| Q1 MAP | `e1m1.map` (id1) | Brushes solid, faces UV-aligned, lights placed |
| Q1 BSP | `start.bsp` | World mesh visible, entities/lights as objects |
| Q1 WAD | `quake.wad` (id1) | All textures appear as materials |
| Q2 MAP | `base1.map` | Same brush rendering, surface flags propagate |
| Q2 BSP | `base1.bsp` | WAL textures load, fullbright / sky materials emit |
| Q3 MAP | `q3dm1.map` | `patchDef2` patches tessellated, `brushDef3` brushes render as geometry |
| Q3 BSP | `q3dm1.bsp` | Triangle soup + patches + meshverts all draw |
| Reload | Re-run any import | No duplicate materials, no Python errors |

## Architecture

Two layers, separated so parsers are testable without Blender:

* `quakeblend/formats/` — pure Python parsers. **Must not import `bpy`.**
* `quakeblend/blender/` — operators, builders, preferences, UI.

## Tests

```powershell
python -m pytest
```

The test suite exercises the pure-Python formats and utility layers.

To exercise registration, materials, rollback, MAP/BSP/WAD imports, MAP
export, and unregister/re-register against an installed extension, run:

```powershell
$blender = "C:\Program Files\Blender Foundation\Blender 5.1\blender.exe"
pwsh ./scripts/build_extension.ps1 -BlenderExe $blender
$zip = (Get-ChildItem ./dist/quakeblend-*.zip |
  Sort-Object LastWriteTime -Descending | Select-Object -First 1).FullName
& $blender --command extension install-file -r user_default -e $zip
& $blender --background --python scripts/blender_smoke.py -- `
  --extension-root bl_ext.user_default.quakeblend
```

A successful run ends with:

```text
QUAKEBLEND_SMOKE_OK registration materials transaction map bsp wad export unregister
```

The manual viewport checks listed above still cover visual rendering quality.

## Contributing

Issues and pull requests welcome at
<https://github.com/Tzeentchnet/QuakeBlend>. Please keep the strict layer
separation: anything under `quakeblend/formats/` must remain importable
without `bpy` so it can run under plain `pytest`.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
