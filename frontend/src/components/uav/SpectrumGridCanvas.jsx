import { useEffect, useMemo, useRef } from "react";

import { spectrumGridRaster } from "../../lib/spectrumGrid.js";


export default function SpectrumGridCanvas({ grid, colorRange, className = "" }) {
  const canvasRef = useRef(null);
  const displayedRef = useRef(null);
  const raster = useMemo(() => spectrumGridRaster(grid, colorRange), [colorRange, grid]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    if (raster.rows < 1 || raster.columns < 1) {
      canvas.getContext("2d")?.clearRect(0, 0, canvas.width, canvas.height);
      displayedRef.current = null;
      return;
    }
    const resized = canvas.width !== raster.columns || canvas.height !== raster.rows;
    if (resized) {
      canvas.width = raster.columns;
      canvas.height = raster.rows;
    }
    const context = canvas.getContext("2d", { alpha: true });
    if (!context) return;
    const image = context.createImageData(raster.columns, raster.rows);
    const identity = `${grid?.layer_index ?? "none"}:${grid?.transmitter_id ?? "all"}`;
    const previous = displayedRef.current;
    if (resized || !raster.hasValues || !previous?.hasValues || previous.identity !== identity) {
      image.data.set(raster.pixels);
      context.putImageData(image, 0, 0);
      displayedRef.current = { identity, hasValues: raster.hasValues, pixels: raster.pixels.slice() };
      return;
    }

    // Only the display blends. Measurements and the original reconstruction
    // remain exact; changing layers or clearing a layer always draws at once.
    const startPixels = previous.pixels;
    const targetPixels = raster.pixels;
    const observedMask = grid?.observed_mask || [];
    const startedAt = performance.now();
    let frameId;
    const paint = (now) => {
      const progress = Math.min(1, (now - startedAt) / 900);
      const mix = 1 - (1 - progress) ** 3;
      for (let cell = 0; cell < raster.rows * raster.columns; cell += 1) {
        const index = cell * 4;
        const measured = Boolean(observedMask[Math.floor(cell / raster.columns)]?.[cell % raster.columns]);
        for (let channel = 0; channel < 4; channel += 1) {
          image.data[index + channel] = measured
            ? targetPixels[index + channel]
            : startPixels[index + channel] + (targetPixels[index + channel] - startPixels[index + channel]) * mix;
        }
      }
      context.putImageData(image, 0, 0);
      displayedRef.current = { identity, hasValues: true, pixels: image.data.slice() };
      if (progress < 1) frameId = requestAnimationFrame(paint);
    };
    frameId = requestAnimationFrame(paint);
    return () => cancelAnimationFrame(frameId);
  }, [grid, raster]);

  return (
    <canvas
      ref={canvasRef}
      className={`uav-rem-raster${className ? ` ${className}` : ""}`}
      role="img"
      aria-label={`${raster.rows} × ${raster.columns} 在线频谱空间网格`}
    />
  );
}
