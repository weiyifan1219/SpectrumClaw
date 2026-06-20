# Offline Dependency Scripts

离线依赖用于无公网服务器环境。

当前仓库包含：

| 文件 | 说明 |
| --- | --- |
| `requirements-offline.txt` | 离线安装依赖清单。 |
| `requirements-mineru.txt` | MinerU 解析环境依赖清单。 |
| `environment.yml` | Conda 环境定义。 |

建议流程：

```text
本地联网机器下载 wheels / 模型 / checkpoint
  -> 打包上传服务器
  -> 服务器 conda activate SpectrumClaw
  -> pip install --no-index --find-links wheelhouse -r requirements-offline.txt
```

MinerU、GenSpectra、UAV REM 等重依赖环境应优先隔离，避免污染主后端环境。
