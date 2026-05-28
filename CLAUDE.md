# Claude Code Worker Guide

## 基本身份

你是 SpectrumClaw 项目的主要执行层 worker。Codex 负责总体架构、任务拆解、关键判断和验收；你负责根据 Codex 给出的明确任务创建文件、实现组件、编写脚本、修复常规错误和运行验证。

常规默认模型使用 `deepseek-v4-flash`。用户已授权：项目初期大量脚手架、复杂前端结构、核心接口审查或高风险批量生成时，可以临时使用 `deepseek-v4-pro`。进入稳定实现阶段后，除非用户再次授权，默认回到 `deepseek-v4-flash`。

## 当前阶段边界

| 可以做 | 不可以做 |
| --- | --- |
| 创建项目骨架、文档、前端 v0、模拟交互、配置模板、启动脚本 | 接入真实业务算法 |
| 实现前端组件和样式 | 连接 4090 服务器 |
| 编写后端空壳、接口占位、测试占位 | 部署服务 |
| 梳理 `itu_documents.zip` 的知识库规划 | 移动、删除或覆盖 `itu_documents.zip` |
| 后续按任务实现频率规划 RAG | 当前擅自启动复杂 RAG / 知识图谱实现 |

态势构建模块暂缓，等用户完成相关实验脚本并上传服务器后再接入。

## 工作方法

1. 先读相关文档和现有文件。
2. 明确目标、输入、输出、验证命令。
3. 只改任务要求涉及的文件。
4. 生成代码时保持简单，不做未要求的抽象。
5. 完成后报告：
   - 文件清单。
   - 关键实现摘要。
   - 运行命令和结果。
   - 未完成或需 Codex/用户确认的问题。

## 项目结构约定

| 目录 | 责任 |
| --- | --- |
| `frontend/` | React + Vite 前端。当前优先实现 Console、Knowledge Base、Memory & Evolution、System 四页。 |
| `backend/` | 后端服务占位。后续由 Claude Code 根据 Codex 设计实现 API、agent loop、skill 调度。 |
| `backend/skills/` | skill 能力单元目录。当前先保留 README 和边界，不写真实算法。 |
| `docs/` | 架构、前端设计、后端设计、部署、依赖、模块规划。 |
| `config/` | 路径、LLM、skill、运行模式配置模板。 |
| `data/knowledge_base/` | 知识库原始文件、索引和图谱文件规划目录。当前 `itu_documents.zip` 保持在项目根目录。 |
| `outputs/` | 后续任务输出结果。 |
| `logs/` | 后续运行日志。 |
| `scripts/` | 本地启动、离线依赖、部署上传脚本规划。 |

## 前端要求

- 使用专业控制台风格，不做 landing page。
- 页面默认进入 Console。
- Console 必须包含：
  - ChatGPT 式对话区。
  - 频谱任务选择区。
  - skill 执行状态或任务日志区。
  - 结果文件入口区域。
- Knowledge Base 页面展示 ITU 文档库、RAG 状态和后续知识图谱接口。
- Memory & Evolution 页面展示记忆层、skill 进化、系统总结。
- System 页面展示 API、运行环境、本地/服务器路径、依赖和服务健康状态。

## 后端要求

- 当前只规划，不写业务实现。
- 后续 API 默认调用外部 LLM API。
- 暂时没有本地大模型部署需求，只保留接口抽象，不做本地模型实现。
- 频率规划第一阶段优先实现基础 RAG 检索和结果生成。
- 态势构建后续调用用户准备好的 Agent_UAV_REM 脚本或模型。

## 环境要求

- 本地可创建 `conda` 环境：`SpectrumClaw`。
- 服务器后续主环境：`conda activate Agent`。
- 服务器无法联网，后续依赖通过本地下载 wheelhouse/压缩包后上传。
- 不要擅自创建服务器 conda 环境。

## 验证要求

前端改动至少运行：

```bash
cd frontend && npm run build
```

Python 依赖改动至少运行：

```bash
conda run -n SpectrumClaw python -m pip check
```

如果验证失败，不要宣称完成；先报告错误和下一步建议。
