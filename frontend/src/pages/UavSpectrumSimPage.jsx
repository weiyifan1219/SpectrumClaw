import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  Check,
  CircleStop,
  CircleDot,
  Copy,
  Cpu,
  Gauge,
  Keyboard,
  MapPinned,
  MonitorUp,
  Navigation,
  Play,
  Radio,
  RefreshCw,
  Route,
  ServerCog,
  Waves,
  XCircle,
} from "lucide-react";
import {
  fetchUavSpectrumSimStatus,
  controlUavSimulation,
  startUavSpectrumSimGui,
  startUavSpectrumSim,
  stopUavSpectrumSim,
  stopUavSpectrumSimGui,
  disableUavManualControl,
  enableUavManualControl,
  updateUavManualControl,
  uavManualControlLiveUrl,
  uavSimulationGuiUrl,
  uavSimulationMediaUrl,
  fetchUavSpectrumSituation,
  fetchUavSpectrumGrid,
  refreshUavSpectrumSituation,
} from "../lib/api.js";
import { useUavSimulationLive } from "../hooks/useUavSimulationLive.js";
import LidarRadar from "../components/uav/LidarRadar.jsx";
import FlightControlDock from "../components/uav/FlightControlDock.jsx";
import UavAgentPanel from "../components/uav/UavAgentPanel.jsx";
import UavMissionSituation from "../components/uav/UavMissionSituation.jsx";
import UavSpectrumLayerMap from "../components/uav/UavSpectrumLayerMap.jsx";
import PageToolbar from "../components/PageToolbar.jsx";
import "../styles/uav-spectrum-live.css";
import { applySpectrumGridUpdate } from "../lib/spectrumGrid.js";

const UavSceneCanvas = lazy(() => import("../components/uav/UavSceneCanvas.jsx"));

const UAV_STATUS_CACHE_KEY = "spectrumclaw:uav-runtime-status";
const UAV_VIEW_CACHE_KEY = "spectrumclaw:uav-selected-view";

