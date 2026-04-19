# QuakeBlend

Blender 5.0+ extension for importing **Quake 1, 2, and 3** map data and textures.

## Status

| Phase | Scope | Status |
|------:|:------|:------:|
| 0 | Project skeleton + manifest | done |
| 1 | Palette / WAD / WAL parsers + materials + WAD-only operator | done |
| 2 | Quake 1 `.map` + `.bsp` import (CSG → mesh, entities, lights) | done |
| 3 | Quake 2 `.map` + `.bsp` import (WAL textures, surface flags) | done |
| 4 | Quake 3 `.map` + `.bsp` import (`brushDef3`, Bezier patches) | done |
| 5 | Preferences, logging polish, packaged release | done |

Export is **explicitly out of scope** for this initial release.

## Install (from source)

1. Build the extension zip:
   ```powershell
   pwsh ./scripts/build_extension.ps1
   ```
2. In Blender 5.0+ open *Edit → Preferences → Get Extensions → Install from Disk*
   and pick `dist/quakeblend-*.zip`.

## Usage

After installing, three import operators appear under *File → Import*:

* **Quake MAP (.map)** — import any Q1/Q2/Q3 `.map` text file. Provide a
  semicolon-separated list of `.wad` paths via the operator panel (or set the
  default in *Edit → Preferences → Add-ons → QuakeBlend*) for Q1 textures.
  Quake 3 patches are tessellated to mesh and the original control grid is
  stored in `obj["qb_patch_control_grid"]` for future round-trip.
* **Quake BSP (.bsp)** — auto-detects Q1 (v29), Q2 (IBSP v38), Q3 (IBSP v46).
  For Q2/Q3 supply a *Texture Root* folder containing the `.wal` or
  `.tga` / `.jpg` / `.png` texture files.
* **Quake WAD (.wad)** — load a WAD2/WAD3 archive as a set of materials.

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
| Q3 MAP | `q3dm1.map` | `patchDef2` patches tessellated, `brushDef3` warns |
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

The test suite exercises only the `formats` layer (30 tests).
Manual Blender smoke tests are listed above.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
