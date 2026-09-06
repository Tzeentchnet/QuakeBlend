"""Material-independent MAP projection and tool metadata."""

from __future__ import annotations

from ..formats.image_info import read_image_dimensions
from ..formats.wal import read_wal_path
from .import_options import ToolSurface


class MapResources:
    def __init__(self, index, game, kind, *, sizes, q3_assets=None, shader_mode=False, warn):
        self.index = index
        self.game = game
        self.kind = kind
        self.sizes = sizes
        self.assets = q3_assets
        self.shader_mode = shader_mode
        self.warn = warn
        self.wals = {}
        self.surfaces = {}

    def wal(self, name):
        if name not in self.wals:
            info = self.index.resolve(name, kind="wal") if self.index else None
            self.wals[name] = read_wal_path(info[0]) if info else None
        return self.wals[name]

    def dimensions(self, name):
        key = name.replace("\\", "/").casefold()
        if key not in self.sizes:
            try:
                if self.shader_mode:
                    size = self.assets.projection_size(self.assets.material(name))
                else:
                    info = self.index.resolve(name, kind=self.kind) if self.index else None
                    if info is None:
                        raise ValueError(f"Missing projection image: {name}")
                    if info[1] == "wal":
                        image = self.wal(name)
                        size = image.width, image.height
                    else:
                        size = read_image_dimensions(info[0])
                self.sizes[key] = size
            except (OSError, ValueError, EOFError) as exc:
                self.warn(f"{exc}; using 64x64 MAP projection")
                self.sizes[key] = (64, 64)
        return self.sizes[key]

    def surface(self, tex):
        key = (tex.name, tex.contents, tex.surface_flags, tex.has_q2_trailing_fields)
        if key not in self.surfaces:
            contents, flags, parms = tex.contents, tex.surface_flags, ()
            resolved = True
            try:
                if self.game == "q3" and self.assets:
                    shader = self.assets.shader(tex.name)
                    if shader:
                        parms = tuple(item.args[0] for item in shader.directives
                                      if item.name == "surfaceparm" and len(item.args) == 1)
                elif self.game == "q2" and not tex.has_q2_trailing_fields:
                    image = self.wal(tex.name)
                    if image:
                        contents, flags = image.contents, image.flags
            except (OSError, ValueError, EOFError) as exc:
                resolved = False
                self.warn(f"Tool classification for {tex.name}: {exc}")
            self.surfaces[key] = ToolSurface(tex.name, contents, flags, parms, resolved)
        return self.surfaces[key]
