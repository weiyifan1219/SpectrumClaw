const COLOR_STOPS = [
  [24, 46, 92],
  [22, 119, 160],
  [45, 181, 133],
  [236, 184, 68],
  [235, 80, 57],
];


function cloneMatrix(matrix) {
  return Array.isArray(matrix) ? matrix.map((row) => [...row]) : [];
}


export function isMeasuredSpectrumValue(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}


export function spectrumColor(value, min = -95, max = -30, alpha = 0.92) {
  if (!isMeasuredSpectrumValue(value)) return `rgba(18, 28, 39, ${Math.min(alpha, 0.16)})`;
  const t = Math.max(0, Math.min(1, (Number(value) - min) / Math.max(1e-6, max - min)));
  const scaled = t * (COLOR_STOPS.length - 1);
  const index = Math.min(COLOR_STOPS.length - 2, Math.floor(scaled));
  const local = scaled - index;
  const start = COLOR_STOPS[index];
  const end = COLOR_STOPS[index + 1];
  const color = start.map((channel, channelIndex) => Math.round(channel + (end[channelIndex] - channel) * local));
  return `rgba(${color[0]}, ${color[1]}, ${color[2]}, ${alpha})`;
}


export function spectrumColorRange(grid) {
  const source = grid?.reconstruction?.ready && Array.isArray(grid?.reconstructed_values_dbm)
    ? grid.reconstructed_values_dbm
    : grid?.values_dbm;
  const values = (Array.isArray(source) ? source.flat() : [])
    .filter(isMeasuredSpectrumValue)
    .map(Number)
    .sort((left, right) => left - right);
  if (values.length < 2) return { min: -95, max: -30, dynamic: false };
  const quantile = (ratio) => {
    const index = (values.length - 1) * ratio;
    const lower = Math.floor(index);
    const fraction = index - lower;
    return values[lower] + (values[Math.min(values.length - 1, lower + 1)] - values[lower]) * fraction;
  };
  let min = quantile(0.05) - 1.5;
  let max = quantile(0.95) + 1.5;
  if (max - min < 12) {
    const midpoint = (min + max) / 2;
    min = midpoint - 6;
    max = midpoint + 6;
  }
  return {
    min: Math.max(-120, min),
    max: Math.min(10, max),
    dynamic: true,
  };
}


export function spectrumGridCells(grid) {
  const sparseValues = Array.isArray(grid?.values_dbm) ? grid.values_dbm : [];
  const reconstructedValues = grid?.reconstruction?.ready && Array.isArray(grid?.reconstructed_values_dbm)
    ? grid.reconstructed_values_dbm
    : sparseValues;
  const observedMask = Array.isArray(grid?.observed_mask) ? grid.observed_mask : [];
  return reconstructedValues.flatMap((row, rowIndex) => (row || [])
    .map((value, columnIndex) => ({
      row: rowIndex,
      column: columnIndex,
      value,
      measured: Boolean(observedMask[rowIndex]?.[columnIndex]),
    }))
    .filter((cell) => isMeasuredSpectrumValue(cell.value)));
}


export function spectrumMeasurementTrack(situation, layerIndex, transmitterId = "all") {
  const track = Array.isArray(situation?.measurement_track) ? situation.measurement_track : [];
  return track.flatMap((item) => {
    const update = item?.grid_update;
    const value = Number(update?.values_dbm?.[transmitterId]);
    if (Number(update?.layer_index) !== Number(layerIndex) || !Number.isFinite(value)) return [];
    if (!Array.isArray(item?.position_m) || item.position_m.length !== 3) return [];
    return [{
      sequence: Number(item.sequence || 0),
      source: item.source || "sionna_rt",
      position_m: item.position_m.map(Number),
      row: Number(update.row),
      column: Number(update.column),
      value,
    }];
  });
}


export function spectrumEstimatedSources(grid, transmitterId = "all") {
  const sources = grid?.reconstruction?.estimated_sources;
  if (!sources || typeof sources !== "object") return [];
  return Object.entries(sources).flatMap(([id, model]) => {
    if (transmitterId !== "all" && id !== transmitterId) return [];
    if (!Array.isArray(model?.position_m) || model.position_m.length < 2) return [];
    return [{
      id,
      position_m: model.position_m.map(Number),
      rmse_db: Number(model.rmse_db),
      confidence: Number(model.confidence),
    }];
  });
}


export function applySpectrumGridUpdate(grid, update) {
  if (!grid || !update || Number(update.layer_index) !== Number(grid.layer_index)) return grid;
  const row = Number(update.row);
  const column = Number(update.column);
  const [rows = 0, columns = 0] = grid.shape || [];
  if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || row >= rows || column < 0 || column >= columns) return grid;
  const transmitterId = grid.transmitter_id || "all";
  const value = Number(update.values_dbm?.[transmitterId]);
  if (!Number.isFinite(value)) return grid;

  const values = cloneMatrix(grid.values_dbm);
  const counts = cloneMatrix(grid.counts);
  const mask = cloneMatrix(grid.observed_mask);
  const reconstructed = cloneMatrix(grid.reconstructed_values_dbm);
  const wasObserved = Boolean(mask[row]?.[column]);
  values[row][column] = value;
  counts[row][column] = Number(update.counts?.[transmitterId]) || Number(counts[row][column] || 0) + 1;
  mask[row][column] = 1;
  if (grid?.reconstruction?.ready && reconstructed[row]) reconstructed[row][column] = value;
  const observedCells = Number(grid.observed_cells || 0) + (wasObserved ? 0 : 1);
  const totalCells = Math.max(1, rows * columns);
  const finiteValues = values.flat().filter(isMeasuredSpectrumValue).map(Number);
  return {
    ...grid,
    values_dbm: values,
    counts,
    observed_mask: mask,
    reconstructed_values_dbm: reconstructed.length ? reconstructed : grid.reconstructed_values_dbm,
    observed_cells: observedCells,
    sample_count: Number(grid.sample_count || 0) + 1,
    coverage_ratio: observedCells / totalCells,
    min_dbm: finiteValues.length ? Math.min(...finiteValues) : null,
    max_dbm: finiteValues.length ? Math.max(...finiteValues) : null,
    latest_timestamp: update.timestamp || grid.latest_timestamp,
  };
}
