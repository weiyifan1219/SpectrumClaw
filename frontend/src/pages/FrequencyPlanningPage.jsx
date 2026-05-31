import { useCallback, useState } from "react";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clipboard,
  FileSearch,
  FileText,
  Info,
  Loader2,
  Play,
  RefreshCw,
  Search,
  ShieldAlert,
  XCircle,
} from "lucide-react";
import { runRagQuery } from "../lib/api.js";
import Markdown from "../components/Markdown.jsx";

/* ── presets & query builder ── */

const PRESETS = [
  { id: "civil_24ghz", label: "民用 2.4 GHz 共用频段", band: "2400-2483.5 MHz", region: "Region 3", service: "Mobile,Fixed", coex: "WiFi,Bluetooth", ctx: "民用短距通信与 ISM 设备共存" },
  { id: "vhf_aero", label: "VHF 航空通信", band: "118-137 MHz", region: "Region 2", service: "Aeronautical Mobile", coex: "", ctx: "航空移动通信频段保护与干扰评估" },
  { id: "5g_36ghz", label: "5G 毫米波协调", band: "24.25-27.5 GHz", region: "Region 3", service: "Mobile,Fixed", coex: "Satellite", ctx: "5G NR 与卫星固定业务共存协调" },
  { id: "drone_datalink", label: "无人机数据链", band: "2300-2400 MHz", region: "Region 3", service: "Mobile,Radiolocation", coex: "WiFi,radar", ctx: "无人机短距数据链频段规划" },
  { id: "maritime_vhf", label: "海事 VHF 频段", band: "156-174 MHz", region: "Region 3", service: "Maritime Mobile", coex: "", ctx: "海事移动通信频段分配与保护条件" },
];

function buildQuery(form) {
  const parts = [];
  if (form.frequency_band) parts.push(`${form.frequency_band} 频段`);
  if (form.region) parts.push(`ITU ${form.region}`);
  if (form.country) parts.push(form.country);
  if (form.service) parts.push(`${form.service} 业务分配`);
  if (form.coexistence) parts.push(`共存 干扰 保护条件 ${form.coexistence}`);
  if (form.bandwidth_mhz) parts.push(`${form.bandwidth_mhz} MHz 带宽`);
  if (form.mission_context) parts.push(form.mission_context);
  parts.push("frequency allocation footnote limitation protection criteria Radio Regulations");
  return parts.join(" ");
}

function inferRisk(answer, citations) {
  if (!citations || citations.length === 0) return "unknown";
  if (!answer) return "unknown";
  const lower = answer.toLowerCase();
  if (/not allocated|prohibited|禁止|不得|no allocation|not permitted/i.test(lower)) return "danger";
  if (/secondary|coordination|protection|脚注|footnote|subject to|需协调|限制条件/i.test(lower)) return "warn";
  return "ok";
}

const RISK_META = {
  ok: { label: "可用", color: "var(--ok)", icon: CheckCircle2, bg: "oklch(0.80 0.15 155 / 0.08)", border: "oklch(0.80 0.15 155 / 0.3)" },
  warn: { label: "需注意", color: "var(--warn)", icon: AlertTriangle, bg: "oklch(0.84 0.14 80 / 0.08)", border: "oklch(0.84 0.14 80 / 0.3)" },
  danger: { label: "冲突/不可用", color: "var(--err)", icon: XCircle, bg: "oklch(0.74 0.18 25 / 0.08)", border: "oklch(0.74 0.18 25 / 0.3)" },
  unknown: { label: "证据不足", color: "var(--muted)", icon: Info, bg: "oklch(1 0 0 / 0.03)", border: "var(--line)" },
};

function formatTime() {
  return new Date().toLocaleString("zh-CN", { hour12: false });
}

/* ── internal sub-components ── */

