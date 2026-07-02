import { useEffect, useMemo, useRef, useState } from "react";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  BarChart3,
  GitBranch,
  Grid2x2,
  Layers3,
  MapPinned,
  Play,
  Route,
  Square
} from "lucide-react";
import { fetchUavRemOverview, runSpectrumConstruction } from "../lib/api.js";
import { usePersistentState } from "../lib/usePersistentState.js";

const RESOLUTIONS = [32, 64, 128, 224];
const MODULES = [
  { id: "genspectra", label: "GenSpectra" },
  { id: "uav_rem", label: "UAV REM" },
  { id: "benchmarks", label: "算法对比" }
];
const REM_VIEWS = [
  { id: "ground_truth", label: "真实 REM" },
  { id: "sampled", label: "稀疏采样" },
  { id: "reconstruction", label: "重建图" },
  { id: "error", label: "误差图" }
];

function formatDbm(value) {
  if (typeof value !== "number") return "--";
  return `${value.toFixed(2)} dBm`;
}

function formatRmse(value) {
  if (typeof value !== "number") return "--";
  return `${value.toFixed(3)} dB`;
}

function formatPercent(value) {
  if (typeof value !== "number") return "--";
  return `${(value * 100).toFixed(value < 0.01 ? 2 : 1)}%`;
}

function inferenceLabel(status) {
  switch (status) {
    case "ready":
      return "GenSpectra ready";
    case "partial":
      return "GenSpectra partial";
    case "failed":
      return "GenSpectra failed";
    case "inference_disabled":
      return "GenSpectra preview ready";
    default:
      return "GenSpectra pending";
  }
}

function statusTone(status) {
  if (status === "ready") return "ok";
  if (status === "partial") return "info";
  return "warn";
}

function colorForValue(value, min, max) {
  if (value == null || !Number.isFinite(value)) return [21, 27, 36, 255];
  const t = Math.max(0, Math.min(1, (value - min) / Math.max(1e-6, max - min)));
  const stops = [
    [18, 32, 68],
    [19, 111, 145],
    [42, 172, 126],
    [225, 176, 68],
    [226, 82, 58]
  ];
  const scaled = t * (stops.length - 1);
  const idx = Math.min(stops.length - 2, Math.floor(scaled));
  const local = scaled - idx;
  const a = stops[idx];
  const b = stops[idx + 1];
  return [
    Math.round(a[0] + (b[0] - a[0]) * local),
    Math.round(a[1] + (b[1] - a[1]) * local),
    Math.round(a[2] + (b[2] - a[2]) * local),
    255
  ];
}

function HeatmapCanvas({ matrix, metrics }) {
  const ref = useRef(null);

  useEffect(() => {
    if (!matrix?.length || !ref.current) return;
    const canvas = ref.current;
    const size = matrix.length;
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext("2d");
    const image = ctx.createImageData(size, size);
    const min = metrics?.min_dbm ?? 0;
    const max = metrics?.max_dbm ?? 1;

    for (let y = 0; y < size; y += 1) {
      for (let x = 0; x < size; x += 1) {
        const [r, g, b, a] = colorForValue(matrix[y][x], min, max);
        const offset = (y * size + x) * 4;
        image.data[offset] = r;
        image.data[offset + 1] = g;
        image.data[offset + 2] = b;
        image.data[offset + 3] = a;
      }
    }
    ctx.putImageData(image, 0, 0);
  }, [matrix, metrics]);

  return <canvas ref={ref} className="heatmap-canvas" aria-label="Spectrum Construction heatmap" />;
}

function PathMarkers({ points }) {
  if (!points?.length) return null;
  return (
    <>
      {points.map((point, index) => (
        <span
          key={`${point[0]}-${point[1]}-${index}`}
          className="sc-path-point"
          style={{ left: `${point[0]}%`, top: `${point[1]}%` }}
          title={`Path ${index + 1}`}
        />
      ))}
    </>
  );
}

