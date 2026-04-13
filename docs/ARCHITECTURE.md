# 架构说明

## 1. 设计目标

Kiro Relay 以服务端为中心设计，核心目标有四个：

- 统一门户和网关入口
- 把用户、管理员、套餐和外部入口做成本地可控状态
- 把 Kiro 与 Sub2API 视为两套不同后端，而不是强行揉成一个协议
- 让系统在“上游离线”“外部入口未接好”“管理员未登录”这些场景下仍然能部分可用

## 2. 组件划分

### 门户层

由 `server.py + index.html + assets/*` 组成，负责：

- 页面渲染
- 本地会话管理
- 用户注册/登录
- 管理员登录
- provider 配置和诊断展示

### Kiro 原生中转层

由当前服务对接 `claude-server` 上游：

- 创建用户时向上游 `/v2/users` 建立真实账号
- 轮换 Key、删除用户、读设置、读账号池都走上游管理接口
- 对外再暴露 `/v1/*` OpenAI 兼容接口

### Sub2API 外部入口层

Sub2API 不被当成“另一个 `/v1` 代理实现”，而被视作独立 provider：

- 用户侧入口是外部地址
- 后台可以保存远端地址、健康检查地址、管理 API key
- 只有具备远端同步条件时，才允许用户前台选这个套餐

## 3. Provider 模型

数据库表：`portal_entry_providers`

关键字段：

- `entry_key`：入口标识，如 `kiro`、`sub2api`
- `kind`：`native` 或 `external`
- `public_url` / `admin_url` / `api_base_url` / `health_url`
- `admin_api_key_encrypted`
- `default_allowed_groups`
- `default_concurrency`
- `initial_balance`
- `embed_mode`

### 运行规则

- `kiro` 固定为 `native`，由当前服务直接承载
- `sub2api` 固定为 `external`
- 配置可来自数据库，也可来自环境变量
- 如果某些字段由环境变量托管，后台只能查看，不能覆盖

## 4. 用户创建流程

### Kiro 用户

1. 门户校验本地参数
2. 调上游 `/v2/users` 创建真实用户
3. 把上游 `id` 和 `api_key` 保存到 `portal_users`
4. 用户登录后直接在本面板拿到 API Key 与 Base URL

### Sub2API 用户

分两种模式：

#### local_only

条件：只配置了入口地址，没有配置有效的 `admin API key`

行为：

- 后台仍可建立本地套餐记录
- 不创建远端真实用户
- 前台用户不显示这个 provider
- 管理后台卡片会显示 `local only`

#### remote_sync

条件：已配置入口地址 + `admin API key`

行为：

- 创建用户时调用 `/api/v1/admin/users`
- 更新用户时调用 `/api/v1/admin/users/:id`
- 删除用户时调用 `/api/v1/admin/users/:id`
- 用户面板不显示 Kiro API Key，而是提示进入外部入口继续使用

## 5. 会话与页面加载策略

为了避免前端一打开页面就产生无意义 401：

- 用户页先调用 `/api/auth/session`
- 管理页先调用 `/api/admin/session`
- 只有确认已登录，才继续拉取 dashboard 或管理数据

这样做的好处：

- 浏览器控制台更干净
- 未登录页面不会因为预探测而出现资源报错
- 网页端和 API 端状态分离更清晰

## 6. 健康与诊断

### `/healthz`

返回三类状态：

- 门户自身状态
- Kiro upstream 可达性
- 已启用外部 provider 的健康状态

只要“已启用且已配置”的外部入口不可达，整体状态会降级为 `degraded`。

### Provider 诊断接口

接口：`GET /api/admin/providers/<entry_key>/diagnostics`

当前可输出：

- provider 基本配置
- 配置来源
- 同步模式
- 源码包是否存在
- Docker / Go / Node 是否可用
- TCP 探测
- Admin API 探测

## 7. 为什么不把 Kiro 和 Sub2API 融成一套逻辑

因为两者在系统角色上不同：

- Kiro 是当前服务的原生上游
- Sub2API 是一个完整的外部业务系统

如果硬把两者揉成同一个“用户后端协议”，会带来三个问题：

- 管理语义不一致，容易出现伪成功状态
- API Key、用户入口、账单和权限模型会混淆
- 运维层无法判断问题到底在本系统还是外部系统

所以当前架构采用：

- 统一门户
- 分 provider 管理
- 后端逻辑隔离
- 前台通过套餐选择入口

## 8. 当前已知边界

- 本仓库已集成 Sub2API 管理逻辑，但不包含可直接运行的 Sub2API 进程
- 如果当前机器没有 Docker / Go，就只能先接已有的 Sub2API 服务，或单独部署它
- 生产环境建议使用环境变量托管 Sub2API 配置，而不是只依赖后台手工维护
