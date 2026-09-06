# Installing QuakeBlend

QuakeBlend is a Blender 5.0+ extension. Install a release archive for normal
use, or build the extension archive from source.

The current build has passed Windows checks on Blender 5.0.0 and 5.1.1. Other
operating systems, Blender versions, and GPU configurations are not qualified.

## Install a release

1. Download `quakeblend-*.zip` from the
   [QuakeBlend releases](https://github.com/Tzeentchnet/QuakeBlend/releases)
   page.
2. In Blender 5.0 or newer, open **Edit > Preferences > Get Extensions**.
3. Open the menu in the upper-right corner, choose **Install from Disk**, and
   select the downloaded zip file.

Do not extract the archive before installing it.

## Build from source

Building the extension requires PowerShell. Python 3.11 or newer is required
for the development and test environment described in
[Testing](testing.md), but it is not needed to run the build script itself.

```powershell
git clone https://github.com/Tzeentchnet/QuakeBlend.git
cd QuakeBlend
pwsh ./scripts/build_extension.ps1
```

The script writes `dist/quakeblend-<version>.zip`. Install that archive in
Blender using **Install from Disk** as described above.

### Build with Blender

Pass a Blender executable directly:

```powershell
pwsh ./scripts/build_extension.ps1 `
  -BlenderExe "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
```

Alternatively, set `BLENDER_EXE` before running the script:

```powershell
$env:BLENDER_EXE = "C:\Program Files\Blender Foundation\Blender 5.0\blender.exe"
pwsh ./scripts/build_extension.ps1
```

When the selected executable exists, the script uses Blender's official
`--command extension build` command. Otherwise, it creates the archive with
PowerShell's `Compress-Archive` command.

Both build paths stage the same extension layout. `blender_manifest.toml`,
`__init__.py`, the package directories, and `LICENSE` are placed at the
archive root, and Python cache files are excluded.

## Next steps

- Expand **QuakeBlend** under **Preferences > Add-ons** to configure global
   import defaults. Reinstall the freshly built archive and restart Blender when
   updating an older build; the version label alone may not distinguish local builds.
- Read [Importing files](importing.md) for the available import operators.
- Read [Testing and validation](testing.md) when working from source.
- Return to the [project overview](../README.md).
