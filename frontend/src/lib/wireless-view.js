export const batchRateKey = (root, session) => root && session ? JSON.stringify([root, session]) : "";

export function resolveIQRate(record, singleRate, batchRate) {
  const positive = (value) => Number.isFinite(Number(value)) && Number(value) > 0;
  if (record?.sample_rate_source === "header" && positive(record.sample_rate_hz))
    return { rate: Number(record.sample_rate_hz), source: "header" };
  if (positive(singleRate)) return { rate: Number(singleRate), override: Number(singleRate), source: "single" };
  if (record?.sample_rate_source === "explicit_upload" && positive(record.sample_rate_hz))
    return { rate: Number(record.sample_rate_hz), source: "upload" };
  if (positive(batchRate)) return { rate: Number(batchRate), override: Number(batchRate), source: "batch" };
  return { rate: 0, source: "missing" };
}

// Display candidate classes without changing the model's stored acceptance status.
// Invalid input and failed inference must never be turned into a candidate result.
export function protocolPresentation(protocol) {
  const validScore = (value) => typeof value === "number" && Number.isFinite(value) && value >= 0 && value <= 1;
  const failed = (reason, confidence = null, confidenceText = "—") => ({
    label: "无法识别", tone: "low", confidence, confidenceText, reason,
  });
  if (!["ok", "unknown"].includes(protocol?.status))
    return failed(protocol?.reason || "暂无有效的协议识别结果。");
  const confidence = protocol.confidence;
  if (!validScore(confidence)) return failed(protocol.reason || "模型未返回有效置信度。");
  // Avoid showing a rounded 40%/70% on the lower side of a color boundary.
  const roundedPercent = Math.round(confidence * 1000) / 10;
  const confidenceText = confidence < 0.4 && roundedPercent >= 40 ? "<40%"
    : confidence < 0.7 && roundedPercent >= 70 ? "<70%"
    : `${roundedPercent.toLocaleString("zh-CN", { maximumFractionDigits: 1 })}%`;
  if (confidence < 0.4)
    return failed("模型置信度低于 40%，无法识别该信号的协议。", confidence, confidenceText);
  const probabilities = protocol.probabilities || {};
  const classes = protocol.classes?.length ? protocol.classes : Object.keys(probabilities);
  const candidates = classes.filter((name) => typeof name === "string" && name.trim() && validScore(probabilities[name]));
  const winner = candidates.reduce((best, name) => best === null || probabilities[name] > probabilities[best] ? name : best, null);
  const label = typeof protocol.label === "string" && protocol.label.trim() ? protocol.label : winner;
  if (!label) return failed("模型未返回有效的候选类别。", confidence, confidenceText);
  const medium = confidence < 0.7;
  return { label, tone: medium ? "medium" : "high", confidence, confidenceText,
    reason: medium ? "置信度为 40%～不足 70%，显示最高得分候选类别。" : null };
}

// Empty collections have no page; a shrinking collection clamps to its last page.
export function recordPageInfo(total, offset, limit = 300) {
  const count = Number.isSafeInteger(total) && total > 0 ? total : 0;
  const size = Number.isSafeInteger(limit) && limit > 0 ? limit : 300;
  const start = Number.isSafeInteger(offset) && offset > 0 ? offset : 0;
  const pages = Math.ceil(count / size);
  const lastOffset = Math.max(0, (pages - 1) * size);
  return { total: count, pages, page: count ? Math.floor(Math.min(start, lastOffset) / size) + 1 : 0,
    lastOffset, hasPrevious: start > 0, hasNext: start + size < count };
}
