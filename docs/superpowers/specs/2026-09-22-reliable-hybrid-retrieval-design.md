# LiBao 可靠混合检索改造设计

**状态：** 设计已确认，等待用户审阅

## 背景

LiBao 当前知识库以 `index.json` 保存集合、文档和分块元数据，以 LanceDB 保存向量，并以进程内 `rank_bm25` 保存关键词索引。检索时分别取语义与 BM25 前 50 条，通过 RRF（`k=60`）合并前 20 条候选，再调用 Cross-Encoder rerank 取得最终结果。

现有链路能完成基本混合检索，但索引生命周期存在结构性风险：

- 服务启动时扫描所有集合并全量重建内存 BM25，数据量增长后启动时间和可用性不可控。
- `insert_chunks` 在文档状态仍为 `indexing` 时重建 BM25，而语料收集只接受 `indexed` 文档，新文档可能直到下一次重建或重启才进入关键词索引。
- 归档只修改 `index.json` 中的文档状态，没有同步删除或停用 LanceDB 行，也没有刷新 BM25；语义通道只依据 LanceDB 行状态过滤，因此归档文档可能继续被召回。
- 重索引会覆盖元数据并修改多个存储位置，但没有“旧版本继续服务、新版本准备完成后切换”的机制；中途失败可能留下跨存储不一致。
- 固定字符滑窗不理解标题、段落、句子或模型 token 边界；中文 BM25 逐字分词导致短语语义弱、索引膨胀且排序不稳定。
- 语义通道和 rerank 的故障会静默降级，调用方无法判断结果来自完整混合链路还是单通道回退。
- 当前测试主要验证正常路径，没有覆盖进程重启、增量索引、部分写入、失败回滚、并发重建和迁移恢复。

## 设计目标

1. BM25/全文索引持久化并随新增数据增量更新，服务启动不再全量重建。
2. 上传、重索引、归档、删除在文件元数据和 LanceDB 之间保持可恢复的一致性。
3. 新版本构建失败时继续使用旧版本，避免重索引造成检索空窗。
4. 中文、英文、代码标识符及中英混合内容都具备稳定的词法召回能力。
5. 分块优先保留文档结构，并严格受 token 上限约束；语义分块必须经过评测后才能启用。
6. 保留现有 `semantic`/`bm25` API 开关和 RRF＋rerank 主链，降低兼容风险。
7. 通过离线数据集、故障测试和运行时诊断证明可靠性，而不是只依赖人工体验。

## 非目标

- 不引入 Elasticsearch、OpenSearch、Qdrant 等外部检索服务。
- 不在第一阶段引入 GraphRAG、知识图谱构建或复杂多路查询改写。
- 不默认调用 LLM 为每个分块生成上下文摘要，避免索引成本和不可重复性突然增加。
- 不承诺语义分块一定优于结构分块；它是可选实验策略，不是默认路径。
- 不在本次改造中更换 Embedding 或 rerank 服务商。
- 不把 `index.json` 直接升级成通用数据库；它仍保存面向用户的集合和文档元数据。

## 方案选择

采用现有 LanceDB 内聚方案：向量与持久化 FTS 共用同一张分块表，词法通道使用 LanceDB/Tantivy BM25 索引。默认 tokenizer 采用 ICU，支持中文、英文和混合文本；`jieba/default` 作为显式可选项，仅在本地语言模型资源完整且评测优于 ICU 时启用。

该方案相比继续使用 `rank_bm25`，消除了启动全量重建和独立内存索引；相比另建 Tantivy 服务或外部搜索服务，减少了双存储写入、部署和恢复复杂度。LanceDB 新写入的尚未合并片段仍可参与全文检索，后台 `optimize` 负责把增量片段并入索引，不阻塞文档立即可搜。

## 数据模型

### index.json v2

集合索引升级为版本 2。文档除现有字段外增加：

- `active_generation`：当前对检索可见的索引代次；首次索引成功前为空。
- `building_generation`：正在构建的代次；没有任务时为空。
- `index_state`：`idle`、`building`、`activating`、`cleanup_pending` 或 `repair_required`。
- `chunking_version`：分块算法及参数版本。
- `retrieval_schema_version`：LanceDB 分块表和 FTS 配置版本。
- `embedding_model`、`embedding_dimension`：本代索引的向量兼容性快照。
- `last_indexed_at`、`last_index_error`：诊断与恢复信息。