export default function SituationBuildingPage({ active = true, onBack }) {
  const [activeModule, setActiveModule] = usePersistentState("sc_sb_module", "genspectra");
  const [seed, setSeed] = usePersistentState("sc_sb_seed", 7);
  const [activeResolution, setActiveResolution] = usePersistentState("sc_sb_resolution", 64);
  const [viewMode, setViewMode] = usePersistentState("sc_sb_viewmode", "original");
  const [result, setResult] = usePersistentState("sc_sb_result", null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const [remData, setRemData] = useState(null);
  const [remLoading, setRemLoading] = useState(false);
  const [remError, setRemError] = useState("");
  const [remSceneId, setRemSceneId] = usePersistentState("sc_sb_rem_scene", 148);
  const [remHeightLayer, setRemHeightLayer] = usePersistentState("sc_sb_rem_layer", 2);
  const [remView, setRemView] = usePersistentState("sc_sb_rem_view", "ground_truth");
  const [remGridMode, setRemGridMode] = usePersistentState("sc_sb_rem_grid", false);

  const activeMap = useMemo(() => {
    return result?.maps?.find((item) => item.resolution === activeResolution) ?? result?.maps?.[0] ?? null;
  }, [activeResolution, result]);

  const activeStatus = activeMap?.inference_status ?? result?.checkpoint_status ?? "pending_checkpoint";
  const canShowReconstruction = Boolean(activeMap?.reconstruction);
  const visibleMatrix =
    viewMode === "masked"
      ? activeMap?.masked
      : viewMode === "reconstruction"
        ? activeMap?.reconstruction
        : activeMap?.original;

  const remScene = remData?.scene ?? null;
  const remMatrix = remScene?.maps?.[remView] ?? null;
  const remMetrics = remView === "error" ? remScene?.error_metrics : remScene?.metrics;

  useEffect(() => {
    if (viewMode === "reconstruction" && activeMap && !activeMap.reconstruction) {
      setViewMode("original");
    }
  }, [activeMap, viewMode]);

  async function generate(nextSeed = seed, runModel = false) {
    setLoading(true);
    setError("");
    const requestedResolutions = runModel ? [activeResolution] : RESOLUTIONS;
    try {
      const data = await runSpectrumConstruction({
        seed: Number(nextSeed) || 0,
        resolutions: requestedResolutions,
        mask_ratio: 0.75,
        enable_inference: runModel,
        tx_power_dbm: [14, 20],
        frequency_hz: 1.4e9,
      });
      const modelMap = runModel ? data.maps?.[0] : null;
      setResult((previous) => {
        if (!runModel || !previous?.maps?.length) return data;
        const byResolution = new Map(previous.maps.map((item) => [item.resolution, item]));
        for (const item of data.maps ?? []) byResolution.set(item.resolution, item);
        return {
          ...previous,
          ...data,
          resolutions: previous.resolutions,
          checkpoint_status: data.checkpoint_status,
          checkpoint_note: data.checkpoint_note,
          maps: RESOLUTIONS.map((resolution) => byResolution.get(resolution)).filter(Boolean),
        };
      });
      if (!data.maps?.some((item) => item.resolution === activeResolution)) {
        setActiveResolution(data.maps?.[0]?.resolution ?? 64);
      }
      if (runModel && modelMap?.resolution != null) {
        setActiveResolution(modelMap.resolution);
      }
      if (runModel && modelMap?.reconstruction) {
        setViewMode("reconstruction");
      } else if (runModel) {
        setError(modelMap?.inference_error || data.checkpoint_note || "GenSpectra 未返回重建地图");
      }
    } catch (err) {
      setError(err.message || "Spectrum Construction 生成失败");
    } finally {
      setLoading(false);
    }
  }

  async function loadRem(nextScene = remSceneId, nextLayer = remHeightLayer, revealRecon = false) {
    setRemLoading(true);
    setRemError("");
    try {
      const data = await fetchUavRemOverview({
        scene_id: Number(nextScene) || 148,
        height_layer: Number(nextLayer) || 0,
        method: "abr",
      });
      setRemData(data);
      // show the original (ground truth) first; only reveal reconstruction on an
      // explicit "run". The reconstruction is precomputed inside the npz, so this
      // is a view switch, not real-time inference.
      if (revealRecon && data.scene?.maps?.reconstruction) {
        setRemGridMode(true);
        setRemView("reconstruction");
      } else {
        setRemGridMode(false);
        setRemView("ground_truth");
      }
    } catch (err) {
      setRemError(err.message || "UAV REM 数据读取失败");
    } finally {
      setRemLoading(false);
    }
  }

  // GenSpectra preview loads once on mount.
  useEffect(() => {
    if (!active || result) return;
    generate(seed);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active]);

  // UAV REM / benchmarks auto-reload when the scene or height layer changes, so
  // picking a scene or Z-layer instantly shows that map (defaulting to original).
  useEffect(() => {
    if (!active) return;
    if (activeModule !== "uav_rem" && activeModule !== "benchmarks") return;
    loadRem(remSceneId, remHeightLayer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, remSceneId, remHeightLayer, activeModule]);

  return (
    <div className="page">
      <div className="page-head">
        <div className="title-block">
          <span className="label">Skill · Spectrum Construction</span>
          <h1>Spectrum Construction 工作区</h1>
          <p className="lede">
            接入 GenSpectra 与 Agent_UAV_REM，展示多分辨率频谱构建、UAV 稀疏采样 REM、主动采样路径和算法 RMSE 对比。
          </p>
        </div>
        <div className="actions">
          <button className="btn ghost" onClick={onBack}>
            <ArrowLeft size={14} /> 返回 Console
          </button>
          <button
            className="btn"
            onClick={() => (activeModule === "uav_rem" ? loadRem(remSceneId, remHeightLayer, true) : generate(seed, activeModule === "genspectra"))}
            disabled={loading || remLoading}
          >
            <Play size={14} /> {loading || remLoading ? "运行中" : activeModule === "genspectra" ? "运行 GenSpectra" : activeModule === "uav_rem" ? "运行重建" : "刷新当前页"}
          </button>
        </div>
      </div>

      <div className="sc-workspace-tabs">
        {MODULES.map((module) => (
          <button
            key={module.id}
            className={activeModule === module.id ? "on" : ""}
            onClick={() => setActiveModule(module.id)}
            type="button"
          >
            {module.label}
          </button>
        ))}
      </div>

      {activeModule === "genspectra" && (
        <div className="skill-detail-grid">
          <aside className="card params-card">
            <div className="card-head">
              <span className="title">生成参数</span>
              <span className="eyebrow">Gudmundson</span>
            </div>
            <div className="card-body">
              <div className="field">
                <label>分辨率</label>
                <div className="segment resolution-segment">
                  {RESOLUTIONS.map((resolution) => (
                    <button
                      key={resolution}
                      className={activeResolution === resolution ? "on" : ""}
                      onClick={() => setActiveResolution(resolution)}
                      type="button"
                    >
                      {resolution}
                    </button>
                  ))}
                </div>
              </div>
              <div className="field">
                <label>视图</label>
                <div className="segment sc-view-segment">
                  <button className={viewMode === "original" ? "on" : ""} onClick={() => setViewMode("original")} type="button">
                    真实地图
                  </button>
                  <button className={viewMode === "masked" ? "on" : ""} onClick={() => setViewMode("masked")} type="button">
                    Patch Mask
                  </button>
                  <button
                    className={viewMode === "reconstruction" ? "on" : ""}
                    onClick={() => (canShowReconstruction ? setViewMode("reconstruction") : generate(seed, true))}
                    type="button"
                  >
                    重建地图
                  </button>
                </div>
              </div>
              <div className="field">
                <label>随机种子</label>
                <input className="control mono" value={seed} onChange={(event) => setSeed(event.target.value)} />
              </div>
              <div className="field">
                <label>模型状态</label>
                <input className="control" value={inferenceLabel(activeStatus)} readOnly />
              </div>
            </div>
          </aside>

          <main className="sc-main">
            <section className="card">
              <div className="card-head">
                <span className="title">多分辨率频谱覆盖</span>
                <span className="pill" data-tone={statusTone(activeStatus)}>
                  <span className="dot" /> {activeResolution} × {activeResolution}
                </span>
              </div>
              <div className="card-body">
                <div className="sc-map-frame">
                  {visibleMatrix ? (
                    <>
                      <HeatmapCanvas matrix={visibleMatrix} metrics={activeMap.metrics} />
                      <div className="sc-map-grid" />
                      <div className="sc-map-legend">
                        <span>Low</span>
                        <span>Power dBm</span>
                        <span>High</span>
                      </div>
                    </>
                  ) : (
                    <div className="sc-empty">{loading ? "生成多分辨率矩阵中" : "暂无数据"}</div>
                  )}
                </div>
                {error && (
                  <div className="sc-error">
                    <AlertTriangle size={14} /> {error}
                  </div>
                )}
              </div>
            </section>

            <section className="card">
              <div className="card-head">
                <span className="title">分辨率输出</span>
                <span className="eyebrow">Generated Maps</span>
              </div>
              <div className="card-body">
                <div className="sc-resolution-grid">
                  {(result?.maps ?? []).map((item) => (
                    <button
                      key={item.resolution}
                      className={`sc-resolution-tile ${activeResolution === item.resolution ? "on" : ""}`}
                      onClick={() => setActiveResolution(item.resolution)}
                      type="button"
                    >
                      <span>{item.resolution} × {item.resolution}</span>
                      <strong>{item.rmse == null ? formatDbm(item.metrics.mean_dbm) : `RMSE ${formatRmse(item.rmse)}`}</strong>
                    </button>
                  ))}
                </div>
              </div>
            </section>
          </main>

          <StatusCard activeMap={activeMap} activeStatus={activeStatus} result={result} />
        </div>
      )}

      {activeModule === "uav_rem" && (
        <div className="skill-detail-grid">
          <aside className="card params-card">
            <div className="card-head">
              <span className="title">UAV REM 参数</span>
              <span className="eyebrow">Agent_UAV_REM</span>
            </div>
            <div className="card-body">
              <div className="field">
                <label>测试场景</label>
                <select className="control" value={remSceneId} onChange={(event) => setRemSceneId(Number(event.target.value))}>
                  {(remData?.scene_options ?? [148]).map((sceneId) => (
                    <option key={sceneId} value={sceneId}>
                      scene {sceneId}
                    </option>
                  ))}
                </select>
              </div>
              <div className="field">
                <label>高度层</label>
                <div className="segment resolution-segment">
                  {[0, 1, 2, 3, 4].map((layer) => (
                    <button
                      key={layer}
                      className={remHeightLayer === layer ? "on" : ""}
                      onClick={() => setRemHeightLayer(layer)}
                      type="button"
                    >
                      Z{layer}
                    </button>
                  ))}
                </div>
              </div>
              <div className="field">
                <label>REM 视图</label>
                <div className="segment sc-rem-view-segment">
                  {REM_VIEWS.map((view) => (
                    <button key={view.id} className={remView === view.id ? "on" : ""} onClick={() => setRemView(view.id)} type="button">
                      {view.label}
                    </button>
                  ))}
                </div>
              </div>
              <button className="btn" onClick={() => loadRem(remSceneId, remHeightLayer, true)} disabled={remLoading} type="button">
                <Play size={14} /> {remLoading ? "运行中" : "运行重建"}
              </button>
            </div>
          </aside>

          <main className="sc-main">
            <section className="card">
              <div className="card-head">
                <span className="title">UAV 稀疏采样 REM</span>
                <span className="pill" data-tone={remScene ? "ok" : "warn"}>
                  <span className="dot" /> {remScene ? `scene ${remScene.scene_id} · Z${remScene.height_layer}` : "waiting"}
                </span>
                <button
                  className="btn ghost sc-grid-toggle"
                  onClick={() => setRemGridMode((prev) => !prev)}
                  title={remGridMode ? "单图模式" : "四图对比"}
                  type="button"
                >
                  {remGridMode ? <Square size={14} /> : <Grid2x2 size={14} />}
                </button>
              </div>
              <div className="card-body">
                {remGridMode && remScene?.maps ? (
                  <div className="sc-rem-grid-4">
                    {REM_VIEWS.map((view) => {
                      const mat = remScene.maps[view.id];
                      const met = view.id === "error" ? remScene.error_metrics : remScene.metrics;
                      return (
                        <div key={view.id} className={`sc-rem-grid-cell ${remView === view.id ? "on" : ""}`} onClick={() => setRemView(view.id)}>
                          <span className="sc-rem-grid-label">{view.label}</span>
                          {mat ? (
                            <HeatmapCanvas matrix={mat} metrics={met} />
                          ) : (
                            <div className="sc-empty">--</div>
                          )}
                        </div>
                      );
                    })}
                  </div>
                ) : (
                  <div className="sc-map-frame">
                    {remMatrix ? (
                      <>
                        <HeatmapCanvas matrix={remMatrix} metrics={remMetrics} />
                        <div className="sc-map-grid" />
                        {remView !== "error" && <PathMarkers points={remScene.path_points} />}
                        <div className="sc-map-legend">
                          <span>Low</span>
                          <span>{remView === "error" ? "Abs Error dB" : "RSS dBm"}</span>
                          <span>High</span>
                        </div>
                      </>
                    ) : (
                      <div className="sc-empty">{remLoading ? "读取 Agent_UAV_REM 场景中" : "暂无 REM 数据"}</div>
                    )}
                  </div>
                )}
                {remError && (
                  <div className="sc-error">
                    <AlertTriangle size={14} /> {remError}
                  </div>
                )}
              </div>
            </section>

            <section className="card">
              <div className="card-head">
                <span className="title">REM 功能</span>
                <span className="eyebrow">REM Functions</span>
              </div>
              <div className="card-body">
                <div className="sc-algo-grid">
                  {(remData?.algorithm_cards ?? []).map((card) => (
                    <div className="sc-algo-card" key={card.name}>
                      <span>{card.role}</span>
                      <strong>{card.name}</strong>
                      <p>{card.description}</p>
                    </div>
                  ))}
                </div>
              </div>
            </section>
          </main>

          <aside className="card">
            <div className="card-head">
              <span className="title">REM 运行状态</span>
              <span className="eyebrow">Status</span>
            </div>
            <div className="card-body sc-status">
              <Stat icon={<MapPinned size={15} />} label="分辨率" value={remData?.summary?.resolution ?? "128 × 128 × 5"} />
              <Stat icon={<Route size={15} />} label="路径点" value={remScene?.path_points?.length ? `${remScene.path_points.length} shown` : "--"} />
              <Stat icon={<Activity size={15} />} label="采样覆盖" value={formatPercent(remScene?.coverage_ratio)} />
              <div className="sc-metric-grid">
                <div>
                  <span>RMSE</span>
                  <strong>{formatRmse(remScene?.rmse)}</strong>
                </div>
                <div>
                  <span>Samples</span>
                  <strong>{remScene?.sample_count ?? "--"}</strong>
                </div>
                <div>
                  <span>Mean RSS</span>
                  <strong>{formatDbm(remScene?.metrics?.mean_dbm)}</strong>
                </div>
                <div>
                  <span>Mean Error</span>
                  <strong>{formatDbm(remScene?.error_metrics?.mean_dbm)}</strong>
                </div>
              </div>
              <div className="sc-note" data-status={remData?.source?.available ? "ready" : "failed"}>
                <span className="eyebrow">{remData?.source?.available ? "AGENT_UAV_REM READY" : "AGENT_UAV_REM MISSING"}</span>
                <p>{remData?.summary?.goal ?? "等待 Agent_UAV_REM 结果文件。"}</p>
              </div>
            </div>
          </aside>
        </div>
      )}

      {activeModule === "benchmarks" && <BenchmarksPanel remData={remData} />}
    </div>
  );
}

function StatusCard({ activeMap, activeStatus, result }) {
  return (
    <aside className="card">
      <div className="card-head">
        <span className="title">运行状态</span>
        <span className="eyebrow">Status</span>
      </div>
      <div className="card-body sc-status">
        <Stat icon={<Activity size={15} />} label="生成器" value="Gudmundson path-loss" />
        <Stat icon={<Layers3 size={15} />} label="掩码率" value={result ? `${Math.round(result.mask_ratio * 100)}% patch` : "75% patch"} />
        <Stat
          icon={<Layers3 size={15} />}
          label="Patch Grid"
          value={activeMap ? `${activeMap.patch_grid?.[0] ?? 16} × ${activeMap.patch_grid?.[1] ?? 16} · p${activeMap.patch_size}` : "16 × 16"}
        />

        <div className="sc-metric-grid">
          <div>
            <span>Min</span>
            <strong>{formatDbm(activeMap?.metrics?.min_dbm)}</strong>
          </div>
          <div>
            <span>Mean</span>
            <strong>{formatDbm(activeMap?.metrics?.mean_dbm)}</strong>
          </div>
          <div>
            <span>Max</span>
            <strong>{formatDbm(activeMap?.metrics?.max_dbm)}</strong>
          </div>
          <div>
            <span>RMSE</span>
            <strong>{formatRmse(activeMap?.rmse)}</strong>
          </div>
        </div>

        <div className="sc-note" data-status={activeStatus}>
          <span className="eyebrow">{activeStatus === "ready" ? "GENSPECTRA READY" : "GENSPECTRA STATUS"}</span>
          <p>
            {activeStatus === "ready"
              ? "当前分辨率已返回 GenSpectra reconstruction，可切换查看真实地图、Patch Mask 和重建地图。"
              : activeMap?.inference_error || result?.checkpoint_note || "当前为快速预览模式，已展示真实地图与 Patch Mask。"}
          </p>
        </div>
      </div>
    </aside>
  );
}

function Stat({ icon, label, value }) {
  return (
    <div className="sc-stat">
      {icon}
      <div>
        <span>{label}</span>
        <strong>{value}</strong>
      </div>
    </div>
  );
}

function BenchmarksPanel({ remData }) {
  const methods = remData?.comparison?.methods ?? [];
  const rates = remData?.comparison?.rates ?? [];
  const bestMean = methods.length ? Math.min(...methods.map((item) => item.mean_rmse)) : 1;
  const activePolicies = remData?.active_sampling?.policies ?? [];

  return (
    <div className="sc-benchmark-layout">
      <section className="card">
        <div className="card-head">
          <span className="title">算法 RMSE 对比</span>
          <span className="eyebrow">10 Sampling Rates</span>
        </div>
        <div className="card-body">
          <div className="sc-rate-row">
            {rates.map((rate) => (
              <span key={rate}>{formatPercent(rate)}</span>
            ))}
          </div>
          <div className="sc-benchmark-list">
            {methods.map((method) => (
              <div className="sc-benchmark-row" key={method.method}>
                <div>
                  <strong>{method.method}</strong>
                  <span>{method.type}</span>
                </div>
                <div className="sc-benchmark-bar">
                  <i style={{ width: `${Math.max(12, Math.min(100, (bestMean / method.mean_rmse) * 100))}%` }} />
                </div>
                <em>{formatRmse(method.mean_rmse)}</em>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <span className="title">主动采样策略</span>
          <span className="eyebrow">ABR vs Random</span>
        </div>
        <div className="card-body">
          <div className="sc-policy-grid">
            {activePolicies.map((policy) => (
              <div className="sc-policy-card" key={policy.policy}>
                <span>{policy.policy}</span>
                <strong>{formatRmse(policy.mean_rmse)}</strong>
                <p>
                  {policy.mean_samples == null ? "--" : `${policy.mean_samples} samples`} ·{" "}
                  {policy.mean_elapsed == null ? "--" : `${policy.mean_elapsed}s avg`}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <span className="title">接入来源</span>
          <span className="eyebrow">Artifacts</span>
        </div>
        <div className="card-body sc-source-list">
          <div>
            <GitBranch size={15} />
            <span>{remData?.source?.root ?? "/workspace/YiFan/Agent_UAV_REM"}</span>
          </div>
          <div>
            <BarChart3 size={15} />
            <span>results/final_comparison.csv</span>
          </div>
          <div>
            <MapPinned size={15} />
            <span>results/abr/scene_*_abr.npz</span>
          </div>
        </div>
      </section>
    </div>
  );
}
