# 频谱构建 / 态势构建

早期文档中的“态势构建”现在主要落在 `backend/skills/spectrum_construction/` 和前端 `SituationBuildingPage.jsx`。`backend/skills/situation_building/` 仅保留历史兼容 README。

## 当前能力

| 子能力 | 状态 | 说明 |
| --- | --- | --- |
| Gudmundson 物理预览 | 可用 | 生成 32/64/128/224 多分辨率功率图。 |
| ViT patch 掩码 | 可用 | 按分辨率对应 patch size 随机遮挡，模拟稀疏观测。 |
| GenSpectra 重建 | 可选 | 优先 sidecar，失败走独立 Python 子进程；缺 checkpoint 时降级。 |
| UAV REM 读取 | 可用 | 只读 `Agent_UAV_REM` 结果，展示真值、采样、重建、误差和算法对比。 |

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/api/spectrum-construction/generate` | 生成多分辨率物理图，可选推理和持久化。 |
| `POST` | `/api/spectrum-construction/uav-rem/overview` | 读取 UAV REM 场景和基线对比。 |

## 关键配置

| 配置 | 默认值 |
| --- | --- |
| `SPECTRUMCLAW_GENSPECTRA_ROOT` | `/workspace/YiFan/GenSpectra` |
| `SPECTRUMCLAW_GENSPECTRA_PYTHON` | `/root/miniconda3/envs/Agent_UAV/bin/python` |
| `SPECTRUMCLAW_GENSPECTRA_HOST` | `127.0.0.1` |
| `SPECTRUMCLAW_GENSPECTRA_PORT` | `8231` |
| `SPECTRUMCLAW_GENSPECTRA_TIMEOUT` | `300` |

## 数据流

```text
前端点击运行
  -> /api/spectrum-construction/generate
  -> GudmundsonMapGenerator
  -> observed_mask + masked map
  -> optional GenSpectra inference
  -> original/masked/reconstruction/rmse/metrics
```

```text
前端选择 UAV REM 场景
  -> /api/spectrum-construction/uav-rem/overview
  -> read final_comparison.csv / results.csv / scene_*.npz
  -> comparison + active_sampling + scene maps
```

## 边界

| 边界 | 说明 |
| --- | --- |
| 不训练 | SpectrumClaw 不训练 GenSpectra 或 UAV REM 模型。 |
| 不修改外部项目 | 只读外部实验目录。 |
| 可降级 | 缺少 root、Python 或 checkpoint 时返回明确状态。 |
| 可审计 | API 调用写入 memory skill_runs。 |
