const BASE = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8230`;
const TIMEOUT_MS = 60_000;

function isNetworkError(err) {
  return err?.message?.includes("Failed to fetch") || err?.message?.includes("NetworkError");
}

function parseStreamLine(line, onEvent) {
  if (!line.startsWith("data:")) return;
  try {
    onEvent(JSON.parse(line.slice(5).trimStart()));
  } catch {
    /* skip malformed */
  }
}

async function streamJsonEvents(path, body, onEvent, {
  timeout = TIMEOUT_MS,
  timeoutMessage = "请求超时",
  networkMessage = "网络连接失败",
  statusMessage = (status) => `服务端错误 (${status})`,
} = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);

  try {
    const resp = await fetch(`${BASE}${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      onEvent({ type: "error", data: statusMessage(resp.status, detail) });
      return;
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const line of lines) {
        parseStreamLine(line, onEvent);
      }
    }

    buffer += decoder.decode();
    if (buffer) {
      for (const line of buffer.split("\n")) {
        parseStreamLine(line, onEvent);
      }
    }
  } catch (err) {
    if (err?.name === "AbortError") {
      onEvent({ type: "error", data: timeoutMessage });
    } else if (isNetworkError(err)) {
      onEvent({ type: "error", data: networkMessage });
    } else {
      onEvent({ type: "error", data: err.message });
    }
  } finally {
    clearTimeout(timer);
  }
}

export async function sendChatStream(messages, options = {}, onEvent) {
  return streamJsonEvents("/api/chat/stream", { messages, ...options }, onEvent);
}

