#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
if str(PACKAGE_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from uav_rem_active_mapping.validation import validate_dataset


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate generated Sionna RT UAV REM NPZ samples.")
    parser.add_argument("dataset", type=Path)
    args = parser.parse_args()
    print(json.dumps(validate_dataset(args.dataset), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
