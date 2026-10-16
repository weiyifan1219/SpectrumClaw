from __future__ import annotations

import json


def test_variant_exports_paired_gazebo_sionna_and_manifest_assets(tmp_path):
    from uav_rem_active_mapping.scene_variants import export_layout_assets, urban_layout

    scene = urban_layout(layout_index=1, split="train")
    assets = export_layout_assets(scene, tmp_path)

    assert assets.manifest_path.is_file()
    assert assets.gazebo_world_path.is_file()
    assert assets.sionna_xml_path.is_file()
    assert assets.sionna_mesh_path.is_file()
    manifest = json.loads(assets.manifest_path.read_text(encoding="utf-8"))
    assert manifest["scene_id"] == "urban_layout_01"
    assert manifest["split"] == "train"
    assert manifest["spatial_frame"] == "local-ENU"
    assert scene.point_inside_building(0.0, 0.0) is False
    assert len(scene.buildings) >= 5


def test_layout_ids_are_deterministic_and_split_disjoint():
    from uav_rem_active_mapping.scene_variants import urban_layout

    first = urban_layout(layout_index=8, split="test")
    second = urban_layout(layout_index=8, split="test")

    assert first.scene_id == "urban_layout_08"
    assert first.buildings == second.buildings
    assert first.family_id == "urban_layout_08"


def test_formal_and_pilot_layout_ranges_are_supported():
    from uav_rem_active_mapping.scene_variants import urban_layout

    assert urban_layout(layout_index=34, split="test").scene_id == "urban_layout_34"
    assert urban_layout(layout_index=35, split="pretrain").scene_id == "urban_layout_35"
    assert urban_layout(layout_index=36, split="test").scene_id == "urban_layout_36"
