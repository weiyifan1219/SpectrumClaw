#!/usr/bin/env python3
"""Native Sionna RT single-pose measurement sidecar for the urban UAV scene."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


PROFILE_ID = "sionna_urban_2_4ghz"
RESULT_PREFIX = "SPECTRUMCLAW_RESULT "
FREQUENCY_HZ = 2.4e9
BUILDINGS = (
    ("office_east", (13.0, 12.0, 9.0), (10.0, 10.0, 18.0)),
    ("tower_northwest", (-13.0, 14.0, 11.0), (9.0, 8.0, 22.0)),
    ("residential_west", (-16.0, -11.0, 7.5), (12.0, 10.0, 15.0)),
    ("warehouse_southeast", (14.0, -14.0, 5.0), (16.0, 8.0, 10.0)),
    ("library_north", (0.0, 25.0, 5.5), (18.0, 7.0, 11.0)),
    ("clinic_west", (-27.0, 7.0, 6.0), (10.0, 10.0, 12.0)),
)
ANCHORS = (
    # Three declared mast positions use road corridors in the same urban_block
    # geometry. They are independent Sionna transmitters, not visual clones;
    # every displayed link must still be admitted by PathSolver for the current
    # receiver pose.
    ("tx-01", (42.0, 6.0, 24.0), 20.0),
    ("tx-02", (-42.0, -6.0, 24.0), 20.0),
    ("tx-03", (6.0, 42.0, 24.0), 20.0),
)
_INVALID_OBJECT_ID = (1 << 32) - 1


def extract_ray_paths(
    vertices: Any,
    objects: Any,
    valid: Any,
    *,
    anchor_positions: tuple[tuple[float, float, float], ...],
    receiver_position: list[float],
    max_paths_per_anchor: int = 8,
) -> list[list[dict[str, Any]]]:
    """Convert Sionna's path tensors into bounded, display-safe ENU polylines.

    Every intermediate point comes from ``Paths.vertices`` produced for the
    current receiver pose.  The UI may simplify the visual treatment, but it
    never invents a reflection point or a propagation path.
    """
    result: list[list[dict[str, Any]]] = []
    depth_count = len(vertices)
    for tx_index, source in enumerate(anchor_positions):
        paths: list[dict[str, Any]] = []
        path_count = len(valid[0][tx_index])
        for path_index in range(path_count):
            if not bool(valid[0][tx_index][path_index]) or len(paths) >= max_paths_per_anchor:
                continue
            points = [[float(axis) for axis in source]]
            for depth in range(depth_count):
                object_id = int(objects[depth][0][tx_index][path_index])
                if object_id == _INVALID_OBJECT_ID:
                    continue
                point = [float(axis) for axis in vertices[depth][0][tx_index][path_index]]
                if all(math.isfinite(axis) for axis in point):
                    points.append(point)
            points.append([float(axis) for axis in receiver_position])
            paths.append({
                "id": f"path-{path_index + 1}",
                "points_m": points,
                "interaction_count": max(0, len(points) - 2),
            })
        result.append(paths)
    return result


def _add_box(vertices: list[tuple[float, float, float]], faces: list[tuple[int, int, int]], center, size) -> None:
    x, y, z = center
    sx, sy, sz = (axis / 2 for axis in size)
    base = len(vertices)
    vertices.extend([
        (x - sx, y - sy, z - sz), (x + sx, y - sy, z - sz),
        (x + sx, y + sy, z - sz), (x - sx, y + sy, z - sz),
        (x - sx, y - sy, z + sz), (x + sx, y - sy, z + sz),
        (x + sx, y + sy, z + sz), (x - sx, y + sy, z + sz),
    ])
    for first, second, third, fourth in ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 4, 0)):
        faces.extend(((base + first, base + second, base + third), (base + first, base + third, base + fourth)))


def write_urban_block_scene_assets(directory: str | Path) -> Path:
    """Write a compact EM scene derived from ``simulation/worlds/urban_block.sdf``."""
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    vertices: list[tuple[float, float, float]] = []
    faces: list[tuple[int, int, int]] = []
    _add_box(vertices, faces, (0.0, 0.0, -0.1), (120.0, 120.0, 0.2))
    for _name, center, size in BUILDINGS:
        _add_box(vertices, faces, center, size)

    ply_path = directory / "urban_block.ply"
    with ply_path.open("w", encoding="utf-8") as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(vertices)}\nproperty float x\nproperty float y\nproperty float z\n")
        handle.write(f"element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n")
        for vertex in vertices:
            handle.write(f"{vertex[0]} {vertex[1]} {vertex[2]}\n")
        for face in faces:
            handle.write(f"3 {face[0]} {face[1]} {face[2]}\n")

    xml_path = directory / "urban_block.xml"
    xml_path.write_text(
        """<scene version=\"2.1.0\">
  <bsdf type=\"itu-radio-material\" id=\"urban-concrete\">
    <string name=\"type\" value=\"concrete\"/>
    <float name=\"thickness\" value=\"0.2\"/>
  </bsdf>
  <shape type=\"ply\" id=\"urban-block\">
    <string name=\"filename\" value=\"urban_block.ply\"/>
    <boolean name=\"face_normals\" value=\"true\"/>
    <ref id=\"urban-concrete\" name=\"bsdf\"/>
  </shape>
