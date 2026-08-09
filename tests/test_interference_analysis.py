from __future__ import annotations


def _base_request(**overrides):
    request = {
        "scenario": "城市应急通信",
        "emitter_type": "base_station",
        "frequency_band": "2400-2483.5 MHz",
        "tx_power_dbm": 20.0,
        "bandwidth_mhz": 20.0,
        "coverage_radius_m": 100.0,
        "environment": "urban",
        "noise_figure_db": 7.0,
        "antenna_gain_dbi": 2.0,
        "feeder_loss_db": 1.0,
        "interferers": [],
    }
    request.update(overrides)
    return request


def test_interference_analysis_reports_usable_link_without_interferers():
    from backend.skills.interference_analysis.analyzer import analyze_interference

    result = analyze_interference(_base_request(environment="rural"))

    assert result["availability"] == "available"
    assert result["risk_level"] == "low"
    assert result["link_budget"]["sinr_db"] > result["link_budget"]["required_sinr_db"]
    assert result["recommended_channels"]
    assert result["basis"]["propagation_model"] == "log-distance + FSPL reference"
    assert result["limitations"]


def test_cochannel_interferer_reduces_sinr_and_marks_band_unavailable():
    from backend.skills.interference_analysis.analyzer import analyze_interference

    result = analyze_interference(_base_request(interferers=[{
        "name": "邻站",
        "emitter_type": "base_station",
        "frequency_mhz": 2441.75,
        "bandwidth_mhz": 20.0,
        "power_dbm": 40.0,
        "distance_m": 50.0,
        "antenna_gain_dbi": 8.0,
        "activity_factor": 1.0,
    }]))

    assert result["availability"] == "unavailable"
    assert result["risk_level"] == "high"
    assert result["link_budget"]["sinr_margin_db"] < 0
    assert any(item["type"] == "co_channel" for item in result["interference_findings"])
    assert result["avoid_ranges"]


def test_recommended_channels_avoid_a_busy_subband():
    from backend.skills.interference_analysis.analyzer import analyze_interference

    result = analyze_interference(_base_request(interferers=[{
        "name": "现网热点",
        "emitter_type": "wifi_ap",
        "frequency_mhz": 2442.0,
        "bandwidth_mhz": 20.0,
        "power_dbm": 23.0,
        "distance_m": 30.0,
    }]))

    centers = [item["center_mhz"] for item in result["recommended_channels"]]
    assert centers
    assert all(abs(center - 2442.0) >= 20.0 for center in centers[:2])
    assert all("score" in item and "estimated_sinr_db" in item for item in result["recommended_channels"])
