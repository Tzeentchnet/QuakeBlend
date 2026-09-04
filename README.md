# QuakeBlend

Blender 5.0+ extension for importing **Quake 1, 2, and 3** map data and textures.

Repository: <https://github.com/Tzeentchnet/QuakeBlend>

## Capabilities

* Import Quake 1, Quake 2, and Quake 3 `.map` and `.bsp` levels.
* Convert CSG brushes, Q3 `brushDef3` geometry, and `patchDef2` surfaces into
  Blender meshes.
* Load Q1 WAD2/WAD3, Q2 WAL, and Q3 image textures with game-aware material
  handling.
* Import entities as lights, cameras, and empties while preserving their
  properties and BSP submodels.
* Export imported MAP sources with Q1, Q2, and Q3 conversion, patch handling,
  texture remapping, and optional entity edits.
* Use a configurable world scale, with `1/32` as the default.

## Installation

Grab `quakeblend-*.zip` from the
[Releases](https://github.com/Tzeentchnet/QuakeBlend/releases) page. In
Blender 5.0+, open **Edit > Preferences > Get Extensions**, choose
**Install from Disk**, and select the zip.

To build an installable archive from source:

```powershell
git clone https://github.com/Tzeentchnet/QuakeBlend.git
cd QuakeBlend
pwsh ./scripts/build_extension.ps1
```

The script writes `dist/quakeblend-<version>.zip`. See the
[installation guide](docs/installation.md) for requirements and build
options.

## Documentation

* [Installation](docs/installation.md): release installation, requirements,
  and source builds.
* [Importing](docs/importing.md): MAP, BSP, WAD, and WAL options and behavior.
* [Exporting](docs/exporting.md): MAP conversion, scene overlays, and
  limitations.
* [Testing and validation](docs/testing.md).
* [Architecture and contributing](docs/architecture.md): project layers,
  pipelines, data contracts, and contribution guidance.

## License

GPL-3.0-or-later. See [LICENSE](LICENSE).
