const COLOR_STOPS = [
  [24, 46, 92],
  [22, 119, 160],
  [45, 181, 133],
  [236, 184, 68],
  [235, 80, 57],
];
const TOTAL_POWER_RANGE = Object.freeze({ min: -65, max: -20, dynamic: false });
const SOURCE_POWER_RANGE = Object.freeze({ min: -80, max: -25, dynamic: false });


function replaceMatrixCell(matrix, row, column, value) {
  if (!Array.isArray(matrix) || !Array.isArray(matrix[row])) return [];
  const next = [...matrix];
  next[row] = [...matrix[row]];
  next[row][column] = value;
  return next;
}


function spectrumColorChannels(value, min = -65, max = -20, alpha = 0.92) {
  if (!isMeasuredSpectrumValue(value)) return [18, 28, 39, Math.round(Math.min(alpha, 0.16) * 255)];
  const t = Math.max(0, Math.min(1, (Number(value) - min) / Math.max(1e-6, max - min)));
  const scaled = t * (COLOR_STOPS.length - 1);
  const index = Math.min(COLOR_STOPS.length - 2, Math.floor(scaled));
  const local = scaled - index;
  const start = COLOR_STOPS[index];
  const end = COLOR_STOPS[index + 1];
  return [
    ...start.map((channel, channelIndex) => Math.round(channel + (end[channelIndex] - channel) * local)),
    Math.round(Math.max(0, Math.min(1, alpha)) * 255),
  ];
}


function displayedSpectrumValues(grid) {
  const sparseValues = Array.isArray(grid?.values_dbm) ? grid.values_dbm : [];
  return (grid?.reconstruction?.ready || grid?.reconstruction?.stale) && Array.isArray(grid?.reconstructed_values_dbm)
    ? grid.reconstructed_values_dbm
    : sparseValues;
}


export function isMeasuredSpectrumValue(value) {
  return value !== null && value !== undefined && value !== "" && Number.isFinite(Number(value));
}


export function spectrumColor(value, min = -65, max = -20, alpha = 0.92) {
  const [red, green, blue, opacity] = spectrumColorChannels(value, min, max, alpha);
  return `rgba(${red}, ${green}, ${blue}, ${opacity / 255})`;
}


export function spectrumColorRange(grid) {
  // A fixed scale keeps every cell's color comparable as the original
  // reconstruction adds measurements and refits the source positions.
  return grid?.transmitter_id && grid.transmitter_id !== "all"
    ? SOURCE_POWER_RANGE
    : TOTAL_POWER_RANGE;
}


