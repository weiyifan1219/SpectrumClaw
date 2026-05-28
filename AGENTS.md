# SpectrumClaw Agent Guide

## 全局协作规则

| 角色 | 职责 | 当前边界 |
| --- | --- | --- |
| Codex | 总控、架构师、任务规划者、问题诊断者、前端交互与审美把关、核心文档作者 | 负责设计、验收、关键接口和风险判断；不大面积代替 worker 写后端业务代码 |
| Claude Code MCP | 主要执行层 worker | 常规默认模型 `deepseek-v4-flash`；项目初期大量脚手架、复杂审查或高风险批量生成可临时使用 `deepseek-v4-pro` |
| 用户 | 产品方向和阶段确认 | 决定优先级、服务器部署时机、真实算法脚本接入时机 |

## 回答和执行风格

- 回答必须使用中文。
- 对总结、Plan、Task、长内容，先整理逻辑，再优先用表格表达。
- 先明确假设、目标和验证方式，再动手。
- 保持简单：当前阶段只做必要骨架、前端 v0、API 接入预留和频率规划 RAG 规划。
- 修改要外科手术式进行：只改与请求直接相关的文件，不顺手重构。
- 多步骤任务必须给出可验证目标，完成前要运行必要验证命令。

## 项目目标

SpectrumClaw 是“电磁频谱领域智能体”项目，目标是通过大语言模型对话和 skill 化能力调用，完成频谱领域任务。

| 模块 | 当前状态 | 说明 |
| --- | --- | --- |
| 频率规划 | 第一阶段优先 | 先基于 `itu_documents.zip` 建立基础 RAG 检索与问答流程，后续扩展知识图谱 |
| 态势构建 | 暂缓接入 | 等用户完成相关实验脚本并上传服务器后，再对接 `/home/lenovo/workspace/Agent_UAV_REM` |
| 调制方式识别 | 预留 | 先保留 skill 接口和页面入口 |
| 频谱决策 | 预留 | 先保留 skill 接口和页面入口 |
| 干扰分析 | 预留 | 先保留 skill 接口和页面入口 |

## 参考项目

| 项目 | 借鉴内容 | 禁止事项 |
| --- | --- | --- |
| `/home/lenovo/workspace/AerialClaw` | console 页面组织、skill registry、agent loop、任务日志、记忆系统、反思和进化机制、部署脚本组织 | 不复用无人机/PX4/Gazebo 专属业务逻辑 |
| `/home/lenovo/workspace/Agent_UAV_REM` | 后续态势构建算法、模型、脚本、输入输出和可视化能力 | 当前阶段不接入真实态势构建 |
| `https://github.com/HKUDS/RAG-Anything` | 频谱知识库后续 multimodal RAG、文档解析、图谱化知识组织思路 | 当前阶段不引入复杂数据流和完整 RAG-Anything 实现 |

## 模型使用策略

| 场景 | 模型策略 |
| --- | --- |
| 常规文件创建、简单修改、普通调试 | 优先 `deepseek-v4-flash` |
| 项目初期大量骨架生成、复杂前端结构、核心接口审查 | 允许使用 `deepseek-v4-pro` |
| 后续进入稳定实现阶段 | 默认回到 `deepseek-v4-flash`，除非用户再次授权 |

## 当前阶段工作边界

- 可以创建项目骨架、基础文档、前端 v0、依赖说明和本地开发环境。
- 可以实现前端本地模拟对话，用于验证 console 交互。
- 不写真实业务算法。
- 不连接 4090 服务器。
- 不部署。
- 不安装服务器依赖。
- 不移动、删除、覆盖 `itu_documents.zip`。
- 后端只做规划和目录边界，具体业务实现后续交给 Claude Code MCP。

## 环境和部署约束

| 环境 | 用途 | 约束 |
| --- | --- | --- |
| 本地 `/home/lenovo/workspace/SpectrumClaw` | 代码备份、轻量开发、前端预览、依赖下载中转 | 可以创建本地 conda 环境 `SpectrumClaw` |
| 4090 服务器 | 主运行环境 | 后续使用 `conda activate Agent`，服务器无法联网，依赖需离线上传 |
| 依赖管理 | 本地生成 `requirements.txt` / wheelhouse | 后续部署前必须区分本地环境和服务器环境 |

## 前端设计原则

- 主页面是 `Console`，默认承载频谱智能体对话、任务选择、任务日志、结果入口。
- 页面走线要清晰：用户输入 -> agent 判断/用户选择任务 -> skill 执行状态 -> 结果区域。
- 保留四个一级页面：`Console`、`Knowledge Base`、`Memory & Evolution`、`System`。
- UI 风格采用“频谱控制台 + 知识花园”方向：克制、专业、信息密度高，使用线缆式流程和频谱色带表达模块关系。
- 不做营销 landing page。

## 开发命令

| 目标 | 命令 |
| --- | --- |
| 安装前端依赖 | `cd frontend && npm install` |
| 启动前端 | `cd frontend && npm run dev -- --host 127.0.0.1` |
| 构建前端 | `cd frontend && npm run build` |
| 创建本地环境 | `conda create -n SpectrumClaw python=3.11 -y` |
| 安装 Python 依赖 | `conda run -n SpectrumClaw python -m pip install -r requirements.txt` |

## 提交和验收

- 当前 `.git` 目录可能不是有效 Git 仓库；如果 `git diff` 不可用，用文件清单和关键改动摘要代替。
- 完成前至少验证：
  - 前端依赖可安装。
  - `npm run build` 通过。
  - `conda run -n SpectrumClaw python --version` 可用。
  - Python 依赖安装无冲突，优先运行 `pip check`。
