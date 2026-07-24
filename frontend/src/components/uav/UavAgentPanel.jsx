import { Bot, CheckCircle2, ClipboardCheck, CornerDownLeft, ShieldCheck, Square, WandSparkles } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useUavAgentRun } from "../../hooks/useUavAgentRun.js";

const QUICK_TASKS = [
  { label: "安全周界巡检", intent: "巡检安全周界后返回" },
  { label: "北门画面采集", intent: "前往北门采集画面并返回" },
  { label: "安全路线搜索", intent: "执行安全路线搜索并返回" },
];

function eventLabel(event) {
  if (event.event_type === "intent") return "任务意图";
  if (event.event_type === "policy_decision") return "安全检查";
  if (event.event_type === "tool_call") return "受限工具";
  if (event.event_type === "observation") return "环境观测";
  if (event.event_type === "completion") return "任务完成";
  if (event.event_type === "run_started") return "任务开始";
  if (event.event_type === "interruption") return "意外中断";
  return event.event_type === "error" ? "异常" : "运行状态";
}

export default function UavAgentPanel({ manualActive = false, onRunChange }) {
  const [intent, setIntent] = useState("");
  const { run, events, busy, error, createDraft, approve, cancel } = useUavAgentRun();
  const awaitingApproval = run?.status === "awaiting_approval";
  const running = run?.status === "running";
  const completed = run?.status === "completed";
  const terminal = ["completed", "failed", "cancelled", "interrupted", "rejected"].includes(run?.status);
  const terminalTitle = run?.status === "completed" ? "任务执行成功" : run?.status === "cancelled" ? "任务已取消" : run?.status === "interrupted" ? "任务意外中断" : run?.status === "rejected" ? "任务未获批准" : "任务执行失败";
  const terminalDetail = run?.status === "completed" ? "已清除导航目标，并在安全终点悬停。" : run?.summary || "任务已停止继续执行，可重新创建安全任务。";
  const latestEvent = useMemo(() => events.at(-1), [events]);

  useEffect(() => {
    onRunChange?.(run);
  }, [onRunChange, run]);

  const submit = async (value = intent) => {
    const trimmed = value.trim();
    if (!trimmed) return;
    await createDraft(trimmed);
  };

  return (
    <aside className="card uav-agent-panel" aria-label="无人机智能体任务工作区">
      <header className="uav-agent-panel-head"><div><span className="eyebrow">AGENT OPERATIONS</span><h2><Bot size={18} /> 无人机任务智能体</h2></div><span className="uav-agent-scope"><ShieldCheck size={13} /> 仿真沙箱</span></header>
      <p className="uav-agent-intro">描述目标，智能体只会生成预审任务计划。飞行前必须经过安全检查与明确批准。</p>
      <div className="uav-agent-composer">
        <textarea value={intent} onChange={(event) => setIntent(event.target.value)} placeholder="例如：巡检安全周界，采集画面后返回" rows={3} disabled={busy || running} />
        <button type="button" onClick={() => submit()} disabled={!intent.trim() || busy || running}><WandSparkles size={15} /> 生成任务计划</button>
      </div>
      <div className="uav-agent-quick" aria-label="固定安全任务">
        {QUICK_TASKS.map((task) => <button key={task.label} type="button" onClick={() => { setIntent(task.intent); void submit(task.intent); }} disabled={busy || running}>{task.label}</button>)}
      </div>
      {manualActive && <div className="uav-agent-warning"><ShieldCheck size={14} /> WASD 正在接管；智能体不可审批或执行飞行任务。</div>}
      {run && <section className="uav-agent-run">
        <div className="uav-agent-run-title"><ClipboardCheck size={15} /><strong>{run.plan?.template || "任务草案"}</strong><span data-state={run.status}>{run.status}</span></div>
        <p>{run.summary}</p>
        <dl><div><dt>任务</dt><dd>{run.intent}</dd></div><div><dt>安全边界</dt><dd>模板 · 地标 · 高度均受限</dd></div></dl>
        <div className="uav-agent-lifecycle" aria-label="任务生命周期">
          <span data-state={run.started_at ? "done" : "pending"}><i /> 已开始</span><b />
          <span data-state={terminal ? (run.status === "completed" ? "success" : "terminal") : "active"}><i /> {terminal ? "已结束" : "执行中"}</span>
        </div>
        {awaitingApproval && <button className="uav-agent-approve" type="button" onClick={() => approve()} disabled={busy || manualActive}><CheckCircle2 size={15} /> 批准并执行计划</button>}
        {running && <button className="uav-agent-cancel" type="button" onClick={() => cancel()} disabled={busy}><Square size={14} /> 取消并请求悬停</button>}
        {terminal && <div className={completed ? "uav-agent-complete" : "uav-agent-terminal"} role="status"><CheckCircle2 size={15} /><div><strong>{terminalTitle}</strong><span>{terminalDetail}</span></div></div>}
      </section>}
      <section className="uav-agent-audit" aria-live="polite">
        <ClipboardCheck size={14} />
        <span>{latestEvent ? `${eventLabel(latestEvent)} · ${latestEvent.summary}` : <><CornerDownLeft size={14} /> 任务日志会同步显示在下方快捷控制条。</>}</span>
      </section>
      {error && <div className="uav-agent-error" role="alert">{error}</div>}
    </aside>
  );
}
