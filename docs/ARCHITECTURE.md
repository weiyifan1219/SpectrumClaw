# 系统架构

## 架构原则

| 原则 | 说明 |
| --- | --- |
| Console-first | 用户先进入可操作控制台，不做展示型 landing page |
| Skill-first | 每个频谱能力都是独立 skill，便于调用、替换和进化 |
| API-first LLM | 当前只走外部 API，不部署本地大模型 |
| Server-primary | 最终以 4090 服务器为主运行环境，本地用于备份和中转 |
| MVP-first | 先跑通前端、RAG 和任务结果闭环，再做复杂调度 |

## 逻辑分层

| 层 | 目录 | 责任 |
| --- | --- | --- |
| Frontend | `frontend/` | 控制台、对话、任务选择、知识库、记忆、系统状态 |
| API Service | `backend/` | HTTP/WebSocket、任务创建、日志推送、结果文件索引 |
| Agent Core | `backend/agent/` | 意图识别、skill 选择、任务上下文、反思 |
| Skills | `backend/skills/` | 频率规划、态势构建、调制识别、频谱决策、干扰分析 |
| Knowledge | `data/knowledge_base/` | 原始文档、RAG 索引、后续知识图谱 |
| Runtime | `outputs/`, `logs/` | 输出文件、任务日志、运行日志 |

## 当前 MVP 数据路径

```text
User -> Frontend Console -> mock agent response
```

当前不接入真实后端业务。后续 MVP-1 数据路径：

```text
User -> Frontend Console -> Backend API -> Agent Router
     -> frequency_planning skill -> RAG retriever -> LLM API
     -> result markdown/json -> Frontend result panel
```

## 后续 Skill 调用路径

```text
Intent
  -> Skill Registry
  -> Skill Adapter
  -> Script / Model / Retriever / External API
  -> Structured Result
  -> Log + Output Artifact
```

## 本地与服务器边界

| 环境 | 角色 | 数据 |
| --- | --- | --- |
| 本地 | 开发、备份、前端预览、依赖下载中转 | 源码、wheelhouse、轻量测试数据 |
| 4090 服务器 | 主运行、模型推理、长期服务 | 项目副本、Agent conda 环境、模型文件、输出结果 |

服务器部署阶段再执行上传、安装和启动。