分块元数据按 `document_id -> generation -> chunks` 保存，不再直接覆盖唯一一组 chunks。每个分块至少记录：

- `chunk_id`、`generation`、`chunk_index`；
- 原始 `content` 与用于词法检索的 `retrieval_text`；
- `section_path`、字符偏移、token 数；
- 分块策略和算法版本。

`index.json` 继续使用临时文件＋`os.replace` 原子写入。读取旧版文件时执行内存规范化；只有迁移成功后才写回 v2，避免半迁移文件。

### LanceDB chunks_v2

新建版本化分块表，至少包含：

- `chunk_id`、`document_id`、`collection_id`、`org_id`；
- `generation`、`chunk_index`；
- `content`、`retrieval_text`；
- `section_path`、`start_offset`、`end_offset`、`token_count`；
- `vector`、`embedding_model`、`schema_version`；
- `created_at`。

FTS 建在 `retrieval_text` 上。`retrieval_text` 由文件名、标题层级、必要元数据和原始分块正文确定性拼接，返回给用户的仍是 `content`，避免检索增强文本污染答案引用。

LanceDB 不再把 `status='indexed'` 作为唯一可见性来源。检索结果必须经过 `index.json` 中 `active_generation` 校验；即使崩溃留下 staging 或旧代行，也不会对用户可见。

## 索引状态机与一致性

### 首次索引和重索引

每个文档使用进程内异步锁串行化索引、归档和删除操作。流程如下：

1. 读取文档当前 `active_generation`，创建新的唯一 generation。
2. 写入 `building_generation` 和 `index_state=building`，保留旧 active 代次不变。
3. 提取结构、分块、计算 `retrieval_text`，再批量生成 embedding。
4. 将新代分块写入 LanceDB；创建 FTS 只发生在首次建表或检索 schema/tokenizer 版本变化时，不在每次写入后重建。
5. 校验新代的分块数量、chunk ID 唯一性、向量维度、空文本、Lance 行数和最小检索冒烟结果。
6. 原子更新 `index.json`：把新 generation 设置为 `active_generation`，清空 building 状态，并更新文档为 `indexed`。
7. 异步清理旧代 Lance 行和旧代分块元数据；清理失败记录为 `cleanup_pending`，但不影响新代服务。

任何第 6 步之前的失败都只清理新代数据并保留旧 active 代次。若文档没有旧 active 代次，则状态为 `failed`；若旧代仍可用，用户态保持可检索，并单独记录本次重建错误。

### 归档与删除

归档先在原子元数据中把文档设为 `archived`，搜索的 active-generation 校验立即排除该文档；随后清理 Lance 行。即使物理清理失败，文档也不会继续出现在结果中。

删除先写入逻辑删除标记并撤销 active generation，再删除 Lance 行、分块元数据和原文。物理清理可重试，检索可见性不依赖清理是否完成。集合删除复用相同顺序批量处理。

### 启动恢复

启动时不扫描语料重建 BM25，只执行轻量恢复：

- 确认分块表及所需 FTS 索引存在且版本兼容；
- 扫描具有 `building_generation`、`activating`、`cleanup_pending` 或 `repair_required` 的文档；
- 清理未激活的孤立代次，或完成已激活版本的延迟清理；
- 对 active 代次做元数据与 Lance 行数校验；异常只标记对应文档，不阻塞其他知识库启动。

恢复操作必须幂等，同一任务运行多次结果一致。

## 分块策略

默认 `chunking_strategy=auto`，采用确定性多阶段分块：

1. 依据文档类型保留 Markdown 标题、列表、代码块及自然段等结构边界。
2. 对超过上限的结构块使用递归分隔符继续切分，优先级为标题/段落、换行、句末标点、空白，最后才按 token 硬切。
3. 使用与 embedding 模型相适配的 token 计数器约束最大块大小；无法加载专用 tokenizer 时使用稳定的回退估算，并在元数据中记录。
4. 小块只与同一 section 内相邻块合并，不跨标题拼接无关内容。
5. overlap 只用于被强制切开的长块，按 token 比例设置并受绝对上限限制；天然结构块不机械重复。

保留现有 `chunk_size` 和 `overlap` API 字段，但解释为最大 token 数和强制切分重叠上限。旧集合迁移时记录旧参数，重索引后才采用新算法。

