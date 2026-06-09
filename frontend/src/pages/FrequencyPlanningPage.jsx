import { useCallback, useEffect, useState } from "react";
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
import { runFrequencyPlanStream } from "../lib/api.js";
import Markdown from "../components/Markdown.jsx";
import { usePersistentState } from "../lib/usePersistentState.js";

/* ── presets grounded in actual ITU document library (natural-language questions) ── */

const PRESETS = [
  {
    id: "maritime_mobile", label: "海上移动业务频率分配",
    band: "415-526.5 kHz / 4 MHz", region: "", service: "Maritime Mobile", coex: "", ctx: "",
    query: "海上移动业务的频率分配包括哪些频段？说明各频段的主/次状态、共享条件和使用限制。",
    desc: "检索海上移动业务多频段划分、共享条件与相邻业务约束",
  },
  {
    id: "met_sat", label: "气象卫星业务频段",
    band: "1690-1710 MHz", region: "", service: "Meteorological Satellite", coex: "", ctx: "",
    query: "气象卫星业务（空对地）使用哪些频段？说明可用频段和与相邻业务的共存约束。",
    desc: "检索气象卫星（空对地）频段及与相邻业务的共存约束",
  },
  {
    id: "aero_radionav", label: "航空无线电导航频段",
    band: "645-862 MHz / 15 GHz", region: "", service: "Aeronautical Radionavigation", coex: "", ctx: "",
    query: "航空无线电导航业务的频段是如何划分的？说明主要频段和需要保护的相邻业务。",
    desc: "检索航空无线电导航频段划分与需保护的相邻业务",
  },
  {
    id: "radio_astronomy", label: "射电天文保护频段",
    band: "22-23 GHz", region: "", service: "Radio Astronomy", coex: "", ctx: "",
    query: "射电天文业务受保护的频段有哪些？说明保护条件和相邻业务的干扰约束。",
    desc: "检索射电天文受保护频段、保护标准与相邻业务共存约束",
  },
  {
    id: "aero_mobile", label: "航空移动业务频段",
    band: "14.5-15.35 GHz", region: "", service: "Aeronautical Mobile", coex: "", ctx: "",
    query: "航空移动业务使用哪些频段？请说明主要/次要划分和适用区域。",
    desc: "检索航空移动业务（AMS）的频段划分、主/次状态与区域差异",
  },
];

const NL_EXAMPLES = [
  { label: "海上搜救通信系统", text: "我要在沿海地区部署一套海上搜救通信系统，需要使用海上移动业务频段，请告诉我可用频段、各频段的主/次状态、共享条件和使用限制，以及与相邻业务的共存约束。" },
  { label: "机场航空无线电导航", text: "机场要部署一套航空无线电导航设备，请规划可用频段，说明主要频段、保护要求以及需要规避或协调的相邻业务。" },
  { label: "射电天文观测站", text: "我要架设一个射电天文观测站，请告诉我哪些频段受到保护、保护条件是什么，以及相邻频段有哪些业务可能造成干扰需要规避。" },
  { label: "船舶AIS遇险呼叫", text: "我们要部署一套船舶自动识别与遇险呼叫系统，工作在 VHF 海上频段，请规划可用信道、说明使用限制和与其他海上业务的共存约束。" },
];

function buildQuery(form) {
  const preset = PRESETS.find((p) => p.id === form.scenario);
  if (preset && preset.query) return preset.query;
  // Manual input → natural-language planning question (retrieves better than keyword soup)
  const band = form.frequency_band || "目标频段";
  const region = form.region ? `在 ${form.region}` : "";
  const svc = form.service ? `${form.service} 业务的` : "";
  const parts = [`${band} 频段${region}的${svc}频率划分、业务分配和限制条件是什么？`];
  if (form.coexistence) parts.push(`需考虑与 ${form.coexistence} 的共存约束。`);
  if (form.bandwidth_mhz) parts.push(`所需带宽约 ${form.bandwidth_mhz} MHz。`);
  if (form.mission_context) parts.push(form.mission_context);
  return parts.join(" ");
}