</scene>
""",
        encoding="utf-8",
    )
    return xml_path


def measure(request: dict[str, Any], asset_dir: str | Path) -> dict[str, Any]:
    if request.get("profile_id") != PROFILE_ID:
        raise ValueError("未知的 Sionna 测量配置")
    position = request.get("position_m")
    if not isinstance(position, list) or len(position) != 3 or not all(isinstance(value, (int, float)) and math.isfinite(value) for value in position):
        raise ValueError("Sionna 测量需要有限的三维 ENU 位姿")

    import numpy as np
    import mitsuba as mi

    mi.set_variant("cuda_ad_mono_polarized")
    from sionna.rt import PathSolver, PlanarArray, Receiver, Transmitter, load_scene

    scene = load_scene(str(write_urban_block_scene_assets(asset_dir)))
    scene.frequency = FREQUENCY_HZ
    scene.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    scene.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
    receiver = Receiver(name="uav", position=mi.Point3f(*position))
    scene.add(receiver)
    for anchor_id, anchor_position, power_dbm in ANCHORS:
        transmitter = Transmitter(name=anchor_id, position=mi.Point3f(*anchor_position), power_dbm=power_dbm)
        transmitter.look_at(receiver)
        scene.add(transmitter)

    paths = PathSolver()(scene, max_depth=2, samples_per_src=10000, diffuse_reflection=False, diffraction=False)
    coefficients, delays = paths.cir(normalize_delays=False, out_type="numpy")
    power_by_anchor = np.sum(np.abs(coefficients) ** 2, axis=(0, 1, 3, 4, 5))
    delays = np.asarray(delays)
    ray_paths_by_anchor = extract_ray_paths(
        np.asarray(paths.vertices).tolist(),
        np.asarray(paths.objects).tolist(),
        np.asarray(paths.valid).tolist(),
        anchor_positions=tuple(position for _anchor_id, position, _power_dbm in ANCHORS),
        receiver_position=[float(value) for value in position],
    )
    anchors = []
    for index, (anchor_id, _anchor_position, tx_power_dbm) in enumerate(ANCHORS):
        path_delays = np.asarray(delays[0, index]).reshape(-1)
        path_count = int(np.count_nonzero(np.isfinite(path_delays) & (path_delays >= 0)))
        gain = float(power_by_anchor[index])
        anchors.append({
            "id": anchor_id,
            "received_power_dbm": round(tx_power_dbm + 10 * math.log10(max(gain, 1e-30)), 4),
            "path_count": path_count,
            "ray_paths": ray_paths_by_anchor[index],
        })
    return {
        "kind": "spectrum_observation",
        "source": "sionna_rt",
        "profile_id": PROFILE_ID,
        "timestamp": float(request["timestamp"]),
        "position_m": [float(value) for value in position],
        "frequency_hz": FREQUENCY_HZ,
        "anchors": anchors,
    }


def serve_json_lines(source, sink, *, asset_dir: str | Path, measure_fn=None) -> None:
    """Serve many bounded pose requests in one warm Sionna process."""
    evaluator = measure_fn or measure
    for raw_line in source:
        line = raw_line.strip()
        if not line:
            continue
        request_id = ""
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                raise ValueError("Sionna RT 请求必须是 JSON 对象")
            request_id = str(request.get("request_id") or "")
            if not request_id:
                raise ValueError("Sionna RT 请求缺少 request_id")
            observation = evaluator(request, asset_dir)
            response = {"request_id": request_id, "ok": True, "observation": observation}
        except Exception as exc:
            response = {"request_id": request_id, "ok": False, "error": str(exc)}
        sink.write(RESULT_PREFIX + json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sink.flush()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--request", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--assets", type=Path, default=Path("/workspace/YiFan/spectrumclaw_runtime/artifacts/uav-sionna/scene"))
    args = parser.parse_args()
    if args.serve:
        serve_json_lines(sys.stdin, sys.stdout, asset_dir=args.assets)
        return
    if args.request is None or args.output is None:
        parser.error("--request and --output are required unless --serve is used")
    result = measure(json.loads(args.request.read_text(encoding="utf-8")), args.assets)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