function RequestForm({ form, onChange, onPreset, disabled }) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const activePreset = PRESETS.find((p) => p.id === form.scenario);

  const set = (key, val) => onChange({ ...form, [key]: val });

  return (
    <div className="fp-form">
      {/* presets */}
      <div className="fp-field">
        <label className="fp-label">场景预设</label>
        <select className="fp-select" value={form.scenario || ""} onChange={(e) => {
          const p = PRESETS.find((x) => x.id === e.target.value);
          if (p) {
            onPreset(p);
            onChange({
              ...form,
              scenario: p.id, frequency_band: p.band, region: p.region,
              service: p.service, coexistence: p.coex, mission_context: p.ctx,
            });
          }
        }} disabled={disabled}>
          <option value="">手动输入…</option>
          {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
      </div>

      {/* required fields */}
      <div className="fp-field">
        <label className="fp-label">目标频段 <span className="fp-required">*</span></label>
        <input className="fp-input" placeholder="例: 2300-2400 MHz" value={form.frequency_band} onChange={(e) => set("frequency_band", e.target.value)} disabled={disabled} />
      </div>

      <div className="fp-row-2">
        <div className="fp-field">
          <label className="fp-label">ITU 区域</label>
          <select className="fp-select" value={form.region} onChange={(e) => set("region", e.target.value)} disabled={disabled}>
            <option value="">自动 / 不限</option>
            <option value="Region 1">Region 1 (欧洲/非洲)</option>
            <option value="Region 2">Region 2 (美洲)</option>
            <option value="Region 3">Region 3 (亚太)</option>
          </select>
        </div>
        <div className="fp-field">
          <label className="fp-label">国家/地区</label>
          <input className="fp-input" placeholder="中国" value={form.country} onChange={(e) => set("country", e.target.value)} disabled={disabled} />
        </div>
      </div>

      <div className="fp-field">
        <label className="fp-label">业务类型</label>
        <input className="fp-input" placeholder="例: Fixed, Mobile, Radiolocation" value={form.service} onChange={(e) => set("service", e.target.value)} disabled={disabled} />
      </div>

      <div className="fp-row-2">
        <div className="fp-field">
          <label className="fp-label">带宽 (MHz)</label>
          <input className="fp-input" type="number" placeholder="20" value={form.bandwidth_mhz} onChange={(e) => set("bandwidth_mhz", e.target.value)} disabled={disabled} />
        </div>
        <div className="fp-field">
          <label className="fp-label">共存约束</label>
          <input className="fp-input" placeholder="WiFi, Bluetooth, radar" value={form.coexistence} onChange={(e) => set("coexistence", e.target.value)} disabled={disabled} />
        </div>
      </div>

      <div className="fp-field">
        <label className="fp-label">任务背景</label>
        <textarea className="fp-textarea" rows={2} placeholder="自由描述任务场景…" value={form.mission_context} onChange={(e) => set("mission_context", e.target.value)} disabled={disabled} />
      </div>

      {/* advanced toggle */}
      <button className="fp-advanced-toggle" onClick={() => setShowAdvanced(!showAdvanced)} type="button">
        <span>{showAdvanced ? <ChevronDown size={12} /> : <ChevronRight size={12} />}</span>
        高级检索参数
      </button>

      {showAdvanced && (
        <div className="fp-advanced">
          <div className="fp-field">
            <label className="fp-label">检索模式</label>
            <div className="fp-segment">
              {["hybrid", "vector", "keyword", "graph"].map((m) => (
                <button key={m} className={form.retrieval_mode === m ? "on" : ""} onClick={() => set("retrieval_mode", m)} disabled={disabled}>
                  {m === "hybrid" ? "混合" : m === "vector" ? "向量" : m === "keyword" ? "关键词" : "图谱"}
                </button>
              ))}
            </div>
          </div>
          <div className="fp-field">
            <label className="fp-label">Top-K: {form.top_k}</label>
            <input className="fp-range" type="range" min={3} max={20} value={form.top_k} onChange={(e) => set("top_k", Number(e.target.value))} disabled={disabled} />
          </div>
        </div>
      )}

      {/* query preview */}
      <div className="fp-query-preview">
        <div className="fp-query-label">
          <Search size={12} />
          RAG Query Preview
        </div>
        <p className="fp-query-text">{buildQuery(form)}</p>
      </div>
    </div>
  );
}

function ResultPanel({ status, result, risk }) {
  const riskInfo = RISK_META[risk] || RISK_META.unknown;
  const RiskIcon = riskInfo.icon;

  if (status === "idle") {
    return (
      <div className="fp-result-empty">
        <div className="fp-empty-icon"><FileSearch size={28} /></div>
        <h3>等待运行规划</h3>
        <p>在左侧填写频段、区域、业务等参数后，点击“运行规划”启动 RAG 检索与分析。</p>
        <div className="fp-empty-presets">
          {PRESETS.slice(0, 3).map((p) => (
            <span key={p.id} className="fp-preset-chip">{p.label}</span>
          ))}
        </div>
      </div>
    );
  }

  if (status === "running") {
    return (
      <div className="fp-result-running">
        <div className="fp-pipeline">
          <PipelineStep label="Query Analysis" active />
          <PipelineStep label="Hybrid Retrieval" active={false} />
          <PipelineStep label="Rerank" active={false} />
          <PipelineStep label="Answer Generation" active={false} />
        </div>
      </div>
    );
  }

  if (status === "error") {
    return (
      <div className="fp-result-empty">
        <div className="fp-empty-icon" style={{ color: "var(--err)" }}><ShieldAlert size={28} /></div>
        <h3>运行失败</h3>
        <p>{result?.error || "RAG 查询失败，请确认后端服务已启动并重试。"}</p>
      </div>
    );
  }

  if (status === "empty") {
    return (
      <div className="fp-result-empty">
        <div className="fp-empty-icon"><Info size={28} /></div>
        <h3>证据不足</h3>
        <p>RAG 检索未返回足够证据支撑频段规划建议。尝试调整频段范围、区域或业务类型，或补充更多任务背景信息。</p>
      </div>
    );
  }

  // success
  return (
    <div className="fp-result">
      {/* risk badge + metadata */}
      <div className="fp-result-header">
        <div className="fp-risk-badge" style={{ background: riskInfo.bg, borderColor: riskInfo.border, color: riskInfo.color }}>
          <RiskIcon size={14} /> {riskInfo.label}
        </div>
        <span className="fp-result-meta">
          {result?.citations?.length || 0} 条引用 · {result?.retrieved_blocks?.length || 0} 个检索块 · {formatTime()}
        </span>
      </div>

      {/* answer markdown */}
      <div className="fp-answer">
        <Markdown>{result?.answer || "(模型返回为空)"}</Markdown>
      </div>
    </div>
  );
}

