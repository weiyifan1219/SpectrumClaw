const BASE = import.meta.env.VITE_API_BASE || `http://${window.location.hostname}:8230`;
const TIMEOUT_MS = 60_000;

export async function sendChatStream(messages, options = {}, onEvent) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const resp = await fetch(`${BASE}/api/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ messages, ...options }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      throw new Error(detail ? `服务端错误 (${resp.status})` : `服务端错误 (${resp.status})`);
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
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6));
            onEvent(event);
          } catch { /* skip malformed */ }
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      onEvent({ type: "error", data: "请求超时" });
    } else if (err.message.includes("Failed to fetch")) {
      onEvent({ type: "error", data: "网络连接失败" });
    } else {
      onEvent({ type: "error", data: err.message });
    }
  } finally {
    clearTimeout(timer);
  }
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
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 180_000);

  try {
    const resp = await fetch(`${BASE}/api/rag/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      onEvent({ type: "error", data: detail ? `RAG stream failed (${resp.status}): ${detail.slice(0, 200)}` : `RAG stream failed (${resp.status})` });
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
        if (line.startsWith("data: ")) {
          try {
            const event = JSON.parse(line.slice(6));
            onEvent(event);
          } catch { /* skip malformed */ }
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      onEvent({ type: "error", data: "RAG 查询超时（超过 180 秒），请重试" });
    } else if (err.message?.includes("Failed to fetch") || err.message?.includes("NetworkError")) {
      onEvent({ type: "error", data: "网络连接失败：无法访问后端服务，请确认后端已启动" });
    } else {
      onEvent({ type: "error", data: err.message });
    }
  } finally {
    clearTimeout(timer);
  }
}

export async function runFrequencyPlanStream(question, onEvent, { thinkingEnabled = true } = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 180_000);

  try {
    const resp = await fetch(`${BASE}/api/rag/frequency_plan/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, thinking_enabled: thinkingEnabled }),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      onEvent({ type: "error", data: detail ? `频率规划检索失败 (${resp.status}): ${detail.slice(0, 200)}` : `频率规划检索失败 (${resp.status})` });
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
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch { /* skip malformed */ }
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      onEvent({ type: "error", data: "频率规划查询超时（超过 180 秒），请重试" });
    } else if (err.message?.includes("Failed to fetch") || err.message?.includes("NetworkError")) {
      onEvent({ type: "error", data: "网络连接失败：无法访问后端服务，请确认后端已启动" });
    } else {
      onEvent({ type: "error", data: err.message });
    }
  } finally {
    clearTimeout(timer);
  }
}

/* ── Spectrum Decision streaming (agent mode) ── */

export async function runDecisionAllocationStream(params, onEvent) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 180_000);

  try {
    const resp = await fetch(`${BASE}/api/spectrum-decision/allocate/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(params),
      signal: controller.signal,
    });
    if (!resp.ok) {
      const detail = await resp.text().catch(() => "");
      onEvent({ type: "error", data: detail ? `分配失败 (${resp.status}): ${detail.slice(0, 200)}` : `分配失败 (${resp.status})` });
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
        if (line.startsWith("data: ")) {
          try {
            onEvent(JSON.parse(line.slice(6)));
          } catch { /* skip malformed */ }
        }
      }
    }
  } catch (err) {
    if (err.name === "AbortError") {
      onEvent({ type: "error", data: "决策分配超时（超过 180 秒），请重试" });
    } else if (err.message?.includes("Failed to fetch") || err.message?.includes("NetworkError")) {
      onEvent({ type: "error", data: "网络连接失败：无法访问后端服务，请确认后端已启动" });
    } else {
      onEvent({ type: "error", data: err.message });
    }
  } finally {
    clearTimeout(timer);
  }
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

export function ragDocPdfUrl(docId, { filename, page } = {}) {
  const p = new URLSearchParams();
  if (filename) p.set("filename", filename);
  const qs = p.toString();
  const hash = page ? `#page=${page}` : "";
  return `${BASE}/api/rag/docs/${encodeURIComponent(docId || "_")}/pdf${qs ? `?${qs}` : ""}${hash}`;
}
