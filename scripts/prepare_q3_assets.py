"""Audit or prepare an exact-path Q3 BSP shader dependency folder."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import shutil
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from quakeblend.formats import bsp_q3
from quakeblend.utils.q3_assets import Q3Assets, resource_name


def prepare(
    installation: Path,
    output: Path,
    *,
    member: str,
    expected_sha256: str | None = None,
    audit_only: bool = False,
) -> dict:
    installation = installation.resolve(strict=True)
    output = output.resolve()
    repository = Path(__file__).resolve().parents[1]
    if output.is_relative_to(installation) or output.is_relative_to(repository):
        raise ValueError("Private output must be outside the installation and repository")
    if output.exists():
        raise FileExistsError(output)
    assets = Q3Assets.from_packages([installation / "baseq3" / f"pak{number}.pk3" for number in range(9)])
    source = assets.entries[resource_name(member)]
    source_data = assets.read(source)
    source_sha256 = hashlib.sha256(source_data).hexdigest()
    if expected_sha256 is not None and source_sha256 != expected_sha256.casefold():
        raise ValueError("BSP differs from the expected snapshot")
    level = bsp_q3.read(io.BytesIO(source_data))
    usage = Counter(face.texture for face in level.faces)
    resources = {source.name: source}
    records = []
    for index, texture in enumerate(level.textures):
        spec = assets.material(texture.name)
        record = {"name": texture.name, "source_faces": usage[index],
                  "kind": "explicit_shader" if spec.shader else "implicit_image",
                  "missing": list(spec.missing), "shader": asdict(spec.shader) if spec.shader else None,
                  "images": {name: resource.name if resource else None for name, resource in spec.images}}
        if spec.shader:
            resource = assets.entries[spec.shader.source]
            resources[resource.name] = resource
        for _, resource in spec.images:
            if resource:
                resources[resource.name] = resource
        if spec.editor_image:
            resources[spec.editor_image.name] = spec.editor_image
            record["editor_image"] = spec.editor_image.name
        records.append(record)
    report = {"source": assets.provenance(source), "audit_only": audit_only,
              "materials": records, "resources": [assets.provenance(item) for item in resources.values()]}
    output.mkdir(parents=True, exist_ok=False)
    try:
        if not audit_only:
            for resource in resources.values():
                target = output / "assets" / resource.name
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(assets.read(resource))
        (output / "audit.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except Exception:
        shutil.rmtree(output)
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--installation-root", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--bsp-member", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--audit-only", action="store_true")
    args = parser.parse_args()
    report = prepare(
        args.installation_root,
        args.output_dir,
        member=args.bsp_member,
        expected_sha256=args.expected_sha256,
        audit_only=args.audit_only,
    )
    print(json.dumps({"output": str(args.output_dir), "materials": len(report["materials"]),
                      "resources": len(report["resources"]),
                      "missing": {item["name"]: item["missing"] for item in report["materials"] if item["missing"]}}, indent=2))


if __name__ == "__main__":
    main()
