const BASE = `http://${window.location.hostname}:8230`;
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
