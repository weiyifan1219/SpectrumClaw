# 离线依赖

GPU 服务器或生产环境可能无法直接联网。依赖管理分为主后端环境、MinerU 解析环境、GenSpectra/UAV REM 外部环境三类。

## 依赖文件

| 文件 | 用途 |
| --- | --- |
| `requirements.txt` | 主后端运行依赖。 |
| `requirements-offline.txt` | 离线安装清单。 |
| `requirements-mineru.txt` | MinerU 解析环境依赖。 |
| `environment.yml` | Conda 环境定义。 |
| `frontend/package-lock.json` | 前端依赖锁定。 |

## 建议流程

```text
联网机器
  -> 下载 Python wheels / npm cache / 模型 / checkpoint
  -> 打包上传服务器
  -> 服务器使用 --no-index / lockfile 安装
```

Python 示例：

```bash
python -m pip download -r requirements-offline.txt -d wheelhouse
python -m pip install --no-index --find-links wheelhouse -r requirements-offline.txt
```

前端示例：

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

## 重依赖隔离

| 环境 | 建议 |
| --- | --- |
| 主后端 | 保持 FastAPI/RAG/Memory/NumPy/SciPy 等主链路可运行。 |
| MinerU | 独立环境处理 PDF 解析，避免污染主服务。 |
| GenSpectra | 通过 sidecar 或子进程使用外部 Python。 |
| UAV REM | 只读实验产物，不把训练环境并入主后端。 |
