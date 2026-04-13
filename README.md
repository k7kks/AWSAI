# Kiro Relay

Kiro Relay 是一套面向正式部署的服务端中转系统，不是前端 Demo。

它把用户门户、管理后台和 OpenAI 兼容网关放进同一个服务里，同时支持两类上游：

- `kiro`：当前服务直接管理的原生上游
- `sub2api`：外部接入的成熟业务系统，由当前服务做用户映射、后台管理和网关转发

当前版本的关键设计是：

- 用户前台统一，不再区分 `kiro` 或 `sub2api`
- 后台保留 provider 维度，管理员可以单独管理两套逻辑
- `/v1/*` 网关按用户 API key 反查本地用户，再决定转发到哪个 provider

## 统一用户侧

用户访问门户时，只看到一套入口：

- 登录
- 注册
- 工作区面板
- API Key
- Base URL
- OpenAI SDK 示例

前台不再暴露“选 Kiro 还是选 Sub2API”的概念。用户拿到哪个套餐，由后台创建的用户记录决定。

系统内部的做法是：

- `portal_users.provider_key` 标记该用户属于哪个 provider
- `portal_users.upstream_api_key` 保存这个用户真实可用的上游 API key
- 用户调用 `/v1/*` 时，网关先用传入的 key 反查本地用户，再路由到对应 provider

这意味着用户体验是统一的，但后端依然是两套隔离逻辑。

## 后台能力

管理后台仍然按 provider 管理：

- 用户管理
- provider 配置
- provider 健康检查和诊断
- 账号池管理
- 快照备份与恢复
- 注册任务管理

后台可以同时看到：

- `kiro` 的内置能力
- `sub2api` 的接入状态、管理地址、API Base URL、健康检查地址、admin API key 状态

## Sub2API 接入方式

Sub2API 现在不是一个前台可见的“第二入口页面”，而是后台可管理的外部 provider。

只要在管理后台或环境变量里配置这些信息，就可以接入：

- `publicUrl`
- `adminUrl`
- `apiBaseUrl`
- `healthUrl`
- `adminApiKey`

没有域名也可以，直接用 IP 地址即可，例如：

- `http://<公网IP>:8080`
- `http://<公网IP>:8080/admin`
- `http://<公网IP>:8080/v1`
- `http://<公网IP>:8080/health`

当 `sub2api` 配好 `adminApiKey` 后，系统会进入 `remote_sync` 模式：

- 创建本地用户时，同步创建远端用户
- 为该用户申请 Sub2API API key
- 把这个 key 保存到 `portal_users.upstream_api_key`
- 用户后续直接使用当前门户发下去的 key 调用 `/v1/*`

如果只配了地址、没配 `adminApiKey`，则保持 `local_only`：

- 后台仍可维护 provider
- 不自动创建远端用户
- 不适合作为正式可售套餐

## 网关路由模型

外部客户端始终调用当前门户的 `/v1/*`。

网关处理流程如下：

1. 从 `Authorization`、`x-api-key` 或 `x-goog-api-key` 读取 API key
2. 在 `portal_users.upstream_api_key` 中查找所属用户
3. 根据该用户的 `provider_key` 找到目标 provider
4. 把请求转发给：
   - Kiro 原生上游
   - Sub2API 的 `apiBaseUrl`
5. 对上游重新注入真实鉴权头

因此，前台统一，网关统一，provider 差异只保留在后台和服务端路由层。

## 关键文件

- `server.py`：Flask 主服务，包含页面接口、后台接口、provider 管理和 `/v1/*` 网关
- `index.html`：统一门户页面，公共前台与管理后台共用
- `assets/app.js`：前端状态管理和 API 调用逻辑
- `assets/styles.css`：门户样式
- `docs/ARCHITECTURE.md`：服务端架构说明
- `docs/PROJECT_STRUCTURE.md`：仓库结构说明

## 本地启动

依赖：

- Python 3.11+
- Windows PowerShell 或 Linux shell

安装：

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

## 访问入口

- 用户前台：`/`
- 管理后台：`/admin`
- 健康检查：`/healthz`

如果服务绑定在公网 IP 上，直接按 IP 访问即可：

- `http://<公网IP>:<端口>/`
- `http://<公网IP>:<端口>/admin`

## 生产配置

建议优先用环境变量固定正式配置，尤其是 `sub2api`：

- `RELAY_SUB2API_PUBLIC_URL`
- `RELAY_SUB2API_ADMIN_URL`
- `RELAY_SUB2API_API_BASE_URL`
- `RELAY_SUB2API_HEALTH_URL`
- `RELAY_SUB2API_ADMIN_API_KEY`
- `RELAY_SUB2API_DEFAULT_ALLOWED_GROUPS`
- `RELAY_SUB2API_DEFAULT_CONCURRENCY`
- `RELAY_SUB2API_INITIAL_BALANCE`
- `RELAY_SUB2API_ENABLED`

如果这些字段由环境变量托管，后台会展示状态，但不会覆盖它们。

## 已实现的服务端能力

- 本地用户与管理员会话
- Kiro 原生用户创建、更新、删除、Key 轮换
- Sub2API provider 配置、诊断和远端同步
- 用户 API key 反查路由
- OpenAI 兼容 `/v1/models`
- OpenAI 兼容 `/v1/responses`
- OpenAI 兼容 `/v1/<subpath>`
- 快照创建、下载、恢复命令复制
- 账号池与注册任务管理

## 文档

- [架构说明](./docs/ARCHITECTURE.md)
- [项目结构](./docs/PROJECT_STRUCTURE.md)
