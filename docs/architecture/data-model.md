# 数据模型与运行数据

本地单机版本不依赖 SQL 数据库。业务数据由 FileStore/JSONL 保存，知识库和记忆使用 LanceDB/BM25，checkpoint、上传文件和工作区使用独立目录。

默认布局：

```text
~/.LiBao/
├── settings.json
├── conversations.json / tasks.json / ...
├── sessions/
├── task_events/
├── checkpoints/
├── kb/
├── uploads/
├── workspaces/
└── cache/
```

源码仓库不应包含上述运行数据。升级逻辑必须保持幂等，并为配置、checkpoint 和文件表格式变化补充回归测试。
