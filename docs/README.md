# QuakeBlend Documentation

QuakeBlend's public documentation is grouped by audience. Source-only tooling
and tests are kept in this repository for reproducibility, but they are not
included in the installable Blender extension archive.

Local planning notes, raw captures, and acceptance entry points that require
privately owned assets belong under the ignored `.private/` directory. They are
intentionally excluded from Git and are not prerequisites for using or testing
the public project.

## User guides

- [Installation](installation.md): install a release or build the extension.
- [Importing](importing.md): supported formats, options, materials, and metadata.
- [Exporting](exporting.md): source-backed MAP conversion and transform limits.
- [Q3 shaders](q3-shaders.md): shader-mode controls, supported behavior, and
  rendering limits.

## Contributor and reference guides

- [Architecture and contributing](architecture.md): project layers, pipelines,
  data contracts, and contribution conventions.
- [Testing and validation](testing.md): Python, package, Blender, and CI checks.
- [Public test assets](test-assets.md): licensed LibreQuake fixtures, acquisition,
  provenance, and external-tool boundaries.

[Return to the project overview](../README.md).
