import { Activity, CheckCircle2, CircleDot, Play, Route } from "lucide-react";

function missionActivity(run, vehicleAction, manualActive) {
  if (vehicleAction === "takeoff") return "正在请求起飞至 3 m…";
  if (vehicleAction === "hover") return "正在请求 PX4 悬停…";
  if (vehicleAction === "return_to_launch") return "正在请求返航…";
  if (run?.status === "running") return run.summary || "智能体正在执行受限任务…";
  if (run?.status === "completed") return run.summary || "任务成功，已在安全终点悬停。";
  if (run?.status === "failed") return run.summary || "任务未完成，请查看智能体面板。";
  if (run?.status === "cancelled") return run.summary || "任务已取消，已请求悬停。";
  if (run?.status === "interrupted") return run.summary || "任务意外中断，飞控已停止继续执行。";
  if (run?.status === "rejected") return run.summary || "任务未通过安全检查。";
  if (manualActive) return "手动飞控已接管；智能体任务暂停。";
  return "PX4 已就绪；可起飞、悬停或返航。";
}

export default function FlightControlDock({
  onVehicleAction,
  unavailable,
  missionRun,
  vehicleAction,
  manualActive,
}) {
  const activity = missionActivity(missionRun, vehicleAction, manualActive);
  const completed = missionRun?.status === "completed";
  return <section className="uav-flight-dock" aria-label="PX4 快捷飞行控制">
    <div className="uav-flight-dock-log" aria-live="polite" data-completed={completed ? "true" : "false"}>
      {completed ? <CheckCircle2 size={14} /> : <Activity size={14} />}
      <span>{activity}</span>
    </div>
    <div className="uav-flight-dock-actions">
      <button type="button" onClick={() => onVehicleAction("takeoff")} disabled={unavailable}><Play size={14} /> 起飞</button>
      <button type="button" onClick={() => onVehicleAction("hover")} disabled={unavailable}><CircleDot size={14} /> 悬停</button>
      <button type="button" onClick={() => onVehicleAction("return_to_launch")} disabled={unavailable}><Route size={14} /> 返航</button>
    </div>
  </section>;
}
