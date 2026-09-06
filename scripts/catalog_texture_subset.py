"""Record hashes for an acquired exact-match LibreQuake texture subset."""

from __future__ import annotations

import argparse
import hashlib
import json
import struct
from pathlib import Path

from quakeblend.utils.paths import safe_join_under_root


NOTICES = (
    "docs/COPYING", "docs/CREDITS", "docs/README-IMPORTANT-LICENCE-INFO",
    "docs/freedoom-docs/COPYING.adoc", "docs/freedoom-docs/CREDITS",
)


def build_catalog(audit: dict, tree: dict, root: Path) -> dict:
    if tree.get("truncated") is not False or audit["revision"] != tree["sha"]:
        raise ValueError("Audit and complete tree must use the same revision")
    upstream = {entry["path"]: entry for entry in tree["tree"]}
    texture_names = {path: name for name, path in audit["exact"].items()}
    files = []
    for relative in [*NOTICES, *sorted(texture_names)]:
        path = safe_join_under_root(root, relative)
        if path is None:
            raise ValueError(f"Unsafe source path: {relative}")
        data = path.read_bytes()
        blob = f"blob {len(data)}\0".encode("ascii") + data
        if hashlib.sha1(blob).hexdigest() != upstream[relative]["sha"]:
            raise ValueError(f"Git blob mismatch: {relative}")
        entry = {"path": relative, "bytes": len(data),
                 "sha256": hashlib.sha256(data).hexdigest()}
        if relative in texture_names:
            if data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
                raise ValueError(f"Not a PNG: {relative}")
            width, height = struct.unpack(">II", data[16:24])
            if not width or not height:
                raise ValueError(f"Empty image: {relative}")
            entry.update(texture_name=texture_names[relative], width=width, height=height)
        files.append(entry)
    return {"schema_version": 1, "assets": [{
        "id": "librequake-e3m4-textures",
        "cache_directory": root.name,
        "repository": "lavenderdotpet/LibreQuake",
        "revision": tree["sha"],
        "source_base_url": "https://raw.githubusercontent.com/"
                           f"lavenderdotpet/LibreQuake/{tree['sha']}/",
        "license": "BSD-3-Clause",
        "license_scope": "Original PNG subset; retain all five included upstream notices.",
        "qualification": "partial-exact-name-png-subset",
        "format": "png-texture-subset",
        "source_map_asset": "librequake-e3m4",
        "coverage": audit,
        "files": files,
    }]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("audit", type=Path)
    parser.add_argument("tree", type=Path)
    parser.add_argument("root", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    catalog = build_catalog(
        json.loads(args.audit.read_text(encoding="utf-8-sig")),
        json.loads(args.tree.read_text(encoding="utf-8-sig")), args.root,
    )
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(catalog, output, indent=2)
        output.write("\n")
    print(f"Cataloged {len(catalog['assets'][0]['files'])} verified files")


if __name__ == "__main__":
    main()
