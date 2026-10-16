from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import torch
from scipy.ndimage import distance_transform_edt, label
from torch.utils.data import Dataset


LIGHT_SPEED_MPS = 299_792_458.0


class EpochDataset(Dataset):
    """Epoch state must be shared with persistent DataLoader workers."""

    @property
    def epoch(self) -> int:
        return int(self._epoch.item())

    @epoch.setter
    def epoch(self, value: int) -> None:
        if not hasattr(self, "_epoch"):
            self._epoch = torch.zeros((), dtype=torch.int64).share_memory_()
        self._epoch.fill_(int(value))


def standardize_rss(rss_dbm: np.ndarray, *, mean_dbm: float, std_db: float) -> np.ndarray:
    if not np.isfinite(mean_dbm) or not np.isfinite(std_db) or std_db <= 0:
        raise ValueError("RSS归一化统计量必须有限且std_db>0")
    return ((np.asarray(rss_dbm, dtype=np.float32) - float(mean_dbm)) / float(std_db)).astype(np.float32)


def _collect_records(roots: Iterable[str | Path], split: str) -> list[tuple[Path, str]]:
    records = []
    for root_value in roots:
        root = Path(root_value)
        manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
        for item in manifest["samples"]:
            if str(item.get("split", manifest.get("split", ""))) == split:
                records.append((root / item["path"], str(item["sample_id"])))
    return records


def compute_rss_statistics(
    *,
    roots: Iterable[str | Path],
    split: str,
    height_m: float,
    frequency_hz: float,
) -> dict[str, float | int]:
    records = _collect_records(roots, split)
    if not records:
        raise ValueError(f"没有找到 split={split} 的样本")
    total = 0.0
    total_square = 0.0
    count = 0
    for path, _sample_id in records:
        with np.load(path, allow_pickle=False) as archive:
            heights = np.asarray(archive["heights_m"], dtype=np.float64)
            frequencies = np.asarray(archive["frequencies_hz"], dtype=np.float64)
            height_matches = np.flatnonzero(np.isclose(heights, float(height_m)))
            frequency_matches = np.flatnonzero(np.isclose(frequencies, float(frequency_hz)))
            if len(height_matches) != 1 or len(frequency_matches) != 1:
                raise ValueError(f"样本不包含目标频率/高度: {path}")
            height_index = int(height_matches[0])
            frequency_index = int(frequency_matches[0])
            rss = np.asarray(archive["rss_dbm"][frequency_index, height_index], dtype=np.float64)
            valid = np.asarray(archive["valid_rx_mask"][height_index], dtype=bool)
            values = rss[valid]
            total += float(values.sum())
            total_square += float(np.square(values).sum())
            count += int(values.size)
    mean = total / count
    variance = max(total_square / count - mean * mean, 0.0)
    std = math.sqrt(variance)
    if std <= 1e-8:
        raise ValueError("训练集RSS方差为0，无法执行单位方差归一化")
    return {
        "mean_dbm": float(mean),
        "std_db": float(std),
        "valid_cell_count": count,
        "sample_count": len(records),
        "height_m": float(height_m),
        "frequency_hz": float(frequency_hz),
    }


