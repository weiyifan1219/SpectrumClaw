# 部署规划

## 环境定位

| 环境 | 定位 |
| --- | --- |
| 本地 | 代码备份、前端预览、轻量开发、依赖下载中转 |
| 4090 服务器 | 主运行环境、模型推理、长期服务 |

当前阶段不连接服务器，不部署。

## 本地备份方案

| 项目 | 路径 |
| --- | --- |
| 项目目录 | `/home/lenovo/workspace/SpectrumClaw` |
| 本地 conda 环境 | `SpectrumClaw` |
| 知识库压缩包 | `itu_documents.zip` |
| wheelhouse | `wheelhouse/` |

## 服务器主部署方案

后续再确认服务器目录。默认流程规划：

```text
local SpectrumClaw
  -> rsync/scp upload
  -> server conda activate Agent
  -> install offline wheels if needed
  -> start backend
  -> start frontend or serve dist
```

## 服务器约束

- 使用已有 `conda activate Agent`。
- 不随意创建新 conda 环境。
- 服务器无法联网。
- 缺失依赖时，本地下载 wheelhouse 后上传。
- 日志、输出、模型和知识库路径必须配置化。

## 启动脚本规划

| 脚本 | 用途 |
| --- | --- |
| `scripts/local/start_frontend.sh` | 本地启动前端 |
| `scripts/local/start_backend.sh` | 后续本地启动后端 |
| `scripts/deploy/README.md` | 后续服务器部署步骤 |
| `scripts/offline/README.md` | 离线依赖下载和打包说明 |

## 路径规划

| 类型 | 本地路径 | 服务器路径 |
| --- | --- | --- |
| 项目 | `/home/lenovo/workspace/SpectrumClaw` | 后续确认 |
| 日志 | `logs/` | 后续配置 |
| 输出 | `outputs/` | 后续配置 |
| 模型 | `models/` 或外部配置路径 | 后续配置 |
| 知识库 | `data/knowledge_base/` | 后续配置 |
