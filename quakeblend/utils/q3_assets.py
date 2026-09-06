"""Exact Q3 resource lookup for prepared folders and offline PK3 preparation."""

from __future__ import annotations

import hashlib
import os
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Sequence

from ..formats.shader_q3 import Shader, parse
from ..formats.image_info import image_dimensions


MAX_MEMBER_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024


def resource_name(name: str) -> str:
    normalized = name.replace("\\", "/").casefold()
    parts = normalized.split("/")
    reserved = {"con", "prn", "aux", "nul", *(f"com{number}" for number in range(1, 10)),
                *(f"lpt{number}" for number in range(1, 10))}
    if (not normalized or any(part in {"", ".", ".."} or part.endswith((".", " "))
                              or part.split(".")[0] in reserved for part in parts)
            or any(ord(char) < 32 or char in ':<>"|?*' for char in normalized)):
        raise ValueError(f"Unsafe Q3 resource name: {name!r}")
    return normalized


@dataclass(frozen=True)
class Resource:
    name: str
    path: Path
    size: int
    member: str | None = None


@dataclass(frozen=True)
class MaterialSpec:
    name: str
    shader: Shader | None
    images: tuple[tuple[str, Resource | None], ...]
    editor_image: Resource | None
    missing: tuple[str, ...]


class Q3Assets:
    def __init__(self, entries: dict[str, Resource]):
        self.entries = entries
        self._data: dict[str, bytes] = {}
        self._bytes = 0
        self._shaders: dict[str, list[Shader]] | None = None

    @classmethod
    def from_folder(cls, root: Path) -> Q3Assets:
        root = root.resolve(strict=True)
        if not root.is_dir():
            raise ValueError(f"Q3 asset root is not a directory: {root}")
        entries = {}
        for directory, folders, files in os.walk(root, followlinks=False):
            folders.sort()
            for folder in folders:
                if not (Path(directory) / folder).resolve(strict=True).is_relative_to(root):
                    raise ValueError(f"Q3 resource directory escapes asset root: {folder}")
            for filename in sorted(files):
                path = Path(directory) / filename
                resolved = path.resolve(strict=True)
                if not resolved.is_relative_to(root):
                    raise ValueError(f"Q3 resource escapes asset root: {path}")
                name = resource_name(path.relative_to(root).as_posix())
                if name in entries:
                    raise ValueError(f"Duplicate case-insensitive Q3 resource: {name}")
                entries[name] = Resource(name, resolved, resolved.stat().st_size)
        return cls(entries)

    @classmethod
    def from_packages(cls, packages: Sequence[Path]) -> Q3Assets:
        entries = {}
        for path in packages:
            with zipfile.ZipFile(path) as archive:
                seen = set()
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    name = resource_name(info.filename)
                    if name in seen:
                        raise ValueError(f"Duplicate case-insensitive member in {path}: {name}")
                    seen.add(name)
                    if info.flag_bits & 1:
                        raise ValueError(f"Encrypted Q3 resource: {path}:{name}")
                    entries[name] = Resource(name, path.resolve(), info.file_size, info.filename)
        return cls(entries)

    def read(self, resource: Resource) -> bytes:
        if resource.name in self._data:
            return self._data[resource.name]
        if resource.size > MAX_MEMBER_BYTES or self._bytes + resource.size > MAX_TOTAL_BYTES:
            raise ValueError(f"Q3 resource byte limit exceeded: {resource.name}")
        if resource.member is None:
            with resource.path.open("rb") as stream:
                data = stream.read(resource.size + 1)
        else:
            with zipfile.ZipFile(resource.path) as archive:
                info = archive.getinfo(resource.member)
                if info.file_size != resource.size:
                    raise ValueError(f"Q3 archive changed while reading: {resource.path}")
                with archive.open(info) as stream:
                    data = stream.read(resource.size + 1)
        if len(data) != resource.size:
            raise ValueError(f"Q3 resource size changed: {resource.name}")
        self._data[resource.name] = data
        self._bytes += len(data)
        return data

    def image(self, name: str) -> Resource | None:
        normalized = resource_name(name)
        suffix = PurePosixPath(normalized).suffix
        candidates = [normalized] if suffix else []
        if suffix == ".tga":
            candidates.append(normalized[:-4] + ".jpg")
        elif not suffix:
            candidates.extend(normalized + extension for extension in (".tga", ".jpg", ".png", ".jpeg"))
        return next((self.entries[candidate] for candidate in candidates if candidate in self.entries), None)

    def shader(self, name: str) -> Shader | None:
        if self._shaders is None:
            shaders: dict[str, list[Shader]] = {}
            for key, resource in sorted(self.entries.items()):
                if key.startswith("scripts/") and key.endswith(".shader"):
                    for shader in parse(self.read(resource).decode("latin-1"), source=key):
                        shaders.setdefault(resource_name(shader.name), []).append(shader)
            self._shaders = shaders
        matches = self._shaders.get(resource_name(name), [])
        if len(matches) > 1:
            sources = ", ".join(f"{shader.source}:{shader.line}" for shader in matches)
            raise ValueError(f"Ambiguous Q3 shader {name}: {sources}")
        return matches[0] if matches else None

    def material(self, name: str) -> MaterialSpec:
        shader = self.shader(name)
        requests = shader.dependencies() if shader else (name,)
        images = tuple((request, self.image(request)) for request in requests)
        editor = shader.get("qer_editorimage") if shader else None
        if editor is not None and len(editor.args) != 1:
            raise ValueError(f"{shader.source}:{editor.line}: invalid qer_editorimage")
        editor_image = self.image(editor.args[0]) if editor else None
        return MaterialSpec(name, shader, images, editor_image,
                            tuple(request for request, image in images if image is None))

    def provenance(self, resource: Resource) -> dict:
        return {"path": resource.name, "source": str(resource.path), "member": resource.member,
                "bytes": resource.size, "sha256": hashlib.sha256(self.read(resource)).hexdigest()}

    def projection_size(self, spec: MaterialSpec) -> tuple[int, int]:
        resource = spec.editor_image or next((image for _, image in spec.images if image is not None), None)
        if resource is None:
            raise ValueError(f"Missing projection image: {spec.name}")
        return image_dimensions(self.read(resource), PurePosixPath(resource.name).suffix)
