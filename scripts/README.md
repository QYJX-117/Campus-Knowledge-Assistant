# 脚本目录

- `perf_test.py`：并发问答压测。先启动后端，再运行：

  ```bash
  cd backend
  uv run python ../scripts/perf_test.py
  ```

  默认使用本地演示管理员 `admin@campus.example / admin123`，可在脚本顶部修改 `BASE`、`EMAIL`、`PASSWORD`。

知识库索引的构建入口在后端 CLI：

```bash
cd backend
uv run python -m app.cli
```

该命令会加载 `../knowledge-base/` 下的 Markdown 文档并写入 FAISS / BM25 索引；首次启动服务时也会自动执行。
