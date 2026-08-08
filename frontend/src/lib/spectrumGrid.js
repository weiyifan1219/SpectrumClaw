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
  const wasObserved = Boolean(mask[row]?.[column]);
  values[row][column] = value;
  counts[row][column] = Number(update.counts?.[transmitterId]) || Number(counts[row][column] || 0) + 1;
  mask[row][column] = 1;
  const observedCells = Number(grid.observed_cells || 0) + (wasObserved ? 0 : 1);
  const totalCells = Math.max(1, rows * columns);
  const finiteValues = values.flat().filter(isMeasuredSpectrumValue).map(Number);
  return {
    ...grid,
    values_dbm: values,
    counts,
    observed_mask: mask,
    observed_cells: observedCells,
    sample_count: Number(grid.sample_count || 0) + 1,
    coverage_ratio: observedCells / totalCells,
    min_dbm: finiteValues.length ? Math.min(...finiteValues) : null,
    max_dbm: finiteValues.length ? Math.max(...finiteValues) : null,
    latest_timestamp: update.timestamp || grid.latest_timestamp,
  };
}
