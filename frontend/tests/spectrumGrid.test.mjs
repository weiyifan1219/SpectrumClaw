import assert from "node:assert/strict";
import test from "node:test";

import { applySpectrumGridUpdate, isMeasuredSpectrumValue } from "../src/lib/spectrumGrid.js";


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
