import assert from "node:assert/strict";
import test from "node:test";

import { rayDisplayPoints, rayTopologyKey, writeRayEndpoint } from "../src/lib/spectrumRays.js";


test("visual ray keeps real topology but follows the current UAV receiver pose", () => {
  const path = {
    id: "path-1",
    points_m: [[42, 6, 24], [13, 12, 18], [0, 0, 20]],
  };

  assert.deepEqual(rayDisplayPoints(path, [8, -4, 21]), [
    [42, 6, 24],
    [13, 12, 18],
    [8, -4, 21],
  ]);
  assert.deepEqual(path.points_m.at(-1), [0, 0, 20]);
});


test("pose-only frames do not rebuild the measured ray topology", () => {
  const transmitters = [{ id: "tx-01", position_m: [42, 6, 24] }];
  const base = {
    sequence: 7,
    current_position_m: [0, 0, 20],
    observation: { anchors: [{ id: "tx-01", ray_paths: [{ id: "path-1", points_m: [[42, 6, 24], [0, 0, 20]] }] }] },
  };

  assert.equal(
    rayTopologyKey(base, transmitters, "all"),
    rayTopologyKey({ ...base, computing: true, current_position_m: [12, 2, 20] }, transmitters, "all"),
  );
  assert.notEqual(rayTopologyKey(base, transmitters, "all"), rayTopologyKey({ ...base, sequence: 8 }, transmitters, "all"));
  assert.notEqual(rayTopologyKey(base, transmitters, "all"), rayTopologyKey(base, transmitters, "tx-01"));
});


test("ray endpoint buffer update touches only the final vertex", () => {
  const positions = new Float32Array([42, 24, -6, 13, 18, -12, 0, 20, 0]);

  assert.equal(writeRayEndpoint(positions, [8, 21, 4]), true);

  assert.deepEqual([...positions], [42, 24, -6, 13, 18, -12, 8, 21, 4]);
  assert.equal(writeRayEndpoint(positions, [8.00001, 21, 4]), false);
});