/* ── extract trailing ```json structured block from the streamed answer ── */
function extractStructured(text) {
  if (!text) return { structured: null, markdown: text || "" };
  // match the LAST fenced json block
  const re = /```json\s*([\s\S]*?)```/gi;
  let last = null;
  let m;
  while ((m = re.exec(text)) !== null) last = m;
  if (!last) return { structured: null, markdown: text };
  try {
    const structured = JSON.parse(last[1].trim());
    const markdown = (text.slice(0, last.index) + text.slice(last.index + last[0].length)).trim();
    return { structured, markdown };
  } catch {
    return { structured: null, markdown: text };
  }
}

function inferRisk(answer, citations) {
  if (!citations || citations.length === 0) return "unknown";
  if (!answer) return "unknown";
  const lower = answer.toLowerCase();
  if (/not allocated|prohibited|禁止|不得|no allocation|not permitted|cannot be used|不可用|不建议使用/i.test(lower)) return "danger";

  const normalizedScores = citations
    .map((c) => Number(c.relevance ?? c.score ?? 0))
    .filter((v) => Number.isFinite(v) && v > 0);
  const bestScore = normalizedScores.length ? Math.max(...normalizedScores) : 0;
  const strongEvidence = citations.length >= 2 || bestScore >= 0.55;
  const weakEvidenceLanguage = /not found|no relevant|does not contain|没有找到|未找到|未检索到|证据不足|无法确认/i.test(lower);
  const hardConstraint = /secondary service|secondary basis|subject to coordination|coordination is required|需协调|二级业务|须协调/i.test(lower);

  if (weakEvidenceLanguage) return strongEvidence ? "warn" : "unknown";
  if (hardConstraint && !strongEvidence) return "warn";
  return strongEvidence ? "ok" : "warn";
}

const RISK_META = {
  ok: { label: "可直接使用", color: "var(--ok)", icon: CheckCircle2, bg: "oklch(0.80 0.15 155 / 0.08)", border: "oklch(0.80 0.15 155 / 0.3)" },
  warn: { label: "需注意相邻业务/协调", color: "var(--warn)", icon: AlertTriangle, bg: "oklch(0.84 0.14 80 / 0.08)", border: "oklch(0.84 0.14 80 / 0.3)" },
  danger: { label: "存在冲突/不可用", color: "var(--err)", icon: XCircle, bg: "oklch(0.74 0.18 25 / 0.08)", border: "oklch(0.74 0.18 25 / 0.3)" },
  unknown: { label: "风险待评估", color: "var(--muted)", icon: Info, bg: "oklch(1 0 0 / 0.03)", border: "var(--line)" },
};

/* 规划质量 = 是否产出了可用的明确规划（有具体频段+业务），与风险等级相互独立。
   一个 risk=warn 但有明确频段/业务/建议的结果，依然是「有效规划」这一好结果。 */
function planQuality(structured) {
  if (!structured) return "insufficient";
  const band = structured.frequency_band;
  const hasBand = band && band !== "unknown" && String(band).trim() !== "";
  const hasServices = Array.isArray(structured.services) && structured.services.length > 0;
  return hasBand && hasServices ? "valid" : "insufficient";
}

const QUALITY_META = {
  valid: { label: "规划有效", color: "var(--ok)", icon: CheckCircle2, bg: "oklch(0.80 0.15 155 / 0.12)", border: "oklch(0.80 0.15 155 / 0.4)" },
  insufficient: { label: "信息不足", color: "var(--muted)", icon: Info, bg: "oklch(1 0 0 / 0.04)", border: "var(--line)" },
};

function formatTime() {
  return new Date().toLocaleString("zh-CN", { hour12: false });
}

function buildPipelineSteps(status, result) {
  const stages = result?._stages || {};
  return [
    { label: "Query Analysis", key: "query_analysis", state: stages.query_analysis || "pending" },
    { label: "Hybrid Retrieval", key: "retrieval", state: stages.retrieval || "pending" },
    { label: "Rerank", key: "rerank", state: stages.rerank || "pending" },
    { label: "Footnote/Adjacent", key: "multihop", state: stages.multihop || "pending" },
    { label: "Answer Generation", key: "answer", state: stages.answer || "pending" },
  ];
}

/* ── internal sub-components ── */

