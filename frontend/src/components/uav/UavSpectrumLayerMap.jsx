import { useMemo, useState } from "react";
import { Activity, Clock3, Eye, EyeOff, Grid2x2, Layers3, Navigation, Play, Radio, RefreshCw, Route, Signal } from "lucide-react";
import { spectrumColor, spectrumColorRange, spectrumEstimatedSources, spectrumGridCells, spectrumMeasurementTrack } from "../../lib/spectrumGrid.js";
import { rayDisplayPoints } from "../../lib/spectrumRays.js";

const MAP_RANGE_M = 60;
const LAYERS = [0, 1, 2, 3, 4, 5];
const RAY_COLORS = ["#f7c948", "#48d8ff", "#b787ff", "#ff7a9f", "#64e7a3", "#ff9f43", "#83a7ff"];

function mapPoint([east = 0, north = 0]) {
  return [
    ((Number(east) + MAP_RANGE_M) / (MAP_RANGE_M * 2)) * 100,
    100 - ((Number(north) + MAP_RANGE_M) / (MAP_RANGE_M * 2)) * 100,
  ];
}

function pointString(points) {
  return points.map((point) => mapPoint(point).join(",")).join(" ");
}

function pathColor(path, anchorId) {
  const key = `${anchorId || ""}:${path.id || ""}`;
  const index = [...key].reduce((total, character) => total + character.charCodeAt(0), 0) % RAY_COLORS.length;
  return RAY_COLORS[index];
}

function dbmLabel(value) {
  return Number.isFinite(Number(value)) ? `${Number(value).toFixed(1)} dBm` : "—";
}

function ageLabel(age) {
  if (!Number.isFinite(Number(age))) return "等待样本";
  return Number(age) < 60 ? `${Math.round(Number(age))} 秒前` : `${Math.floor(Number(age) / 60)} 分钟前`;
}

