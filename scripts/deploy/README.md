# Deploy Scripts

部署相关脚本位于 `scripts/` 根目录，本目录保留说明。

| 脚本 | 用途 |
| --- | --- |
| `scripts/deploy/server_deploy.sh` | 服务器部署/同步入口。 |
| `scripts/deploy/setup_server.sh` | 服务器初始化。 |
| `scripts/ingest/server_full_ingest.sh` | 服务器全量知识库入库。 |
| `scripts/ingest/server_parallel_chain.sh` | 并行处理链路。 |
| `scripts/local/start_links.sh` | 本地到服务器的 proxy + autossh 链路守护。 |
| `scripts/local/install_user_services.sh` | 安装本地 systemd 用户服务；默认只托管服务器链路。 |
| `scripts/local/reconnect_network.sh` | 切换网络后重连服务器链路并输出服务器前端地址。 |
| `scripts/local/network_watchdog.sh` | 监听网卡/地址/路由变化，自动触发网络重连。 |
| `scripts/server_backend_guard.sh` | 远端无 systemd 时，按进程退出事件重启后端。 |
| `scripts/local/deploy_server_frontend.sh` | 构建前端并部署到服务器，由后端 `8230` 同源托管。 |

这些脚本包含具体机器路径和端口约定，迁移到新服务器前应先审查变量。

## AutoDL 当前实例

服务器代码位于 `/root/workspace/SpectrumClaw`，日志与运行状态位于数据盘
`/root/autodl-tmp/spectrumclaw`。构建前端时使用 `VITE_API_BASE='' npm --prefix frontend run build`，
生产页面与 API 均由后端固定在 `0.0.0.0:8230` 提供。`scripts/server_backend_guard.sh`
会接管已运行的后端，并在后端异常退出后使用同一端口重新启动。

本实例的 `/init/bin/customer.cmd.sh` 在开机时执行 `/etc/autodl.sh`。将以下内容放入
`/etc/autodl.sh` 即可在开机后启动守护脚本：

```bash
#!/usr/bin/env bash
setsid -f /root/workspace/SpectrumClaw/scripts/server_backend_guard.sh \
  </dev/null >/root/autodl-tmp/spectrumclaw/logs/backend-guard-launch.log 2>&1
```

客户端如通过 SSH 访问，在客户端仓库运行
`bash scripts/local/seetacloud_web_tunnel.sh`，之后固定使用
`http://127.0.0.1:8230/#uav_spectrum_sim`。脚本使用已配置的
`seetacloud-bjb1` SSH 别名，在断线后以同一个本地端口自动重连；端口冲突时直接报错，
不会改用随机端口。Codex 应用内预览的临时转发端口不是网页服务端口，不能当作固定书签。

本机稳定运行可执行 `bash scripts/local/install_user_services.sh`。本地用户已启用 linger，服务会在退出、终端关闭和重新登录后自动拉起。若需要临时本地 Vite 开发页，执行 `ENABLE_LOCAL_FRONTEND=1 bash scripts/local/install_user_services.sh`。

## 服务器同源访问

执行 `bash scripts/local/deploy_server_frontend.sh` 后，前端和后端由服务器同一个 `8230` 端口提供。通过本机自动 SSH 链路访问时，固定使用下面这个地址：

```text
http://<本机可达IP>:8230/
```

端口 `8230` 由本机 systemd 链路固定监听；网络切换后 IP 可能变化，但端口和服务不变，脚本会输出新的本机 IP。服务器公网地址 `http://<服务器IP>:8230/` 只有在上游网络/安全组开放 TCP `8230` 时才可直接使用。
