"""Audit a MAP's texture references against a downloaded GitHub tree listing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path, PurePosixPath

from quakeblend.formats import map_q1


def audit_textures(names: set[str], tree: dict) -> dict:
    if tree.get("truncated") is not False:
        raise ValueError("A complete GitHub tree listing is required")
    sources: dict[str, list[str]] = {}
    for entry in tree["tree"]:
        path = PurePosixPath(entry["path"])
        if (entry["type"] == "blob" and path.parts[0] == "texture-wads"
                and path.suffix.casefold() == ".png"):
            sources.setdefault(path.stem.casefold(), []).append(path.as_posix())
    exact = {}
    ambiguous = {}
    encoded_candidates = {}
    missing = []
    for name in sorted(names):
        matches = sorted(sources.get(name.casefold(), []))
        if len(matches) == 1:
            exact[name] = matches[0]
        elif matches:
            ambiguous[name] = matches
        else:
            encoded = ("star_" + name[1:] if name.startswith("*") else
                       "plus_" + name[1:] if name.startswith("+") else name)
            candidates = sorted(set(
                sources.get(encoded.casefold(), [])
                + sources.get(encoded.casefold() + "_fbr", [])
            ))
            if candidates:
                encoded_candidates[name] = candidates
            else:
                missing.append(name)
    return {
        "revision": tree["sha"],
        "required_textures": len(names),
        "exact": exact,
        "ambiguous": ambiguous,
        "encoded_candidates": encoded_candidates,
        "missing": missing,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("map", type=Path)
    parser.add_argument("tree", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    level = map_q1.parse_path(args.map)
    names = {face.tex.name for entity in level.entities
             for brush in entity.brushes for face in brush.faces}
    report = audit_textures(names, json.loads(args.tree.read_text(encoding="utf-8-sig")))
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(text)
    print(text)


if __name__ == "__main__":
    main()
