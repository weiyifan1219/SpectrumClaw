import { ShieldCheck } from "lucide-react";
import { systemRows } from "../data/mockData.js";

const groups = ["External", "Runtime", "Storage", "Service"];

export default function SystemPage() {
  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">System · Status</span>
          <h1>运行系统状态</h1>
          <p className="lede">
            查看环境、API、路径、依赖与服务健康状况;区分本地备份环境与 4090 主运行环境。
          </p>
        </div>
        <div className="actions">
          <button className="btn primary"><ShieldCheck size={14} /> 健康检查</button>
        </div>
      </div>

      <div className="sys-overview">
        {[
          { k: "Local", v: "SpectrumClaw", d: "本地预览 · 备份", tone: "ok" },
          { k: "Server", v: "4090 · Agent env", d: "未连接 · 待部署", tone: "muted" },
          { k: "Knowledge", v: "ITU 文档", d: "Pinned · 887 MB", tone: "info" }
        ].map((s) => (
          <div className="stat-card" key={s.k}>
            <span className="k">{s.k}</span>
            <div className="v">{s.v}</div>
            <div className="d">{s.d}</div>
          </div>
        ))}
      </div>

      {groups.map((g) => {
        const rows = systemRows.filter((r) => r.group === g);
        if (!rows.length) return null;
        return (
          <div className="sys-group" key={g}>
            <div className="sys-group-title">{g}</div>
            <div className="sys-table">
              {rows.map((r) => (
                <div className="sys-row" key={r.name}>
                  <strong>{r.name}</strong>
                  <span className="mono">{r.value}</span>
                  <span className="pill" data-tone={r.tone}>
                    <span className="dot" /> {r.status}
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