export default function UavSpectrumLayerMap({
  scene,
  vehicle,
  situation,
  grid,
  selectedTransmitter = "all",
  layerIndex = 4,
  followHeight = true,
  compact = false,
  loading = false,
  error = "",
  survey = null,
  surveyStarting = false,
  surveyDisabled = false,
  onSelectTransmitter,
  onSelectLayer,
  onFollowHeight,
  onRefresh,
  onStartSurvey,
}) {
  const [showRays, setShowRays] = useState(true);
  const objects = Array.isArray(scene?.objects) ? scene.objects : [];
  const transmitters = Array.isArray(scene?.transmitters) ? scene.transmitters : [];
  const anchors = Array.isArray(situation?.observation?.anchors) ? situation.observation.anchors : [];
  const paths = useMemo(() => anchors
    .filter((anchor) => selectedTransmitter === "all" || anchor.id === selectedTransmitter)
    .flatMap((anchor) => (anchor.ray_paths || []).map((path) => ({ ...path, anchorId: anchor.id }))), [anchors, selectedTransmitter]);
  const [rows = 30, columns = 30] = grid?.shape || [30, 30];
  const cellWidth = 100 / Math.max(1, columns);
  const cellHeight = 100 / Math.max(1, rows);
  const cells = useMemo(() => spectrumGridCells(grid), [grid]);
  const colorRange = useMemo(() => spectrumColorRange(grid), [grid]);
  const vehiclePosition = Array.isArray(vehicle?.position_m) ? vehicle.position_m : situation?.current_position_m;
  const measurementTrack = useMemo(
    () => spectrumMeasurementTrack(situation, layerIndex, selectedTransmitter),
    [layerIndex, selectedTransmitter, situation?.measurement_track],
  );
  const [vehicleX, vehicleY] = vehiclePosition ? mapPoint(vehiclePosition) : [50, 50];
  const layerRange = grid?.height_range_m || [layerIndex * 5, (layerIndex + 1) * 5];
  const computing = Boolean(situation?.computing);
  const currentUpdate = situation?.grid_update?.layer_index === layerIndex ? situation.grid_update : null;
  const availableTransmitters = Array.isArray(grid?.available_transmitters) && grid.available_transmitters.length
    ? grid.available_transmitters
    : transmitters.map((transmitter) => transmitter.id).filter(Boolean);
  const visibleAnchors = selectedTransmitter === "all" ? anchors : anchors.filter((anchor) => anchor.id === selectedTransmitter);
  const strongestPower = visibleAnchors
    .map((anchor) => Number(anchor.received_power_dbm))
    .filter(Number.isFinite)
    .reduce((strongest, value) => Math.max(strongest, value), Number.NEGATIVE_INFINITY);
  const frequency = Number(situation?.observation?.frequency_hz);
  const reconstructionReady = Boolean(grid?.reconstruction?.ready);
  const estimatedSources = useMemo(
    () => spectrumEstimatedSources(grid, selectedTransmitter),
    [grid, selectedTransmitter],
  );
  const displayedSources = reconstructionReady && estimatedSources.length ? estimatedSources : transmitters;
  const surveyRunning = survey?.state === "running" || survey?.state === "draining";
  const surveyCompleted = survey?.state === "completed";
  const surveyProgress = Math.min(100, (Number(survey?.samples_collected || 0) / Math.max(1, Number(survey?.planned_waypoints || 7))) * 100);

  return (
    <section className={`uav-spectrum-layer-map${compact ? " is-compact" : ""}`} aria-label="实时电磁强度高度层地图">
      <header className="uav-spectrum-layer-head">
        <div>
          <span className="eyebrow">LIVE SPECTRUM SITUATION · LOCAL ENU</span>
          <h2><Grid2x2 size={17} /> 电磁频谱态势</h2>
          <p>{rows} × {columns} 网格 · {grid?.cell_size_m ?? 4} m/格 · Z {Number(layerRange[0]).toFixed(0)}–{Number(layerRange[1]).toFixed(0)} m</p>
        </div>
        <span className="uav-spectrum-compute-state" data-state={computing ? "running" : situation?.current ? "current" : "idle"}>
          <Activity size={12} /> {computing ? "GPU 射线计算中" : situation?.current ? "实时采集中" : "等待位姿变化"}
        </span>
      </header>

      <div className="uav-spectrum-layer-toolbar">
        <label className="uav-spectrum-source-select">
          <span>信号源</span>
          <select value={selectedTransmitter} onChange={(event) => onSelectTransmitter?.(event.target.value)}>
            <option value="all">总 RF 功率</option>
            {availableTransmitters.map((transmitterId) => <option key={transmitterId} value={transmitterId}>{transmitterId} RSS</option>)}
          </select>
        </label>
        <div className="uav-spectrum-layer-buttons" role="group" aria-label="高度层">
          {LAYERS.map((layer) => (
            <button key={layer} type="button" className={layerIndex === layer ? "active" : ""} onClick={() => onSelectLayer?.(layer)}>
              Z{layer} <small>{layer * 5}–{(layer + 1) * 5}m</small>
            </button>
          ))}
        </div>
        <button type="button" className={followHeight ? "active" : ""} onClick={() => onFollowHeight?.(!followHeight)}><Layers3 size={12} /> 跟随无人机高度</button>
        <button type="button" className={showRays ? "active" : ""} onClick={() => setShowRays((value) => !value)}>{showRays ? <Eye size={12} /> : <EyeOff size={12} />} 射线证据</button>
      </div>

      <div className="uav-spectrum-layer-canvas">
        <svg viewBox="0 0 100 100" preserveAspectRatio="xMidYMid meet">
          <defs>
            <pattern id="live-rem-grid" width={cellWidth} height={cellHeight} patternUnits="userSpaceOnUse">
              <path d={`M ${cellWidth} 0 L 0 0 0 ${cellHeight}`} fill="none" stroke="currentColor" strokeWidth=".12" />
            </pattern>
          </defs>
          <rect className="uav-rem-unknown" width="100" height="100" />
          <path className="uav-spectrum-road" d="M0 50 H100 M50 0 V100" />
          {cells.map((cell) => (
            <rect
              key={`${cell.row}-${cell.column}`}
              className={`uav-rem-measured-cell ${cell.measured ? "is-measured" : "is-estimated"}`}
              x={cell.column * cellWidth}
              y={cell.row * cellHeight}
              width={cellWidth}
              height={cellHeight}
              fill={spectrumColor(cell.value, colorRange.min, colorRange.max, cell.measured ? 0.96 : 0.84)}
            >
              <title>{`cell [${cell.row}, ${cell.column}] · ${Number(cell.value).toFixed(2)} dBm · ${cell.measured ? "无人机实测" : "盲源定位 + 残差插值"}`}</title>
            </rect>
          ))}
          <rect className="uav-rem-grid-lines" width="100" height="100" fill="url(#live-rem-grid)" />
          {objects.map((object) => {
            const [x, y] = mapPoint(object.position_m || []);
            const [width, depth] = object.size_m || [8, 8];
            return <rect key={object.id} className="uav-rem-building" x={x - width / 2.4} y={y - depth / 2.4} width={width / 1.2} height={depth / 1.2} rx=".6" />;
          })}
          {measurementTrack.length > 1 && <polyline className="uav-rem-measurement-track" points={pointString(measurementTrack.map((item) => item.position_m))} />}
          {measurementTrack.map((item) => {
            const [x, y] = mapPoint(item.position_m);
            return <circle key={`measurement-${item.sequence}`} className="uav-rem-measurement-point" cx={x} cy={y} r=".48"><title>{`实测网格 [${item.row}, ${item.column}] · ${item.value.toFixed(2)} dBm`}</title></circle>;
          })}
          {showRays && paths.map((path) => <polyline key={`${path.anchorId}-${path.id}`} className="uav-rem-live-ray" points={pointString(rayDisplayPoints(path, vehiclePosition))} style={{ stroke: pathColor(path, path.anchorId) }} />)}
          {displayedSources.map((transmitter) => {
            const [x, y] = mapPoint(transmitter.position_m || []);
            const active = selectedTransmitter === "all" || selectedTransmitter === transmitter.id;
            const estimated = Object.hasOwn(transmitter, "rmse_db");
            return <g key={transmitter.id} transform={`translate(${x} ${y})`} className="uav-rem-transmitter" data-active={active} data-estimated={estimated}><circle r="2.1" /><path d="M-2.8 0H2.8M0-2.8V2.8" /><title>{estimated ? `${transmitter.id} RSS 盲估位置 · RMSE ${transmitter.rmse_db.toFixed(2)} dB` : transmitter.id}</title></g>;
          })}
          {currentUpdate && <rect className="uav-rem-current-cell" x={currentUpdate.column * cellWidth} y={currentUpdate.row * cellHeight} width={cellWidth} height={cellHeight} />}
          {vehiclePosition && <g transform={`translate(${vehicleX} ${vehicleY})`} className="uav-rem-vehicle"><circle r="2.8" /><path d="M0 -2.4 L1.2 0 L2.4 1.2 L.7 1.2 L0 2.4 L-.7 1.2 L-2.4 1.2 L-1.2 0 Z" /></g>}
        </svg>
        <div className="uav-rem-map-hud top-left"><Radio size={11} /> {reconstructionReady ? "盲源定位 + 残差插值" : selectedTransmitter === "all" ? "总 RF 功率" : `${selectedTransmitter} RSS`}</div>
        <div className="uav-rem-map-hud top-right"><Route size={11} /> {measurementTrack.length} 个航迹实测格 · {paths.length} 条拓扑</div>
        <div className="uav-rem-colorbar"><span>{colorRange.min.toFixed(1)} dBm</span><i /><span>{colorRange.max.toFixed(1)} dBm</span></div>
        {(loading || error || !cells.length) && <div className="uav-rem-empty-layer"><strong>{loading ? "正在加载高度层" : error ? "高度层读取失败" : "当前高度层尚无测量格"}</strong><span>{error || (loading ? "正在同步 3090 上的实时网格…" : "无人机进入该层并移动后，Sionna RT 观测会实时写入网格。")}</span></div>}
      </div>

      <div className="uav-spectrum-survey-control" data-state={survey?.state || "idle"}>
        <div className="uav-spectrum-survey-copy">
          <span><Navigation size={13} /> Z4 A* 避障航线采样</span>
          <strong>{surveyRunning ? survey?.message || "无人机正在沿避障航线采样" : surveyCompleted ? "采样完成 · 无位置先验态势已生成" : survey?.error || `${survey?.planned_waypoints || "—"} 个避障航点 · Z4 内部 21 m`}</strong>
          <i><b style={{ width: `${surveyRunning || surveyCompleted ? surveyProgress : 0}%` }} /></i>
        </div>
        <button type="button" onClick={onStartSurvey} disabled={surveyStarting || surveyRunning || surveyDisabled}>
          {surveyStarting || surveyRunning ? <Activity size={13} className="uav-spin" /> : <Play size={13} />}
          {surveyStarting ? "正在启动…" : surveyRunning ? `${survey?.samples_collected || 0} 个样本` : surveyCompleted ? "重新采样并重建" : "开始飞行采样"}
        </button>
      </div>

      <div className="uav-spectrum-evidence-strip" aria-label="当前频谱态势摘要">
        <div><Signal size={13} /><span>最强链路</span><strong>{dbmLabel(Number.isFinite(strongestPower) ? strongestPower : null)}</strong></div>
        <div><Route size={13} /><span>传播证据</span><strong>{paths.length} 条路径</strong></div>
        <div><Radio size={13} /><span>工作频点</span><strong>{Number.isFinite(frequency) ? `${(frequency / 1e9).toFixed(2)} GHz` : "2.40 GHz"}</strong></div>
        <div><Clock3 size={13} /><span>样本时效</span><strong>{ageLabel(situation?.age_s)}</strong></div>
        <button type="button" onClick={onRefresh} disabled={loading}><RefreshCw size={13} className={loading ? "uav-spin" : ""} /> {loading ? "更新中…" : "更新当前态势"}</button>
      </div>

      <footer className="uav-spectrum-layer-stats">
        <span><b>{grid?.observed_cells ?? 0}</b> / {rows * columns} 已测网格</span>
        <span><b>{((grid?.reconstruction?.coverage_ratio ?? grid?.coverage_ratio ?? 0) * 100).toFixed(2)}%</b> {reconstructionReady ? "融合态势覆盖" : "实测覆盖率"}</span>
        <span><b>{grid?.sample_count ?? 0}</b> 有效样本</span>
        <span><b>{grid?.min_dbm == null ? "—" : Number(grid.min_dbm).toFixed(1)}</b> 至 <b>{grid?.max_dbm == null ? "—" : Number(grid.max_dbm).toFixed(1)}</b> dBm</span>
      </footer>
    </section>
  );
}
