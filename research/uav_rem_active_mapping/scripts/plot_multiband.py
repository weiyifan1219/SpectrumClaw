#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a shared-scale five-band Sionna GT plate.")
    parser.add_argument("sample", type=Path)
    parser.add_argument("--height-m", type=float, default=13.0)
    parser.add_argument("--output", type=Path, required=True, help="Output stem without extension")
    args = parser.parse_args()

    with np.load(args.sample, allow_pickle=False) as archive:
        rss = np.asarray(archive["rss_dbm"], dtype=np.float32)
        frequencies = np.asarray(archive["frequencies_hz"], dtype=np.float64)
        heights = np.asarray(archive["heights_m"], dtype=np.float32)
        valid_all = np.asarray(archive["valid_rx_mask"], dtype=bool)
        building_height = np.asarray(archive["building_height_m"], dtype=np.float32)
    matches = np.flatnonzero(np.isclose(heights, args.height_m))
    if len(matches) != 1:
        raise ValueError(f"样本不包含唯一高度 {args.height_m} m")
    height_index = int(matches[0])
    valid = valid_all[height_index]
    valid_values = rss[:, height_index][:, valid]
    color_min, color_max = np.percentile(valid_values, [1.0, 99.0])

    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 8,
    })
    figure, axes = plt.subplots(2, 3, figsize=(10.8, 7.4), constrained_layout=True)
    cmap = plt.colormaps["inferno"].copy()
    cmap.set_bad("black")
    image = None
    for index, axis in enumerate(axes.flat[:5]):
        plane = np.ma.masked_where(~valid, rss[index, height_index])
        image = axis.imshow(plane, cmap=cmap, vmin=color_min, vmax=color_max, origin="upper")
        axis.set_title(f"{frequencies[index] / 1e9:g} GHz")
        axis.set_xticks([])
        axis.set_yticks([])
    geometry_axis = axes.flat[5]
    geometry = geometry_axis.imshow(building_height, cmap="Greys", origin="upper", vmin=0)
    geometry_axis.set_title("Building height prior")
    geometry_axis.set_xticks([])
    geometry_axis.set_yticks([])
    figure.colorbar(
        image,
        ax=list(axes.flat[:5]),
        orientation="horizontal",
        shrink=0.72,
        pad=0.06,
        label="RSS (dBm)",
    )
    figure.colorbar(geometry, ax=geometry_axis, shrink=0.78, pad=0.03, label="Height (m)")
    figure.suptitle(f"Sionna RT ground truth at {args.height_m:g} m\nBlack cells: building interior")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output.with_suffix(".png"), dpi=300, bbox_inches="tight")
    figure.savefig(args.output.with_suffix(".pdf"), bbox_inches="tight")
    figure.savefig(args.output.with_suffix(".svg"), bbox_inches="tight")
    plt.close(figure)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
