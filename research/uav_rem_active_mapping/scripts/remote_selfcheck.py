#!/usr/bin/env python3
"""Dependency-light 3090 self-check. Does not invoke Sionna RT."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

import numpy as np


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
for path in (PACKAGE_ROOT / "src", REPOSITORY_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from uav_rem_active_mapping.dataset_builder import build_dataset
from uav_rem_active_mapping.validation import validate_dataset


class _SyntheticSionnaTestProvider:
    provider_name = "sionna_rt"

    def generate_total_rss(self, *, spec, scene, frequency_hz, height_m, seed):
        return np.full((spec.rows, spec.columns), -75.0 + height_m * 0.01, dtype=np.float32)


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="uav-rem-selfcheck-") as directory:
        manifest = build_dataset(
            output_dir=directory,
            provider=_SyntheticSionnaTestProvider(),
            scene_seeds=[5],
            split="pilot",
        )
        report = validate_dataset(directory)
    assert manifest["sample_count"] == 1
    assert report["ok"] is True
    print("REMOTE_SELF_CHECK_OK", report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
