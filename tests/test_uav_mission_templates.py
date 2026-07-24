"""Tests for fixed, reviewable UAV mission templates."""

from __future__ import annotations


def test_inspection_template_uses_only_preapproved_perimeter_route():
    from backend.skills.uav_spectrum_sim.templates import compile_template

    compiled = compile_template("inspect_safe_perimeter")

    assert compiled.mission == "survey_safe_perimeter"
    assert compiled.requires_navigation is True
    assert compiled.return_home is True
    assert compiled.evidence == []


def test_camera_evidence_template_requires_safe_landmark_and_fresh_frames():
    from backend.skills.uav_spectrum_sim.templates import compile_template

    compiled = compile_template("collect_camera_evidence", landmark="east_gate")

    assert compiled.mission == "navigate_to_safe_landmark"
    assert compiled.landmark == "east_gate"
    assert compiled.evidence == ["camera_frames"]
    assert compiled.requires_navigation is True


def test_search_template_records_lidar_evidence_without_accepting_raw_route():
    from backend.skills.uav_spectrum_sim.templates import compile_template

    compiled = compile_template("search_safe_route")

    assert compiled.mission == "survey_safe_perimeter"
    assert compiled.evidence == ["lidar_summary"]
    assert compiled.requires_navigation is True
