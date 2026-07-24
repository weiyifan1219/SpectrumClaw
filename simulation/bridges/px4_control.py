#!/usr/bin/env python3
"""Small, simulation-only PX4 SITL action adapter.

It follows AerialClaw's adapter boundary: the web / agent process never talks
to Gazebo directly. It checks PX4's local SITL commander state, then calls only
PX4's local SITL commander clients for an allow-listed action set. This is
necessary because this simulation's intentional preflight failure rejects
external MAVLink arming, while the SITL commander supports ``arm -f``.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path
LOCK_PATH = Path("/tmp/spectrumclaw-px4-control.lock")


@contextmanager
def exclusive_control():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("w", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield


def px4_build_dir() -> Path:
    configured = os.environ.get("SPECTRUMCLAW_PX4_DIR")
    project_root = Path(__file__).resolve().parents[2]
    px4_root = Path(configured) if configured else project_root / "simulation" / "third_party" / "PX4-Autopilot"
    build_dir = px4_root / "build" / "px4_sitl_default"
    if not (build_dir / "bin" / "px4-commander").is_file() or not (build_dir / "bin" / "px4-param").is_file():
        raise RuntimeError("未找到当前 SITL 的 PX4 commander 控制端")
    return build_dir


def run_px4_client(build_dir: Path, binary: str, *arguments: str) -> dict:
    """Run one fixed PX4 client command; no user-provided shell is exposed."""
    result = subprocess.run(
        [str(build_dir / "bin" / binary), *arguments],
        cwd=build_dir,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout).strip() or f"{binary} 返回 {result.returncode}"
        raise RuntimeError(detail)
    return {"client": binary, "arguments": list(arguments), "output": result.stdout.strip()}


def commander_status(build_dir: Path) -> dict:
    receipt = run_px4_client(build_dir, "px4-commander", "status")
    output = receipt["output"]
    mode = re.search(r"navigation mode: (.+)", output)
    return {
        "connected": True,
        "armed": "INFO  [commander] Armed" in output and "INFO  [commander] Disarmed" not in output,
        "navigation_mode": mode.group(1).strip() if mode else "unknown",
        "source": "px4-commander",
    }


def execute(action: str, altitude_m: float | None = None) -> dict:
    with exclusive_control():
        build_dir = px4_build_dir()
        before = commander_status(build_dir)
        if action == "status":
            return {"ok": True, "action": action, "vehicle": before}
        if action == "arm":
            receipt = run_px4_client(build_dir, "px4-commander", "arm", "-f")
        elif action == "takeoff":
            altitude = float(altitude_m if altitude_m is not None else 3.0)
            if not 1.0 <= altitude <= 20.0:
                raise ValueError("仿真起飞高度必须在 1–20 m 之间")
            # Explicitly set the SITL takeoff parameter so the API/UI height
            # is the actual PX4 target rather than a decorative label.
            run_px4_client(build_dir, "px4-param", "set", "MIS_TAKEOFF_ALT", f"{altitude:g}")
            if not before["armed"]:
                run_px4_client(build_dir, "px4-commander", "arm", "-f")
            receipt = run_px4_client(build_dir, "px4-commander", "mode", "auto:takeoff")
        elif action == "land":
            receipt = run_px4_client(build_dir, "px4-commander", "land")
        elif action == "hover":
            receipt = run_px4_client(build_dir, "px4-commander", "mode", "auto:loiter")
        elif action == "return_to_launch":
            receipt = run_px4_client(build_dir, "px4-commander", "mode", "auto:rtl")
        else:
            raise ValueError(f"不支持的仿真飞行指令: {action}")
        return {"ok": True, "action": action, "receipt": receipt, "vehicle": before}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("status", "arm", "takeoff", "hover", "land", "return_to_launch"))
    parser.add_argument("--altitude-m", type=float)
    args = parser.parse_args()
    try:
        print(json.dumps(execute(args.action, args.altitude_m), ensure_ascii=False))
        return 0
    except Exception as exc:
        print(json.dumps({"ok": False, "action": args.action, "error": str(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
