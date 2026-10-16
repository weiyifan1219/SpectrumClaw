#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np


def mask_invalid_receivers(rss_dbm: np.ndarray, valid_rx_mask: np.ndarray) -> np.ma.MaskedArray:
    """Mask building-interior cells for the selected height plane before rendering."""
    if rss_dbm.shape != valid_rx_mask.shape:
        raise ValueError("rss_dbm 与 valid_rx_mask 的形状必须一致")
    return np.ma.masked_where(np.asarray(valid_rx_mask) == 0, rss_dbm)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one Sionna RT ground-truth height plane.")
    parser.add_argument("sample", type=Path)
    parser.add_argument("--frequency-index", type=int, default=0)
    parser.add_argument("--height-index", type=int, default=1)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    with np.load(args.sample, allow_pickle=False) as archive:
        rss = archive["rss_dbm"][args.frequency_index, args.height_index]
        building_height = archive["building_height_m"]
        valid = archive["valid_rx_mask"][args.height_index]
        heights = archive["heights_m"]
        frequencies = archive["frequencies_hz"]
    figure, axes = plt.subplots(1, 3, figsize=(15, 4.5), constrained_layout=True)
    rss_cmap = plt.colormaps["turbo"].copy()
    rss_cmap.set_bad(color="black")
    image = axes[0].imshow(mask_invalid_receivers(rss, valid), cmap=rss_cmap, origin="upper")
    axes[0].set_title(f"Sionna GT RSS: {frequencies[args.frequency_index] / 1e9:.3g} GHz, z={heights[args.height_index]:.0f} m")
    figure.colorbar(image, ax=axes[0], label="dBm")
    height_image = axes[1].imshow(building_height, cmap="Greys", origin="upper")
    axes[1].set_title("Building height prior")
    figure.colorbar(height_image, ax=axes[1], label="m")
    axes[2].imshow(valid, cmap="viridis", vmin=0, vmax=1, origin="upper")
    axes[2].set_title("Valid receiver mask")
    for axis in axes:
        axis.set_xlabel("East grid column")
        axis.set_ylabel("North grid row")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    figure.savefig(args.output, dpi=180)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
