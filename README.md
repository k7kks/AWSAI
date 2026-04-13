# Kiro Relay

Kiro Relay 是一个面向正式服务端部署的中转门户，而不是前端 Demo。

它把三类能力放在同一套服务里：

- 用户门户：注册、登录、套餐查看、入口分流
- 管理后台：用户管理、入口管理、快照、账号池、注册任务
- 网关层：对外提供 OpenAI 兼容 `/v1/*` 接口，并把请求转发给上游

当前仓库同时支持两类套餐入口：

- `kiro`：内置原生中转，用户在本系统内直接拿 API Key 和 Base URL
- `sub2api`：外部受管入口，用户通过外部入口继续使用，后台可选远端同步用户

## 系统定位

这个项目的目标不是“做一个能点的页面”，而是提供一套可以长期运维的服务端系统：

- 本地持久化用户、管理员、会话、快照元数据
- 对上游 Kiro / Amazon Q 中转服务做统一控制
- 对外部入口（如 Sub2API）做接入、诊断、开关和同步状态管理
- 保留 Windows 启动脚本和 Linux 部署脚本，便于实际落地

## 核心能力

### 1. 原生 Kiro 中转

- 用户注册后自动在上游 Kiro 网关创建用户
- 门户保存本地用户映射、配额、限速和 API Key
- 用户面板提供 Base URL、API Key、用量概览
- 管理后台支持用户启停、删除、Key 轮换

### 2. Sub2API 外部入口集成

- 门户与管理后台都能显示 `sub2api` 入口卡片
- 后台可以配置 `public/admin/api/health` 地址、默认分组、默认并发、初始余额
- 支持两种模式：
  - `local_only`：只保留本地套餐记录，不做远端同步
  - `remote_sync`：配置 `admin API key` 后，创建/更新/删除用户时同步到 Sub2API
- 提供服务端诊断信息：
  - 配置来源（数据库 / 环境变量）
  - 健康检查
  - TCP 可达性
  - Admin API 鉴权检查
  - Docker / Go 运行条件探测

### 3. 管理后台

- 本地管理员登录
- 中转用户管理
- 入口提供方管理
- 账号池刷新、启停、删除
- 快照创建、下载、恢复命令复制
- 注册任务与注册账号管理

### 4. 运维能力

- `/healthz` 健康检查
- 会话探测端点：`/api/auth/session`、`/api/admin/session`
- 快照备份与恢复
- Windows 一键启动、Linux systemd 安装

## 服务端架构

### 请求路径

- 用户访问 `/`：进入用户门户
- 用户访问 `/admin`：进入管理后台
- 客户端访问 `/v1/*`：进入 OpenAI 兼容网关
- 管理员访问 `/api/admin/providers`：管理入口提供方

### Provider 模型

系统内部把入口抽象为 `portal_entry_providers`：

- `kiro`：`native`，由当前 Flask 服务直接承载
- `sub2api`：`external`，通过外部地址跳转或同步远端用户

公开注册是否展示给用户，不由前端写死，而由服务端决定：

- `kiro` 总是允许展示
- `sub2api` 只有在“已启用 + 已配置 + 可远端同步”时才对前台开放
- 后台始终可见，方便管理员继续配置和诊断

更多设计细节见：[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)

## 仓库结构

项目关键目录和文件说明见：[docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)

最常用的几个入口：

- `server.py`：Flask 主服务，包含 API、会话、用户、provider、快照、兼容网关
- `index.html`：统一门户页面，用户和管理员入口共用
- `assets/app.js`：前端状态与 API 调用逻辑
- `assets/styles.css`：门户样式
- `start.ps1`：只启动门户
- `start-stack.ps1`：同时启动门户和上游 Kiro 中转
- `deploy/linux/install-relay.sh`：Linux 安装脚本

## 本地开发与启动

### 依赖

- Python 3.11+
- Windows 下可直接运行 PowerShell 启动脚本
- 如果要实际部署 Sub2API，本机还需要 Docker 或 Go 构建环境

安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\python.exe -m pip install -r .\requirements.txt
```

### 只启动门户

```powershell
powershell -ExecutionPolicy Bypass -File .\start.ps1
```

### 启动完整 Kiro 栈

```powershell
powershell -ExecutionPolicy Bypass -File .\start-stack.ps1
```

### 停止完整栈

```powershell
powershell -ExecutionPolicy Bypass -File .\stop-stack.ps1
```

## 生产部署

### Windows

准备运行环境：

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy\windows\install-relay.ps1
```

启动：

```powershell
powershell -ExecutionPolicy Bypass -File .\start-stack.ps1
```

