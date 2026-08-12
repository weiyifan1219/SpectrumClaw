function finitePoint(point) {
  return Array.isArray(point) && point.length === 3 && point.every((value) => Number.isFinite(Number(value)));
}


export function rayDisplayPoints(path, receiverPosition) {
  const points = Array.isArray(path?.points_m)
    ? path.points_m.filter(finitePoint).map((point) => point.map(Number))
    : [];
  if (points.length < 2 || !finitePoint(receiverPosition)) return points;
  return [...points.slice(0, -1), receiverPosition.map(Number)];
}


export function rayTopologyKey(situation, transmitters, selectedTransmitter) {
  const observation = situation?.observation;
  const anchors = Array.isArray(observation?.anchors) ? observation.anchors : [];
  const sourceKey = (Array.isArray(transmitters) ? transmitters : [])
    .map((source) => `${source.id}:${(source.position_m || []).join(",")}:${source.altitude_m ?? ""}`)
    .join("|");
  const topologyVersion = situation?.sequence
    ?? situation?.captured_at
    ?? observation?.timestamp
    ?? anchors.map((anchor) => `${anchor.id}:${(anchor.ray_paths || []).map((path) => `${path.id}:${path.points_m?.length || 0}`).join(",")}`).join("|");
  return `${topologyVersion ?? "none"}::${selectedTransmitter || "all"}::${sourceKey}`;
}


export function writeRayEndpoint(positionArray, point, epsilon = 1e-4) {
  if (!positionArray || positionArray.length < 3 || !finitePoint(point)) return false;
  const offset = positionArray.length - 3;
  const next = point.map(Number);
  if (
    Math.abs(positionArray[offset] - next[0]) <= epsilon
    && Math.abs(positionArray[offset + 1] - next[1]) <= epsilon
    && Math.abs(positionArray[offset + 2] - next[2]) <= epsilon
  ) return false;
  positionArray[offset] = next[0];
  positionArray[offset + 1] = next[1];
  positionArray[offset + 2] = next[2];
  return true;
}
