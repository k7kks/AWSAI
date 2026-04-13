# 架构说明

## 1. 总体目标

Kiro Relay 以服务端为中心设计，目标不是做两套前台，而是把两类上游统一收敛到一个门户和一个网关下：

- 用户只面对一套门户
- 管理员在后台管理不同 provider
- 网关根据 API key 自动分流到正确上游

因此，这个项目不是“前台切换入口”的壳，而是一套本地持久化、可运维、可扩展的 relay control plane。

## 2. 核心组件

### 门户层

由 `server.py`、`index.html`、`assets/app.js` 和 `assets/styles.css` 组成，负责：

- 用户注册与登录
- 管理员登录
- 用户工作区面板
- provider 配置页面
- 本地 session 管理

### Provider 层

系统当前支持两个 provider：

- `kiro`
  - `native`
  - 当前 Flask 服务直接对接上游 Kiro / Claude relay
- `sub2api`
  - `external`
  - 当前服务不重写它的业务逻辑，只负责接入、同步和转发

### 网关层

对外提供统一的 OpenAI 兼容接口：

- `GET /v1/models`
- `POST /v1/responses`
- `GET|POST|PUT|PATCH|DELETE /v1/<subpath>`

调用方不需要知道自己最终落到哪个 provider。

## 3. 统一前台，后台区分 provider

当前版本的公开前台不再显示 provider 选择。

用户看到的始终是：

- 登录
- 注册
- API Key
- Base URL
- SDK 示例

provider 差异只保留在服务端：

- `portal_users.provider_key`
- `portal_users.upstream_api_key`
- `portal_entry_providers`

这意味着：

- 前台页面统一
- 管理后台仍然能分别管理 `kiro` 和 `sub2api`
- 用户拿哪个套餐，不由前端决定，而由后台建档和本地用户记录决定

## 4. 数据模型

### `portal_users`

关键字段：

- `provider_key`
- `upstream_user_id`
- `upstream_api_key`
- `workspace`
- `email`
- `plan_key`
- `enabled`

这里最关键的是：

- `provider_key` 决定用户属于哪个 provider
- `upstream_api_key` 保存这个用户真实可用的上游 API key

当前实现已经为 `upstream_api_key` 建索引，供网关快速反查用户。

### `portal_entry_providers`

关键字段：

- `entry_key`
- `kind`
- `public_url`
- `admin_url`
- `api_base_url`
- `health_url`
- `admin_api_key_encrypted`
- `default_allowed_groups`
- `default_concurrency`
- `initial_balance`
- `embed_mode`

用途：

- 后台展示 provider 状态
- 保存 Sub2API 的外部地址和管理凭据
- 决定是否允许远端同步

## 5. 用户创建流程

### Kiro 用户

1. 本地校验参数
2. 调用 Kiro 上游创建真实用户
3. 保存 `upstream_user_id` 和 `upstream_api_key`
4. 用户登录后在统一工作区面板查看自己的 key 和 base URL

### Sub2API 用户

1. 本地校验参数
2. 调用 Sub2API 管理接口创建远端用户
3. 用该用户邮箱和密码登录 Sub2API
4. 为该用户申请 API key
5. 把得到的 key 保存到 `portal_users.upstream_api_key`

这样做的结果是：

- 用户前台不需要再跳去第二套门户拿 key
- 当前 relay 可以直接把这把 key 当作用户的调用凭据
- `/v1/*` 可以统一按 key 路由

## 6. 网关路由流程

请求进入 `/v1/*` 后，服务端按以下顺序处理：

1. 从 `Authorization`、`x-api-key` 或 `x-goog-api-key` 提取 key
2. 在 `portal_users.upstream_api_key` 中查找本地用户
3. 检查该用户是否启用
4. 根据 `provider_key` 查找 provider 配置
5. 构造目标 API Base URL
6. 去掉客户端原始鉴权头
7. 注入真实上游鉴权头
8. 转发到目标 provider

其中：

- `kiro` 的 `/v1/responses` 继续走兼容转换
- 非 `kiro` provider 的 `/v1/responses` 直接透传
- `kiro` 不支持 `/v1/responses/*` 子路径时会明确返回 400

## 7. 管理后台职责

后台负责 provider 维度的管理，不负责给用户展示 provider 差异。

管理员可以做的事情包括：

- 新建和编辑用户
- 选择用户归属的 provider
- 保存或更新 Sub2API 的 `public/admin/api/health` 地址
- 保存或清除 Sub2API 的 `admin API key`
- 查看 provider 健康和诊断信息
- 管理快照、账号池和注册任务

这也是为什么用户前台统一后，后台仍然必须保留 provider 管理能力。

## 8. Sub2API 配置原则

Sub2API 接入按服务端思维处理：

- 可以使用域名
- 也可以直接使用 IP 地址
- 生产环境建议用环境变量托管
- 后台主要用于查看状态和补齐配置，不应成为唯一的配置来源

一个典型的 IP 配置示例是：

- `public_url = http://203.0.113.10:8080`
- `admin_url = http://203.0.113.10:8080/admin`
- `api_base_url = http://203.0.113.10:8080/v1`
- `health_url = http://203.0.113.10:8080/health`

当 `admin_api_key` 有效时，provider 进入 `remote_sync`。
当只有地址、没有管理密钥时，provider 只能停留在 `local_only`。

## 9. 为什么不在前台区分 Kiro 和 Sub2API

因为对用户来说，这两者不应该体现为两套站点入口，而应该只是“不同来源的套餐”。

如果前台也做 provider 区分，会带来这些问题：

- 用户需要理解不必要的内部实现细节
- 同一个门户会出现两套注册和交付心智
- API Key、Base URL 和使用方式无法统一

当前架构选择的是：

- 前台统一
- 后台区分
- 网关自动路由
- 本地用户记录承担 provider 归属

这更符合正式服务端系统，而不是演示型页面。

## 10. 边界与约束

- 本仓库负责接入和管理 Sub2API，不内置 Sub2API 进程本体
- 如果 Sub2API 未配置 `admin API key`，就不应把它当成可正式交付套餐
- 用户 API key 现在直接对应真实上游 key，因此数据库保护和备份策略必须按生产标准执行
- provider 配置若由环境变量托管，后台应只读展示，避免和运维配置打架