function RequestForm({ form, onChange, onPreset, disabled, mode, onModeChange }) {
  const [showAdvanced, setShowAdvanced] = useState(false);
  const activePreset = PRESETS.find((p) => p.id === form.scenario);

  const set = (key, val) => onChange({ ...form, [key]: val });

  return (
    <div className="fp-form">
      {/* mode toggle */}
      <div className="fp-field">
        <label className="fp-label">输入方式</label>
        <div className="fp-segment">
          <button className={mode === "manual" ? "on" : ""} onClick={() => onModeChange("manual")} disabled={disabled} type="button">参数化</button>
          <button className={mode === "nl" ? "on" : ""} onClick={() => onModeChange("nl")} disabled={disabled} type="button">自然语言</button>
        </div>
      </div>

      {mode === "nl" ? (
        <>
          <div className="fp-field">
            <label className="fp-label">需求描述 <span className="fp-required">*</span></label>
            <textarea className="fp-textarea" rows={6}
              placeholder="用自然语言描述频率规划需求。例：「我要在沿海地区部署一套海上搜救通信系统，需要 VHF 频段，请告诉我可用的频段、信道安排和使用限制，以及与现有海上业务的共存约束」"
              value={form.nl_request || ""}
              onChange={(e) => set("nl_request", e.target.value)}
              disabled={disabled} />
            <p className="fp-preset-desc">智能体将基于 ITU-R 知识库检索并给出结构化频率规划分析。</p>
          </div>
          <div className="fp-field">
            <label className="fp-label">示例需求</label>
            <div className="fp-nl-examples">
              {NL_EXAMPLES.map((ex, i) => (
                <button key={i} className="fp-preset-chip" type="button" disabled={disabled}
                  title={ex.text}
                  onClick={() => set("nl_request", ex.text)}>{ex.label}</button>
              ))}
            </div>
          </div>
        </>
      ) : (
        <>
      {/* presets */}
      <div className="fp-field">
        <label className="fp-label">场景预设</label>
        <select className="fp-select" value={form.scenario || ""} onChange={(e) => {
          const p = PRESETS.find((x) => x.id === e.target.value);
          if (p) {
            onPreset(p);
          }
        }} disabled={disabled}>
          <option value="">手动输入…</option>
          {PRESETS.map((p) => <option key={p.id} value={p.id}>{p.label}</option>)}
        </select>
        {activePreset && (
          <p className="fp-preset-desc">{activePreset.desc}</p>
        )}
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
        </>
      )}
    </div>
  );
}

function ReasoningBox({ reasoning, open }) {
  if (!reasoning) return null;
  return (
    <details className="reasoning-box" open={open}>
      <summary>思考过程{open ? "…" : ""}</summary>
      <p>{reasoning}</p>
    </details>
  );
}

const ALLOC_META = {
  primary: { label: "主要业务", tone: "ok" },
  secondary: { label: "次要业务", tone: "warn" },
  "not-allocated": { label: "未划分", tone: "danger" },
  mixed: { label: "混合划分", tone: "info" },
  unknown: { label: "未确定", tone: "muted" },
};

function StructuredCards({ data }) {
  if (!data) return null;
  const alloc = ALLOC_META[data.allocation_status] || ALLOC_META.unknown;
  const services = Array.isArray(data.services) ? data.services : [];
  const footnotes = Array.isArray(data.footnotes) ? data.footnotes : [];
  const adjacent = Array.isArray(data.adjacent_bands) ? data.adjacent_bands : [];
  const coex = Array.isArray(data.coexistence_constraints) ? data.coexistence_constraints : [];

  return (
    <div className="fp-cards">
      <div className="fp-card fp-card-head">
        <div className="fp-card-band">
          {data.frequency_band || "—"}
          {data.region && data.region !== "unspecified" && <span className="fp-card-region">{data.region}</span>}
        </div>
        <span className={`fp-alloc-badge ${data.allocation_status || "unknown"}`} data-tone={alloc.tone}>
          {alloc.label}
        </span>
      </div>

      {services.length > 0 && (
        <div className="fp-card">
          <div className="fp-card-label">业务划分</div>
          <div className="fp-tags">
            {services.map((s, i) => (
              <span key={i} className={`fp-tag ${s.status === "primary" ? "primary" : "secondary"}`}>
                {s.name}{s.status ? ` · ${s.status === "primary" ? "主要" : "次要"}` : ""}
              </span>
            ))}
          </div>
        </div>
      )}

      {footnotes.length > 0 && (
        <div className="fp-card">
          <div className="fp-card-label">脚注</div>
          <div className="fp-tags">
            {footnotes.map((f, i) => <span key={i} className="fp-footnote-chip">{f}</span>)}
          </div>
        </div>
      )}

      {adjacent.length > 0 && (
        <div className="fp-card">
          <div className="fp-card-label">相邻频段</div>
          <div className="fp-tags">
            {adjacent.map((b, i) => <span key={i} className="fp-tag adj">{b}</span>)}
          </div>
        </div>
      )}

      {coex.length > 0 && (
        <div className="fp-card">
          <div className="fp-card-label">共存约束</div>
          <ul className="fp-coex-list">
            {coex.map((c, i) => <li key={i}>{c}</li>)}
          </ul>
        </div>
      )}

      {data.recommendation && (
        <div className="fp-reco">
          <strong>规划建议</strong>
          <p>{data.recommendation}</p>
        </div>
      )}
    </div>
  );
}

