# UAV Active REM

Sionna RT 驱动的多场景、多频段、多高度 UAV 态势地图工程。当前唯一主线：

```text
五频段 × 五高度 × 多建筑场景 GT
  → 通用传播预训练
  → 13 m、0–5%连续航迹微调
  → 冻结 belief 网络
  → Masked PPO + A* + Gazebo/PX4
```

## 数据契约

- `rss_dbm`: `[F,Z,128,128]`
- `F`: 1.4、1.8、2.4、3.5、5.8 GHz
- `Z`: 9、13、17、21、25 m
- 建筑内部：`valid_rx_mask=0`，不进入损失和指标
- 信号源位置/功率：仅作 GT 元数据，不作为部署输入
- RT：LOS、镜面反射、漫反射、折射、绕射、边缘绕射，静态确定性多径

## 目录

| 路径 | 内容 |
|---|---|
| `configs/dataset/` | `multiband`、`pilot`、正式场景和平台测试配置 |
| `data/raw_gt/` | 不可修改的 Sionna RT NPZ 与 manifest |
| `data/episodes/` | 后续 RL 连续航迹 episode |
| `src/uav_rem_active_mapping/` | 唯一正式实现 |
| `scripts/` | 数据、训练、评估入口 |
| `checkpoints/` | 预训练、微调、策略 checkpoint |
| `results/` | 可视化和机器可读报告 |
| `logs/` | 当前正式任务日志；失败/废弃日志及时删除 |

详细数据划分和训练逻辑见 `docs/RESEARCH_PLAN.md`。

## 3090 多频 pilot

```bash
cd /workspace/YiFan/SpectrumClaw/research/uav_rem_active_mapping
CUDA_VISIBLE_DEVICES=0 PYTHONPATH=src \
  /root/miniconda3/envs/spectrumclaw-rt/bin/python scripts/generate_variants.py \
  --config configs/dataset/pilot.yaml
```

正式数据只在 pilot 通过数值、掩码、场景绑定与可视化检查后生成。
