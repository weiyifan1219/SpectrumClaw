# SpectrumClaw Frontend

React + Vite 前端已接入真实后端 API。

## 命令

```bash
npm install
npm run dev -- --host 127.0.0.1 --port 5173
npm run build
```

连接 3090 后端时：

```bash
VITE_API_BASE=http://127.0.0.1:8230 npm run dev -- --host 127.0.0.1 --port 5173
```

## 当前页面

| 页面 | 状态 |
| --- | --- |
| Console | 对话、流式输出、工具/RAG 路由、skill 入口。 |
| Frequency Planning | 专用频率规划接口：结构化卡片（分配状态/业务/脚注/相邻频段/共存约束/风险/建议）+ 多跳检索 + 流式思考过程；支持参数化与自然语言两种输入。 |
| Spectrum Construction | GenSpectra 点击运行显示重建图；UAV REM 显示真实 REM/采样/重建/误差。 |
| Spectrum Decision | 多用户资源分配交互。 |
| Knowledge Base | 旧 KB 统计、新 RAG 状态和知识图谱视图。 |
| Memory & Evolution | 真实 memory API 页面。 |
| System | 系统状态页。 |