增加可选 `semantic` 策略：先按句子生成 embedding，再依据相邻语义距离寻找断点，并始终经过递归 token 上限保护。该策略默认关闭；只有离线评测在目标语料上达到门槛后，才能由集合配置显式启用。语义分块失败时确定性回退到 `auto`，并记录诊断。

## 中文和混合语言词法检索

- 默认 FTS tokenizer 为 ICU，避免当前逐字插空格。
- `retrieval_text` 保留原始中文、英文单词、数字和代码标识符，不预先破坏文本。
- Jieba 作为配置项，不作为默认依赖；启用前验证语言模型资源、索引可复现性和部署包完整性。
- 建立中文短语、专有名词、英文缩写、版本号、函数名和中英混合查询的 golden 数据集。
- 不把 tokenizer 的原始 BM25 分数与向量距离直接相加；继续使用基于排名的融合，避免不同分数空间不可比。

## 检索链路

1. 校验查询和集合权限，加载目标文档的 active generation 映射。
2. 语义搜索与 FTS 搜索并行执行；每路召回数量可配置，默认保持当前 50。
3. 两路结果都过滤非 active generation、归档、软删除和跨组织数据；不足时允许有限 over-fetch 补足。
4. 对每路结果按 chunk ID 去重，使用 RRF 融合；首版保持 `k=60` 和等权，避免无评测依据的调参。
5. 取前 20 个候选进行 rerank；rerank 不可用时保留确定性的 RRF 顺序。
6. rerank 后合并同文档高度重叠的相邻块，必要时附带前后邻块作为上下文，但命中分块和分数保持可追踪。
7. 返回 top-k 及来源信息。普通 API 保持兼容；内部诊断额外记录每个候选的通道排名、RRF 分数、rerank 分数和降级原因。

语义通道、FTS 通道或 rerank 单独失败时允许降级；双召回通道都失败时返回明确错误，而不是伪装成“没有结果”。

## FTS 索引维护

- 应用启动调用 `ensure_fts_index`，只在索引缺失或 tokenizer/schema 版本变化时创建新索引。
- 正常上传只追加新代行，不执行全量重建。
- `optimize` 按新增/删除行阈值、碎片数或定时维护触发，不在用户请求中同步执行。
- 维护任务加全局互斥锁；失败仅记录待维护状态，不影响新写入通过增量片段被查询。
- 暴露索引版本、待清理 generation 数、碎片/未优化规模、最近 optimize 时间和最近错误等健康信息。

## 迁移与回滚

采用旁路迁移，不原地破坏现有 `vectors.lance`：

1. 创建 `chunks_v2` 及 ICU FTS。
2. 从现有 `index.json` 与旧 Lance 表读取 chunk 文本和向量，生成 generation、`retrieval_text` 与结构元数据；向量模型和维度兼容时直接复制，不重复调用 embedding。
3. 对每个文档校验旧 chunk 数、新表行数和可检索性，通过后才写入 v2 active generation。
4. 所有文档迁移完成并通过全局验收后，运行时切换到 v2。
5. 旧表和旧 index 备份保留一个明确的兼容窗口；失败时运行时继续使用旧链路，不删除旧数据。

迁移记录按文档持久化，可中断、续跑和幂等重试。任何不兼容向量维度或缺失旧行都标记为需要重新 embedding，不以空向量迁移。

## API 与配置兼容性

- `POST /kb/search` 现有 `hybrid={semantic,bm25}` 保持有效；`bm25` 名称继续作为 API 兼容别名，内部实现改为 LanceDB FTS。
- 集合创建增加可选 `chunking_strategy`、token 上限和 tokenizer 配置；旧请求仍使用兼容默认值。
- 搜索响应原有字段不删除。调试详情只在显式 debug 参数或受保护诊断接口中返回，避免改变 Agent 工具上下文。
- 配置增加 FTS tokenizer、召回池大小、RRF k、rerank 候选数、optimize 阈值和恢复策略；默认值保持现有检索行为。
- embedding 模型、维度、分块版本或 tokenizer 改变时必须生成新的 retrieval schema/version，不允许静默复用不兼容索引。

## 可观测性

每次搜索生成 request ID，并记录：

