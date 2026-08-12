import assert from "node:assert/strict";
import test from "node:test";

import { applySpectrumGridUpdate, isMeasuredSpectrumValue, spectrumColorRange, spectrumEstimatedSources, spectrumGridCells, spectrumMeasurementTrack } from "../src/lib/spectrumGrid.js";


function emptyGrid() {
  return {
    layer_index: 4,
    transmitter_id: "all",
    shape: [2, 2],
    values_dbm: [[null, null], [null, null]],
    counts: [[0, 0], [0, 0]],
    observed_mask: [[0, 0], [0, 0]],
    observed_cells: 0,
    sample_count: 0,
    coverage_ratio: 0,
  };
}


test("live grid update fills the measured cell and preserves unknown cells", () => {
  const current = emptyGrid();
  const next = applySpectrumGridUpdate(current, {
    layer_index: 4,
    row: 1,
    column: 0,
    values_dbm: { all: -48.25, "tx-01": -50.0 },
  });

  assert.equal(next.values_dbm[1][0], -48.25);
  assert.equal(next.values_dbm[0][0], null);
  assert.equal(next.observed_mask[1][0], 1);
  assert.equal(next.counts[1][0], 1);
  assert.equal(next.observed_cells, 1);
  assert.equal(next.sample_count, 1);
  assert.equal(next.coverage_ratio, 0.25);
  assert.equal(current.values_dbm[1][0], null);
});


test("update for another height layer does not mutate the visible grid", () => {
  const current = emptyGrid();
  const next = applySpectrumGridUpdate(current, {
    layer_index: 1,
    row: 1,
    column: 0,
    values_dbm: { all: -48.25 },
  });

  assert.equal(next, current);
});

test("only finite non-null values are rendered as measured spectrum cells", () => {
  assert.equal(isMeasuredSpectrumValue(null), false);
  assert.equal(isMeasuredSpectrumValue(undefined), false);
  assert.equal(isMeasuredSpectrumValue(""), false);
  assert.equal(isMeasuredSpectrumValue(Number.NaN), false);
  assert.equal(isMeasuredSpectrumValue(-35.57), true);
  assert.equal(isMeasuredSpectrumValue("-42.1"), true);
});

test("reconstructed layer keeps measured cells distinguishable from IDW estimates", () => {
  const cells = spectrumGridCells({
    shape: [2, 2],
    values_dbm: [[-50, null], [null, -70]],
    reconstructed_values_dbm: [[-50, -55], [-65, -70]],
    observed_mask: [[1, 0], [0, 1]],
    reconstruction: { ready: true, method: "idw" },
  });

  assert.deepEqual(cells, [
    { row: 0, column: 0, value: -50, measured: true },
    { row: 0, column: 1, value: -55, measured: false },
    { row: 1, column: 0, value: -65, measured: false },
    { row: 1, column: 1, value: -70, measured: true },
  ]);
});

test("color range follows the reconstructed layer instead of a fixed global scale", () => {
  const range = spectrumColorRange({
    reconstructed_values_dbm: [[-62, -58, -55], [-51, -48, -44]],
    reconstruction: { ready: true },
  });

  assert.ok(range.min > -95);
  assert.ok(range.max < -30);
  assert.ok(range.max - range.min >= 12);
  assert.equal(range.dynamic, true);
});

test("authoritative Sionna measurement track exposes one value per flown grid cell", () => {
  const track = spectrumMeasurementTrack({
    measurement_track: [
      { sequence: 4, source: "sionna_rt", position_m: [-4, 0, 21], grid_update: { layer_index: 4, row: 15, column: 14, values_dbm: { all: -42, "tx-01": -44 } } },
      { sequence: 5, source: "sionna_rt", position_m: [0, 0, 21], grid_update: { layer_index: 4, row: 15, column: 15, values_dbm: { all: -40, "tx-01": -43 } } },
      { sequence: 6, source: "sionna_rt", position_m: [4, 0, 16], grid_update: { layer_index: 3, row: 15, column: 16, values_dbm: { all: -39 } } },
    ],
  }, 4, "tx-01");

  assert.deepEqual(track, [
    { sequence: 4, source: "sionna_rt", position_m: [-4, 0, 21], row: 15, column: 14, value: -44 },
    { sequence: 5, source: "sionna_rt", position_m: [0, 0, 21], row: 15, column: 15, value: -43 },
  ]);
});

test("blind source markers come only from reconstruction estimates", () => {
  const grid = {
    reconstruction: {
      estimated_sources: {
        "tx-01": { position_m: [38, 6, 22.5], rmse_db: 1.2, confidence: 0.7 },
        "tx-02": { position_m: [-42, -10, 22.5], rmse_db: 2.1, confidence: 0.5 },
      },
    },
  };

  assert.deepEqual(spectrumEstimatedSources(grid, "tx-01"), [
    { id: "tx-01", position_m: [38, 6, 22.5], rmse_db: 1.2, confidence: 0.7 },
  ]);
  assert.equal(spectrumEstimatedSources({}, "all").length, 0);
});
