# LiBao MCP Gateway 接入计划

## Goal

把用户提供的远程 MCP Gateway 注册到 LiBao Agent 的本地 MCP 配置中，并确认 LiBao 能完成鉴权、初始化和工具发现。不要修改 Codex 配置，也不把凭据写入仓库。

## Architecture / Current Integration Point

- LiBao 已有 `POST /api/v1/tools/mcp/register` 注册接口。
- 注册服务会用请求中的 URL 和请求头连接 MCP Gateway，执行初始化与工具列表发现，并将服务记录写入 LiBao 本地数据目录 `~/.LiBao/mcp_servers.json`。
- LiBao 的服务级 `enabled` 与工具定义的启用状态分开；本次注册启用服务，但发现的工具仍需按需在 LiBao 工具管理界面启用。
- 认证头使用用户在本次请求中提供的 `Authorization` 值；凭据值不写入本计划、进度账本、仓库或最终回复。

## Global Constraints

- 目标是用户的 LiBao Agent 项目，不是 Codex。
- 保留工作区已有修改，不执行 reset、checkout 或清理操作。
- 只改 LiBao 的本地运行数据；除非现有注册链路无法完成，否则不改项目源码。
- 命令输出只展示脱敏后的注册结果，不打印 Authorization 值或完整配置文件。
- 完成后给出通过 LiBao API 添加其他 MCP 服务的可复用格式，并说明带鉴权服务如何处理。

## Tasks

### 1. 通过 LiBao 现有注册链路接入 Gateway

**Files / State**

- Read and verify `C:/Users/Admin1/.LiBao/mcp_servers.json` without exposing header values.
- Use the existing backend route in `apps/backend/app/api/routers/tools.py`; no source edit is expected.
- Persist only to LiBao's local runtime data under `C:/Users/Admin1/.LiBao/`.

**Interface**

Send a registration request to `http://127.0.0.1:<LiBao-port>/api/v1/tools/mcp/register` with:

- `name`: `my-gateway`
- `url_or_command`: `http://119.91.36.153:8080/mcp`
- `headers`: an `Authorization` header whose value is supplied at execution time from the user's credential
- `enable`: `true`

**Steps**

1. Check the existing local LiBao data and whether the default backend port is already in use.
2. Start LiBao's backend only if needed.
3. POST the registration request and capture only status, server name, URL, enabled state, and discovered tool count.
4. Verify the persisted record has the expected name/URL, contains the Authorization header key, and has at least the returned discovered tools.

### 2. Verify and document self-service additions

**Verification**

- Check LiBao health and registration response through the running local API.
- Run the focused MCP/backend tests that already exist; if a check fails, diagnose the cause before changing anything.
- Review the final diff/status to ensure no Codex configuration or repository source was changed by this task.

**User handoff**

- Explain the JSON fields for adding another URL-based or stdio MCP server.
- Provide the LiBao API endpoint and a safe request example with a token placeholder in the explanation only.
- Explain that newly discovered tools may need individual enabling in LiBao.