export async function sendChat(messages, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const resp = await fetch(`${BASE}/api/chat`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, ...options }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(detail ? `服务端错误 (${resp.status}): ${detail}` : `服务端错误 (${resp.status})`);
    }
    const data = await resp.json();
    return { reply: data.reply, metadata: data.metadata };
  } catch (err) {
    if (err.name === "AbortError") {
      throw new Error("请求超时：后端或模型 API 响应时间过长，请稍后重试");
    }
    if (err.message.includes("Failed to fetch") || err.message.includes("NetworkError")) {
      throw new Error("网络连接失败：无法访问后端服务，请确认后端已启动");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchLlmOptions() {
  const resp = await fetch(`${BASE}/api/llm/options`);
  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new Error(detail ? `模型配置读取失败 (${resp.status})` : `模型配置读取失败 (${resp.status})`);
  }
  return resp.json();
}

export async function healthCheck() {
  const resp = await fetch(`${BASE}/health`);
  return resp.json();
}

/* ── RAG API ── */

export async function runRagQuery(question) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 120_000);

  try {
    const resp = await fetch(`${BASE}/api/rag/query`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(detail ? `RAG query failed (${resp.status}): ${detail.slice(0, 200)}` : `RAG query failed (${resp.status})`);
    }
    return resp.json();
  } catch (err) {
    if (err.name === "AbortError") throw new Error("RAG 查询超时（超过 120 秒），请重试");
    if (err.message?.includes("Failed to fetch") || err.message?.includes("NetworkError"))
      throw new Error("网络连接失败：无法访问后端服务，请确认后端已启动（python -m backend.app）");
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function runRagStream(question, onEvent) {
  return streamJsonEvents("/api/rag/stream", { question }, onEvent, {
    timeout: 180_000,
    timeoutMessage: "RAG 查询超时（超过 180 秒），请重试",
    networkMessage: "网络连接失败：无法访问后端服务，请确认后端已启动",
    statusMessage: (status, detail) => detail ? `RAG stream failed (${status}): ${detail.slice(0, 200)}` : `RAG stream failed (${status})`,
  });
}

export async function runFrequencyPlanStream(question, onEvent, { thinkingEnabled = true } = {}) {
  return streamJsonEvents("/api/rag/frequency_plan/stream", { question, thinking_enabled: thinkingEnabled }, onEvent, {
    timeout: 180_000,
    timeoutMessage: "频率规划查询超时（超过 180 秒），请重试",
    networkMessage: "网络连接失败：无法访问后端服务，请确认后端已启动",
    statusMessage: (status, detail) => detail ? `频率规划检索失败 (${status}): ${detail.slice(0, 200)}` : `频率规划检索失败 (${status})`,
  });
}

/* ── Spectrum Decision streaming (agent mode) ── */

export async function runDecisionAllocationStream(params, onEvent) {
  return streamJsonEvents("/api/spectrum-decision/allocate/stream", params, onEvent, {
    timeout: 180_000,
    timeoutMessage: "决策分配超时（超过 180 秒），请重试",
    networkMessage: "网络连接失败：无法访问后端服务，请确认后端已启动",
    statusMessage: (status, detail) => detail ? `分配失败 (${status}): ${detail.slice(0, 200)}` : `分配失败 (${status})`,
  });
}

/* ── Spectrum Construction API ── */
export async function runSpectrumConstruction(options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 300_000);

  try {
    const resp = await fetch(`${BASE}/api/spectrum-construction/generate`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(detail ? `Spectrum Construction failed (${resp.status}): ${detail.slice(0, 200)}` : `Spectrum Construction failed (${resp.status})`);
    }
    return resp.json();
  } catch (err) {
    if (err.name === "AbortError") throw new Error("Spectrum Construction 生成超时，请重试");
    if (err.message?.includes("Failed to fetch") || err.message?.includes("NetworkError")) {
      throw new Error("网络连接失败：无法访问后端服务，请确认后端已启动");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchUavRemOverview(options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 60_000);

  try {
    const resp = await fetch(`${BASE}/api/spectrum-construction/uav-rem/overview`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(options),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(detail ? `UAV REM overview failed (${resp.status}): ${detail.slice(0, 200)}` : `UAV REM overview failed (${resp.status})`);
    }
    return resp.json();
  } catch (err) {
    if (err.name === "AbortError") throw new Error("UAV REM 数据读取超时，请重试");
    if (err.message?.includes("Failed to fetch") || err.message?.includes("NetworkError")) {
      throw new Error("网络连接失败：无法访问后端服务，请确认后端已启动");
    }
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

/* ── memory API ── */

export async function fetchMemoryOverview() {
  const resp = await fetch(`${BASE}/api/memory/overview`);
  if (!resp.ok) throw new Error(`Memory overview failed (${resp.status})`);
  return resp.json();
}

export async function fetchMemoryItems({ kind, threadId, skillName, tag, limit = 50 } = {}) {
  const params = new URLSearchParams();
  if (kind) params.set("kind", kind);
  if (threadId) params.set("thread_id", threadId);
  if (skillName) params.set("skill_name", skillName);
  if (tag) params.set("tag", tag);
  params.set("limit", String(limit));
  const resp = await fetch(`${BASE}/api/memory/items?${params}`);
  if (!resp.ok) throw new Error(`Memory items failed (${resp.status})`);
  return resp.json();
}

export async function fetchMemoryThread(threadId) {
  const resp = await fetch(`${BASE}/api/memory/threads/${encodeURIComponent(threadId)}`);
  if (!resp.ok) throw new Error(`Memory thread failed (${resp.status})`);
  return resp.json();
}

export async function submitFeedback({ targetType, targetId, rating, comment = "" }) {
  const resp = await fetch(`${BASE}/api/memory/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ target_type: targetType, target_id: targetId, rating, comment }),
  });
  if (!resp.ok) throw new Error(`Feedback failed (${resp.status})`);
  return resp.json();
}

export async function fetchMemoryReports(limit = 10) {
  const resp = await fetch(`${BASE}/api/memory/reports?limit=${limit}`);
  if (!resp.ok) throw new Error(`Memory reports failed (${resp.status})`);
  return resp.json();
}

export async function triggerReflect(hours = 168) {
  const resp = await fetch(`${BASE}/api/memory/reflect?hours=${hours}`, {
    method: "POST",
  });
  if (!resp.ok) {
    let detail = `反思生成失败 (${resp.status})`;
    try {
      const body = await resp.json();
      if (body.detail) detail = body.detail;
    } catch {
      /* ignore */
    }
    throw new Error(detail);
  }
  return resp.json();
}

/* ── Knowledge Base / RAG status & docs ── */

export async function fetchKbStats({ timeout = 60_000 } = {}) {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), timeout);
  try {
    const resp = await fetch(`${BASE}/api/kb/stats`, { signal: ctrl.signal });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    return await resp.json();
  } finally {
    clearTimeout(t);
  }
}

export async function fetchRagStatus() {
  const resp = await fetch(`${BASE}/api/rag/status`);
  if (!resp.ok) throw new Error(`RAG status failed (${resp.status})`);
  return resp.json();
}

export async function fetchRagDocs({ status, search, limit = 50, offset = 0 } = {}) {
  const p = new URLSearchParams();
  if (status) p.set("status", status);
  if (search) p.set("search", search);
  p.set("limit", String(limit));
  p.set("offset", String(offset));
  const resp = await fetch(`${BASE}/api/rag/docs?${p}`);
  if (!resp.ok) throw new Error(`RAG docs failed (${resp.status})`);
  return resp.json();
}

export async function fetchGraphEntities({ type, search, limit = 120 } = {}) {
  const p = new URLSearchParams();
  if (type) p.set("type", type);
  if (search) p.set("search", search);
  p.set("limit", String(limit));
  const resp = await fetch(`${BASE}/api/rag/graph/entities?${p}`);
  if (!resp.ok) throw new Error(`Graph entities failed (${resp.status})`);
  return resp.json();
}

export async function fetchGraphEntity(name) {
  const resp = await fetch(`${BASE}/api/rag/graph/entity/${encodeURIComponent(name)}`);
  if (!resp.ok) throw new Error(`Graph entity failed (${resp.status})`);
  return resp.json();
}

export async function uploadRagDoc(file) {
  const form = new FormData();
  form.append("file", file);
  const resp = await fetch(`${BASE}/api/rag/upload`, { method: "POST", body: form });
  if (!resp.ok) {
    const detail = await resp.text().catch(() => "");
    throw new Error(detail ? `上传失败 (${resp.status}): ${detail.slice(0, 200)}` : `上传失败 (${resp.status})`);
  }
  return resp.json();
}

/* ── System: logs & artifacts ── */

export async function fetchSystemLogs() {
  const resp = await fetch(`${BASE}/api/system/logs`);
  if (!resp.ok) throw new Error(`Logs list failed (${resp.status})`);
  return resp.json();
}

export async function fetchSystemHealth({ timeout = 10_000 } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  try {
    const resp = await fetch(`${BASE}/api/system/health/deep`, { signal: ctrl.signal });
    if (!resp.ok) throw new Error(`System health failed (${resp.status})`);
    return resp.json();
  } catch (err) {
    if (err?.name === "AbortError") throw new Error("系统健康检查超时，请稍后重试");
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

export async function fetchSystemLog(name, { tail = 100 } = {}) {
  const resp = await fetch(`${BASE}/api/system/logs/${encodeURIComponent(name)}?tail=${tail}`);
  if (!resp.ok) throw new Error(`Log fetch failed (${resp.status})`);
  return resp.json();
}

export async function fetchSystemArtifacts({ category, search, limit = 100 } = {}) {
  const p = new URLSearchParams();
  if (category) p.set("category", category);
  if (search) p.set("search", search);
  p.set("limit", String(limit));
  const resp = await fetch(`${BASE}/api/system/artifacts?${p}`);
  if (!resp.ok) throw new Error(`Artifacts list failed (${resp.status})`);
  return resp.json();
}

export async function fetchArtifactPreview(path) {
  const resp = await fetch(`${BASE}/api/system/artifacts/preview/${encodeURIComponent(path)}`);
  if (!resp.ok) throw new Error(`Preview failed (${resp.status})`);
  return resp.json();
}

export function artifactDownloadUrl(path) {
  return `${BASE}/api/system/artifacts/download/${encodeURIComponent(path)}`;
}

export function ragDocPdfUrl(docId, { filename, page } = {}) {
  const p = new URLSearchParams();
  if (filename) p.set("filename", filename);
  const qs = p.toString();
  const hash = page ? `#page=${page}` : "";
  return `${BASE}/api/rag/docs/${encodeURIComponent(docId || "_")}/pdf${qs ? `?${qs}` : ""}${hash}`;
}

/* ── Jobs / Agent Trace ── */

export async function fetchJobs({ limit = 20, status } = {}) {
  const p = new URLSearchParams();
  p.set("limit", String(limit));
  if (status) p.set("status", status);
  const resp = await fetch(`${BASE}/api/jobs?${p}`);
  if (!resp.ok) throw new Error(`Jobs failed (${resp.status})`);
  return resp.json();
}

export async function fetchJob(jobId, { eventLimit = 100 } = {}) {
  const p = new URLSearchParams();
  p.set("event_limit", String(eventLimit));
  const resp = await fetch(`${BASE}/api/jobs/${encodeURIComponent(jobId)}?${p}`);
  if (!resp.ok) throw new Error(`Job failed (${resp.status})`);
  return resp.json();
}

/* ── Thread / Conversation History ── */

export async function fetchThreads({ limit = 50 } = {}) {
  const resp = await fetch(`${BASE}/api/memory/threads?limit=${limit}`);
  if (!resp.ok) throw new Error(`Threads fetch failed (${resp.status})`);
  return resp.json();
}

export async function deleteThread(threadId) {
  const resp = await fetch(`${BASE}/api/memory/threads/${encodeURIComponent(threadId)}`, {
    method: "DELETE",
  });
  if (!resp.ok) throw new Error(`Thread delete failed (${resp.status})`);
  return resp.json();
}