- 语义、FTS、融合、rerank 各阶段耗时和命中数；
- 实际使用的索引版本、tokenizer、embedding 与 rerank 模型；
- 各通道是否成功、降级原因及最终采用的排序路径；
- 被 generation/status/权限过滤的候选数量。

日志不得记录完整敏感文档正文。健康检查区分“可用但降级”“需要维护”“不可检索”，方便 Web 端和运维判断真实状态。

## 测试与评测

### 单元测试

- 结构分块不跨标题错误合并，长块遵守 token 上限，重叠只出现在强制切分处。
- ICU 对中文短语、中英混合、数字和代码标识符产生稳定命中。
- generation 切换、旧代保留、清理重试和恢复操作幂等。
- RRF 排序确定、通道开关兼容、相邻块去重稳定。

### 集成与故障测试

- 新文档索引完成后立即可被 FTS 命中，进程重启后仍可命中且没有全量重建。
- 在分块、embedding、Lance 写入、验证、激活和清理每一步注入失败；旧 active 代次始终可用。
- 归档和删除返回成功后，语义与 FTS 两路都立即不可见。
- 同一文档并发重建、重建期间归档/删除不会产生双 active 或状态回退。
- 启动可清理孤立 building generation，并能继续未完成的延迟清理。
- FTS、embedding、rerank 分别故障时符合降级契约；双召回故障返回明确错误。
- v1 到 v2 迁移可中断续跑，校验失败可回滚到旧链路。

### 离线质量评测

建立项目内固定、版本化的中文与混合语言问答集，至少覆盖：

- 直接关键词、同义表达、跨段信息、标题定位；
- 中文专有名词、英文缩写、代码/API 名、版本号；
- 多个近似文档的区分、无答案问题和归档文档排除。

报告 Recall@5/10、MRR、nDCG@10、rerank 前后增益、无答案误召回率和 P95 延迟。迁移后的默认方案不得低于现有基线 Recall@10；中文精确词法查询必须全部通过 golden 测试；任何准备默认启用的语义分块或 tokenizer 变更必须在同一数据集上证明收益且无显著延迟回归。

## 分阶段交付

1. 建立检索基线、golden 数据和故障测试骨架。
2. 引入 `chunks_v2`、持久化 FTS、版本配置和旁路迁移器。
3. 实现 generation 状态机、文档锁、启动恢复及归档/删除一致性。
4. 实现结构感知＋递归 token 分块，并增加 ICU/Jieba 可配置词法策略。
5. 改造混合搜索并行召回、active 过滤、诊断和明确降级语义。
6. 补齐 API、Web 配置/健康展示和运维文档。
7. 完成迁移演练、离线评测、性能测试和回滚验证后再切换默认链路。

## 验收标准

1. 启动日志和测试证明服务重启不会扫描全部分块重建 BM25。
2. 新增文档完成索引后可立即被语义与 FTS 两路检索，重启后结果保持一致。
3. 重索引任意阶段失败都不会让已成功索引的旧版本消失。
4. 归档或删除成功后，两路检索都无法返回目标文档，即使 Lance 物理清理暂时失败。
5. 同一文档不存在两个对用户可见的 active generation，恢复任务可幂等修复中间状态。
6. 中文短语、中英混合、代码标识符和版本号的 golden 查询全部通过。
7. 混合检索、单通道降级和 rerank 降级均有可观察诊断；双通道失败不会返回误导性的空结果。
8. v1 数据可旁路迁移、断点续跑并安全回滚，迁移前数据不被破坏。
9. 离线 Recall@10 不低于当前基线，P95 延迟和索引资源使用处于设定预算内。

## 参考依据

- LanceDB Full-text Search：持久化 FTS、增量片段查询及 optimize 生命周期。
- Lance/Tantivy tokenizer：ICU 适用于 CJK/混合文本，Jieba 依赖本地语言模型资源。
- LangChain RecursiveCharacterTextSplitter 与 LlamaIndex SemanticSplitter：递归边界和可选语义断点实现参考。
- Anthropic Contextual Retrieval 与 Late Chunking：`retrieval_text` 和上下文保留思路，但首版采用确定性低成本实现。
- RAGAS 指标体系：检索相关性、上下文精确度与召回评测参考。
- 近期分块评测研究：语义分块收益与任务相关，因此必须以项目数据评测后启用。