function PipelineStep({ label, active }) {
  return (
    <div className={`fp-pipe-step ${active ? "active" : ""}`}>
      <div className="fp-pipe-dot">{active && <Loader2 size={10} className="spin" />}</div>
      <span className="fp-pipe-label">{label}</span>
    </div>
  );
}

function CitationPanel({ result, selectedCitation, onSelect }) {
  if (!result) {
    return (
      <div className="fp-cite-empty">
        <FileText size={24} />
        <p>运行规划后，引用和检索证据将在此显示</p>
      </div>
    );
  }

  const citations = result?.citations || [];
  const blocks = result?.retrieved_blocks || [];
  const debug = result?.debug || {};

  // merge citations with blocks where possible
  const merged = citations.map((c, i) => {
    const match = blocks.find((b) =>
      (b.metadata?.source_path || b.metadata?.source || "") === (c.source || "") &&
      (b.metadata?.page_idx ?? b.metadata?.page ?? "") === (c.page || "")
    );
    return { ...c, excerpt: match?.text || c.excerpt || "", block_type: match?.metadata?.block_type || c.block_type || "", score: c.relevance || c.score || 0, index: i };
  });

  return (
    <div className="fp-cite-panel">
      {/* debug section */}
      {debug.query_analysis && (
        <details className="fp-debug">
          <summary><Search size={11} /> Query Analysis</summary>
          <div className="fp-debug-body">
            {Object.entries(debug.query_analysis).map(([k, v]) => (
              <div key={k} className="fp-debug-row">
                <span className="fp-debug-key">{k}</span>
                <span className="fp-debug-val">{String(v)}</span>
              </div>
            ))}
          </div>
        </details>
      )}

      {/* citations */}
      <div className="fp-cite-section-label">
        Citations <span className="fp-cite-count">{citations.length}</span>
      </div>

      {merged.map((c) => {
        const isSel = selectedCitation?.index === c.index;
        return (
          <div key={c.index} className={`fp-cite-card ${isSel ? "selected" : ""}`} onClick={() => onSelect(isSel ? null : c)}>
            <div className="fp-cite-head">
              <strong className="fp-cite-source" title={c.source}>{c.source?.split("/").pop() || `引用 ${c.index + 1}`}</strong>
              {c.page && <span className="fp-cite-page">p.{c.page}</span>}
            </div>
            <div className="fp-cite-meta">
              {c.block_type && <span className="fp-cite-type">{c.block_type}</span>}
              <span className="fp-cite-score">{Math.round((c.score || 0) * 100)}%</span>
            </div>
            <div className="fp-cite-score-bar">
              <div className="fp-cite-score-fill" style={{ width: `${(c.score || 0) * 100}%` }} />
            </div>
            {isSel && c.excerpt && (
              <div className="fp-cite-excerpt">{c.excerpt.slice(0, 600)}</div>
            )}
          </div>
        );
      })}

      {citations.length === 0 && blocks.length > 0 && (
        <div className="fp-cite-section-label">Retrieved Blocks <span className="fp-cite-count">{blocks.length}</span></div>
      )}
      {citations.length === 0 && blocks.slice(0, 5).map((b, i) => (
        <div key={i} className="fp-cite-card" onClick={() => onSelect({ index: i, excerpt: b.text, source: b.metadata?.source_path || "", page: b.metadata?.page_idx || b.metadata?.page || "", block_type: b.metadata?.block_type || "", score: 0 })}>
          <div className="fp-cite-head">
            <strong className="fp-cite-source">{(b.metadata?.source_path || "").split("/").pop() || `Block ${i + 1}`}</strong>
          </div>
          <div className="fp-cite-excerpt">{b.text?.slice(0, 300)}</div>
        </div>
      ))}
    </div>
  );
}

