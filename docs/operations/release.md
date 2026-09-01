# 发布包边界

`scripts/build-release.*` 只生成临时发布目录，不把产物写回源码目录。发布包包含：后端运行源码、`backend/frontend_dist` 前端构建物、启动脚本、README、LICENSE 和必要的沙箱参考配置。发布包只启动 FastAPI，由 `http://127.0.0.1:<port>` 同时提供 REST/SSE 和 SPA，不需要独立前端服务器。

发布包排除：DevPanel、Mock、测试、开发文档、`.git`、虚拟环境、node_modules、日志、截图、用户数据、上传文件、知识库和任何密钥。

发布前必须通过后端/前端测试、契约快照检查、secret scan、路径扫描和全新环境启动冒烟测试。当前发布目标仍是本地单用户，不是公网多用户服务。