def compute_multiband_statistics(
    *,
    roots: Iterable[str | Path],
    split: str,
    heights_m: Sequence[float],
    frequencies_hz: Sequence[float],
) -> dict[str, object]:
    """Compute train-only RSS statistics independently for every band."""
    records = _collect_records(roots, split)
    if not records:
        raise ValueError(f"没有找到 split={split} 的样本")
    totals = np.zeros(len(frequencies_hz), dtype=np.float64)
    squares = np.zeros(len(frequencies_hz), dtype=np.float64)
    counts = np.zeros(len(frequencies_hz), dtype=np.int64)
    for path, _sample_id in records:
        with np.load(path, allow_pickle=False) as archive:
            archive_heights = np.asarray(archive["heights_m"], dtype=np.float64)
            archive_frequencies = np.asarray(archive["frequencies_hz"], dtype=np.float64)
            # NPZ decompresses the entire member on every access, even a slice.
            rss_volume = archive["rss_dbm"]
            valid_volume = archive["valid_rx_mask"]
            height_indices = []
            for height in heights_m:
                matches = np.flatnonzero(np.isclose(archive_heights, float(height)))
                if len(matches) != 1:
                    raise ValueError(f"样本不包含唯一高度 {height}: {path}")
                height_indices.append(int(matches[0]))
            for output_index, frequency in enumerate(frequencies_hz):
                matches = np.flatnonzero(np.isclose(archive_frequencies, float(frequency)))
                if len(matches) != 1:
                    raise ValueError(f"样本不包含唯一频率 {frequency}: {path}")
                frequency_index = int(matches[0])
                for height_index in height_indices:
                    rss = np.asarray(rss_volume[frequency_index, height_index], dtype=np.float64)
                    valid = np.asarray(valid_volume[height_index], dtype=bool)
                    values = rss[valid]
                    totals[output_index] += float(values.sum())
                    squares[output_index] += float(np.square(values).sum())
                    counts[output_index] += int(values.size)
    per_frequency = {}
    for index, frequency in enumerate(frequencies_hz):
        mean = totals[index] / counts[index]
        variance = max(squares[index] / counts[index] - mean * mean, 0.0)
        std = math.sqrt(variance)
        if std <= 1e-8:
            raise ValueError(f"频率 {frequency} Hz 的训练集RSS方差为0")
        per_frequency[str(int(round(float(frequency))))] = {
            "mean_dbm": float(mean),
            "std_db": float(std),
            "valid_cell_count": int(counts[index]),
        }
    return {
        "per_frequency": per_frequency,
        "sample_count": len(records),
        "heights_m": [float(value) for value in heights_m],
        "frequencies_hz": [float(value) for value in frequencies_hz],
        "source_split": split,
    }


def _measurement_mask(
    flyable: np.ndarray,
    *,
    count: int,
    mode: str,
    rng: np.random.Generator,
) -> np.ndarray:
    candidates = np.argwhere(flyable > 0)
    if count == 0:
        return np.zeros_like(flyable, dtype=np.float32)
    if count < 0 or count > len(candidates):
        raise ValueError("采样数量必须位于可飞格点数量范围内")
    if mode == "random":
        selected = candidates[rng.choice(len(candidates), size=count, replace=False)]
    elif mode == "clustered":
        centres = candidates[rng.choice(len(candidates), size=min(4, len(candidates)), replace=False)]
        distances = np.min(
            np.sum((candidates[:, None, :] - centres[None, :, :]) ** 2, axis=2),
            axis=1,
        )
        selected = candidates[np.argsort(distances + rng.random(len(candidates)) * 4.0)[:count]]
    elif mode == "trajectory":
        components, _ = label(flyable > 0)  # Four-neighbour connectivity.
        sizes = np.bincount(components.ravel())
        sizes[0] = 0
        eligible = np.argwhere(np.isin(components, np.flatnonzero(sizes >= count)))
        if len(eligible) == 0:
            raise ValueError("没有足够大的连通可飞区域支持该采样预算")
        start = tuple(int(v) for v in eligible[rng.integers(len(eligible))])
        selected_list = [start]
        visited = {start}
        stack = [start]
        # A randomized depth-first walk retraces visited edges at dead ends.
        # Measurements remain unique; the physical walk never teleports or
        # cuts diagonally through a building corner.
        while len(selected_list) < count:
            row, column = stack[-1]
            neighbours = [(row + dr, column + dc) for dr, dc in ((-1,0),(1,0),(0,-1),(0,1))
                          if 0 <= row + dr < flyable.shape[0] and 0 <= column + dc < flyable.shape[1]
                          and flyable[row + dr, column + dc] and (row + dr, column + dc) not in visited]
            if neighbours:
                point = neighbours[rng.integers(len(neighbours))]
                visited.add(point)
                selected_list.append(point)
                stack.append(point)
            else:
                stack.pop()
        selected = np.asarray(selected_list, dtype=np.int64)
    else:
        raise ValueError(f"未知mask模式: {mode}")
    mask = np.zeros_like(flyable, dtype=np.float32)
    mask[selected[:, 0], selected[:, 1]] = 1.0
    return mask