function readSessionJson(key) {
  try {
    const value = window.sessionStorage.getItem(key);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

function initialViewerMode() {
  const saved = readSessionJson(UAV_VIEW_CACHE_KEY);
  return ["observe", "spectrum", "gui"].includes(saved) ? saved : "observe";
}

const STAGE_LABELS = {
  "01_system": "ROS 2 Humble",
  "02_px4": "PX4 v1.17",
  "03_sionna_rt": "Sionna RT 2.0.1",
  "04_ros_gazebo_px4_smoke": "PX4 / Gazebo Smoke Test",
  "05_sionna_rt_smoke": "CUDA RT Smoke Test",
  "06_versions": "版本锁定",
  "07_debug_bridge": "Foxglove Bridge",
};

const VIEW_MODES = [
  {
    id: "observe",
    index: "01",
    title: "飞控工作台",
    description: "实景飞行、任务编排与控制日志",
    icon: Navigation,
  },
  {
    id: "spectrum",
    index: "02",
    title: "电磁频谱态势",
    description: "三维传播、实时 REM 与链路证据",
    icon: Radio,
  },
  {
    id: "gui",
    index: "03",
    title: "系统诊断",
    description: "原生 Gazebo 与运行环境检查",
    icon: MonitorUp,
  },
];

function formatTime(timestamp) {
  if (!timestamp) return "—";
  try {
    return new Date(timestamp * 1000).toLocaleString("zh-CN", {
      hour12: false,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
  } catch {
    return "—";
  }
}

function RuntimeBadge({ state }) {
  const running = state === "running";
  return (
    <span className="uav-runtime-badge" data-state={running ? "running" : "stopped"}>
      <i /> {running ? "仿真运行中" : "仿真待命"}
    </span>
  );
}

function UavModeNavigation({ value, onChange, runtimeState, spectrumCurrent, liveConnection }) {
  const handleKeyDown = (event, currentIndex) => {
    let nextIndex = currentIndex;
    if (event.key === "ArrowRight") nextIndex = (currentIndex + 1) % VIEW_MODES.length;
    else if (event.key === "ArrowLeft") nextIndex = (currentIndex - 1 + VIEW_MODES.length) % VIEW_MODES.length;
    else if (event.key === "Home") nextIndex = 0;
    else if (event.key === "End") nextIndex = VIEW_MODES.length - 1;
    else return;
    event.preventDefault();
    onChange(VIEW_MODES[nextIndex].id);
    event.currentTarget.parentElement?.querySelectorAll('[role="tab"]')[nextIndex]?.focus();
  };

  return (
    <nav className="uav-mode-navigation" role="tablist" aria-label="无人机仿真子页面">
      {VIEW_MODES.map((mode, index) => {
        const Icon = mode.icon;
        const selected = value === mode.id;
        const state = mode.id === "observe"
          ? runtimeState === "running" ? "运行中" : "待命"
          : mode.id === "spectrum"
            ? spectrumCurrent ? "实时" : "待采样"
            : liveConnection === "online" ? "已连接" : "检查中";
        return (
          <button
            key={mode.id}
            id={`uav-mode-${mode.id}`}
            type="button"
            role="tab"
            aria-selected={selected}
            aria-controls={`uav-panel-${mode.id}`}
            tabIndex={selected ? 0 : -1}
            className={selected ? "is-active" : ""}
            onClick={() => onChange(mode.id)}
            onKeyDown={(event) => handleKeyDown(event, index)}
          >
            <span className="uav-mode-index">{mode.index}</span>
            <span className="uav-mode-icon"><Icon size={17} /></span>
            <span className="uav-mode-copy"><strong>{mode.title}</strong><small>{mode.description}</small></span>
            <span className="uav-mode-state" data-active={selected ? "true" : "false"}><i /> {state}</span>
          </button>
        );
      })}
    </nav>
  );
}

function UavDiagnosticsPanel({ data, runtime, liveConnection, copied, onCopy, onOpenSystem }) {
  const stages = Object.entries(data?.stages || {});
  const readyCount = stages.filter(([, ready]) => ready).length;
  const guiOnline = runtime?.gui?.state === "online";
  const cameraOnline = runtime?.camera?.state === "online";

  return (
    <aside className="card uav-diagnostics-rail" aria-label="无人机仿真系统诊断">
      <header className="uav-diagnostics-head">
        <div><span className="eyebrow">RUNTIME DIAGNOSTICS</span><h2><ServerCog size={18} /> 运行链路</h2></div>
        <span className="uav-diagnostics-score" data-ready={data?.environment_ready ? "true" : "false"}>{readyCount}/{stages.length || 7}</span>
      </header>

      <div className="uav-diagnostics-overview">
        <div data-tone={runtime?.state === "running" ? "ok" : "muted"}><Cpu size={15} /><span>仿真核心</span><strong>{runtime?.state === "running" ? "PX4 / Gazebo 运行中" : "等待启动"}</strong></div>
        <div data-tone={cameraOnline ? "ok" : "warn"}><Gauge size={15} /><span>视觉链路</span><strong>{cameraOnline ? "六路画面在线" : "相机桥未就绪"}</strong></div>
        <div data-tone={liveConnection === "online" ? "ok" : "warn"}><Activity size={15} /><span>实时遥测</span><strong>{liveConnection === "online" ? "WebSocket 已连接" : "正在重连"}</strong></div>
        <div data-tone={guiOnline ? "ok" : "muted"}><MonitorUp size={15} /><span>图形会话</span><strong>{guiOnline ? "原生 GUI 在线" : "按需启动"}</strong></div>
      </div>

      <section className="uav-diagnostics-checks">
        <div className="uav-diagnostics-section-title"><Check size={14} /> 环境自检</div>
        {stages.length ? stages.map(([key, ready]) => (
          <div className="uav-diagnostics-check" key={key} data-ready={ready ? "true" : "false"}>
            {ready ? <Check size={14} /> : <XCircle size={14} />}
            <span>{STAGE_LABELS[key] || key}</span>
            <em>{ready ? "READY" : "CHECK"}</em>
          </div>
        )) : <div className="uav-diagnostics-empty">正在读取 3090 环境自检结果…</div>}
      </section>

      <dl className="uav-diagnostics-facts">
        <div><dt>Runtime PID</dt><dd>{runtime?.pid || "—"}</dd></div>
        <div><dt>启动时间</dt><dd>{formatTime(runtime?.started_at)}</dd></div>
        <div><dt>飞控模式</dt><dd>{runtime?.manual?.enabled ? "Manual Offboard" : "Agent Ready"}</dd></div>
      </dl>

      <div className="uav-diagnostics-actions">
        <button type="button" onClick={onCopy}><Copy size={14} /> {copied ? "已复制调试地址" : "复制 Foxglove 地址"}</button>
        <button type="button" onClick={onOpenSystem}><ServerCog size={14} /> 打开完整系统诊断</button>
      </div>
    </aside>
  );
}

function MissionMap({ scene, runtimeState }) {
  if (!scene) {
    return <div className="uav-map-loading" aria-label="正在加载仿真场景"><span /></div>;
  }
  const [width, height] = scene.area_m || [250, 180];
  const points = scene.waypoints_m || [];
  const path = points.map(([x, y], index) => `${index ? "L" : "M"}${x},${height - y}`).join(" ");
  const [launchX, launchY] = points[0] || [0, 0];

  return (
    <div className="uav-map-viewport">
      <svg viewBox={`0 0 ${width} ${height}`} role="img" aria-label="低空频谱仿真任务航线图">
        <defs>
          <pattern id="uav-grid" width="12" height="12" patternUnits="userSpaceOnUse">
            <path d="M 12 0 L 0 0 0 12" fill="none" stroke="currentColor" strokeWidth="0.55" />
          </pattern>
          <radialGradient id="uav-coverage" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#45d4ff" stopOpacity="0.32" />
            <stop offset="58%" stopColor="#2c9efb" stopOpacity="0.11" />
            <stop offset="100%" stopColor="#2c9efb" stopOpacity="0" />
          </radialGradient>
          <filter id="uav-glow" x="-100%" y="-100%" width="300%" height="300%">
            <feGaussianBlur stdDeviation="2.5" result="blur" />
            <feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge>
          </filter>
        </defs>
        <rect width={width} height={height} className="uav-map-base" />
        <rect width={width} height={height} className="uav-map-grid" fill="url(#uav-grid)" />
        <path className="uav-map-contour" d={`M8,30 C44,12 75,30 110,17 S185,24 240,8`} />
        <path className="uav-map-contour faint" d={`M5,141 C41,113 82,148 126,130 S194,141 246,111`} />
        {(scene.transmitters || []).map((tx) => {
          const [x, y] = tx.position_m;
          return (
            <g key={tx.id} transform={`translate(${x} ${height - y})`}>
              <circle r="35" fill="url(#uav-coverage)" />
              <circle r="4.4" className="uav-tx-dot" filter="url(#uav-glow)" />
              <text y="-9" className="uav-svg-label">{tx.id.toUpperCase()}</text>
            </g>
          );
        })}
        <path d={path} className="uav-route-line" />
        {points.map(([x, y], index) => (
          <g key={`${x}-${y}`} transform={`translate(${x} ${height - y})`}>
            <circle r={index === 0 ? "5" : "3.2"} className={index === 0 ? "uav-launch-node" : "uav-waypoint"} />
            <text x="6" y="-7" className="uav-svg-label">{index === 0 ? "起飞点" : `W${index}`}</text>
          </g>
        ))}
        <g transform={`translate(${launchX} ${height - launchY})`} className={runtimeState === "running" ? "uav-aircraft is-running" : "uav-aircraft"}>
          <path d="M0,-12 L3,-2 L10,3 L2,3 L0,12 L-2,3 L-10,3 L-3,-2 Z" />
        </g>
      </svg>
      <div className="uav-map-overlay top-left"><MapPinned size={14} /> {scene.frame}</div>
      <div className="uav-map-overlay top-right"><Route size={14} /> {points.length} 个航点</div>
      <div className="uav-map-overlay bottom-left"><Radio size={14} /> 2.40 / 2.45 GHz</div>
      <div className="uav-map-overlay bottom-right"><span className="uav-map-scale" /> 50 m</div>
    </div>
  );
}

const CAMERA_LABELS = { front: "前视", rear: "后视", left: "左视", right: "右视", down: "下视", chase: "追随" };

const SENSOR_DIRECTIONS = ["front", "rear", "left", "right", "down"];

function FlightControlOverlay({ enabled, status, transport, onEnable, onDisable, onInput, yawInput, unavailable }) {
  const pressed = useRef(new Set());
  const sending = useRef(false);
  const queued = useRef(false);
  const yaw = useRef(yawInput);
  yaw.current = yawInput;
  const vector = useCallback(() => {
    const forwardKey = pressed.current.has("KeyW");
    const backwardKey = pressed.current.has("KeyS");
    const leftKey = pressed.current.has("KeyA");
    const rightKey = pressed.current.has("KeyD");
    const turning = forwardKey && leftKey !== rightKey;
    const keyboardYaw = turning ? (rightKey ? 0.78 : -0.78) : 0;
    return {
      forward: turning ? 0.72 : (forwardKey ? 1 : 0) + (backwardKey ? -1 : 0),
      right: turning ? 0 : (rightKey ? 1 : 0) + (leftKey ? -1 : 0),
      up: (pressed.current.has("KeyE") ? 1 : 0) + (pressed.current.has("KeyQ") ? -1 : 0),
      yaw: Math.max(-1, Math.min(1, keyboardYaw + yaw.current)),
    };
  }, []);
  const transmit = useCallback(async () => {
    if (!enabled || sending.current) { queued.current = enabled; return; }
    sending.current = true;
    try { await onInput(vector()); } finally {
      sending.current = false;
      if (queued.current) { queued.current = false; void transmit(); }
    }
  }, [enabled, onInput, vector]);
  useEffect(() => {
    if (!enabled) return undefined;
    const allowed = ["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE"];
    const usable = (event) => !event.metaKey && !event.ctrlKey && !event.altKey && allowed.includes(event.code)
      && !["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName);
    const keyDown = (event) => { if (!usable(event)) return; event.preventDefault(); pressed.current.add(event.code); void transmit(); };
    const keyUp = (event) => { if (!usable(event)) return; event.preventDefault(); pressed.current.delete(event.code); void transmit(); };
    const blur = () => { pressed.current.clear(); void transmit(); };
    const keepAlive = window.setInterval(() => void transmit(), 80);
    window.addEventListener("keydown", keyDown); window.addEventListener("keyup", keyUp); window.addEventListener("blur", blur);
    return () => { window.clearInterval(keepAlive); window.removeEventListener("keydown", keyDown); window.removeEventListener("keyup", keyUp); window.removeEventListener("blur", blur); pressed.current.clear(); };
  }, [enabled, transmit]);
  const active = enabled && status?.state === "active";
  return (
    <section className="uav-flight-overlay" aria-label="画面内 PX4 键盘遥控">
      <div className="uav-flight-overlay-head"><Keyboard size={14} /><span>PX4 遥控</span><em data-active={enabled ? "true" : "false"}>{active ? transport === "websocket" ? "WS LOW-LATENCY" : "OFFBOARD" : enabled ? "CONNECTING" : "SAFE HOLD"}</em></div>
      <div className="uav-flight-overlay-body">
        {enabled ? (
          <button type="button" onClick={onDisable}><CircleStop size={13} /> 退出手动飞控</button>
        ) : (
          <button type="button" onClick={onEnable} disabled={unavailable}><Play size={13} /> 启用手动飞控</button>
        )}
        <div className="uav-flight-key-row" aria-label="WASD、Q、E 控制提示"><kbd>WASD</kbd><span>移动 / 转向</span><kbd>Q/E</kbd><span>升降</span></div>
      </div>
    </section>
  );
}

function GazeboObserver({ camera, runtimeState, liveCamera, lidar, controlOverlay, manualEnabled, onYawInput }) {
  const [frameVersion, setFrameVersion] = useState(0);
  const [activeDirection, setActiveDirection] = useState("chase");
  const draggingRef = useRef(false);
  const yawResetTimer = useRef(null);
  const currentCamera = liveCamera || camera;
  const streams = currentCamera?.streams || {};
  const activeStream = streams[activeDirection];
  const activeLabel = activeDirection === "chase" ? "追随实景" : `${CAMERA_LABELS[activeDirection]}相机`;

  useEffect(() => {
    if (!Object.values(streams).some((stream) => stream?.ready)) return undefined;
    // Thumbnails are deliberately capped at 2 FPS; the main view below is a
    // persistent MJPEG stream and therefore does not need browser polling.
    const timer = window.setInterval(() => setFrameVersion(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [currentCamera?.state]);

  useEffect(() => {
    if (activeStream?.ready) return;
    if (streams.chase?.ready) setActiveDirection("chase");
    else {
      const fallback = SENSOR_DIRECTIONS.find((direction) => streams[direction]?.ready);
      if (fallback) setActiveDirection(fallback);
    }
  }, [activeDirection, activeStream?.ready, streams]);

  useEffect(() => () => window.clearTimeout(yawResetTimer.current), []);

  const stopLooking = useCallback(() => {
    draggingRef.current = false;
    window.clearTimeout(yawResetTimer.current);
    onYawInput(0);
  }, [onYawInput]);

  const beginLooking = useCallback((event) => {
    if (!manualEnabled || activeDirection !== "chase") return;
    event.preventDefault();
    draggingRef.current = true;
    event.currentTarget.setPointerCapture?.(event.pointerId);
  }, [activeDirection, manualEnabled]);

  const lookAround = useCallback((event) => {
    if (!draggingRef.current || !manualEnabled || activeDirection !== "chase") return;
    const yaw = Math.max(-1, Math.min(1, event.movementX / 28));
    if (Math.abs(yaw) < 0.02) return;
    onYawInput(yaw);
    window.clearTimeout(yawResetTimer.current);
    yawResetTimer.current = window.setTimeout(() => onYawInput(0), 90);
  }, [activeDirection, manualEnabled, onYawInput]);

  if (!activeStream?.ready) {
    return (
      <div className="uav-viewer-pending" role="status">
        <div className="uav-viewer-pending-orb"><MonitorUp size={24} /></div>
        <strong>{runtimeState === "running" ? "正在接入 Gazebo 观测台…" : "Gazebo 观测台随仿真启动"}</strong>
        <span>主画面将显示追随实景；五路机载相机将在下方作为可切换缩略图出现。</span>
      </div>
    );
  }
  return (
    <div className="uav-observer" aria-label="Gazebo 实景与五路机载相机统一观察台">
      <img key={activeDirection} className={manualEnabled && activeDirection === "chase" ? "uav-observer-main is-look-enabled" : "uav-observer-main"} alt={`Gazebo 渲染的无人机${activeLabel}实时画面`} src={uavSimulationMediaUrl(`${activeStream.frame_url}/stream`)} onPointerDown={beginLooking} onPointerMove={lookAround} onPointerUp={stopLooking} onPointerCancel={stopLooking} />
      <div className="uav-observer-hud"><span>GAZEBO LIVE RENDER</span><strong>{activeLabel}</strong><em>{activeDirection === "chase" ? "CHASE · 24 FPS" : "AIRBORNE CAMERA · 2 FPS"}</em></div>
      <div className="uav-observer-look-hint">{activeDirection !== "chase" ? "切回追随实景后可转向" : manualEnabled ? "拖拽主画面转向 · W/S 前后 · W+A / W+D 转向" : "启用手动飞控后，可拖拽画面并使用 WASD"}</div>
      {activeDirection !== "chase" && <button className="uav-observer-chase" type="button" onClick={() => setActiveDirection("chase")} aria-pressed="false">
        <Navigation size={13} /> 返回追随实景
      </button>}
      <LidarRadar lidar={lidar} />
      {controlOverlay}
      <div className="uav-observer-thumbnails" role="group" aria-label="五路机载相机，点击切换主画面">
        {SENSOR_DIRECTIONS.map((direction) => {
          const stream = streams[direction];
          const selected = direction === activeDirection;
          return (
            <button key={direction} type="button" className={selected ? "is-active" : ""} onClick={() => setActiveDirection(direction)} aria-pressed={selected}>
              {stream?.ready ? <img alt="" src={uavSimulationMediaUrl(`${stream.frame_url}?frame=${Math.floor(frameVersion / 1000) || stream.updated_at || 0}`)} /> : <span className="uav-thumb-pending">连接中</span>}
              <span><Waves size={11} /> {CAMERA_LABELS[direction]}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

function InteractiveGazeboViewer({ gui, runtimeState, onStart, onStop, busy }) {
  if (runtimeState !== "running") {
    return (
      <div className="uav-viewer-pending" role="status">
        <div className="uav-viewer-pending-orb"><MonitorUp size={24} /></div>
        <strong>交互式 Gazebo 视图随仿真启动</strong>
        <span>先启动 PX4/Gazebo，随后可在此页面直接使用第三人称和自由相机。</span>
      </div>
    );
  }
  if (gui?.state === "online") {
    return (
      <div className="uav-gazebo-gui" aria-label="内嵌的原生 Gazebo 交互式三维视图">
        <iframe title="Gazebo 原生交互式三维视图" src={uavSimulationGuiUrl(gui.embed_url)} allow="clipboard-read; clipboard-write" />
        <button className="uav-gui-stop" type="button" onClick={onStop} disabled={busy}>
          <CircleStop size={13} /> 关闭交互视图
        </button>
      </div>
    );
  }
  const starting = gui?.state === "starting";
  return (
    <div className="uav-viewer-pending" role="status">
      <div className="uav-viewer-pending-orb"><MonitorUp size={24} className={starting ? "uav-spin" : ""} /></div>
      <strong>{starting ? "正在启动服务器原生 Gazebo GUI…" : "打开交互式 Gazebo 三维视图"}</strong>
      <span>GUI 在 3090 的隔离图形会话中渲染，并直接嵌入当前 SpectrumClaw 页面。</span>
      {!starting && <button className="btn" type="button" onClick={onStart} disabled={busy}><MonitorUp size={14} /> 打开交互视图</button>}
    </div>
  );
}

function ManualFlightConsole({ enabled, status, yawInput, onEnable, onTakeoffAndEnable, onDisable, onInput, unavailable }) {
  const pressed = useRef(new Set());
  const sending = useRef(false);
  const queued = useRef(false);
  const yaw = useRef(yawInput);
  yaw.current = yawInput;

  const vector = useCallback(() => {
    const forwardKey = pressed.current.has("KeyW");
    const backwardKey = pressed.current.has("KeyS");
    const leftKey = pressed.current.has("KeyA");
    const rightKey = pressed.current.has("KeyD");
    // Aircraft-style steering: WA / WD is an arcing turn, rather than a
    // diagonal world-axis slide. A/D alone remains a deliberate side-step.
    const turning = forwardKey && leftKey !== rightKey;
    const keyboardYaw = turning ? (rightKey ? 0.78 : -0.78) : 0;
    return {
      forward: turning ? 0.72 : (forwardKey ? 1 : 0) + (backwardKey ? -1 : 0),
      right: turning ? 0 : (rightKey ? 1 : 0) + (leftKey ? -1 : 0),
      up: (pressed.current.has("KeyE") ? 1 : 0) + (pressed.current.has("KeyQ") ? -1 : 0),
      yaw: Math.max(-1, Math.min(1, keyboardYaw + yaw.current)),
    };
  }, []);

  const transmit = useCallback(async () => {
    if (!enabled || sending.current) {
      queued.current = true;
      return;
    }
    sending.current = true;
    try {
      await onInput(vector());
    } finally {
      sending.current = false;
      if (queued.current) {
        queued.current = false;
        void transmit();
      }
    }
  }, [enabled, onInput, vector]);

  useEffect(() => {
    if (!enabled) return undefined;
    const usable = (event) => !event.metaKey && !event.ctrlKey && !event.altKey && ["KeyW", "KeyA", "KeyS", "KeyD", "KeyQ", "KeyE"].includes(event.code);
    const onKeyDown = (event) => {
      if (!usable(event) || ["INPUT", "TEXTAREA", "SELECT"].includes(event.target?.tagName)) return;
      event.preventDefault();
      pressed.current.add(event.code);
      void transmit();
    };
    const onKeyUp = (event) => {
      if (!usable(event)) return;
      event.preventDefault();
      pressed.current.delete(event.code);
      void transmit();
    };
    const onBlur = () => {
      pressed.current.clear();
      void transmit();
    };
    const keepAlive = window.setInterval(() => void transmit(), 80);
    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.clearInterval(keepAlive);
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
      pressed.current.clear();
    };
  }, [enabled, transmit]);

  const grounded = status?.state === "grounded";
  const stateLabel = status?.state === "active"
    ? "OFFBOARD ACTIVE"
    : grounded
      ? "已落地 · 需要起飞"
      : enabled
        ? "正在接管 PX4…"
        : "SAFE HOLD";
  return (
    <section className="card uav-manual-card" aria-label="PX4 仿真遥控台">
      <div className="uav-manual-intro">
        <span className="eyebrow">PX4 SITL · MANUAL OFFBOARD</span>
        <h2><Keyboard size={18} /> 键盘遥控台</h2>
        <p>启用后，浏览器通过低延迟长连接更新受限速度意图，3090 以 50 Hz 驱动 PX4 SITL；W+A 左前转、W+D 右前转，机头与追随实景同步改变方向。</p>
        <div className="uav-manual-status" data-active={enabled ? "true" : "false"}><span className="dot" /> {stateLabel}</div>
        {enabled ? (
          <button className="uav-manual-toggle is-active" type="button" onClick={onDisable}><CircleStop size={14} /> 退出遥控并悬停</button>
        ) : (
          <div className="uav-manual-actions">
            <button className="uav-manual-toggle" type="button" onClick={onTakeoffAndEnable} disabled={unavailable}><Play size={14} /> 起飞 3 m 并启用 WASD</button>
            <button className="uav-manual-toggle subtle" type="button" onClick={onEnable} disabled={unavailable}><Keyboard size={14} /> 仅接管空中无人机</button>
          </div>
        )}
      </div>
      <div className="uav-keyboard-guide" aria-label="键盘控制说明">
        <div className="uav-key-group"><kbd>W</kbd><span>前进</span></div>
        <div className="uav-key-group"><kbd>W+A</kbd><span>左前转</span></div>
        <div className="uav-key-group"><kbd>W+D</kbd><span>右前转</span></div>
        <div className="uav-key-group"><kbd>A</kbd><span>左移</span></div>
        <div className="uav-key-group"><kbd>S</kbd><span>后退</span></div>
        <div className="uav-key-group"><kbd>D</kbd><span>向右</span></div>
        <div className="uav-key-group"><kbd>Q</kbd><span>下降</span></div>
        <div className="uav-key-group"><kbd>E</kbd><span>上升</span></div>
      </div>
    </section>
  );
}

export default function UavSpectrumSimPage({ active = true, onBack, onOpenSystem }) {
  const [data, setData] = useState(() => readSessionJson(UAV_STATUS_CACHE_KEY));
  const [loading, setLoading] = useState(false);
  const [action, setAction] = useState("");
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);
  const [viewerMode, setViewerMode] = useState(initialViewerMode);
  const [spectrumSituation, setSpectrumSituation] = useState(null);
  const [spectrumGrid, setSpectrumGrid] = useState(null);
  const [spectrumLayer, setSpectrumLayer] = useState(4);
  const [followSpectrumHeight, setFollowSpectrumHeight] = useState(true);
  const [spectrumLoading, setSpectrumLoading] = useState(false);
  const [spectrumError, setSpectrumError] = useState("");
  const [selectedTransmitter, setSelectedTransmitter] = useState("all");
  const [vehicleAction, setVehicleAction] = useState("");
  const [manualEnabled, setManualEnabled] = useState(false);
  const [manualYaw, setManualYaw] = useState(0);
  const [manualTransport, setManualTransport] = useState("idle");
  const [agentRun, setAgentRun] = useState(null);
  const [trajectory, setTrajectory] = useState([]);
  const manualSocketRef = useRef(null);
  const manualReconnectTimer = useRef(null);
  const manualSessionTokenRef = useRef("");
  const spectrumLoadedRef = useRef(false);
  const liveSpectrumSequenceRef = useRef(0);
  const statusLoadedRef = useRef(false);
  const { snapshot: liveSnapshot, connection: liveConnection } = useUavSimulationLive(active, 250, viewerMode === "spectrum");

  const refresh = useCallback(async ({ quiet = false } = {}) => {
    if (!quiet) setLoading(true);
    setError("");
    try {
      const next = await fetchUavSpectrumSimStatus();
      setData(next);
      return next;
    } catch (err) {
      setError(err.message || "无法读取仿真运行状态");
      return null;
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  const loadSpectrumSituation = useCallback(async ({ measure = false } = {}) => {
    setSpectrumLoading(true);
    setSpectrumError("");
    try {
      const next = measure ? await refreshUavSpectrumSituation() : await fetchUavSpectrumSituation();
      setSpectrumSituation(next);
      return next;
    } catch (err) {
      setSpectrumError(err.message || "无法读取 Sionna RT 频谱态势");
      return null;
    } finally {
      setSpectrumLoading(false);
    }
  }, []);

  const loadSpectrumGrid = useCallback(async (layer = spectrumLayer, transmitter = selectedTransmitter) => {
    setSpectrumError("");
    try {
      const next = await fetchUavSpectrumGrid(layer, transmitter);
      setSpectrumGrid(next);
      return next;
    } catch (err) {
      setSpectrumError(err.message || "无法读取实时频谱网格");
      return null;
    }
  }, [selectedTransmitter, spectrumLayer]);

  useEffect(() => {
    if (!active || statusLoadedRef.current) return;
    statusLoadedRef.current = true;
    void refresh({ quiet: Boolean(data) });
  }, [active, data, refresh]);

  useEffect(() => {
    if (!data) return;
    try {
      window.sessionStorage.setItem(UAV_STATUS_CACHE_KEY, JSON.stringify(data));
    } catch {
      // The live endpoint remains authoritative when storage is unavailable.
    }
  }, [data]);

  useEffect(() => {
    try {
      window.sessionStorage.setItem(UAV_VIEW_CACHE_KEY, JSON.stringify(viewerMode));
    } catch {
      // Keep the current in-memory selection when storage is unavailable.
    }
  }, [viewerMode]);

  useEffect(() => {
    if (!active || viewerMode !== "spectrum" || spectrumLoadedRef.current) return;
    spectrumLoadedRef.current = true;
    void loadSpectrumSituation();
  }, [active, loadSpectrumSituation, viewerMode]);

  useEffect(() => {
    if (!active || viewerMode !== "spectrum") return;
    void loadSpectrumGrid(spectrumLayer, selectedTransmitter);
  }, [active, loadSpectrumGrid, selectedTransmitter, spectrumLayer, viewerMode]);

  useEffect(() => {
    const live = liveSnapshot?.spectrum;
    if (!live) return;
    if (live.error) setSpectrumError(live.error);
    const sequence = Number(live.sequence || 0);
    const isNewSample = sequence > liveSpectrumSequenceRef.current && Boolean(live.observation);
    if (isNewSample) liveSpectrumSequenceRef.current = sequence;
    setSpectrumSituation((current) => {
      const observation = live.observation || current?.observation;
      const history = [...(current?.history || [])];
      if (isNewSample && live.observation) {
        history.unshift({
          run_id: `sionna-realtime-${sequence}`,
          captured_at: live.captured_at,
          position_m: live.observation.position_m,
          anchors: live.observation.anchors,
        });
      }
      return {
        ...(current || {}),
        ...live,
        observation,
        history: history.slice(0, 16),
      };
    });
    if (!isNewSample || !live.grid_update) return;
    if (followSpectrumHeight && Number(live.grid_update.layer_index) !== spectrumLayer) {
      setSpectrumLayer(Number(live.grid_update.layer_index));
    }
    setSpectrumGrid((current) => applySpectrumGridUpdate(current, live.grid_update));
  }, [followSpectrumHeight, liveSnapshot?.spectrum, spectrumLayer]);

  useEffect(() => {
    if (!active || agentRun?.status !== "running") return undefined;
    void loadSpectrumSituation();
    const timer = window.setInterval(() => { void loadSpectrumSituation(); }, 2000);
    return () => window.clearInterval(timer);
  }, [active, agentRun?.status, loadSpectrumSituation]);

  // The simulator can be restarted outside this page (for example after a
  // backend guard recovery).  Buttons must follow the live WebSocket state,
  // not remain disabled because the initial HTTP status was "stopped".
  const runtime = useMemo(() => {
    const initial = data?.runtime || { state: "stopped" };
    const live = liveSnapshot?.runtime;
    if (!live) return initial;
    return {
      ...initial,
      ...live,
      camera: { ...initial.camera, ...live.camera },
      manual: { ...initial.manual, ...live.manual },
    };
  }, [data?.runtime, liveSnapshot?.runtime]);
  const activeVehicle = liveSnapshot?.vehicle || runtime.camera?.vehicle || null;
  const positionKey = Array.isArray(activeVehicle?.position_m) ? activeVehicle.position_m.map((value) => Number(value).toFixed(2)).join(",") : "";

  useEffect(() => {
    if (!followSpectrumHeight || viewerMode !== "spectrum") return;
    const altitude = Number(activeVehicle?.position_m?.[2]);
    if (!Number.isFinite(altitude)) return;
    const nextLayer = Math.max(0, Math.min(100, Math.floor(Math.max(0, altitude) / 5)));
    setSpectrumLayer((current) => current === nextLayer ? current : nextLayer);
  }, [activeVehicle?.position_m, followSpectrumHeight, positionKey, viewerMode]);

  // A bounded browser-side trace is enough for the situation panel. It is
  // derived only from the live Gazebo telemetry already delivered to the page,
  // never from a second simulation/control channel.
  useEffect(() => {
    if (!positionKey || runtime.state !== "running") return;
    const [x, y, z] = activeVehicle.position_m.map(Number);
    if (![x, y, z].every(Number.isFinite)) return;
    setTrajectory((current) => {
      const previous = current.at(-1);
      const moved = !previous || Math.hypot(previous.x - x, previous.y - y, previous.z - z) > 1.1;
      const elapsed = !previous || Date.now() - previous.at > 1500;
      if (!moved && !elapsed) return current;
      return [...current, { x, y, z, at: Date.now() }].slice(-40);
    });
  }, [activeVehicle, positionKey, runtime.state]);

  // A simulator restart invalidates any old browser socket.  Drop local
  // control immediately so it cannot reconnect and write stale zero inputs
  // into a newly started PX4 bridge.
  useEffect(() => {
    if (runtime.state === "running" && runtime.manual?.bridge_running) return;
    if (manualEnabled) {
      manualSocketRef.current?.close();
      manualSocketRef.current = null;
      manualSessionTokenRef.current = "";
      setManualYaw(0);
      setManualEnabled(false);
    }
  }, [runtime.state, runtime.manual?.bridge_running, manualEnabled]);
  const canStart = Boolean(data?.environment_ready) && runtime.state !== "running";

  async function runAction(kind) {
    setAction(kind);
    setError("");
    try {
      const next = kind === "start" ? await startUavSpectrumSim() : await stopUavSpectrumSim();
      setData(next);
      if (kind === "start") {
        window.setTimeout(() => refresh({ quiet: true }), 1800);
      }
    } catch (err) {
      setError(err.message || "仿真控制请求失败");
    } finally {
      setAction("");
    }
  }

  async function runGuiAction(kind) {
    setAction(`gui-${kind}`);
    setError("");
    try {
      const next = kind === "start" ? await startUavSpectrumSimGui() : await stopUavSpectrumSimGui();
      setData(next);
      if (kind === "start") {
        window.setTimeout(() => refresh({ quiet: true }), 1400);
        window.setTimeout(() => refresh({ quiet: true }), 3200);
      }
    } catch (err) {
      setError(err.message || "Gazebo 交互视图控制失败");
    } finally {
      setAction("");
    }
  }

  async function runVehicleAction(kind) {
    setVehicleAction(kind);
    setError("");
    try {
      await controlUavSimulation(kind, kind === "takeoff" ? { altitude_m: 3 } : {});
      window.setTimeout(() => refresh({ quiet: true }), 650);
    } catch (err) {
      setError(err.message || "无人机仿真控制失败");
    } finally {
      setVehicleAction("");
    }
  }

  const enableManualControl = useCallback(async () => {
    setError("");
    try {
      const result = await enableUavManualControl();
      manualSessionTokenRef.current = result.session_token || "";
      if (!manualSessionTokenRef.current) throw new Error("服务器未返回有效遥控会话");
      setManualYaw(0);
      setManualEnabled(true);
      window.setTimeout(() => refresh({ quiet: true }), 500);
    } catch (err) {
      setError(err.message || "无法启用 PX4 遥控桥");
    }
  }, [refresh]);

  const waitForAltitude = useCallback(async (targetAltitude) => {
    const deadline = Date.now() + 25_000;
    while (Date.now() < deadline) {
      const next = await refresh({ quiet: true });
      const altitude = next?.runtime?.camera?.vehicle?.position_m?.[2];
      if (Number.isFinite(altitude) && altitude >= targetAltitude - 0.4) return;
      await new Promise((resolve) => window.setTimeout(resolve, 250));
    }
    throw new Error("PX4 未在限定时间内到达 3 m；未启用 WASD 遥控");
  }, [refresh]);

  const takeoffAndEnableManual = useCallback(async () => {
    setVehicleAction("manual-takeoff");
    setError("");
    try {
      // Explicitly clear a previous browser lease before asking the PX4
      // commander to take off.  Manual Offboard begins only after takeoff.
      await disableUavManualControl();
      manualSocketRef.current?.close();
      manualSocketRef.current = null;
      setManualEnabled(false);
      await controlUavSimulation("takeoff", { altitude_m: 3 });
      await waitForAltitude(3);
      const result = await enableUavManualControl();
      manualSessionTokenRef.current = result.session_token || "";
      if (!manualSessionTokenRef.current) throw new Error("服务器未返回有效遥控会话");
      setManualYaw(0);
      setManualEnabled(true);
    } catch (err) {
      setError(err.message || "无法起飞并启用 WASD 遥控");
      setManualEnabled(false);
    } finally {
      setVehicleAction("");
    }
  }, [waitForAltitude]);

  useEffect(() => {
    if (!manualEnabled) {
      manualSocketRef.current?.close();
      manualSocketRef.current = null;
      window.clearTimeout(manualReconnectTimer.current);
      setManualTransport("idle");
      return undefined;
    }

    let disposed = false;
    let socket = null;
    const connect = () => {
      if (disposed) return;
      setManualTransport("connecting");
      socket = new WebSocket(uavManualControlLiveUrl(manualSessionTokenRef.current));
      manualSocketRef.current = socket;
      socket.onopen = () => {
        if (!disposed) setManualTransport("websocket");
      };
      socket.onerror = () => socket.close();
      socket.onclose = () => {
        if (manualSocketRef.current === socket) manualSocketRef.current = null;
        if (!disposed) {
          setManualTransport("fallback");
          manualReconnectTimer.current = window.setTimeout(connect, 700);
        }
      };
    };
    connect();
    return () => {
      disposed = true;
      window.clearTimeout(manualReconnectTimer.current);
      if (manualSocketRef.current === socket) manualSocketRef.current = null;
      socket?.close();
    };
  }, [manualEnabled]);

  const updateManualControl = useCallback(async (vector) => {
    const socket = manualSocketRef.current;
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify(vector));
      return;
    }
    try {
      await updateUavManualControl({ ...vector, sessionToken: manualSessionTokenRef.current });
    } catch (err) {
      setError(err.message || "PX4 遥控指令发送失败");
      setManualEnabled(false);
    }
  }, []);

  const disableManualControl = useCallback(async () => {
    setError("");
    // Release the local input listener immediately.  The backend independently
    // clears its short-lived lease, so a slow hover acknowledgement cannot
    // leave the UI or the agent panel falsely occupied.
    manualSocketRef.current?.close();
    manualSocketRef.current = null;
    window.clearTimeout(manualReconnectTimer.current);
    setManualYaw(0);
    manualSessionTokenRef.current = "";
    setManualEnabled(false);
    try {
      await disableUavManualControl();
    } catch (err) {
      setError(err.message || "遥控已在本地释放，但服务器悬停确认失败；请检查运行状态");
    } finally {
      window.setTimeout(() => refresh({ quiet: true }), 350);
    }
  }, [refresh]);

  async function copyDebugAddress() {
    try {
      await navigator.clipboard.writeText("ws://127.0.0.1:8765");
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setError("无法自动复制，请手动使用 ws://127.0.0.1:8765");
    }
  }

  const activeCamera = liveSnapshot?.runtime?.camera || runtime.camera;
  const activeLidar = activeCamera?.lidar;
  const flightControlOverlay = (
    <FlightControlOverlay
      enabled={manualEnabled}
      status={liveSnapshot?.runtime?.manual || runtime.manual}
      transport={manualTransport}
      onEnable={enableManualControl}
      onDisable={disableManualControl}
      onInput={updateManualControl}
      yawInput={manualYaw}
      unavailable={runtime.state !== "running" || !runtime.manual?.bridge_running}
    />
  );

  return (
    <main className="page uav-sim-page">
      <header className="page-head uav-sim-head">
        <div className="title-block">
          <span className="label">Module · UAV Spectrum Simulation</span>
          <div className="uav-title-line">
            <h1>无人机仿真与智能体控制</h1>
            <RuntimeBadge state={runtime.state} />
          </div>
          <p className="lede">PX4/Gazebo 与飞控运行在 3090；本地浏览器直接渲染真实位姿、五路机载相机和智能体控制状态。</p>
        </div>
        <PageToolbar active={active}><div className="actions uav-head-actions">
          <button className="btn ghost" type="button" onClick={onBack}><ArrowLeft size={14} /> 返回 Console</button>
          <button className="btn ghost" type="button" onClick={() => refresh()} disabled={loading || Boolean(action)} aria-label="刷新仿真状态">
            <RefreshCw size={14} className={loading ? "uav-spin" : ""} /> 刷新状态
          </button>
          {runtime.state === "running" ? (
            <button className="btn danger" type="button" onClick={() => runAction("stop")} disabled={Boolean(action)}>
              <CircleStop size={14} /> {action === "stop" ? "停止中…" : "停止仿真"}
            </button>
          ) : (
            <button className="btn" type="button" onClick={() => runAction("start")} disabled={!canStart || Boolean(action)}>
              <Play size={14} /> {action === "start" ? "启动中…" : "启动仿真"}
            </button>
          )}
        </div></PageToolbar>
      </header>

      {error && <div className="uav-alert" role="alert"><AlertTriangle size={16} /><span>{error}</span><button type="button" onClick={() => refresh()}>重试</button></div>}

      <section className="uav-status-strip" aria-label="仿真状态">
        <span data-tone={runtime.state === "running" ? "ok" : "muted"}><Activity size={13} /> PX4 / Gazebo · {runtime.state === "running" ? "运行中" : "待命"}</span>
        <span data-tone={spectrumSituation?.current ? "ok" : spectrumSituation?.available ? "warn" : "muted"}><Radio size={13} /> Sionna RT · {spectrumSituation?.current ? "当前样本" : spectrumSituation?.available ? "待更新" : "未测量"}</span>
        <span data-tone={runtime.manual?.enabled ? "warn" : "ok"}><Keyboard size={13} /> 飞控 · {runtime.manual?.enabled ? "人工接管" : "智能体可用"}</span>
        <button className="uav-status-system" type="button" onClick={() => setViewerMode("gui")}><ServerCog size={13} /> 3090 · {data?.environment_ready ? "环境就绪" : "需要检查"}</button>
      </section>

      <UavModeNavigation
        value={viewerMode}
        onChange={setViewerMode}
        runtimeState={runtime.state}
        spectrumCurrent={Boolean(spectrumSituation?.current)}
        liveConnection={liveConnection}
      />

      <section
        key={viewerMode}
        id={`uav-panel-${viewerMode}`}
        className={`uav-mode-panel is-${viewerMode}`}
        role="tabpanel"
        aria-labelledby={`uav-mode-${viewerMode}`}
      >
        {viewerMode === "observe" && (
          <div className="uav-flight-layout">
            <section className="card uav-primary-stage">
              <header className="uav-workbench-head">
                <div><span className="eyebrow">FLIGHT CONTROL · LIVE</span><h2><Navigation size={18} /> 实景飞控台</h2><p>Gazebo 追随视角、五路机载相机、LiDAR 与 PX4 控制保持在同一操作面。</p></div>
                <span className="pill" data-tone={liveConnection === "online" ? "ok" : runtime.state === "running" ? "warn" : "muted"}><span className="dot" /> {liveConnection === "online" ? "LIVE LINK" : runtime.state === "running" ? "RECONNECTING" : "SIM STANDBY"}</span>
              </header>
              <div className="uav-stage-canvas">
                <GazeboObserver camera={runtime.camera} liveCamera={liveSnapshot?.runtime?.camera} lidar={activeLidar} runtimeState={runtime.state} controlOverlay={flightControlOverlay} manualEnabled={manualEnabled} onYawInput={setManualYaw} />
              </div>
              <div className="uav-map-note"><InfoMark /> 中间为追随实景主画面；下方相机缩略图可无缝切换。手动飞控、任务智能体与实时日志共享同一运行状态。</div>
              <FlightControlDock
                onVehicleAction={runVehicleAction}
                unavailable={runtime.state !== "running" || !runtime.manual?.bridge_running || Boolean(vehicleAction)}
                missionRun={agentRun}
                vehicleAction={vehicleAction}
                manualActive={manualEnabled || Boolean(runtime.manual?.enabled)}
              />
            </section>
            <aside className="uav-flight-rail" aria-label="智能体任务与任务态势">
              <UavAgentPanel manualActive={manualEnabled || Boolean(runtime.manual?.enabled)} onRunChange={setAgentRun} />
              <UavMissionSituation scene={data?.scene} vehicle={activeVehicle} trajectory={trajectory} run={agentRun} lidar={activeLidar} />
            </aside>
          </div>
        )}

        {viewerMode === "spectrum" && (
          <div className="uav-spectrum-mode">
            <div className="uav-spectrum-balance">
              <section className="card uav-primary-stage uav-spectrum-3d-stage">
                <header className="uav-workbench-head">
                  <div><span className="eyebrow">SIONNA RT · 3D PROPAGATION</span><h2><Waves size={18} /> 三维传播仿真</h2><p>真实无人机位姿、发射源与射线路径在本地 WebGL 场景中同步渲染。</p></div>
                  <span className="pill" data-tone={spectrumSituation?.current ? "ok" : spectrumLoading ? "warn" : "muted"}><span className="dot" /> {spectrumLoading ? "COMPUTING" : spectrumSituation?.current ? "RF CURRENT" : "WAITING SAMPLE"}</span>
                </header>
                <div className="uav-stage-canvas">
                  <Suspense fallback={<div className="uav-viewer-pending"><strong>正在载入三维电磁场景</strong><span>初始化本地 WebGL 渲染器…</span></div>}>
                    <UavSceneCanvas
                      vehicle={activeVehicle}
                      connection={liveConnection}
                      controlOverlay={flightControlOverlay}
                      spectrumSituation={spectrumSituation}
                      transmitters={data?.scene?.transmitters}
                      selectedTransmitter={selectedTransmitter}
                      onSelectTransmitter={setSelectedTransmitter}
                    />
                  </Suspense>
                </div>
                <div className="uav-map-note"><InfoMark /> 三维画面只叠加 Sionna RT 返回的真实传播路径；无人机跨越测量阈值后会自动更新当前位置的链路功率。</div>
              </section>

              <UavSpectrumLayerMap
                scene={data?.scene}
                vehicle={activeVehicle}
                situation={spectrumSituation}
                grid={spectrumGrid}
                selectedTransmitter={selectedTransmitter}
                layerIndex={spectrumLayer}
                followHeight={followSpectrumHeight}
                loading={spectrumLoading}
                error={spectrumError}
                onSelectTransmitter={setSelectedTransmitter}
                onSelectLayer={(layer) => { setFollowSpectrumHeight(false); setSpectrumLayer(layer); }}
                onFollowHeight={setFollowSpectrumHeight}
                onRefresh={() => loadSpectrumSituation({ measure: true })}
              />
            </div>
          </div>
        )}

        {viewerMode === "gui" && (
          <div className="uav-diagnostics-layout">
            <section className="card uav-primary-stage uav-gui-stage">
              <header className="uav-workbench-head">
                <div><span className="eyebrow">GAZEBO · NATIVE GUI</span><h2><MonitorUp size={18} /> 图形诊断台</h2><p>按需打开 3090 隔离图形会话，用于自由相机、场景检查和故障定位。</p></div>
                <span className="pill" data-tone={runtime.gui?.state === "online" ? "ok" : "muted"}><span className="dot" /> {runtime.gui?.state === "online" ? "GUI ONLINE" : "ON DEMAND"}</span>
              </header>
              <div className="uav-stage-canvas"><InteractiveGazeboViewer gui={runtime.gui} runtimeState={runtime.state} busy={Boolean(action)} onStart={() => runGuiAction("start")} onStop={() => runGuiAction("stop")} /></div>
              <div className="uav-map-note"><InfoMark /> 原生 Gazebo GUI 是诊断入口，不影响飞控页的实时相机和任务状态；关闭后仿真核心仍可继续运行。</div>
            </section>
            <UavDiagnosticsPanel data={data} runtime={runtime} liveConnection={liveConnection} copied={copied} onCopy={copyDebugAddress} onOpenSystem={onOpenSystem} />
          </div>
        )}
      </section>
    </main>
  );
}

function InfoMark() {
  return <span className="uav-info-mark" aria-hidden="true">i</span>;
}
