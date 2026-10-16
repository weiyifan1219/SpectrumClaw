from __future__ import annotations

import math
import json
import warnings
import tempfile
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .contracts import DatasetSpec
from .scenes import SceneSpec
from .data_io import atomic_write_text


class SionnaRadioMapProvider:
    provider_name = "sionna_rt"

    def __init__(
        self,
        *,
        asset_dir: str | Path,
        samples_per_tx: int = 1_000_000,
        max_depth: int = 2,
        los: bool = True,
        specular_reflection: bool = True,
        diffuse_reflection: bool = True,
        refraction: bool = True,
        diffraction: bool = True,
        edge_diffraction: bool = True,
        solve_plane: Callable[..., Any] | None = None,
    ) -> None:
        if samples_per_tx <= 0 or max_depth < 0:
            raise ValueError("samples_per_tx 必须为正且 max_depth 不能为负")
        self.asset_dir = Path(asset_dir)
        self.samples_per_tx = int(samples_per_tx)
        self.max_depth = int(max_depth)
        self.los = bool(los)
        self.specular_reflection = bool(specular_reflection)
        self.diffuse_reflection = bool(diffuse_reflection)
        self.refraction = bool(refraction)
        self.diffraction = bool(diffraction)
        self.edge_diffraction = bool(edge_diffraction)
        self._solve_plane = solve_plane or self._solve_with_sionna
        self._prepared_assets: set[str] = set()

    def rt_metadata(self) -> dict[str, object]:
        return {
            "engine": "sionna_rt",
            "samples_per_tx": self.samples_per_tx,
            "max_depth": self.max_depth,
            "los": self.los,
            "specular_reflection": self.specular_reflection,
            "diffuse_reflection": self.diffuse_reflection,
            "refraction": self.refraction,
            "diffraction": self.diffraction,
            "edge_diffraction": self.edge_diffraction,
        }

    def generate_total_rss(
        self,
        *,
        spec: DatasetSpec,
        scene: SceneSpec,
        frequency_hz: float,
        height_m: float,
        seed: int,
    ) -> np.ndarray:
        self.last_plane_seed = int(seed)
        self.last_plane_attempts = 0
        for attempt in range(3):
            actual_seed = int(seed) + attempt
            raw_watts = np.asarray(self._solve_plane(
                spec=spec, scene=scene, frequency_hz=float(frequency_hz),
                height_m=float(height_m), seed=actual_seed,
            ), dtype=np.float64)
            self.last_plane_seed = actual_seed
            self.last_plane_attempts = attempt + 1
            if np.isfinite(raw_watts).all():
                break
            warnings.warn(f"RT非有限值，重采样射线: scene={scene.scene_id} frequency={frequency_hz} height={height_m} seed={actual_seed} attempt={attempt + 1}/3", RuntimeWarning)
        if raw_watts.ndim == 2:
            raw_watts = raw_watts[None, :, :]
        expected = (len(scene.transmitters), spec.rows, spec.columns)
        if raw_watts.shape != expected:
            raise ValueError(f"Sionna rss 形状应为 {expected}，实际为 {raw_watts.shape}")
        if not np.all(np.isfinite(raw_watts)):
            raise ValueError(f"Sionna 返回非有限功率: scene={scene.scene_id} frequency={frequency_hz} height={height_m} seed={seed}")
        total_watts = np.sum(np.maximum(raw_watts, 0.0), axis=0)
        # Sionna rows progress south-to-north; persisted row zero is north.
        total_watts = np.flip(total_watts, axis=0)
        dbm = 10.0 * np.log10(np.maximum(total_watts, 1e-17) * 1_000.0)
        return np.clip(dbm, -140.0, 30.0).astype(np.float32)

    def _solve_with_sionna(
        self,
        *,
        spec: DatasetSpec,
        scene: SceneSpec,
        frequency_hz: float,
        height_m: float,
        seed: int,
    ) -> np.ndarray:
        import mitsuba as mi

        mi.set_variant("cuda_ad_mono_polarized")
        from sionna.rt import PlanarArray, RadioMapSolver, Transmitter, load_scene
        if scene.asset_name == "urban_block.xml":
            from simulation.rf_engine.sionna_measurement_sidecar import write_urban_block_scene_assets
            scene_xml = self.asset_dir / "urban_block.xml"
            scene_mesh = self.asset_dir / "urban_block.ply"
            if scene.scene_id not in self._prepared_assets:
                self.asset_dir.mkdir(parents=True, exist_ok=True)
                with tempfile.TemporaryDirectory(dir=self.asset_dir) as directory:
                    prepared = write_urban_block_scene_assets(directory)
                    atomic_write_text(scene_mesh, (prepared.parent / "urban_block.ply").read_text())
                    atomic_write_text(scene_xml, prepared.read_text())
        else:
            from .scene_variants import write_sionna_assets
            scene_directory = self.asset_dir / scene.scene_id
            scene_xml = scene_directory / scene.asset_name
            scene_mesh = scene_directory / f"{scene.scene_id}.ply"
            if scene.scene_id not in self._prepared_assets:
                scene_xml, scene_mesh = write_sionna_assets(scene, scene_directory)
        self._prepared_assets.add(scene.scene_id)
        scene_rt = load_scene(str(scene_xml))
        scene_rt.frequency = float(frequency_hz)
        scene_rt.tx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
        scene_rt.rx_array = PlanarArray(num_rows=1, num_cols=1, pattern="iso", polarization="V")
        try:
            frequency_index = tuple(float(value) for value in spec.frequencies_hz).index(float(frequency_hz))
        except ValueError as exc:
            raise ValueError("frequency_hz 不属于数据契约") from exc
        for index, transmitter in enumerate(scene.transmitters):
            scene_rt.add(Transmitter(
                name=f"hidden-source-{index + 1}",
                position=mi.Point3f(*transmitter.position_m),
                orientation=mi.Point3f(*transmitter.orientation_rad),
                power_dbm=float(transmitter.powers_dbm[frequency_index]),
            ))
        west, east, south, north = spec.bounds_enu_m
        radio_map = RadioMapSolver()(
            scene_rt,
            center=mi.Point3f((west + east) / 2.0, (south + north) / 2.0, float(height_m)),
            orientation=mi.Point3f(0.0, 0.0, 0.0),
            size=mi.Point2f(east - west, north - south),
            cell_size=mi.Point2f(*spec.cell_size_m),
            samples_per_tx=self.samples_per_tx,
            max_depth=self.max_depth,
            los=self.los,
            specular_reflection=self.specular_reflection,
            diffuse_reflection=self.diffuse_reflection,
            refraction=self.refraction,
            diffraction=self.diffraction,
            edge_diffraction=self.edge_diffraction,
            # Sionna RT 2.0.1 on the 3090 accepts the Mitsuba/Dr.Jit scalar,
            # not a Python int, for RadioMapSolver's sampler seed.
            seed=mi.UInt(int(seed) % (2**32)),
        )
        watts = np.asarray(radio_map.rss.numpy(), dtype=np.float64)
        # Finite checks and bounded, recorded ray-seed retries are centralized
        # in generate_total_rss. Never replace NaN with a fabricated RSS value.
        return watts
