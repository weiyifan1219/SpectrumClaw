# SpectrumClaw

SpectrumClaw 是一个面向电磁频谱领域的智能体项目。项目目标是把大语言模型对话、skill 调用、频谱知识库、后续知识图谱、算法脚本和可视化结果组织成一个可部署到 4090 服务器的工作台。

当前阶段优先完成：

| 优先级 | 内容 | 状态 |
| --- | --- | --- |
| P0 | 前端 Console v0 和基础对话体验 | 本地前端模拟实现 |
| P0 | 项目骨架、文档、环境复现文件 | 已规划并创建 |
| P1 | 频率规划 RAG | 先用 `itu_documents.zip` 作为外挂资料库，后续实现 |
| P2 | 态势构建 | 等用户准备好实验脚本后接入 |

## 页面规划

| 页面 | 作用 |
| --- | --- |
| Console | 与频谱智能体对话，选择频谱任务，查看任务日志和结果入口 |
| Knowledge Base | 展示 ITU 文档库、RAG 索引状态、后续知识图谱入口 |
| Memory & Evolution | 展示记忆层、能力清单、skill 演化总结 |
| System | 展示运行环境、API 状态、本地/服务器路径、依赖和服务健康状态 |

## 本地开发

### 前端

```bash
cd frontend
npm install
npm run dev -- --host 127.0.0.1
```

### Python 环境

```bash
conda create -n SpectrumClaw python=3.11 -y
conda run -n SpectrumClaw python -m pip install -r requirements.txt
conda run -n SpectrumClaw python -m pip check
```

## 重要路径

| 路径 | 说明 |
| --- | --- |
| `itu_documents.zip` | 第一批频率规划资料库，当前不移动 |
| `frontend/` | React + Vite 前端 |
| `backend/` | 后端和 skill 目录占位，后续实现 |
| `docs/` | 架构、设计、部署和模块规划 |
| `data/knowledge_base/` | 后续 RAG 原始文件、索引和图谱目录 |
| `outputs/` | 后续任务输出 |
| `logs/` | 后续运行日志 |

## 当前限制

- 当前前端对话是本地模拟，用于验证交互和页面结构。
- 还没有接入真实 LLM API。
- 还没有实现真实 RAG、知识图谱、态势构建和频谱算法。
- 还没有连接或部署到 4090 服务器。
