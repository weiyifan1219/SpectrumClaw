# Deploy Scripts

部署相关脚本位于 `scripts/` 根目录，本目录保留说明。

| 脚本 | 用途 |
| --- | --- |
| `scripts/server_deploy.sh` | 服务器部署/同步入口。 |
| `scripts/setup_server.sh` | 服务器初始化。 |
| `scripts/server_full_ingest.sh` | 服务器全量知识库入库。 |
| `scripts/server_parallel_chain.sh` | 并行处理链路。 |
| `scripts/local/start_links.sh` | 本地到服务器的 proxy + autossh 链路守护。 |
| `scripts/local/install_user_services.sh` | 安装本地 systemd 用户服务；默认只托管服务器链路。 |
| `scripts/local/reconnect_network.sh` | 切换网络后重连服务器链路并输出服务器前端地址。 |
| `scripts/local/network_watchdog.sh` | 监听网卡/地址/路由变化，自动触发网络重连。 |
| `scripts/server_backend_guard.sh` | 远端无 systemd 时，按进程退出事件重启后端。 |
| `scripts/local/deploy_server_frontend.sh` | 构建前端并部署到服务器，由后端 `8230` 同源托管。 |

这些脚本包含具体机器路径和端口约定，迁移到新服务器前应先审查变量。

本机稳定运行可执行 `bash scripts/local/install_user_services.sh`。本地用户已启用 linger，服务会在退出、终端关闭和重新登录后自动拉起。若需要临时本地 Vite 开发页，执行 `ENABLE_LOCAL_FRONTEND=1 bash scripts/local/install_user_services.sh`。

## 服务器同源访问

执行 `bash scripts/local/deploy_server_frontend.sh` 后，前端和后端由服务器同一个 `8230` 端口提供。通过本机自动 SSH 链路访问时，固定使用下面这个地址：

```text
http://<本机可达IP>:8230/
```

端口 `8230` 由本机 systemd 链路固定监听；当前可用地址为 `http://192.168.139.129:8230/`。网络切换后 IP 可能变化，但端口和服务不变，脚本会输出新的本机 IP。服务器公网地址 `http://<服务器IP>:8230/` 只有在上游网络/安全组开放 TCP `8230` 时才可直接使用。
