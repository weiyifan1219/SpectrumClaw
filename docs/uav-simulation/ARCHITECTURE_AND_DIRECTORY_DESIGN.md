# UAV 仿真第一阶段架构与目录设计

## 架构边界

```text
SpectrumClaw（保持原有 Agent / 前端 / 态势算法不变）
                         │  后续阶段才接入任务级 API
                         ▼
UAV Spectrum Simulation Gateway（本阶段仅预留目录）
      ┌──────────────────┼──────────────────┐
      ▼                  ▼                  ▼
ROS 2 Humble       Sionna RT 2.0.1       运行产物目录
PX4 v1.17          Python 3.11           独立于 Git
Gazebo Harmonic    独立 Conda 环境
```

本阶段只落地三套隔离运行环境及其验证。Agent 不直接访问 ROS Topic；ROS 2 与 Sionna RT 不共享 Python 解释器；前端、任务 API 和三维重建适配器均延后实现。

## 本地 GUI 调试链路

服务器保持 headless。安装器会加入 `ros-humble-foxglove-bridge`，桥接器只绑定服务器 `127.0.0.1:8765`；本地执行 `scripts/local/start_uav_debug_link.sh` 后，可用 Foxglove 连接 `ws://127.0.0.1:8765`。该链路可以查看 ROS Topic、TF、图像和参数，而不需要在服务器上安装桌面环境或暴露调试端口。

## 目录设计

```text
SpectrumClaw/
├── simulation/
│   ├── bootstrap/
│   │   └── install_phase1.sh       # 可恢复的服务器安装器
│   ├── third_party/
│   │   ├── versions.lock.yaml      # 目标版本锁定
│   │   └── PX4-Autopilot/          # 第三方源码（安装后，不纳入 Git）
│   ├── ros2_ws/                    # 下一阶段创建 ROS 2 工作区
│   ├── rf_engine/                  # 下一阶段创建 Sionna RT 服务
│   └── gateway/                    # 下一阶段创建任务网关
└── docs/uav-simulation/
    ├── ENVIRONMENT_AUDIT.md
    └── ARCHITECTURE_AND_DIRECTORY_DESIGN.md

/workspace/YiFan/spectrumclaw_runtime/
├── cache/                          # 可再生下载缓存
├── install-state/                  # 阶段成功标记与实际版本记录
├── logs/                           # 安装、构建与 smoke 日志
└── artifacts/                      # 后续 Ground Truth、rosbag、重建结果；不纳入 Git
```

## 第一阶段验证标准

| 组件 | 验证命令 | 通过标准 |
| --- | --- | --- |
| ROS 2 Humble（`ros-humble-ros-base`，无 GUI） | `source /opt/ros/humble/setup.bash && ros2 --help` | 命令可用 |
| Gazebo Harmonic | `gz sim --versions` | Harmonic 二进制可用 |
| PX4 v1.17 | `PX4_GZ_HEADLESS=1 make px4_sitl gz_x500` | PX4 与 `gz_x500` 启动日志出现 |
| Sionna RT 2.0.1 | 导入 `sionna.rt`、`mitsuba`、`drjit` | 自动选择 CUDA Mitsuba variant |
```
