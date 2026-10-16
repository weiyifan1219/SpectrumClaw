#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the complete F x Z Sionna GT volume.")
    parser.add_argument("sample", type=Path)
    parser.add_argument("--output", type=Path, required=True, help="Output stem without extension")
    args = parser.parse_args()

    with np.load(args.sample, allow_pickle=False) as archive:
        rss = np.asarray(archive["rss_dbm"], dtype=np.float32)
        frequencies = np.asarray(archive["frequencies_hz"], dtype=np.float64)
        heights = np.asarray(archive["heights_m"], dtype=np.float32)
        valid = np.asarray(archive["valid_rx_mask"], dtype=bool)
    if rss.shape[:2] != (len(frequencies), len(heights)):
        raise ValueError("rss_dbm 的 F/Z 轴与频率/高度数组不一致")

    valid_values = np.concatenate([
        rss[frequency_index, height_index][valid[height_index]]
        for frequency_index in range(len(frequencies))
        for height_index in range(len(heights))
    ])
    color_min, color_max = np.percentile(valid_values, [1.0, 99.0])
    plt.rcParams.update({
        "font.family": "sans-serif",
        "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
        "svg.fonttype": "none",
        "pdf.fonttype": 42,
        "font.size": 7,
    })
    figure, axes = plt.subplots(
        len(heights),
        len(frequencies),
        figsize=(10.5, 10.8),
        constrained_layout=True,
    )
    cmap = plt.colormaps["inferno"].copy()
    cmap.set_bad("black")
    image = None
    for height_index, height in enumerate(heights):
        for frequency_index, frequency in enumerate(frequencies):
            axis = axes[height_index, frequency_index]
            plane = np.ma.masked_where(~valid[height_index], rss[frequency_index, height_index])
            image = axis.imshow(plane, cmap=cmap, vmin=color_min, vmax=color_max, origin="upper")
            if height_index == 0:
                axis.set_title(f"{frequency / 1e9:g} GHz", fontsize=9)
            if frequency_index == 0:
                axis.set_ylabel(f"{height:g} m", fontsize=9)
            axis.set_xticks([])
            axis.set_yticks([])
    figure.colorbar(
        image,
        ax=axes.ravel().tolist(),
        orientation="horizontal",
        shrink=0.58,
        pad=0.025,
        label="RSS (dBm)",
    )
    figure.suptitle("Sionna RT ground-truth volume\nBlack cells: building interior at the corresponding height", fontsize=11)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output.with_suffix(".png"), dpi=300, bbox_inches="tight")
    figure.savefig(args.output.with_suffix(".pdf"), bbox_inches="tight")
    figure.savefig(args.output.with_suffix(".svg"), bbox_inches="tight")
    plt.close(figure)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
