# 离线依赖管理

## 目标

服务器无法联网，后续部署需要在本地下载 Python wheels、前端依赖或模型文件，再上传到服务器安装。

## Python 依赖

本地生成 wheelhouse：

```bash
conda run -n SpectrumClaw python -m pip download -r requirements.txt -d wheelhouse
```

服务器离线安装：

```bash
conda activate Agent
python -m pip install --no-index --find-links wheelhouse -r requirements.txt
```

## 前端依赖

第一阶段前端依赖通过 `frontend/package-lock.json` 锁定。后续服务器部署可以选择：

| 方案 | 说明 |
| --- | --- |
| 本地构建 dist 后上传 | 推荐，服务器不需要 npm install |
| 上传 npm cache | 仅在服务器需要重新构建时使用 |

## 依赖拆分建议

| 文件 | 用途 |
| --- | --- |
| `requirements.txt` | 当前本地和后端基础依赖 |
| `requirements-rag.txt` | 后续重型 RAG/embedding 依赖 |
| `requirements-gpu.txt` | 后续 GPU/深度学习依赖 |

当前只保留 `requirements.txt`，避免过早引入重依赖。
