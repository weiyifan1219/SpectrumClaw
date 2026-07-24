import { Building2, CircleDotDashed, Map, Radio, Signal } from "lucide-react";

const MAP_RANGE_M = 45;

function mapPoint([east = 0, north = 0]) {
  const x = ((Number(east) + MAP_RANGE_M) / (MAP_RANGE_M * 2)) * 100;
  const y = 100 - ((Number(north) + MAP_RANGE_M) / (MAP_RANGE_M * 2)) * 100;
  return [Math.max(2, Math.min(98, x)), Math.max(2, Math.min(98, y))];
}

function phaseLabel(run) {
  if (!run) return "等待任务";
  if (run.status === "running") return "任务执行中";
  if (run.status === "completed") return "任务成功 · 已悬停";
  if (run.status === "failed") return "任务失败 · 已停止";
  if (run.status === "cancelled") return "已取消 · 已请求悬停";
  if (run.status === "interrupted") return "意外中断 · 待复核";
  if (run.status === "rejected") return "安全检查未通过";
  return "等待人工批准";
}

export default function UavMissionSituation({ scene, vehicle, trajectory = [], run, lidar }) {
  const objects = Array.isArray(scene?.objects) ? scene.objects : [];
  const signalSources = Array.isArray(scene?.signal_sources) ? scene.signal_sources : [];
  const anchors = trajectory.filter((sample, index) => {
    if (index === 0 || index === trajectory.length - 1) return true;
    const previous = trajectory[index - 1];
    return Math.hypot(sample.x - previous.x, sample.y - previous.y) >= 2.6;
  }).slice(-14);
  const line = anchors.map((sample, index) => {
    const [x, y] = mapPoint([sample.x, sample.y]);
    return `${index ? "L" : "M"}${x},${y}`;
  }).join(" ");
  const position = Array.isArray(vehicle?.position_m) ? vehicle.position_m : null;
  const [vehicleX, vehicleY] = position ? mapPoint(position) : [50, 50];
  const activeSignals = signalSources.filter((source) => source.enabled);
  const lidarReturns = lidar?.available && Array.isArray(lidar?.ranges_m)
    ? lidar.ranges_m.filter((range) => Number.isFinite(Number(range)) && Number(range) < Number(lidar.range_max_m || 30)).length
    : 0;

  return (
    <section className="card uav-mission-situation" aria-label="无人机任务态势">
      <header className="uav-mission-situation-head">
        <div><span className="eyebrow">MISSION SITUATION</span><h2><Map size={17} /> 任务态势</h2></div>
        <span className="uav-situation-phase" data-state={run?.status || "idle"}>{phaseLabel(run)}</span>
      </header>
      <div className="uav-situation-map" role="img" aria-label="城市街区、无人机飞行轨迹、建筑物和信号源接口态势图">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <rect className="uav-situation-ground" width="100" height="100" rx="3" />
          <path className="uav-situation-road" d="M0 50 H100 M50 0 V100" />
          {objects.map((object) => {
            const [x, y] = mapPoint(object.position_m || []);
            const [width, height] = object.size_m || [8, 8];
            return <rect key={object.id} className="uav-situation-building" x={x - Math.max(3, width / 3.3)} y={y - Math.max(3, height / 3.3)} width={Math.max(6, width / 1.65)} height={Math.max(6, height / 1.65)} rx="1.5" />;
          })}
          {signalSources.map((source) => {
            const [x, y] = mapPoint(source.position_m || []);
            return <g key={source.id} transform={`translate(${x} ${y})`} className={source.enabled ? "is-active" : ""}>
              <circle className="uav-situation-signal-ring" r="6" />
              <circle className="uav-situation-signal" r="2" />
            </g>;
          })}
          {line && <path className="uav-situation-track" d={line} />}
          {anchors.map((sample, index) => {
            const [x, y] = mapPoint([sample.x, sample.y]);
            return <circle key={`${sample.at}-${index}`} className={index === 0 ? "uav-situation-track-start" : "uav-situation-track-point"} cx={x} cy={y} r={index === 0 ? "2.5" : "1.15"} />;
          })}
          {position && <g transform={`translate(${vehicleX} ${vehicleY})`} className="uav-situation-vehicle"><path d="M0 -5 L2 0 L5 2 L1 2 L0 5 L-1 2 L-5 2 L-2 0 Z" /></g>}
        </svg>
      </div>
      <div className="uav-situation-stats">
        <div><Building2 size={14} /><span>建筑物</span><strong>{objects.length} 已载入</strong></div>
        <div><CircleDotDashed size={14} /><span>LiDAR</span><strong>{lidar?.available ? `${lidarReturns} 回波` : "等待数据"}</strong></div>
        <div><Signal size={14} /><span>信号源</span><strong>{activeSignals.length ? `${activeSignals.length} 已激活` : `${signalSources.length} 接口预留`}</strong></div>
      </div>
      <p className="uav-situation-note"><Radio size={13} /> 建筑物来自 urban_block 场景；信号源仅为后续频谱模块预留，当前未参与任务决策。</p>
    </section>
  );
}
