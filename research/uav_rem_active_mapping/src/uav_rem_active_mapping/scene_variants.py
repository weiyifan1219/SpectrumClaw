from __future__ import annotations

import json
import io
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .scenes import SceneSpec
from .data_io import atomic_write_text


@dataclass(frozen=True)
class SceneAssetPaths:
    manifest_path: Path
    gazebo_world_path: Path
    sionna_xml_path: Path
    sionna_mesh_path: Path


def urban_layout(*, layout_index: int, split: str) -> SceneSpec:
    if not 1 <= int(layout_index) <= 64:
        raise ValueError("layout_index 必须位于 [1,64]")
    if split not in {"pretrain", "finetune", "validation", "test", "train"}:
        raise ValueError("split 必须是 pretrain、finetune、validation、test 或兼容用 train")
    rng = np.random.default_rng(2026082800 + int(layout_index))
    buildings = []
    while len(buildings) < 6:
        width, depth = (float(value) for value in rng.uniform(8.0, 17.0, size=2))
        height = float(rng.uniform(8.0, 28.0))
        east = float(rng.uniform(-43.0, 43.0))
        north = float(rng.uniform(-43.0, 43.0))
        if abs(east) <= 10.0 + width / 2.0 or abs(north) <= 4.0 + depth / 2.0:
            continue
        if any(
            abs(east - center[0]) < (width + size[0]) / 2.0 + 3.0
            and abs(north - center[1]) < (depth + size[1]) / 2.0 + 3.0
            for _name, center, size in buildings
        ):
            continue
        buildings.append((
            f"building_{len(buildings) + 1:02d}",
            (east, north, height / 2.0),
            (width, depth, height),
        ))
    scene_id = f"urban_layout_{int(layout_index):02d}"
    return SceneSpec(
        family_id=scene_id,
        scene_id=scene_id,
        asset_name=f"{scene_id}.xml",
        material_profile_id="itu-concrete-v1",
        buildings=tuple(buildings),
        transmitters=(),
    )


def _add_box(vertices, faces, center, size) -> None:
    x, y, z = center
    sx, sy, sz = (axis / 2.0 for axis in size)
    base = len(vertices)
    vertices.extend([
        (x - sx, y - sy, z - sz), (x + sx, y - sy, z - sz),
        (x + sx, y + sy, z - sz), (x - sx, y + sy, z - sz),
        (x - sx, y - sy, z + sz), (x + sx, y - sy, z + sz),
        (x + sx, y + sy, z + sz), (x - sx, y + sy, z + sz),
    ])
    for first, second, third, fourth in ((0, 1, 2, 3), (4, 7, 6, 5), (0, 4, 5, 1), (1, 5, 6, 2), (2, 6, 7, 3), (3, 7, 6, 2)):
        faces.extend(((base + first, base + second, base + third), (base + first, base + third, base + fourth)))


def write_sionna_assets(scene: SceneSpec, directory: str | Path) -> tuple[Path, Path]:
    destination = Path(directory)
    destination.mkdir(parents=True, exist_ok=True)
    vertices, faces = [], []
    _add_box(vertices, faces, (0.0, 0.0, -0.1), (120.0, 120.0, 0.2))
    for _name, center, size in scene.buildings:
        _add_box(vertices, faces, center, size)
    mesh_path = destination / f"{scene.scene_id}.ply"
    with io.StringIO() as handle:
        handle.write("ply\nformat ascii 1.0\n")
        handle.write(f"element vertex {len(vertices)}\nproperty float x\nproperty float y\nproperty float z\n")
        handle.write(f"element face {len(faces)}\nproperty list uchar int vertex_indices\nend_header\n")
        for vertex in vertices:
            handle.write(f"{vertex[0]} {vertex[1]} {vertex[2]}\n")
        for face in faces:
            handle.write(f"3 {face[0]} {face[1]} {face[2]}\n")
        atomic_write_text(mesh_path, handle.getvalue())
    xml_path = destination / scene.asset_name
    atomic_write_text(xml_path,
        f"""<scene version=\"2.1.0\">
  <bsdf type=\"itu-radio-material\" id=\"urban-concrete\"><string name=\"type\" value=\"concrete\"/><float name=\"thickness\" value=\"0.2\"/></bsdf>
  <shape type=\"ply\" id=\"{scene.scene_id}\"><string name=\"filename\" value=\"{mesh_path.name}\"/><boolean name=\"face_normals\" value=\"true\"/><ref id=\"urban-concrete\" name=\"bsdf\"/></shape>
</scene>
""",
    )
    return xml_path, mesh_path