def _shadow_target(
    *,
    rss_dbm: np.ndarray,
    tx_positions_m: np.ndarray,
    tx_powers_dbm: np.ndarray,
    frequency_hz: float,
    height_m: float,
    bounds_enu_m: np.ndarray,
    valid_mask: np.ndarray,
) -> np.ndarray:
    rows, columns = rss_dbm.shape
    west, east_bound, south, north_bound = (float(value) for value in bounds_enu_m)
    east = west + (np.arange(columns) + 0.5) * (east_bound - west) / columns
    north = north_bound - (np.arange(rows) + 0.5) * (north_bound - south) / rows
    grid_east, grid_north = np.meshgrid(east, north)
    received_linear = np.zeros_like(rss_dbm, dtype=np.float64)
    for index, position in enumerate(np.asarray(tx_positions_m, dtype=np.float64)):
        distance = np.sqrt(
            (grid_east - position[0]) ** 2
            + (grid_north - position[1]) ** 2
            + (float(height_m) - position[2]) ** 2
        )
        distance = np.maximum(distance, 1.0)
        fspl_db = 20.0 * np.log10(4.0 * np.pi * distance * float(frequency_hz) / LIGHT_SPEED_MPS)
        power = float(np.asarray(tx_powers_dbm)[index, 0]) - fspl_db
        received_linear += np.power(10.0, power / 10.0)
    free_space_dbm = 10.0 * np.log10(np.maximum(received_linear, 1e-14))
    severity = np.clip((free_space_dbm - rss_dbm - 3.0) / 40.0, 0.0, 1.0)
    return (severity * valid_mask).astype(np.float32)


def _emitter_target(
    tx_positions_m: np.ndarray,
    *,
    bounds_enu_m: np.ndarray,
    rows: int,
    columns: int,
    sigma_cells: float = 2.5,
) -> np.ndarray:
    west, east_bound, south, north_bound = (float(value) for value in bounds_enu_m)
    east = west + (np.arange(columns) + 0.5) * (east_bound - west) / columns
    north = north_bound - (np.arange(rows) + 0.5) * (north_bound - south) / rows
    grid_east, grid_north = np.meshgrid(east, north)
    sigma_east = sigma_cells * (east_bound - west) / columns
    sigma_north = sigma_cells * (north_bound - south) / rows
    heatmap = np.zeros((rows, columns), dtype=np.float64)
    for position in np.asarray(tx_positions_m, dtype=np.float64):
        gaussian = np.exp(
            -0.5 * (
                ((grid_east - position[0]) / sigma_east) ** 2
                + ((grid_north - position[1]) / sigma_north) ** 2
            )
        )
        heatmap = np.maximum(heatmap, gaussian)
    if heatmap.max() > 0:
        heatmap /= heatmap.max()
    return heatmap.astype(np.float32)


