"""Audit exact and tolerance-merged brush topology in the pinned LibreQuake MAP."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path

from quakeblend.formats import csg, map_q1
from quakeblend.utils.constants import CSG_EPSILON


def edge_counts(rings):
    faces = set()
    edges = Counter()
    for ring in rings:
        identity = frozenset(ring)
        if len(identity) < 3 or identity in faces:
            continue
        faces.add(identity)
        edges.update(frozenset((first, second))
                     for first, second in zip(ring, ring[1:] + ring[:1]))
    return dict(sorted(Counter(edges.values()).items()))


def audit_brush(brush, *, epsilon=CSG_EPSILON):
    planes = [face.plane for face in brush.faces]
    rings = csg.brush_faces_from_planes(planes, epsilon=epsilon)
    counts = edge_counts(rings)
    seen = {}
    omitted = []
    for index, ring in enumerate(rings):
        identity = frozenset(ring)
        if len(identity) < 3:
            omitted.append({"face": index, "reason": "empty"})
        elif identity in seen:
            omitted.append({"face": index, "reason": "duplicate", "retained": seen[identity]})
        else:
            seen[identity] = index
    result = {
        "edge_use_counts": counts,
        "vertices": len({point for ring in rings for point in ring}),
        "polygons": len(seen),
        "omitted_faces": omitted,
        "max_plane_error": max((abs(plane.signed_distance(point))
                                for plane, ring in zip(planes, rings) for point in ring), default=0),
        "max_outside_distance": max((plane.signed_distance(point)
                                     for ring in rings for point in ring for plane in planes), default=0),
    }
    if counts and set(counts) == {2}:
        return result
    canonical = []
    merged = []
    distances = []
    for ring in rings:
        merged_ring = []
        for point in ring:
            match = next((other for other in canonical
                          if (point - other).length() < epsilon), None)
            if match is None:
                canonical.append(point)
                match = point
            elif match != point:
                distances.append((point - match).length())
            merged_ring.append(match)
        merged.append(merged_ring)
    return {
        **result,
        "merged_edge_use_counts": edge_counts(merged),
        "ring_sizes": [len(ring) for ring in rings],
        "distinct_vertices": len({point for ring in rings for point in ring}),
        "merged_vertices": len(canonical),
        "merge_distances": sorted(set(distances)),
    }


def main():
    if not __debug__:
        raise RuntimeError("Run validation without Python optimization")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--epsilon", type=float, default=CSG_EPSILON)
    args = parser.parse_args()
    if not 0 < args.epsilon < 1:
        parser.error("--epsilon must be between zero and one game unit")
    asset = json.loads((Path(__file__).resolve().parents[1] / "tests/assets/manifest.json")
                       .read_text(encoding="utf-8"))["assets"][0]
    root = args.cache_root / asset["cache_directory"]
    for entry in asset["files"]:
        path = (root / entry["path"]).resolve()
        assert path.is_relative_to(root.resolve()), path
        data = path.read_bytes()
        assert len(data) == entry["bytes"]
        assert hashlib.sha256(data).hexdigest() == entry["sha256"]
    source = root / asset["map_path"]
    level = map_q1.parse_path(source)
    failures = []
    omissions = []
    totals = Counter()
    max_plane_error = 0
    max_outside_distance = 0
    total = 0
    for entity_index, entity in enumerate(level.entities):
        for brush_index, brush in enumerate(entity.brushes):
            total += 1
            result = audit_brush(brush, epsilon=args.epsilon)
            totals.update({key: result[key] for key in ("vertices", "polygons")})
            max_plane_error = max(max_plane_error, result["max_plane_error"])
            max_outside_distance = max(max_outside_distance, result["max_outside_distance"])
            omissions.extend({"entity": entity_index, "brush": brush_index, **item}
                     for item in result["omitted_faces"])
            if set(result["edge_use_counts"]) != {2}:
                failures.append({"entity": entity_index, "brush": brush_index, **result})
        report = {"source": str(source), "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "brushes": total, "epsilon": args.epsilon, **totals,
              "max_plane_error": max_plane_error, "max_outside_distance": max_outside_distance,
              "omitted_faces": omissions, "nonclosed": len(failures), "failures": failures}
    text = json.dumps(report, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            output.write(text)
    print(json.dumps({key: value for key, value in report.items()
                      if key not in {"failures", "omitted_faces"}}, indent=2))
    print("Omitted faces:", dict(Counter(item["reason"] for item in omissions)))


if __name__ == "__main__":
    main()
