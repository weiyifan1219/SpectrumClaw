# 部署与运行

SpectrumClaw 支持本地开发，也支持本地前端 + GPU 服务器后端的运行方式。当前代码已包含本地启动脚本、LLM forward proxy、SSH 链路守护脚本和服务器部署脚本。

## 推荐运行形态

| 场景 | 运行方式 |
| --- | --- |
| 本地轻量开发 | 本地启动 FastAPI + Vite，使用小规模数据或已有 `data/`。 |
| 服务器后端 | GPU 服务器运行后端/RAG/GenSpectra，本地 Vite 通过 SSH 隧道访问 `8230`。 |
| 离线服务器 | 本地准备 wheelhouse、模型和数据，上传后在服务器环境安装。 |

## 端口约定

| 端口 | 用途 |
| --- | --- |
| `8230` | SpectrumClaw FastAPI backend。 |
| `5173` | Vite dev server。 |
| `8231` | 可选 GenSpectra sidecar。 |
| `8240` | LLM forward proxy / 服务器反向访问本地代理。 |
| `8241` | 可选 VLM/Qwen-VL 链路。 |

## 本地启动

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
npm --prefix frontend install
```

后端：

```bash
scripts/local/start_backend.sh
```

前端：

```bash
scripts/local/start_frontend.sh
```

访问：

```text
http://127.0.0.1:5173/
```

## 本地到服务器链路

`scripts/local/start_links.sh` 会守护两类链路：

| 子链路 | 说明 |
| --- | --- |
| LLM forward proxy | 本地 `127.0.0.1:8240` 转发到外部 LLM API。 |
| autossh 隧道 | 本地 `8230` 到服务器后端，同时服务器反向访问本地 `8240`。 |

命令：

```bash
scripts/local/start_links.sh status
scripts/local/start_links.sh daemon
scripts/local/start_links.sh stop
```

该脚本含私有服务器和 SSH key 路径约定，迁移机器时需要修改。

## 服务器部署

脚本入口：

| 脚本 | 用途 |
| --- | --- |
| `scripts/server_deploy.sh` | 服务器部署/同步入口。 |
| `scripts/setup_server.sh` | 服务器环境初始化。 |
| `scripts/server_full_ingest.sh` | 全量知识库入库。 |
| `scripts/server_parallel_chain.sh` | 批处理链路。 |
| `scripts/deploy/README.md` | 部署脚本说明。 |
| `scripts/offline/README.md` | 离线依赖说明。 |

## 外部模型/产物路径

| 能力 | 默认路径/配置 | 缺失时行为 |
| --- | --- | --- |
| GenSpectra root | `/workspace/YiFan/GenSpectra` 或 `SPECTRUMCLAW_GENSPECTRA_ROOT` | 频谱构建降级为物理预览。 |
| GenSpectra Python | `/root/miniconda3/envs/Agent_UAV/bin/python` 或 `SPECTRUMCLAW_GENSPECTRA_PYTHON` | 返回 `pending_checkpoint` 或错误说明。 |
| Agent_UAV_REM | `/workspace/YiFan/Agent_UAV_REM` 或相关环境配置 | 前端显示 source unavailable 占位结构。 |
| Chroma/Graph | `data/chroma`, `data/graph/spectrum_graph.json` | RAG 状态显示 missing，查询降级或为空。 |

## 验证

```bash
curl http://127.0.0.1:8230/health
npm --prefix frontend run build
pytest -q
```

## Git 推送说明

推送 GitHub 需要本机配置 HTTPS token、Git credential helper、`gh auth login`，或可用的 GitHub SSH key。代码和脚本无法绕过 GitHub 认证。