class SingleHeightDataset(EpochDataset):
    def __init__(
        self,
        *,
        roots: Iterable[str | Path],
        split: str,
        height_m: float = 13.0,
        frequency_hz: float = 2.4e9,
        rss_mean_dbm: float,
        rss_std_db: float,
        sample_rates: Sequence[float] | None = None,
        sample_rate_range: Sequence[float] | None = None,
        mask_modes: Sequence[str] = ("random", "trajectory", "clustered"),
        seed: int = 42,
        max_samples: int | None = None,
        cache_in_memory: bool = False,
        cache_workers: int = 8,
    ) -> None:
        self.height_m = float(height_m)
        self.frequency_hz = float(frequency_hz)
        self.sample_rates = None if sample_rates is None else tuple(float(value) for value in sample_rates)
        self.sample_rate_range = None if sample_rate_range is None else tuple(float(value) for value in sample_rate_range)
        self.mask_modes = tuple(str(value) for value in mask_modes)
        self.rss_mean_dbm = float(rss_mean_dbm)
        self.rss_std_db = float(rss_std_db)
        self.seed = int(seed)
        self.epoch = 0
        if self.sample_rates is None and self.sample_rate_range is None:
            self.sample_rate_range = (0.0, 0.05)
        if self.sample_rates is not None and self.sample_rate_range is not None:
            raise ValueError("sample_rates 与 sample_rate_range 不能同时设置")
        if not self.mask_modes or any(mode not in {"random", "trajectory", "clustered"} for mode in self.mask_modes):
            raise ValueError("mask_modes必须包含有效采样模式")
        if self.sample_rates is not None and (
            not self.sample_rates or any(not 0.0 <= value <= 0.05 for value in self.sample_rates)
        ):
            raise ValueError("sample_rates 必须位于 [0,0.05]")
        if self.sample_rate_range is not None and (
            len(self.sample_rate_range) != 2
            or not 0.0 <= self.sample_rate_range[0] <= self.sample_rate_range[1] <= 0.05
        ):
            raise ValueError("sample_rate_range 必须是 [min,max] 且位于 [0,0.05]")
        records = _collect_records(roots, split)
        if max_samples is not None:
            records = records[: int(max_samples)]
        if not records:
            raise ValueError(f"没有找到 split={split} 的样本")
        self.records = records
        self._cache: list[dict[str, np.ndarray]] | None = None
        if cache_in_memory:
            worker_count = max(1, min(int(cache_workers), len(records)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                self._cache = list(executor.map(lambda record: self._load_static(record[0]), records))

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)

    def __len__(self) -> int:
        return len(self.records)

    def _load_static(self, path: Path) -> dict[str, np.ndarray]:
        with np.load(path, allow_pickle=False) as archive:
            heights = np.asarray(archive["heights_m"], dtype=np.float32)
            frequencies = np.asarray(archive["frequencies_hz"], dtype=np.float64)
            height_matches = np.flatnonzero(np.isclose(heights, self.height_m))
            frequency_matches = np.flatnonzero(np.isclose(frequencies, self.frequency_hz))
            if len(height_matches) != 1 or len(frequency_matches) != 1:
                raise ValueError(f"样本不包含目标频率/高度: {path}")
            height_index = int(height_matches[0])
            frequency_index = int(frequency_matches[0])
            target = np.asarray(archive["rss_dbm"][frequency_index, height_index], dtype=np.float32)
            valid = np.asarray(archive["valid_rx_mask"][height_index], dtype=np.float32)
            flyable = np.asarray(archive["flyable_mask"][height_index], dtype=np.float32)
            building_height = np.asarray(archive["building_height_m"], dtype=np.float32)
            bounds = np.asarray(archive["bounds_enu_m"], dtype=np.float32)
            tx_positions = np.asarray(archive["tx_positions_m"], dtype=np.float32)
            tx_powers = np.asarray(archive["tx_powers_dbm"], dtype=np.float32)
        shadow = _shadow_target(
            rss_dbm=target,
            tx_positions_m=tx_positions,
            tx_powers_dbm=tx_powers,
            frequency_hz=self.frequency_hz,
            height_m=self.height_m,
            bounds_enu_m=bounds,
            valid_mask=valid,
        )
        emitter = _emitter_target(
            tx_positions,
            bounds_enu_m=bounds,
            rows=target.shape[0],
            columns=target.shape[1],
        )
        return {
            "target": target,
            "valid": valid.astype(np.uint8),
            "flyable": flyable.astype(np.uint8),
            "occupancy": (building_height > 0).astype(np.uint8),
            "building_height": building_height.astype(np.float16),
            "shadow": shadow.astype(np.float16),
            "emitter": emitter.astype(np.float16),
        }

    def __getitem__(self, index: int) -> dict[str, torch.Tensor | str]:
        path, sample_id = self.records[index]
        static = self._cache[index] if self._cache is not None else self._load_static(path)
        target = static["target"]
        valid = static["valid"].astype(np.float32, copy=False)
        flyable = static["flyable"].astype(np.float32, copy=False)
        occupancy = static["occupancy"].astype(np.float32, copy=False)
        building_height = static["building_height"].astype(np.float32)
        shadow = static["shadow"].astype(np.float32)
        emitter = static["emitter"].astype(np.float32)

        rng = np.random.default_rng(self.seed + self.epoch * 1_000_003 + int(index) * 10_007)
        if self.sample_rates is not None:
            requested_rate = self.sample_rates[int(rng.integers(len(self.sample_rates)))]
            count = int(round(requested_rate * target.size))
        else:
            minimum = int(math.ceil(self.sample_rate_range[0] * target.size))
            maximum = int(math.floor(self.sample_rate_range[1] * target.size))
            count = int(rng.integers(minimum, maximum + 1))
        observed = _measurement_mask(
            flyable,
            count=count,
            mode=self.mask_modes[int(rng.integers(len(self.mask_modes)))],
            rng=rng,
        )
        standardized = standardize_rss(target, mean_dbm=self.rss_mean_dbm, std_db=self.rss_std_db)
        sparse = standardized * observed
        clearance = np.clip(building_height / 30.0, 0.0, 1.0)
        if count == 0:
            distance = np.ones_like(observed, dtype=np.float32)
        else:
            distance = distance_transform_edt(1.0 - observed).astype(np.float32)
            distance /= math.sqrt(target.shape[0] ** 2 + target.shape[1] ** 2)
        coordinate_east = np.broadcast_to(np.linspace(-1.0, 1.0, target.shape[1], dtype=np.float32), target.shape)
        coordinate_north = np.broadcast_to(np.linspace(-1.0, 1.0, target.shape[0], dtype=np.float32)[:, None], target.shape)
        features = np.stack((
            sparse,
            observed,
            occupancy,
            clearance,
            flyable,
            distance,
            coordinate_east,
            coordinate_north,
        ), axis=0).astype(np.float32)
        return {
            "features": torch.from_numpy(features),
            "target_dbm": torch.from_numpy(target[None, ...]),
            "valid_mask": torch.from_numpy(valid[None, ...]),
            "flyable_mask": torch.from_numpy(flyable[None, ...]),
            "observed_mask": torch.from_numpy(observed[None, ...]),
            "shadow_target": torch.from_numpy(shadow[None, ...]),
            "emitter_target": torch.from_numpy(emitter[None, ...]),
            "sample_rate": torch.tensor(count / target.size, dtype=torch.float32),
            "height_m": torch.tensor(self.height_m, dtype=torch.float32),
            "frequency_hz": torch.tensor(self.frequency_hz, dtype=torch.float64),
            "sample_id": sample_id,
        }


class MultiBandHeightDataset(EpochDataset):
    """Expand each immutable FZHW volume into frequency-height training slices."""

    def __init__(
        self,
        *,
        roots: Iterable[str | Path],
        split: str,
        heights_m: Sequence[float],
        frequencies_hz: Sequence[float],
        normalization: dict[str, object],
        sample_rates: Sequence[float] | None = None,
        sample_rate_range: Sequence[float] | None = None,
        mask_modes: Sequence[str] = ("random", "trajectory", "clustered"),
        seed: int = 42,
        max_samples: int | None = None,
        cache_in_memory: bool = False,
        cache_workers: int = 8,
    ) -> None:
        self.heights_m = tuple(float(value) for value in heights_m)
        self.frequencies_hz = tuple(float(value) for value in frequencies_hz)
        self.sample_rates = None if sample_rates is None else tuple(float(value) for value in sample_rates)
        self.sample_rate_range = None if sample_rate_range is None else tuple(float(value) for value in sample_rate_range)
        self.mask_modes = tuple(str(value) for value in mask_modes)
        self.normalization = normalization
        self.seed = int(seed)
        self.epoch = 0
        if self.sample_rates is None and self.sample_rate_range is None:
            self.sample_rate_range = (0.0, 0.05)
        if self.sample_rates is not None and self.sample_rate_range is not None:
            raise ValueError("sample_rates 与 sample_rate_range 不能同时设置")
        if self.sample_rates is not None and (not self.sample_rates or any(not 0 <= rate <= 0.25 for rate in self.sample_rates)):
            raise ValueError("sample_rates必须位于[0,0.25]")
        if not self.mask_modes or any(mode not in {"random", "trajectory", "clustered"} for mode in self.mask_modes):
            raise ValueError("mask_modes必须包含有效采样模式")
        for frequency in self.frequencies_hz:
            stats = normalization["per_frequency"][str(int(round(frequency))) ]
            if not np.isfinite(stats["mean_dbm"]) or not np.isfinite(stats["std_db"]) or stats["std_db"] <= 0:
                raise ValueError("逐频归一化统计量必须有限且标准差为正")
        if self.sample_rate_range is not None and (
            len(self.sample_rate_range) != 2
            or not 0.0 <= self.sample_rate_range[0] <= self.sample_rate_range[1] <= 0.25
        ):
            raise ValueError("sample_rate_range 必须位于 [0,0.25]")
        records = _collect_records(roots, split)
        if max_samples is not None:
            records = records[: int(max_samples)]
        if not records:
            raise ValueError(f"没有找到 split={split} 的样本")
        self.records = records
        self.slices = [
            (record_index, frequency_index, height_index)
            for record_index in range(len(records))
            for frequency_index in range(len(self.frequencies_hz))
            for height_index in range(len(self.heights_m))
        ]
        self._cache: list[dict[str, np.ndarray]] | None = None
        if cache_in_memory:
            worker_count = max(1, min(int(cache_workers), len(records)))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                self._cache = list(executor.map(lambda record: self._load_volume(record[0]), records))

    def set_epoch(self, epoch: int) -> None:
        self.epoch = int(epoch)

    def __len__(self) -> int:
        return len(self.slices)

    def _load_volume(self, path: Path) -> dict[str, np.ndarray]:
        with np.load(path, allow_pickle=False) as archive:
            archive_heights = np.asarray(archive["heights_m"], dtype=np.float64)
            archive_frequencies = np.asarray(archive["frequencies_hz"], dtype=np.float64)
            height_indices = []
            frequency_indices = []
            for height in self.heights_m:
                matches = np.flatnonzero(np.isclose(archive_heights, height))
                if len(matches) != 1:
                    raise ValueError(f"样本不包含高度 {height}: {path}")
                height_indices.append(int(matches[0]))
            for frequency in self.frequencies_hz:
                matches = np.flatnonzero(np.isclose(archive_frequencies, frequency))
                if len(matches) != 1:
                    raise ValueError(f"样本不包含频率 {frequency}: {path}")
                frequency_indices.append(int(matches[0]))
            return {
                "rss": np.asarray(archive["rss_dbm"], dtype=np.float32)[np.ix_(frequency_indices, height_indices)],
                "valid": np.asarray(archive["valid_rx_mask"], dtype=np.uint8)[height_indices],
                "flyable": np.asarray(archive["flyable_mask"], dtype=np.uint8)[height_indices],
                "building_height": np.asarray(archive["building_height_m"], dtype=np.float16),
                "bounds": np.asarray(archive["bounds_enu_m"], dtype=np.float32),
                "tx_positions": np.asarray(archive["tx_positions_m"], dtype=np.float32),
                "tx_powers": np.asarray(archive["tx_powers_dbm"], dtype=np.float32)[:, frequency_indices],
            }

    def __getitem__(self, index: int) -> dict[str, torch.Tensor | str]:
        record_index, frequency_index, height_index = self.slices[index]
        path, sample_id = self.records[record_index]
        volume = self._cache[record_index] if self._cache is not None else self._load_volume(path)
        target = volume["rss"][frequency_index, height_index]
        valid = volume["valid"][height_index].astype(np.float32, copy=False)
        flyable = volume["flyable"][height_index].astype(np.float32, copy=False)
        building_height = volume["building_height"].astype(np.float32)
        frequency_hz = self.frequencies_hz[frequency_index]
        height_m = self.heights_m[height_index]
        stats = self.normalization["per_frequency"][str(int(round(frequency_hz)))]
        mean_dbm = float(stats["mean_dbm"])
        std_db = float(stats["std_db"])
        rng = np.random.default_rng(self.seed + self.epoch * 1_000_003 + index * 10_007)
        if self.sample_rates is not None:
            count = int(round(self.sample_rates[int(rng.integers(len(self.sample_rates)))] * target.size))
        else:
            minimum = int(math.ceil(self.sample_rate_range[0] * target.size))
            maximum = int(math.floor(self.sample_rate_range[1] * target.size))
            count = int(rng.integers(minimum, maximum + 1))
        count = min(count, int(np.count_nonzero(flyable)))
        observed = _measurement_mask(
            flyable,
            count=count,
            mode=self.mask_modes[int(rng.integers(len(self.mask_modes)))],
            rng=rng,
        )
        standardized = standardize_rss(target, mean_dbm=mean_dbm, std_db=std_db)
        occupancy = (building_height > 0).astype(np.float32)
        relative_height = np.clip((building_height - height_m) / 30.0, -1.0, 1.0)
        if count == 0:
            distance = np.ones_like(observed, dtype=np.float32)
        else:
            distance = distance_transform_edt(1.0 - observed).astype(np.float32)
            distance /= math.sqrt(target.shape[0] ** 2 + target.shape[1] ** 2)
        coordinate_east = np.broadcast_to(np.linspace(-1.0, 1.0, target.shape[1], dtype=np.float32), target.shape)
        coordinate_north = np.broadcast_to(np.linspace(-1.0, 1.0, target.shape[0], dtype=np.float32)[:, None], target.shape)
        features = np.stack((
            standardized * observed,
            observed,
            occupancy,
            relative_height,
            flyable,
            distance,
            coordinate_east,
            coordinate_north,
        ), axis=0).astype(np.float32)
        shadow = _shadow_target(
            rss_dbm=target,
            tx_positions_m=volume["tx_positions"],
            tx_powers_dbm=volume["tx_powers"][:, frequency_index:frequency_index + 1],
            frequency_hz=frequency_hz,
            height_m=height_m,
            bounds_enu_m=volume["bounds"],
            valid_mask=valid,
        )
        emitter = _emitter_target(
            volume["tx_positions"],
            bounds_enu_m=volume["bounds"],
            rows=target.shape[0],
            columns=target.shape[1],
        )
        return {
            "features": torch.from_numpy(features),
            "target_dbm": torch.from_numpy(target[None, ...]),
            "valid_mask": torch.from_numpy(valid[None, ...]),
            "flyable_mask": torch.from_numpy(flyable[None, ...]),
            "observed_mask": torch.from_numpy(observed[None, ...]),
            "shadow_target": torch.from_numpy(shadow[None, ...]),
            "emitter_target": torch.from_numpy(emitter[None, ...]),
            "sample_rate": torch.tensor(count / target.size, dtype=torch.float32),
            "height_m": torch.tensor(height_m, dtype=torch.float32),
            "frequency_hz": torch.tensor(frequency_hz, dtype=torch.float64),
            "rss_mean_dbm": torch.tensor(mean_dbm, dtype=torch.float32),
            "rss_std_db": torch.tensor(std_db, dtype=torch.float32),
            "sample_id": f"{sample_id}/f{frequency_index}/z{height_index}",
        }