/* ── page component ── */

export default function FrequencyPlanningPage({ onBack }) {
  const [form, setForm] = useState({
    scenario: "",
    frequency_band: "",
    region: "",
    country: "",
    service: "",
    bandwidth_mhz: "",
    coexistence: "",
    mission_context: "",
    retrieval_mode: "hybrid",
    top_k: 8,
  });
  const [status, setStatus] = useState("idle"); // idle | ready | running | success | empty | error
  const [result, setResult] = useState(null);
  const [risk, setRisk] = useState("unknown");
  const [selectedCitation, setSelectedCitation] = useState(null);

  const canRun = form.frequency_band.trim().length > 0 && status !== "running";

  const handleRun = useCallback(async () => {
    if (!canRun) return;
    const query = buildQuery(form);
    setStatus("running");
    setResult(null);
    setSelectedCitation(null);
    try {
      const data = await runRagQuery(query);
      const answer = data.answer || "";
      const citations = data.citations || [];
      const hasContent = answer.length > 10 || citations.length > 0;
      setResult(data);
      setRisk(inferRisk(answer, citations));
      setStatus(hasContent ? "success" : "empty");
    } catch (err) {
      setResult({ error: err.message });
      setStatus("error");
    }
  }, [canRun, form]);

  const handleCopy = useCallback(() => {
    if (!result) return;
    const md = [
      `# 频率规划结果`,
      `- 频段: ${form.frequency_band}`,
      `- 区域: ${form.region || "不限"}`,
      `- 业务: ${form.service || "未指定"}`,
      `- 生成时间: ${formatTime()}`,
      ``,
      result.answer || "(无结果)",
      ``,
      `## 引用`,
      ...(result.citations || []).map((c, i) => `- [${i + 1}] ${c.source || ""} p.${c.page || ""}`),
    ].join("\n");
    navigator.clipboard.writeText(md).catch(() => {});
  }, [result, form]);

  const handlePreset = useCallback((preset) => {
    setStatus("idle");
    setResult(null);
    setSelectedCitation(null);
  }, []);

  return (
    <div className="page fp-page">
      {/* header */}
      <div className="page-head compact">
        <div className="title-block">
          <span className="label">Skill · Frequency Planning</span>
          <h1>频率规划工作区</h1>
          <p className="lede">
            基于 ITU RAG 检索给出可引用的频段使用方案；支持多区域、多业务约束。
          </p>
        </div>
        <div className="actions">
          {onBack && (
            <button className="btn ghost" onClick={onBack}><ArrowLeft size={14} /> 返回</button>
          )}
          <button className="btn ghost sm" onClick={handleCopy} disabled={!result}><Clipboard size={13} /> 复制</button>
          <button className="btn primary" onClick={handleRun} disabled={!canRun}>
            {status === "running" ? <Loader2 size={14} className="spin" /> : <Play size={14} />}
            {status === "running" ? "运行中…" : "运行规划"}
          </button>
        </div>
      </div>

      {/* three-column body */}
      <div className="fp-body">
        {/* left: form */}
        <aside className="fp-left card">
          <div className="card-head">
            <span className="title">任务输入</span>
            <span className="eyebrow muted">Request Builder</span>
          </div>
          <div className="card-body">
            <RequestForm form={form} onChange={setForm} onPreset={handlePreset} disabled={status === "running"} />
          </div>
        </aside>

        {/* center: result */}
        <main className="fp-center card">
          <div className="card-head">
            <span className="title">规划结果</span>
            {status === "success" && (
              <span className="pill" data-tone={risk === "ok" ? "ok" : risk === "warn" ? "warn" : risk === "danger" ? "warn" : "muted"}>
                <span className="dot" /> {RISK_META[risk]?.label}
              </span>
            )}
          </div>
          <div className="fp-center-body">
            <ResultPanel status={status} result={result} risk={risk} />
          </div>
          {status === "error" && (
            <div className="fp-center-foot">
              <button className="btn" onClick={handleRun}><RefreshCw size={13} /> 重试</button>
            </div>
          )}
        </main>

        {/* right: citations */}
        <aside className="fp-right card">
          <div className="card-head">
            <span className="title">引用检查器</span>
            <span className="eyebrow">Inspector</span>
          </div>
          <div className="fp-right-body">
            <CitationPanel result={result} selectedCitation={selectedCitation} onSelect={setSelectedCitation} />
          </div>
        </aside>
      </div>
    </div>
  );
}
