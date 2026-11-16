# 检索策略与参数

## 默认参数

| 参数 | 默认值 | 说明 |
|---|---|---|
| `TOP_K` | 5 | 最终送入 LLM 的上下文块数 |
| `CHUNK_SIZE` | 500 | 文本切分长度（字符） |
| `CHUNK_OVERLAP` | 50 | 相邻块重叠 |
| `SIMILARITY_THRESHOLD` | 0.7 | 相似度阈值 |
| `CACHE_TTL_SECONDS` | 3600 | 热 FAQ 缓存有效期 |
| `ENABLE_QUERY_REWRITE` | true | 查询改写 |
| `ENABLE_CONTEXT_COMPRESSION` | true | 上下文压缩 |
| `ENABLE_RERANKER` | false | Cross-Encoder 重排（需本地模型） |
| `ENABLE_SELF_RAG` | false | 点踩后的 Self-RAG 纠错 |
| `ENABLE_AUTO_STRATEGY` | false（示例配置为 true） | 按问题特征自动选路 |

## 策略

### hybrid

- FAISS 向量召回 20 条 + BM25 关键词召回 20 条；
- RRF 融合：`score = 3.0 / (k + rank_dense) + 1.0 / (k + rank_bm25)`，`k = 60`；
- 可选重排后送入上下文压缩。

### dense

- 仅 FAISS `IndexFlatIP` 内积检索；
- Embedding 为本地 `BAAI/bge-small-zh-v1.5`（512 维），或 DashScope `text-embedding-v3`（1024 维）。

### bm25

- `jieba` 分词 → `rank_bm25.BM25Okapi`；
- 适合电话、编号、开放时间、费用等精确信息。

### hyde

- 先让 LLM 生成一段“假设答案”，再用假设答案做向量检索；
- 适合“怎么补办”“怎么办”这类口语化问题。

### multi（Multi-Query）

- LLM 生成 3 路不同表述的查询；
- 分别检索后 RRF 融合，提升召回覆盖率。

### decompose

- LLM 把复合问题拆成多个子问题；
- 逐个检索后合并、去重。

### parent_child（Small-to-Big）

- 子块 300 字用于检索，父块 1000 字用于返回；
- 兼顾检索精度与上下文完整性。

### full（CRAG）

- 先检索并做相关性自检；
- 低质量时改写问题、重新检索；
- 可叠加 Self-RAG：点踩后触发“诊断 → 改写 → 重新生成”。

### auto

按问题语言特征选择策略：

| 特征 | 策略 |
|---|---|
| 口语词（咋、啥、呗…） | `hyde` |
| 对比 / 区别 / 优缺点 | `decompose` 或 `multi` |
| 怎么办 / 怎么解决 | `multi` |
| 什么是 / 有哪些方法 | `dense` |
| 流程 / 电话 / 时间 / 费用 / 材料 | `bm25` |
| 短问题（≤ 8 字） | `multi` |
| 其他 | `hybrid` |

## 评测与调参

开发报告中的参数扫描结论：在当时的 487 个文本块、1024 维 Embedding 条件下，`chunk_size=500`、`overlap=50`、`TopK=5` 的综合表现最好。报告还包含 RAGAS 忠实度 / 相关性评测脚本与参数扫描脚本的说明，见 `docs/reports/`。