def write_gazebo_world(scene: SceneSpec, path: str | Path) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    models = []
    for name, center, size in scene.buildings:
        models.append(
            f"""<model name=\"{name}\"><static>true</static><pose>{center[0]} {center[1]} {center[2]} 0 0 0</pose><link name=\"link\"><collision name=\"collision\"><geometry><box><size>{size[0]} {size[1]} {size[2]}</size></box></geometry></collision><visual name=\"visual\"><geometry><box><size>{size[0]} {size[1]} {size[2]}</size></box></geometry><material><diffuse>0.36 0.47 0.56 1</diffuse></material></visual></link></model>"""
        )
    atomic_write_text(destination,
        f"""<?xml version=\"1.0\"?>
<sdf version=\"1.9\"><world name=\"{scene.scene_id}\"><gravity>0 0 -9.8</gravity><spherical_coordinates><surface_model>EARTH_WGS84</surface_model><world_frame_orientation>ENU</world_frame_orientation><latitude_deg>47.397971057728974</latitude_deg><longitude_deg>8.546163739800146</longitude_deg><elevation>0</elevation></spherical_coordinates><light name=\"sun\" type=\"directional\"><pose>0 0 500 0 0 0</pose><cast_shadows>true</cast_shadows><intensity>1.15</intensity><direction>-0.25 0.45 -0.82</direction></light><model name=\"ground\"><static>true</static><link name=\"link\"><collision name=\"collision\"><geometry><plane><normal>0 0 1</normal><size>120 120</size></plane></geometry></collision><visual name=\"visual\"><geometry><plane><normal>0 0 1</normal><size>120 120</size></plane></geometry></visual></link></model>{''.join(models)}</world></sdf>
""",
    )
    return destination


def export_layout_assets(scene: SceneSpec, root: str | Path, *, split: str = "train", rebuild: bool = False) -> SceneAssetPaths:
    destination = Path(root) / scene.scene_id
    manifest_path = destination / "manifest.json"
    xml_path = destination / "sionna" / scene.asset_name
    mesh_path = destination / "sionna" / f"{scene.scene_id}.ply"
    world_path = destination / "gazebo" / f"{scene.scene_id}.sdf"
    if not rebuild and all(path.is_file() and path.stat().st_size > 0 for path in (manifest_path, xml_path, mesh_path, world_path)):
        return SceneAssetPaths(manifest_path, world_path, xml_path, mesh_path)
    xml_path, mesh_path = write_sionna_assets(scene, destination / "sionna")
    world_path = write_gazebo_world(scene, world_path)
    payload = json.dumps({
        "scene_id": scene.scene_id,
        "scene_family_id": scene.family_id,
        "split": split,
        "spatial_frame": "local-ENU",
        "area_m": [120.0, 120.0],
        "flight_envelope_bounds_m": [-35.0, 35.0, -35.0, 35.0],
        "buildings": [{"id": name, "center_m": list(center), "size_m": list(size)} for name, center, size in scene.buildings],
        "sionna_xml": str(xml_path.relative_to(destination)),
        "sionna_mesh": str(mesh_path.relative_to(destination)),
        "gazebo_world": str(world_path.relative_to(destination)),
    }, ensure_ascii=False, indent=2)
    atomic_write_text(manifest_path, payload)
    return SceneAssetPaths(manifest_path, world_path, xml_path, mesh_path)
