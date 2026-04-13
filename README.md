# Kiro Relay

一个可运行的 Kiro / Amazon Q 中转门户原型，包含：

- 用户注册、登录、个人 API 面板
- 管理员后台
- 账号池设备授权入口
- OpenAI 兼容 `/v1/*` 转发
- 快照备份能力
- Windows 打包与 Linux 部署脚本

## 路由

- 用户入口: `/`
- 管理员入口: `/admin`
- OpenAI 兼容 API: `/v1`
- 健康检查: `/healthz`

首页不展示管理员入口，只能通过 `/admin` 或单独管理域名访问。

## 本地启动

先安装 Python 3.11+，然后安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

只启动门户：

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

启动完整栈：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-stack.ps1
```

停止完整栈：

```powershell
powershell -ExecutionPolicy Bypass -File .\stop-stack.ps1
```

`start-stack.ps1` 会优先使用本地 `.venv`，并在缺少上游可执行文件时自动从 `upstream\claude-server-windows-amd64.zip` 解压。

## 管理员

创建或重置管理员：

```powershell
powershell -ExecutionPolicy Bypass -File .\bootstrap-admin.ps1 `
  -Email admin@example.com `
  -Password 'ChangeMe!2026' `
  -Name 'Relay Admin'
```

## 账号池接入

真正可转发到 Kiro / Amazon Q 的前提，是上游账号池里已经有完成设备授权并成功认领的账号。

操作路径：

1. 打开 `/admin`
2. 在“设备授权”中填写标签
3. 点击“开始授权”
4. 打开返回的验证链接并完成 AWS 设备授权
5. 回到后台点击“刷新”
6. 状态成功后点击“认领”

只要认领成功，账号就会进入上游池，后续 `/v1/*` 请求才会真正走这批账号。

## 快照与恢复

管理后台现在支持创建和下载快照。

命令行也提供完整工具：

创建快照：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-backup.ps1 -Label before-upgrade
```

查看快照：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-list.ps1
```

恢复前做演练：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-restore.ps1 -Snapshot 20260409T110000Z-before-upgrade -DryRun
```

执行恢复：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-restore.ps1 -Snapshot 20260409T110000Z-before-upgrade
```

快照内容默认包含：

- `portal.db`
- `upstream/data/data.sqlite3`
- `run/portal-session-secret.txt`
- `.env`
- `run/services.json`
- 兼容保留的 `relay.db`

默认快照目录是 `.\snapshots`，默认保留最近 20 份，可通过 `.env` 中的 `RELAY_SNAPSHOT_DIR` 和 `RELAY_SNAPSHOT_KEEP_LATEST` 调整。

## 打包

生成可交付压缩包：

```powershell
powershell -ExecutionPolicy Bypass -File .\build-release.ps1
```

输出位置：

- `dist\kiro-relay-<timestamp>.zip`

这个包默认不包含运行期数据库，不会把你当前账号池和用户数据打进去。

## Windows 部署

解压发布包后执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-relay.ps1
```

然后启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-stack.ps1
```

## Linux 部署

仓库里已经带了：

- `deploy/linux/install-relay.sh`
- `deploy/linux/kiro-portal.service`
- `deploy/linux/kiro-upstream.service`
- `deploy/linux/relay.env.example`

典型步骤：

```bash
sudo bash deploy/linux/install-relay.sh
sudo nano /etc/kiro-relay/relay.env
sudo systemctl restart kiro-upstream kiro-portal
```

Linux 安装脚本会：

- 安装 Python 运行时
- 下载官方 `claude-server-linux-amd64.tar.gz`
- 配置 systemd 服务
- 建立运行目录和快照目录

## 公网访问

建议只暴露门户层，内部上游只绑定到 `127.0.0.1:62311`。

推荐结构：

- `relay.example.com` -> 门户首页 `/`
- `relay.example.com/admin` -> 管理后台
- `relay.example.com/v1` -> OpenAI 兼容 API

反向代理示例可参考：

- `deploy/Caddyfile.example`
- `deploy/cloudflared/config.yml.example`

## 环境变量

可参考 `.env.example`。

最关键的几项：

- `RELAY_UPSTREAM_URL`
- `RELAY_UPSTREAM_ADMIN_PASSWORD`
- `RELAY_PUBLIC_PORTAL_BASE_URL`
- `RELAY_PUBLIC_API_BASE_URL`
- `RELAY_PUBLIC_ADMIN_BASE_URL`
- `RELAY_COOKIE_SECURE`
- `RELAY_BOOTSTRAP_ADMIN_EMAIL`
- `RELAY_BOOTSTRAP_ADMIN_PASSWORD`
- `RELAY_SNAPSHOT_DIR`
- `RELAY_SNAPSHOT_KEEP_LATEST`

## 参考

- ZeekLog 文章: [AWS Kiro 账号池管理系统](https://zeeklog.com/aws-kiro-zhang-hao-chi-guan-li-xi-tong-jiang-amazon-q-developer-api-zhuan-huan-wei-openai-jian-rong-ge-shi-zhi-chi-duo-zhang-hao-chi-oidc-zi-dong-ren-zheng-ling-pai-zi-dong-shua-xin-web-25/)
- 上游项目: [kkddytd/claude-api](https://github.com/kkddytd/claude-api)
