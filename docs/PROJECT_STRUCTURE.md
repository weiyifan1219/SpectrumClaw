# 项目目录规范

本仓库按职责划分。新增文件必须先选择所属域，禁止在项目根目录新增临时脚本、构建产物、备份目录或实验输出。

```text
SpectrumClaw/
├── backend/                 # FastAPI、智能体、MCP、技能、RAG、记忆与运行时服务
├── frontend/                # React/Vite 控制台与无人机/频谱三维界面
├── simulation/              # PX4/Gazebo 场景、桥接器、Sionna RF 引擎与环境安装脚本
├── config/                  # 应用 YAML、MinerU 配置与 dependencies/ 下的 Conda/Python 依赖定义
├── scripts/
│   ├── local/               # 本机启动、网络恢复、隧道与本地 LLM 转发
│   ├── deploy/              # 服务器部署与环境初始化
│   ├── ingest/              # MinerU 解析、PDF 去重、回填、入库与批处理
│   ├── eval/                # RAG 评测与报告
│   └── offline/             # 离线安装说明
├── tests/                   # 自动化测试；固定夹具仅放 tests/data/
├── data/                    # 知识库原始资料、解析结果、索引、缓存与归档数据
│   └── archive/             # 不参与当前业务链路的历史产物，只读保留
├── logs/                    # 本机运行日志（不提交）
├── outputs/                 # 小型可复现实验产物（不提交）
├── runs/                    # 评测/任务运行记录（不提交）
├── docs/                    # 架构、部署、设计与计划文档
└── assets/                  # README 与前端静态资产
```

## 维护规则

| 内容 | 固定位置 | 规则 |
| --- | --- | --- |
| 前后端业务功能 | `backend/`、`frontend/` | 不放在脚本或数据目录。 |
| UAV、PX4、Gazebo、Sionna | `simulation/` | 场景定义与 RF 几何必须共享同一 ENU 语义。 |
| 历史/兼容仿真模型 | `simulation/models/legacy/` | 保留原始资产，但不作为当前启动模型。 |
| 启动、部署、解析、评测 | `scripts/<职责>/` | 新脚本必须归类；同时更新调用方和本文件。 |
| 依赖与环境定义 | `config/dependencies/` | 不在根目录散放 requirements 或 environment 文件。 |
| 测试样例 | `tests/data/` | 不使用根目录 `test_data/`。 |
| 可再生成缓存/构建产物 | 忽略目录 | 仅临时生成，完成验证后删除。 |
| 大型历史输出 | `data/archive/` | 归档而非与当前业务数据混放；确认无价值后再单独清除。 |

根目录仅保留项目说明、环境变量模板和版本控制配置：`README*`、`.env*`、`.gitignore`、`.git`。
