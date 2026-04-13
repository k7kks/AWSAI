# 项目结构与文件说明

## 顶层目录

### `server.py`

主服务入口。包含：

- Flask app 创建
- 用户/管理员认证与会话
- provider 配置与诊断
- Kiro upstream 管理接口代理
- OpenAI 兼容 `/v1/*` 转发
- 快照接口
- 注册任务接口

这是整个系统最核心的文件。

### `index.html`

统一门户页面。用户页和管理页都从这里渲染。

### `assets/`

前端静态资源目录。

- `assets/app.js`：页面状态、接口调用、表单交互、provider 管理逻辑
- `assets/styles.css`：门户 UI 样式
- `assets/registration-manager.html`：注册任务相关页面（如果存在）

### `start.ps1`

只启动门户服务，不负责拉起上游 Kiro 进程。适合本地调试门户。

### `start-stack.ps1`

启动完整开发/单机栈：

- 启动上游 Kiro 进程
- 注入环境变量
- 启动 Flask 门户
- 记录 PID 和日志路径

### `stop-stack.ps1`

停止 `start-stack.ps1` 拉起的进程。

### `bootstrap-admin.ps1`

调用 `server.py bootstrap-admin`，快速创建或重置本地管理员。

### `build-release.ps1`

生成发布压缩包，不包含运行期数据库。

### `requirements.txt`

Python 依赖列表。

### `.env.example`

环境变量样例，包含：

- Kiro upstream 配置
- 门户公网地址配置
- 会话安全配置
- Sub2API 环境变量托管配置

### `portal.db`

本地 SQLite 数据库。保存：

- 门户用户
- 管理员
- provider 配置
- 会话
- 注册任务
- 注册日志

生产环境应纳入备份。

## 目录说明

### `assets/`

门户前端资源。

### `configs/`

本地配置文件目录。如果后续引入额外配置文件，建议落在这里。

### `deploy/`

部署相关文件。

- `deploy/windows/install-relay.ps1`：Windows 初始化脚本
- `deploy/linux/install-relay.sh`：Linux 安装脚本
- `deploy/linux/*.service`：systemd 单元
- `deploy/Caddyfile.example`：反向代理示例

### `dist/`

发布构建产物目录。

### `run/`

运行时目录。常见内容：

- `portal-session-secret.txt`
- `encryption.key`
- `services.json`
- 日志文件

### `snapshots/`

快照归档目录。

### `tools/`

工具脚本目录。当前包含快照管理等辅助功能。

### `upstream/`

上游 Kiro/claude-server 运行文件和数据。

### `sub2api-main/`

引入的 Sub2API 上游源码，用于：

- 对照接口实现
- 后续独立部署 Sub2API
- 验证 Admin API 路由与健康检查行为

当前并不是由本仓库直接把它编译成在线服务。

## 业务脚本

### 注册相关

- `registration_service.py`：注册任务的服务层逻辑
- `register_now.py`：自动注册脚本
- `auto_email_registration.py`：邮箱注册流程脚本
- `full_auto_email_registration.py`：更完整的自动注册流程
- `captcha_solver.py`：验证码处理逻辑

这些脚本属于“运营/账号准备工具”，不是门户主链路。

### 账号池相关

- `account_pool_manager.py`
- `account_pool.json`

用于本地账号池管理或辅助逻辑。

### 调试脚本

- `debug_*.py`
- `check_*.py`

主要用于开发排障，不属于正式对外接口。

## 推荐阅读顺序

如果是第一次接手项目，建议按这个顺序读：

1. `README.md`
2. `docs/ARCHITECTURE.md`
3. `server.py`
4. `assets/app.js`
5. `start-stack.ps1`
6. `deploy/linux/install-relay.sh`

## 哪些文件是正式服务链路

正式服务链路核心文件：

- `server.py`
- `index.html`
- `assets/app.js`
- `assets/styles.css`
- `start.ps1`
- `start-stack.ps1`
- `stop-stack.ps1`
- `deploy/linux/*`
- `.env.example`

## 哪些文件更偏工具或实验

以下内容更偏运维工具、注册准备或调试：

- `register_now.py`
- `debug_*.py`
- `check_*.py`
- `AUTO_EMAIL_README.md`
- `REGISTER_MANAGER_README.md`

这些文件重要，但不应与门户主链路混在一起理解。
