# Quake 3 Shader Materials

QuakeBlend can resolve Quake 3 shader definitions when importing Q3 MAP and BSP
files. The implementation approximates supported multipass materials with
Blender materials and Geometry Nodes while preserving source geometry, UVs,
lightmap UVs, and vertex colors for later inspection.

## Choose a material mode

**Q3 materials** offers two modes:

- **Shaders** resolves shader definitions before same-name images. This is the
  default for Q3 imports and enables lighting, animation, and deformation controls.
- **Direct images** looks for same-name loose images and disables shader-specific
  controls. It is useful for simple assets that do not depend on shader scripts.

Set **Texture root** to a prepared directory that retains source-relative paths,
including `scripts/`, `textures/`, and referenced model-image directories. The
importer reads loose files under that root. It does not browse PK3 archives.

## Supported behavior

Shader mode supports:

- ordered image, lightmap, multiply, additive, alpha-blend, and alpha-test stages
- packed animation frames and supported stage color and alpha waves
- UV scroll, scale, rotate, stretch, transform, and turbulence operations
- source vertex colors and alpha
- supported vertex-wave deformation through saved Geometry Nodes
- `qer_editorimage` for MAP projection dimensions, with the first runtime image
  as fallback
- per-lightmap material variants for BSP surfaces
- source-located diagnostics for unsupported directives and missing dependencies

Stage time follows Blender's frame rate and includes subframes. Disabling
**Animation** freezes frame selection, waves, and animated UV operations at time
zero while retaining static UV transforms. Disabling **Deformation** leaves the
source mesh positions unchanged. The two controls are independent.

## Lighting modes

- **Fullbright** composes supported stages without baked lightmap or vertex-RGB
  darkening. It needs no scene lights and is the Q3 BSP default.
- **Blender Lighting** removes baked lighting inputs but lets Blender lights affect
  lit stages. Additive and unlit contributions retain their shader behavior. It
  is the Q3 MAP default.
- **Baked** is available for BSP imports and retains imported lightmap and vertex
  color inputs without adding scene-light response to the composed result.

These settings affect newly created materials only. They do not modify the
World, exposure, view transform, or existing scenes.

## Preparing local assets

The public preparation tool can audit or copy the dependencies for one explicitly
selected BSP from a local `baseq3` package set. Use it only with assets you are
authorized to access and redistribute:

```powershell
python -m scripts.prepare_q3_assets `
  --installation-root '<installation-root>' `
  --bsp-member 'maps/example.bsp' `
  --output-dir '<new-output-directory>' `
  --audit-only
```

Remove `--audit-only` to write a prepared loose-file tree. The output directory
must be new. Supply `--expected-sha256 <digest>` when a workflow needs to pin the
selected BSP bytes. The tool records provenance, honors package precedence,
rejects unsafe names and case collisions, bounds reads, and cleans up partial
output after failure. It has no built-in retail map name or expected digest.

## Limits

This is not a Quake 3 renderer. Hardware gamma and overbright behavior are not
emulated, so Baked materials can look darker than an in-game reference. Blender
transparent-object sorting is not engine multipass ordering, and environment
mapping is evaluated differently.

Sky remains a tagged diagnostic placeholder. Drawing the original boundary as
an ordinary Blender surface writes near depth and can hide geometry that Quake 3
would draw in front of a far-depth sky. The importer does not replace the World
or hide sky surfaces to disguise that mismatch.

Later-stage alpha tests, environment `tcMod` combinations, unsupported first-stage
framebuffer blends, video, fog volumes, portals, autosprites, and arbitrary
deformations are not implemented. Unsupported combinations remain visible as
diagnostic placeholders and warnings.

## Verification

The focused parser, resource, and material-semantics checks use synthetic data:

```powershell
python -m pytest tests/test_shader_q3.py tests/test_shader_q3_math.py `
  tests/test_q3_assets.py tests/test_prepare_q3_assets.py
```

The installed-Blender shader smoke is described in
[Testing and validation](testing.md). See [Importing](importing.md) for the full
Q3 MAP and BSP option reference.