function ResultPanel({ status, result, risk }) {
  const riskInfo = RISK_META[risk] || RISK_META.unknown;
  const RiskIcon = riskInfo.icon;
  const pipeline = buildPipelineSteps(status, result);

  if (status === "idle") {
    return (
      <div className="fp-result-empty">
        <div className="fp-empty-icon"><FileSearch size={28} /></div>
        <h3>等待运行规划</h3>
        <p>在左侧选择一个预设场景或手动填写频段参数，点击"运行规划"启动 RAG 检索与分析。</p>
        <div className="fp-empty-presets">
          {PRESETS.slice(0, 3).map((p) => (
            <span key={p.id} className="fp-preset-chip">{p.label}</span>
          ))}
        </div>
      </div>
    );
  }

  if (status === "running") {
    // hide the trailing JSON fence while it streams in
    const liveAnswer = (result?.answer || "").split("```json")[0];
    return (
      <div className="fp-result-running">
        <div className="fp-pipeline fp-pipeline-compact">
          {pipeline.map((step) => <PipelineStep key={step.label} label={step.label} state={step.state} />)}
        </div>
        <ReasoningBox reasoning={result?.reasoning} open={true} />
        {liveAnswer ? (
          <div className="fp-answer">
            <Markdown>{liveAnswer}</Markdown>
          </div>
        ) : (
          <p className="fp-running-note">正在调用 RAG 检索服务…</p>
        )}
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
  const quality = planQuality(result?.structured);
  const qInfo = QUALITY_META[quality];
  const QIcon = qInfo.icon;
  return (
    <div className="fp-result">
      {/* 主徽章=规划质量；风险等级作为独立属性标签 */}
      <div className="fp-result-header">
        <div className="fp-quality-badge" style={{ background: qInfo.bg, borderColor: qInfo.border, color: qInfo.color }}>
          <QIcon size={14} /> {qInfo.label}
        </div>
        {quality === "valid" && (
          <div className="fp-risk-badge" style={{ background: riskInfo.bg, borderColor: riskInfo.border, color: riskInfo.color }}>
            <RiskIcon size={13} /> {riskInfo.label}
          </div>
        )}
        <span className="fp-result-meta">
          {result?.citations?.length || 0} 条引用 · {result?.retrieved_blocks?.length || 0} 个检索块 · {formatTime()}
        </span>
      </div>

      <div className="fp-pipeline fp-pipeline-compact">
        {pipeline.map((step) => <PipelineStep key={step.label} label={step.label} state={step.state} />)}
      </div>

      {/* structured planning cards */}
      <StructuredCards data={result?.structured} />

      {/* agent reasoning */}
      <ReasoningBox reasoning={result?.reasoning} open={false} />

      {/* answer markdown */}
      <div className="fp-answer">
        <Markdown>{result?.answer || "(模型返回为空)"}</Markdown>
      </div>
    </div>
  );
}

function PipelineStep({ label, state }) {
  return (
    <div className={`fp-pipe-step ${state}`}>
      <div className="fp-pipe-dot">
        {state === "done" && <CheckCircle2 size={12} />}
        {state === "active" && <Loader2 size={10} className="spin" />}
        {state === "error" && <XCircle size={12} />}
      </div>
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
  const [mode, setMode] = usePersistentState("sc_fp_mode", "manual"); // "manual" | "nl"
  const [form, setForm] = usePersistentState("sc_fp_form", {
    scenario: "",
    frequency_band: "",
    region: "",
    country: "",
    service: "",
    bandwidth_mhz: "",
    coexistence: "",
    mission_context: "",
    nl_request: "",
    retrieval_mode: "hybrid",
    top_k: 8,
  });
  const [status, setStatus] = usePersistentState("sc_fp_status", "idle"); // idle | ready | running | success | empty | error
  const [result, setResult] = usePersistentState("sc_fp_result", null);
  const [risk, setRisk] = usePersistentState("sc_fp_risk", "unknown");
  const [selectedCitation, setSelectedCitation] = useState(null);

  // A persisted "running" can't reflect a live request after remount; recover it.
  useEffect(() => {
    if (status === "running") setStatus(result ? "success" : "idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const canRun = status !== "running" && (
    mode === "nl" ? (form.nl_request || "").trim().length > 0 : form.frequency_band.trim().length > 0
  );

  const handleRun = useCallback(async () => {
    if (!canRun) return;
    const query = mode === "nl" ? form.nl_request.trim() : buildQuery(form);
    setStatus("running");
    setResult(null);
    setSelectedCitation(null);
    setRisk("unknown");

    let finalAnswer = "";
    let reasoning = "";
    let finalCitations = [];
    let finalDebug = {};
    const stageStates = { query_analysis: "pending", retrieval: "pending", rerank: "pending", multihop: "pending", answer: "pending" };

    const updateStage = (stage, s) => {
      stageStates[stage] = s;
      setResult((prev) => ({ ...(prev || {}), _stages: { ...stageStates }, answer: finalAnswer, reasoning }));
    };

    runFrequencyPlanStream(query, (event) => {
      if (event.type === "stage") {
        updateStage(event.stage, "active");
      } else if (event.type === "stage_done") {
        updateStage(event.stage, "done");
      } else if (event.type === "thinking") {
        reasoning += event.data;
        setResult((prev) => ({ ...(prev || {}), _stages: { ...stageStates }, answer: finalAnswer, reasoning }));
      } else if (event.type === "content") {
        finalAnswer += event.data;
        setResult((prev) => ({ ...(prev || {}), _stages: { ...stageStates }, answer: finalAnswer, reasoning }));
      } else if (event.type === "done") {
        finalCitations = event.citations || [];
        finalDebug = event.debug || {};
        const { structured, markdown } = extractStructured(finalAnswer);
        // prefer the model's structured risk_level, fall back to heuristic
        const r = (structured && structured.risk_level && structured.risk_level !== "unknown")
          ? structured.risk_level
          : inferRisk(finalAnswer, finalCitations);
        setRisk(r);
        setResult({
          answer: markdown, structured, reasoning,
          citations: finalCitations, debug: finalDebug,
          retrieved_blocks: finalDebug.retrieved_blocks || [],
          _stages: stageStates,
        });
        setStatus(markdown.length > 10 || finalCitations.length > 0 ? "success" : "empty");
      } else if (event.type === "error") {
        setResult({ error: event.data, _stages: stageStates });
        setStatus("error");
      }
    });
  }, [canRun, form, mode]);

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
    setForm((f) => ({
      ...f,
      scenario: preset.id, frequency_band: preset.band, region: preset.region,
      service: preset.service, coexistence: preset.coex, mission_context: preset.ctx,
    }));
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
            <RequestForm form={form} onChange={setForm} onPreset={handlePreset} disabled={status === "running"} mode={mode} onModeChange={setMode} />
          </div>
        </aside>

        {/* center: result */}
        <main className="fp-center card">
          <div className="card-head">
            <span className="title">规划结果</span>
            {status === "success" && (() => {
              const q = planQuality(result?.structured);
              return (
                <span className="pill" data-tone={q === "valid" ? "ok" : "muted"}>
                  <span className="dot" /> {QUALITY_META[q].label}
                </span>
              );
            })()}
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
