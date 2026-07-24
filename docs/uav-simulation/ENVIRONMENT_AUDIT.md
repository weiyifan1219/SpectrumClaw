# UAV 仿真第一阶段环境审计

审计时间：2026-07-18（Asia/Shanghai）
目标服务器：`weiyifan3090`

| 项目 | 审计结果 | 结论 |
| --- | --- | --- |
| 操作系统 | Ubuntu 22.04.3 LTS，内核 `6.8.0-90-generic` | 符合 ROS 2 Humble 与 Gazebo Harmonic 基线 |
| GPU | 2 × NVIDIA GeForce RTX 3090，单卡 24 GB | 适合 PX4/Gazebo 与 Sionna RT GPU Smoke Test |
| NVIDIA 驱动 | 535.274.02 | 将在安装后以 Sionna RT 的 CUDA Mitsuba variant 复核 |
| 容器 | 未检测到 `/.dockerenv` | 按主机环境安装；仍需以运行时 Smoke Test 验证 EGL |
| 图形设备 | `/dev/dri/renderD128`、`/dev/dri/renderD129` 可见 | 具备 EGL 设备前提 |
| CPU / 内存 | 待安装前脚本写入服务器实际审计 | 不在本地猜测 |
| 根分区 | 初检仅余约 7.1 GB；清理可再生包缓存和未运行的项目内 Conda 副本后约 57 GB | 可进入本阶段安装；运行数据另置于 runtime root |
| 当前应用环境 | `/root/miniconda3/envs/SpectrumClaw`，Python 3.11.15，运行中的后端正在使用此路径 | 保留不改；RT 另建独立环境 |
| ROS / Gazebo / PX4 | 当前未发现系统包、命令、PX4 源码或构建产物；但保留了 `/root/.simulation-gazebo`（约 58 MB）的 `x500` 等模型缓存 | 证明历史上运行过仿真；保留模型缓存并补齐已缺失的固定版本安装 |
| 网络 | 服务器不能直连外网 | 使用本机至服务器 `-R 17897` 反向代理 |
| Web 端口 | 现有 SpectrumClaw 后端占用 8230 | 本阶段不改动现有服务 |
| GUI 策略 | 服务器无桌面会话 | 安装 `ros-humble-ros-base`，PX4/Gazebo 使用 headless Smoke Test；不安装 RViz 等桌面组件 |

## 可恢复安装约定

安装器为 [install_phase1.sh](../../simulation/bootstrap/install_phase1.sh)，状态、日志和下载缓存均位于：

```text
/workspace/YiFan/spectrumclaw_runtime/
├── install-state/uav-spectrum-sim-phase1/
├── logs/uav-spectrum-sim-phase1/
└── cache/pip/
```

每个阶段只有成功后才写入 `.done` 标记；代理短暂中断、SSH 断开或单个安装命令失败后，重新建立反向代理并重跑同一脚本即可继续未完成阶段。

## 备份与工作基线

| 资产 | 位置 / 标识 | 验证 |
| --- | --- | --- |
| Git 基线标签 | `pre-uav-spectrum-sim-20260718` | 指向 `010e60e36a662c08ee57b39bbe9812acab9977f7` |
| 开发分支 | `feature/uav-spectrum-sim-mvp` | 已从上述基线创建 |
| 本地 Git Bundle | `/home/weiyifan/workspace/SpectrumClaw-pre-uav-sim-20260718.bundle` | `git bundle verify` 通过 |
| 服务器源码与配置快照 | `/workspace/YiFan/backups/SpectrumClaw-phase1-preinstall-20260718.tgz` | SHA-256：`011ec85e0d48c2db6ee9f2de2724d011f6be136d71d88895ac966e37fefb683b` |

现有工作树有用户未提交改动；本阶段不会重置、覆盖或纳入这些改动。

## 第一阶段完成复核

| 验证项 | 实际结果 | 状态 |
| --- | --- | --- |
| 主机资源 | 64 vCPU、188 GiB 内存、2 × RTX 3090（每卡 24 GiB）、可用磁盘约 49 GiB | 通过 |
| ROS 2 | `ros-humble-ros-base` `0.10.0-1jammy.20260607.081808`，`ROS_DISTRO=humble` | 通过 |
| Gazebo | Harmonic，`gz sim 8.14.0` | 通过 |
| PX4 | `v1.17.0`，提交 `d6f12ad1c4f70ad3230afd7d86e971421e02fef4` | 通过 |
| PX4 / Gazebo Smoke Test | `gz_x500` 无头启动；日志确认 world ready、模型生成和 PX4 启动脚本成功返回；测试进程已回收 | 通过 |
| Sionna RT | 独立 Conda 环境 `spectrumclaw-rt`；`sionna-rt 2.0.1`、`cuda_ad_rgb` | 通过 |
| 本地调试链路 | `foxglove_bridge 3.4.2` 仅绑定服务器回环地址；本地 SSH 转发目标为 `ws://127.0.0.1:8765` | 通过 |

PX4 的无头 smoke test 使用独立进程组；一旦观测到启动成功即主动回收，避免 `timeout` 遗留 Gazebo/PX4 子进程。安装器因此可安全重跑，已完成的阶段会跳过。