### Linux

仓库已提供：

- `deploy/linux/install-relay.sh`
- `deploy/linux/kiro-portal.service`
- `deploy/linux/kiro-upstream.service`
- `deploy/linux/relay.env.example`

典型安装：

```bash
sudo bash deploy/linux/install-relay.sh
sudo nano /etc/kiro-relay/relay.env
sudo systemctl restart kiro-upstream kiro-portal
```

## Sub2API 接入说明

### 推荐策略

如果你要把 `sub2api` 当正式套餐接入，应该按服务端方式配置，而不是仅在页面里填几个 URL：

- 用环境变量固定生产地址和密钥
- 让管理后台用于查看状态，而不是充当唯一配置源
- 没有 `admin API key` 时，不对前台开放 `sub2api` 自助注册

### 关键环境变量

见 [.env.example](.env.example)，与 `sub2api` 相关的主要配置有：

- `RELAY_SUB2API_BASE_URL`
- `RELAY_SUB2API_PUBLIC_URL`
- `RELAY_SUB2API_ADMIN_URL`
- `RELAY_SUB2API_API_BASE_URL`
- `RELAY_SUB2API_HEALTH_URL`
- `RELAY_SUB2API_ADMIN_API_KEY`
- `RELAY_SUB2API_DEFAULT_ALLOWED_GROUPS`
- `RELAY_SUB2API_DEFAULT_CONCURRENCY`
- `RELAY_SUB2API_INITIAL_BALANCE`
- `RELAY_SUB2API_ENABLED`

### 后台看到的状态含义

- `native`：当前服务内置入口
- `local only`：只保留本地套餐记录，还没有远端同步能力
- `remote sync`：已具备同步 Sub2API 用户的条件
- `env managed`：配置受环境变量托管，后台不能覆盖这些字段

## 路由与接口

### 页面入口

- 用户入口：`/`
- 管理入口：`/admin`
- 健康检查：`/healthz`

### 用户侧接口

- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/logout`
- `GET /api/auth/session`
- `GET /api/dashboard`
- `POST /api/apikey/rotate`

### 管理侧接口

- `POST /api/admin/login`
- `POST /api/admin/logout`
- `GET /api/admin/session`
- `GET /api/admin/overview`
- `GET /api/admin/users`
- `GET /api/admin/providers`
- `GET /api/admin/providers/<entry_key>/diagnostics`
- `PUT /api/admin/providers/<entry_key>`
- `GET /api/admin/snapshots`
- `POST /api/admin/snapshots`

### OpenAI 兼容网关

- `GET /v1/models`
- `POST /v1/responses`
- `GET|POST|PUT|PATCH|DELETE /v1/<subpath>`

## 数据与状态文件

运行时常见文件：

- `portal.db`：本地门户数据库
- `run/portal-session-secret.txt`：会话密钥
- `run/encryption.key`：敏感字段加密密钥
- `run/services.json`：Windows 启动脚本记录的进程信息
- `snapshots/`：快照目录
- `upstream/data/`：Kiro 上游运行数据

## 快照与恢复

创建快照：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-backup.ps1 -Label before-upgrade
```

查看快照：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-list.ps1
```

恢复演练：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-restore.ps1 -Snapshot 20260409T110000Z-before-upgrade -DryRun
```

执行恢复：

```powershell
powershell -ExecutionPolicy Bypass -File .\snapshot-restore.ps1 -Snapshot 20260409T110000Z-before-upgrade
```

## 公网访问建议

建议只暴露门户层，对内保留上游服务：

- `relay.example.com` -> 门户首页 `/`
- `relay.example.com/admin` -> 管理后台
- `relay.example.com/v1` -> OpenAI 兼容 API
- 内部上游 Kiro 仅监听 `127.0.0.1:62311`

可参考：

- `deploy/Caddyfile.example`
- `deploy/cloudflared/config.yml.example`

## 相关文档

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/PROJECT_STRUCTURE.md](docs/PROJECT_STRUCTURE.md)
- [sub2api-main/sub2api-main/README_CN.md](sub2api-main/sub2api-main/README_CN.md)

## 参考

- ZeekLog 文章: [AWS Kiro 账号池管理系统](https://zeeklog.com/aws-kiro-zhang-hao-chi-guan-li-xi-tong-jiang-amazon-q-developer-api-zhuan-huan-wei-openai-jian-rong-ge-shi-zhi-chi-duo-zhang-hao-chi-oidc-zi-dong-ren-zheng-ling-pai-zi-dong-shua-xin-web-25/)
- 上游项目: [kkddytd/claude-api](https://github.com/kkddytd/claude-api)
