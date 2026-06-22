import { useCallback, useEffect, useMemo, useState } from "react";
import { RefreshCw, ShieldCheck } from "lucide-react";
import { fetchLlmOptions, fetchSystemHealth } from "../lib/api.js";
import { loadModelSelection, subscribeModelSelection } from "../lib/modelSelection.js";

const GROUPS = ["External", "Runtime", "Storage", "Service"];

function formatTime(ts) {
  if (!ts) return "尚未检查";
  try {
    return new Date(ts * 1000).toLocaleString("zh-CN", { hour12: false });
  } catch {
    return "尚未检查";
  }
}

function statusLabel(status) {
  return {
    ok: "正常",
    warn: "注意",
    error: "异常",
    offline: "离线",
    unknown: "未知",
  }[status] || status || "未知";
}

function matchModelSelection(id, options) {
  if (!id) return null;
  return options.find((m) => m.id === id)
    || options.find((m) => m.model === id)
    || null;
}

export default function SystemPage() {
  const [health, setHealth] = useState(null);
  const [modelOptions, setModelOptions] = useState([]);
  const [selectedModelId, setSelectedModelId] = useState(() => loadModelSelection());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [nextHealth, llmOptions] = await Promise.all([
        fetchSystemHealth(),
        fetchLlmOptions().catch(() => null),
      ]);
      setHealth(nextHealth);
      if (llmOptions?.models) setModelOptions(llmOptions.models);
    } catch (err) {
      setError(err.message || "健康检查失败");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => subscribeModelSelection(setSelectedModelId), []);

  const selectedModel = useMemo(
    () => matchModelSelection(selectedModelId, modelOptions),
    [modelOptions, selectedModelId]
  );

  const summary = useMemo(() => {
    const items = health?.summary || [
      { key: "Backend", value: loading ? "Checking" : "Unknown", detail: "等待后端响应", tone: "info" },
      { key: "Model", value: "Unknown", detail: "等待模型配置", tone: "info" },
      { key: "Knowledge", value: "Unknown", detail: "等待 RAG 状态", tone: "info" },
    ];
    if (!selectedModel) return items;
    return items.map((item) => {
      if (item.key !== "Model") return item;
      return {
        ...item,
        value: selectedModel.label || selectedModel.model,
        detail: `${selectedModel.provider_label || selectedModel.provider} · ${selectedModel.model} · 当前选择`,
        tone: selectedModel.configured ? "ok" : "warn",
      };
    });
  }, [health, loading, selectedModel]);

  const checksByGroup = useMemo(() => {
    const grouped = new Map();
    const checks = (health?.checks || []).map((check) => {
      if (!selectedModel || check.name !== "LLM Provider") return check;
      return {
        ...check,
        status: selectedModel.configured ? "ok" : "warn",
        tone: selectedModel.configured ? "ok" : "warn",
        value: `${selectedModel.provider} · ${selectedModel.model}`,
        detail: `${selectedModel.api_type} · 当前前端选择`,
      };
    });
    for (const check of checks) {
      if (!grouped.has(check.group)) grouped.set(check.group, []);
      grouped.get(check.group).push(check);
    }
    return grouped;
  }, [health, selectedModel]);

  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">System · Status</span>
          <h1>运行系统状态</h1>
          <p className="lede">
            查看 3090 后端、模型、RAG、记忆、日志与频谱技能 sidecar 的实时健康状况。
          </p>
        </div>
        <div className="actions">
          <button className="btn primary" onClick={load} disabled={loading}>
            {loading ? <RefreshCw size={14} className="spin" /> : <ShieldCheck size={14} />}
            {loading ? "检查中" : "健康检查"}
          </button>
        </div>
      </div>

      {error && (
        <div className="inline-error">
          {error}
        </div>
      )}

      <div className="sys-overview">
        {summary.map((s) => (
          <div className="stat-card" key={s.key}>
            <span className="k">{s.key}</span>
            <div className="v">{s.value}</div>
            <div className="d">{s.detail}</div>
          </div>
        ))}
      </div>

      <div className="sys-meta">
        <span>Last check</span>
        <strong>{formatTime(health?.generated_at)}</strong>
      </div>

      {GROUPS.map((group) => {
        const rows = checksByGroup.get(group) || [];
        if (!rows.length) return null;
        return (
          <div className="sys-group" key={group}>
            <div className="sys-group-title">{group}</div>
            <div className="sys-table">
              {rows.map((row) => (
                <div className="sys-row" key={`${row.group}:${row.name}`}>
                  <strong>{row.name}</strong>
                  <span className="mono" title={row.detail}>{row.value}</span>
                  <span className="pill" data-tone={row.tone}>
                    <span className="dot" /> {statusLabel(row.status)}
                  </span>
                </div>
              ))}
            </div>
          </div>
        );
      })}
    </div>
  );
}
