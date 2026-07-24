import { ChevronDown, CircleAlert, Cpu, FileCheck2, ServerCog } from "lucide-react";
import { useMemo, useState } from "react";

const STAGE_LABELS = {
  "01_system": "ROS 2 Humble",
  "02_px4": "PX4 v1.17",
  "03_sionna_rt": "Sionna RT 2.0.1",
  "04_ros_gazebo_px4_smoke": "PX4 / Gazebo Smoke",
  "05_sionna_rt_smoke": "Sionna RT CUDA Smoke",
  "06_versions": "版本锁定",
  "07_debug_bridge": "Foxglove Bridge",
};

export default function UavEnvironmentDiagnostics({ status, loading = false }) {
  const [open, setOpen] = useState(false);
  const stages = status?.stages || {};
  const components = status?.components || {};
  const stageRows = Object.entries(STAGE_LABELS).map(([key, label]) => ({ key, label, ready: Boolean(stages[key]) }));
  const componentRows = useMemo(() => Object.values(components).filter((item) => item?.label), [components]);
  const readyStages = stageRows.filter((stage) => stage.ready).length;
  const unavailable = componentRows.filter((item) => !item.ready).length;
  const runtime = status?.runtime;

  return (
    <section className="sys-uav-diagnostics" aria-label="UAV 仿真环境诊断">
      <button className="sys-uav-diagnostics-toggle" type="button" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
        <span className="sys-uav-diagnostics-title"><ServerCog size={17} /> UAV 仿真环境</span>
        <span className="sys-uav-diagnostics-summary" data-tone={status?.environment_ready ? "ok" : unavailable ? "warn" : "muted"}>
          {loading ? "检查中" : `${readyStages}/${stageRows.length} 阶段就绪${unavailable ? ` · ${unavailable} 项待检查` : ""}`}
        </span>
        <ChevronDown size={16} className={open ? "is-open" : ""} />
      </button>
      {open && <div className="sys-uav-diagnostics-body">
        <div className="sys-uav-runtime">
          <span><Cpu size={14} /> PX4/Gazebo · {runtime?.state === "running" ? "运行中" : "待命"}</span>
          <span><FileCheck2 size={14} /> {runtime?.agent_navigation?.ready ? "智能体导航桥就绪" : "智能体导航桥待检查"}</span>
          {runtime?.camera?.error && <span data-tone="warn"><CircleAlert size={14} /> {runtime.camera.error}</span>}
        </div>
        <div className="sys-uav-stage-grid">
          {stageRows.map((stage) => <div key={stage.key} data-ready={stage.ready ? "true" : "false"}><i /> {stage.label}</div>)}
        </div>
        <div className="sys-uav-component-list">
          {componentRows.map((component) => <div key={component.label}><span>{component.label}</span><strong data-ready={component.ready ? "true" : "false"}>{component.ready ? "Ready" : "待检查"}</strong></div>)}
        </div>
        <p>运行日志：<code>{runtime?.log_file || "等待仿真运行时"}</code></p>
      </div>}
    </section>
  );
}
