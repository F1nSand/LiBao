# 贡献指南

## 开发环境

1. 安装 Python 3.12+、Node.js 20+ 和 uv。
2. 复制 `examples/settings.example.json` 到 `~/.LiBao/settings.json`，只在本机填写密钥。
3. 运行 `scripts/bootstrap.cmd` 或 `scripts/bootstrap.sh`。
4. 使用 `scripts/dev.cmd` 或 `scripts/dev.sh` 启动开发环境。

## 提交前检查

```text
scripts/test.cmd       # Windows
scripts/test.sh        # Linux/macOS
```

后端和前端分别修改时，必须同时更新对应测试、Mock 契约和 `contracts/openapi.json`。不要提交 `.env`、用户数据、构建产物、截图、虚拟环境或本机绝对路径。

## Pull Request

- 一个 PR 聚焦一个行为或结构变更。
- 描述影响范围、兼容性和验证命令。
- API、SSE 事件或配置字段变化需要同步更新 `docs/api/`。
- 不要在 issue、PR 或日志中粘贴真实密钥、用户内容或工作区文件。