export function spectrumGridCells(grid) {
  const sparseValues = Array.isArray(grid?.values_dbm) ? grid.values_dbm : [];
  const reconstructedValues = displayedSpectrumValues(grid);
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


export function spectrumGridRaster(grid, colorRange = TOTAL_POWER_RANGE) {
  const values = displayedSpectrumValues(grid);
  const observedMask = Array.isArray(grid?.observed_mask) ? grid.observed_mask : [];
  const declaredRows = Number(grid?.shape?.[0]);
  const declaredColumns = Number(grid?.shape?.[1]);
  const rows = Number.isInteger(declaredRows) && declaredRows > 0 ? declaredRows : values.length;
  const columns = Number.isInteger(declaredColumns) && declaredColumns > 0
    ? declaredColumns
    : Math.max(0, ...values.map((row) => Array.isArray(row) ? row.length : 0));
  const pixels = new Uint8ClampedArray(rows * columns * 4);
  let hasValues = false;
  for (let row = 0; row < rows; row += 1) {
    for (let column = 0; column < columns; column += 1) {
      const value = values[row]?.[column];
      const measured = Boolean(observedMask[row]?.[column]);
      const valid = isMeasuredSpectrumValue(value);
      const channels = spectrumColorChannels(
        value,
        Number(colorRange?.min ?? TOTAL_POWER_RANGE.min),
        Number(colorRange?.max ?? TOTAL_POWER_RANGE.max),
        valid ? measured ? 0.96 : 0.84 : 0.16,
      );
      pixels.set(channels, (row * columns + column) * 4);
      hasValues ||= valid;
    }
  }
  return { rows, columns, pixels, hasValues };
}


export function spectrumGridHasValues(grid) {
  return displayedSpectrumValues(grid).some((row) => (row || []).some(isMeasuredSpectrumValue));
}


export function fuseReceiverRssiGrid(grid, receiverGrid) {
  // Keep the Sionna source maps intact. A mixed receiver RSSI sample can only
  // correct the total-power view at and near its observed spatial cell.
  if (!grid || grid.transmitter_id !== "all" || receiverGrid?.layer_index !== grid.layer_index) return grid;
  const samples = Array.isArray(receiverGrid.samples) ? receiverGrid.samples : [];
  if (!samples.length) return grid;
  const [rows, columns] = grid.shape || [];
  if (!Number.isInteger(rows) || !Number.isInteger(columns) || rows < 1 || columns < 1) return grid;
  const dense = (grid.reconstruction?.ready || grid.reconstruction?.stale) && Array.isArray(grid.reconstructed_values_dbm);
  const baseline = dense ? grid.reconstructed_values_dbm : grid.values_dbm;
  if (!Array.isArray(baseline)) return grid;
  const sums = new Float64Array(rows * columns);
  const weights = new Float64Array(rows * columns);
  const accepted = [];
  const radius = 12;
  const sigmaSquared = 4 * 4;
  for (const sample of samples) {
    const row = Number(sample.row);
    const column = Number(sample.column);
    const value = Number(sample.rssi_dbm);
    if (!Number.isInteger(row) || !Number.isInteger(column) || row < 0 || column < 0 || row >= rows || column >= columns || !Number.isFinite(value)) continue;
    accepted.push({ row, column, value });
    const reference = baseline[row]?.[column];
    if (!isMeasuredSpectrumValue(reference)) continue;
    const residual = value - Number(reference);
    for (let y = Math.max(0, row - radius); y <= Math.min(rows - 1, row + radius); y += 1) {
      for (let x = Math.max(0, column - radius); x <= Math.min(columns - 1, column + radius); x += 1) {
        const distanceSquared = (y - row) ** 2 + (x - column) ** 2;
        if (distanceSquared > radius ** 2) continue;
        const weight = Math.exp(-distanceSquared / (2 * sigmaSquared));
        const index = y * columns + x;
        sums[index] += weight * residual;
        weights[index] += weight;
      }
    }
  }
  if (!accepted.length) return grid;
  const values = baseline.map((row, y) => (row || []).map((base, x) => {
    const weight = weights[y * columns + x];
    return isMeasuredSpectrumValue(base) && weight > 0
      ? Number(base) + sums[y * columns + x] / weight * Math.min(1, weight)
      : base;
  }));
  const mask = (grid.observed_mask || []).map((row) => [...row]);
  for (const sample of accepted) {
    values[sample.row][sample.column] = sample.value;
    if (mask[sample.row]) mask[sample.row][sample.column] = 1;
  }
  return {
    ...grid,
    ...(dense ? { reconstructed_values_dbm: values } : { values_dbm: values }),
    observed_mask: mask,
    receiver_fusion: { method: "local_gaussian_residual", observed_cells: accepted.length, radius_cells: radius },
  };
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

  const previousValue = grid.values_dbm?.[row]?.[column];
  const wasObserved = Boolean(grid.observed_mask?.[row]?.[column]);
  const values = replaceMatrixCell(grid.values_dbm, row, column, value);
  const counts = replaceMatrixCell(
    grid.counts,
    row,
    column,
    Number(update.counts?.[transmitterId]) || Number(grid.counts?.[row]?.[column] || 0) + 1,
  );
  const mask = replaceMatrixCell(grid.observed_mask, row, column, 1);
  const hasDenseReconstruction = Boolean(grid?.reconstruction?.ready || grid?.reconstruction?.stale);
  const reconstructed = hasDenseReconstruction
    ? replaceMatrixCell(grid.reconstructed_values_dbm, row, column, value)
    : grid.reconstructed_values_dbm;
  const observedCells = Number(grid.observed_cells || 0) + (wasObserved ? 0 : 1);
  const totalCells = Math.max(1, rows * columns);
  const previousMin = isMeasuredSpectrumValue(grid.min_dbm) ? Number(grid.min_dbm) : null;
  const previousMax = isMeasuredSpectrumValue(grid.max_dbm) ? Number(grid.max_dbm) : null;
  const mustRescanRange = wasObserved && (
    Number(previousValue) === previousMin || Number(previousValue) === previousMax
  );
  const finiteValues = mustRescanRange ? values.flat().filter(isMeasuredSpectrumValue).map(Number) : [];
  const minDbm = mustRescanRange
    ? Math.min(...finiteValues)
    : Number.isFinite(previousMin) ? Math.min(previousMin, value) : value;
  const maxDbm = mustRescanRange
    ? Math.max(...finiteValues)
    : Number.isFinite(previousMax) ? Math.max(previousMax, value) : value;
  return {
    ...grid,
    values_dbm: values,
    counts,
    observed_mask: mask,
    reconstructed_values_dbm: reconstructed,
    reconstruction: hasDenseReconstruction
      ? { ...grid.reconstruction, ready: false, stale: true }
      : grid.reconstruction,
    observed_cells: observedCells,
    sample_count: Number(grid.sample_count || 0) + 1,
    coverage_ratio: observedCells / totalCells,
    min_dbm: minDbm,
    max_dbm: maxDbm,
    latest_timestamp: update.timestamp || grid.latest_timestamp,
  };
}
