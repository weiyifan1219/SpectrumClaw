#!/usr/bin/env python3
"""Gazebo camera topic bridge for SpectrumClaw's web console.

This intentionally follows AerialClaw's sensor-bridge pattern: Gazebo Transport
is consumed on the simulator host and the latest camera frame is cached as an
ordinary web image.  The main SpectrumClaw process stays in its existing Python
environment; this small sidecar uses Ubuntu's Gazebo-matched Python bindings.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import subprocess
import tempfile
import time
from pathlib import Path

import numpy as np
from PIL import Image

from gz.msgs10.image_pb2 import Image as GazeboImage
from gz.msgs10.laserscan_pb2 import LaserScan as GazeboLaserScan
from gz.msgs10.pose_v_pb2 import Pose_V as GazeboPoseVector
from gz.transport13 import Node


def list_topics() -> list[str]:
    try:
        result = subprocess.run(
            ["gz", "topic", "-l"], capture_output=True, text=True, check=False, timeout=5
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def list_image_topics() -> list[str]:
    return [topic for topic in list_topics() if topic.endswith("/image")]


CAMERA_DIRECTIONS = ("front", "rear", "left", "right", "down", "chase")


class CameraBridge:
    def __init__(self, output_dir: Path, status_path: Path, max_fps: float, chase_max_fps: float) -> None:
        self.output_dir = output_dir
        self.status_path = status_path
        self.min_intervals = {
            direction: 1.0 / max(chase_max_fps if direction == "chase" else max_fps, 0.1)
            for direction in CAMERA_DIRECTIONS
        }
        self.node = Node()
        self.running = True
        self.cameras = {
            direction: {"topic": "", "frames": 0, "written_frames": 0, "last_frame_at": 0.0, "last_write_at": 0.0}
            for direction in CAMERA_DIRECTIONS
        }
        self.pose_topic = ""
        self.lidar_topic = ""
        self.last_pose_write_at = 0.0
        self.last_lidar_write_at = 0.0
        self.vehicle = {
            "name": "",
            "position_m": [0.0, 0.0, 0.0],
            "quaternion_xyzw": [0.0, 0.0, 0.0, 1.0],
            "updated_at": None,
            "available": False,
        }
        self.lidar = {
            "available": False,
            "count": 0,
            "ranges_m": [],
            "angle_min_rad": 0.0,
            "angle_step_rad": 0.0,
            "range_min_m": 0.0,
            "range_max_m": 0.0,
            "updated_at": None,
        }

    def write_status(self, state: str, error: str = "") -> None:
        payload = {
            "state": state,
            "cameras": {
                direction: {
                    "topic": slot["topic"],
                    "frames": slot["frames"],
                    "written_frames": slot["written_frames"],
                    "last_frame_at": slot["last_frame_at"] or None,
                    "last_write_at": slot["last_write_at"] or None,
                    "online": bool(slot["topic"] and slot["last_frame_at"]),
                }
                for direction, slot in self.cameras.items()
            },
            "vehicle": {**self.vehicle, "pose_topic": self.pose_topic},
            "lidar": {**self.lidar, "topic": self.lidar_topic},
            "error": error,
        }
        self.status_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=self.status_path.parent, delete=False, encoding="utf-8") as handle:
            json.dump(payload, handle)
            temporary = Path(handle.name)
        os.replace(temporary, self.status_path)

    def on_image(self, direction: str, message: GazeboImage) -> None:
        now = time.time()
        slot = self.cameras[direction]
        slot["frames"] += 1
        slot["last_frame_at"] = now
        if now - slot["last_write_at"] < self.min_intervals[direction]:
            return
        width, height = int(message.width), int(message.height)
        payload = bytes(message.data)
        if width <= 0 or height <= 0 or len(payload) < width * height * 3:
            return
        try:
            # PX4's mono camera publishes RGB8.  The payload-size check keeps
            # this conservative for a future model with an alternate format.
            rgb = np.frombuffer(payload, dtype=np.uint8, count=width * height * 3).reshape(height, width, 3)
            image = Image.fromarray(rgb, mode="RGB")
            # Five sensor tiles are only previews.  Encoding them at the same
            # resolution as the selected primary stream steals CPU from the
            # latter without adding visible detail in the browser.
            image.thumbnail((960, 720) if direction == "chase" else (320, 240))
            self.output_dir.mkdir(parents=True, exist_ok=True)
            image_path = self.output_dir / f"{direction}.jpg"
            with tempfile.NamedTemporaryFile("wb", suffix=".jpg", dir=self.output_dir, delete=False) as handle:
                # The browser consumes the chase camera at 24 FPS.  JPEG's
                # optimize pass costs disproportionate CPU for this low-latency
                # path; a slightly lower quality without optimization keeps the
                # 3090 bridge responsive while preserving useful scene detail.
                image.save(handle, format="JPEG", quality=72, optimize=False)
                temporary = Path(handle.name)
            os.replace(temporary, image_path)
            slot["written_frames"] += 1
            slot["last_write_at"] = now
            # Pose/LiDAR callbacks already publish the compact JSON state at
            # 10 Hz.  Writing it again for every JPEG makes filesystem I/O the
            # limiter before CPU or network bandwidth and costs visible FPS.
        except Exception as exc:  # bridge is best-effort; status exposes errors
            self.write_status("error", str(exc))

    def on_lidar(self, message: GazeboLaserScan) -> None:
        now = time.time()
        values = list(message.ranges)
        if not values:
            return
        # AerialClaw also downsamples before network delivery.  Keep the raw
        # Gazebo scan local and publish at most 180 browser points.
        step = max(1, len(values) // 180)
        sampled = [float(value) if math.isfinite(value) else None for value in values[::step]]
        self.lidar = {
            "available": True,
            "count": len(values),
            "ranges_m": sampled,
            "angle_min_rad": float(message.angle_min),
            "angle_step_rad": float(message.angle_step) * step,
            "range_min_m": float(message.range_min),
            "range_max_m": float(message.range_max),
            "updated_at": now,
        }
        if now - self.last_lidar_write_at >= 0.1:
            state = "online" if any(slot["last_frame_at"] for slot in self.cameras.values()) else "waiting"
            self.write_status(state)
            self.last_lidar_write_at = now

    def on_pose(self, message: GazeboPoseVector) -> None:
        """Cache the PX4 vehicle pose for the local WebGL scene.

        Gazebo's dynamic pose topic is published at simulation frequency.  The
        browser only needs a compact 10 Hz state stream, so the sidecar writes
        the shared JSON at that bounded rate instead of on every physics tick.
        """
        for pose in message.pose:
            if "x500_lidar_2d_cam" not in pose.name:
                continue
            self.vehicle = {
                "name": pose.name,
                "position_m": [float(pose.position.x), float(pose.position.y), float(pose.position.z)],
                "quaternion_xyzw": [
                    float(pose.orientation.x), float(pose.orientation.y),
                    float(pose.orientation.z),
                    float(pose.orientation.w),
                ],
                "updated_at": time.time(),
                "available": True,
            }
            now = time.time()
            if now - self.last_pose_write_at >= 0.1:
                state = "online" if any(slot["last_frame_at"] for slot in self.cameras.values()) else "waiting"
                self.write_status(state)
                self.last_pose_write_at = now
            return

    def subscribe_pose_when_available(self) -> None:
        if self.pose_topic:
            return
        candidate = next((topic for topic in list_topics() if topic.endswith("/dynamic_pose/info")), "")
        if candidate and self.node.subscribe(GazeboPoseVector, candidate, self.on_pose):
            self.pose_topic = candidate

    def subscribe_lidar_when_available(self) -> None:
        if self.lidar_topic:
            return
        candidate = next((topic for topic in list_topics() if topic.endswith("/scan") and "lidar" in topic), "")
        if candidate and self.node.subscribe(GazeboLaserScan, candidate, self.on_lidar):
            self.lidar_topic = candidate

    def subscribe_when_available(self) -> None:
        while self.running and not any(slot["topic"] for slot in self.cameras.values()):
            self.subscribe_pose_when_available()
            self.subscribe_lidar_when_available()
            topics = list_image_topics()
            for direction, slot in self.cameras.items():
                candidate = next((topic for topic in topics if f"cam_{direction}" in topic), "")
                if not candidate:
                    continue
                if self.node.subscribe(GazeboImage, candidate, lambda message, d=direction: self.on_image(d, message)):
                    slot["topic"] = candidate
                else:
                    self.write_status("error", f"无法订阅 Gazebo 话题: {candidate}")
            if any(slot["topic"] for slot in self.cameras.values()):
                self.write_status("waiting")
                return
            else:
                self.write_status("waiting", "等待 Gazebo 相机话题")
            time.sleep(1)

    def run(self) -> None:
        self.subscribe_when_available()
        while self.running:
            self.subscribe_pose_when_available()
            self.subscribe_lidar_when_available()
            if any(slot["topic"] and slot["last_frame_at"] and time.time() - slot["last_frame_at"] > 5 for slot in self.cameras.values()):
                self.write_status("waiting", "等待新的 Gazebo 相机帧")
            time.sleep(0.5)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--status", required=True, type=Path)
    parser.add_argument("--max-fps", type=float, default=2.0, help="per-camera limit for five thumbnail streams")
    parser.add_argument("--chase-max-fps", type=float, default=60.0, help="high ceiling; Gazebo sensor rate remains the real limit")
    args = parser.parse_args()
    bridge = CameraBridge(args.output_dir, args.status, args.max_fps, args.chase_max_fps)

    def stop(_signum, _frame):
        bridge.running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    bridge.run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
