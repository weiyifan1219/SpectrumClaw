# Deploy Scripts

部署相关脚本位于 `scripts/` 根目录，本目录保留说明。

| 脚本 | 用途 |
| --- | --- |
| `scripts/server_deploy.sh` | 服务器部署/同步入口。 |
| `scripts/setup_server.sh` | 服务器初始化。 |
| `scripts/server_full_ingest.sh` | 服务器全量知识库入库。 |
| `scripts/server_parallel_chain.sh` | 并行处理链路。 |
| `scripts/local/start_links.sh` | 本地到服务器的 proxy + autossh 链路守护。 |

这些脚本包含具体机器路径和端口约定，迁移到新服务器前应先审查变量。
