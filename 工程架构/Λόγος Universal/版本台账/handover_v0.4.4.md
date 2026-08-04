# Λόγος Agent · 工作交接文档

**交接时间**: 2026-08-01  
**当前版本**: v0.4.4（开发中，未发版）  
**交接人**: Kimi-1（当前会话）→ Kimi-2（新会话）  
**目标**: 继续完成 Phase 4 GraphRAG 与 Synthesize 集成优化（选项 B）

---

## 一、开发进度总览（对照设计文档 v0.3.0）

| 阶段 | 设计文档章节 | 状态 | 关键文件 | 备注 |
|------|-------------|------|---------|------|
| Phase 1 | 8.1 Fast Lane 先行 | ✅ 已完成 | Dify 侧工作流 | 不涉及外部引擎代码 |
| Phase 2 | 8.2 外部引擎骨架 | ✅ 已完成 | `api/planner.py`, `api/retrieve.py`, `core/planner/`, `core/search_*.py` | 召回率提升 +33.3% |
| Phase 2.5 | 8.3 记忆系统 MVP | ✅ 已完成 | `core/memory/ledger.py`, `profile.py`, `views.py`, `policy.py`, `search.py` | Ledger(JSONL)+Profile(SQLite)+Views(Chroma) |
| Phase 3 | 8.4 棱镜闭环 | ✅ 已完成 | `core/synthesize.py`, `api/synthesize.py`, `core/citation_validator.py`, `api/citation_validator.py` | Dify 侧已接入 deep_synthesize Tool |
| Phase 4 | 8.5 Skill Menu 与 GraphRAG | 🔄 **进行中** | `core/graphrag/extractor.py`, `graph_store.py`, `community.py`, `query_engine.py`, `api/graphrag.py` | **B选项（Synthesize+GraphRAG集成）未完成** |
| Phase 5 | 8.6 调优与硬化 | ⬜ 未开始 | — | — |

### 1.1 Phase 4 已完成部分（本次会话前）

- `core/graphrag/extractor.py` — 实体关系抽取引擎（DeepSeek-V4 Flash，max_tokens=4000，截断检测+重试）
- `core/graphrag/graph_store.py` — NetworkX 有向图存储（实体去重 0.85 阈值、别名回查、pickle+GEXF 持久化）
- `core/graphrag/community.py` — Louvain 社区发现 + LLM 社区摘要（**v0.4.4 已并行化**：Semaphore(10) 限制并发）
- `core/graphrag/query_engine.py` — 图查询引擎（实体搜索、子图展开、社区聚合、全局查询）
- `api/graphrag.py` — 9 个 REST 端点（extract/build/query/entity/communities/save/load）
- `api/retrieve.py` — 已集成 BackgroundTasks 自动后台构建图谱（检索返回后立即 enrich，不阻塞）
- `main.py` — 版本 0.4.0，注册 GraphRAG 路由 + shutdown 时保存图谱
- `test_phase4_e2e_graphrag.py` — E2E 测试脚本（5 个用例）

### 1.2 本次会话已完成（B 选项部分）

1. **GraphRAG 上下文注入 Synthesize** ✅
   - `core/synthesize.py`: `generate_report` / `_generate_report_core` 新增 `graph_context` 参数
   - `_build_system_prompt()`: 新增规则 8-11（图谱使用规则，citation 必须指向检索结果 chunk_id）
   - `_build_user_prompt()`: 新增 `graph_context` 注入块
   - `api/synthesize.py`: `SynthesizeRequest` 新增 `graph_context` 字段；`deep_synthesize` 自动调用 `GraphQueryEngine.global_query` 获取图谱上下文；响应新增 `graph_context_injected` 和 `auto_retrieved` 标记
   - **修复**: 显式传入 `graph_context` 时 `graph_context_injected` 标记正确置为 `True`（原bug：仅自动查询成功时才置True）

2. **性能优化（部分完成）** ⚠️
   - `api/synthesize.py` v0.4.4: 检索与图谱查询**并行化**（`asyncio.gather`），减少约 30-60s 串行等待
   - `api/graphrag.py` v0.4.4: Build 端点强制后台阈值从 3 调到 **20**（`CHUNK_SYNC_LIMIT = 20`），同步模式也使用批量抽取
   - `core/graphrag/community.py`: `build_all_summaries()` 已改为**并行化**（`asyncio.gather` + `Semaphore(10)`），75个社区从 240s 压缩到 20s
   - `api/retrieve.py`: 后台 build `_background_graph_build()` 已改为调用 `extract_entities_relations_batch`

### 1.3 本次会话未完成 / 存在 Bug

- **Batch 抽取 Prompt 工程问题** ❌
  - 新增函数 `extract_entities_relations_batch()` 在 `core/graphrag/extractor.py` 末尾
  - **Bug**: LLM 不按要求输出 `{"results": [{"chunk_id": "...", "entities": [...], "relations": [...]}]}` 格式，而是输出 `(subject, predicate, object)` 三元组或截断 JSON
  - **现象**: `_safe_parse_json` 能解析出 JSON，但 `results` 数组为空，导致所有 chunks 返回 `entities=0, relations=0`
  - **Fallback 也失败**: 批量失败后回退到单条 `extract_entities_relations()`，但 DeepSeek API 此时频繁返回空，最终 45s 超时
  - **影响**: TC-GR-01 失败（Build 返回 0 实体/关系），后台 build 也返回 0
  - **尝试过的修复**: `json_mode=False` + `_safe_parse_json` 兜底；降低 batch size 到 2；降低 max_batch_len 到 1800；限制每 chunk 6 实体/4 关系；description 15 字以内 —— **均未解决格式错乱问题**

---

## 二、绝对不可假设的事实（新 Kimi 必须遵守）

1. **当前版本**: `main.py` 中 `version="0.4.0"`，`api/health.py` 硬编码为 `0.2.1`，不同步但不影响功能，可忽略。
2. **知识库内容**: Chroma 向量库和 Dify 知识库中**没有**新能源汽车、市场营销、行业分析类文档。实际内容是《享界超级工厂电力设备综合运维规程》（电力运维）和 FLUX/ComfyUI 提示词文档（AI 绘画）。
3. **检索结果不匹配时的行为**: Synthesize 生成"数据不足"报告、Validate 标记 `missing_citation` 是**正确行为**，不是 Bug。
4. **Dify 当前未运行**（Docker 未启动），Dify KB 检索返回 0 条但不阻塞其他功能。
5. **网页搜索**（Bing/Baidu）已通过 DrissionPage 恢复，端口 9223/9226，但偶发浏览器启动失败（端口冲突/进程残留）。
6. **Dify 部署在机械革命上**，通过 `http://127.0.0.1:8000` 访问外部引擎。
7. **当前图谱已有 276 节点 / 203 边**，存储在 `D:\precision_agent\data\graphrag\`。
8. **Mac Studio Ollama bge-m3 必须启动**，否则 `search_chroma`、`search_memory`、`search_dify_kb` 全部失败（embedding 依赖 Ollama）。
9. **30s 单 chunk 抽取超时**是已知正常行为（LLM 响应不稳定），已有重试机制（2 次）。
10. **Citation Validator 的 content_mismatch**是 LLM 概括性改写的正常表现（状态文档第28条）。
11. **后台 GraphRAG build 30s 超时导致部分 chunk 跳过**是正常行为（状态文档第26条）。

---

## 三、剩余已知问题（精确到代码位置）

| # | 问题 | 位置 | 严重度 | 说明 |
|---|------|------|--------|------|
| 1 | **Batch 抽取 LLM 格式错乱** | `core/graphrag/extractor.py` `extract_entities_relations_batch()` | 🔴 高 | LLM 不输出要求的 `{"results":[...]}` 格式，导致批量抽取全归零。Fallback 单条也因 API 空返回而超时。 |
| 2 | **DeepSeek API 偶发返回空** | `core/llm.py` `call_llm()` | 🟡 中 | 非代码 bug，是 API 稳定性。表现为 `response` 为 `None` 或空字符串，extractor 重试 2 次后仍可能失败。 |
| 3 | **Ollama 依赖未启动时检索层全灭** | `core/chroma_client.py`, `core/memory/search.py` | 🟡 中 | Mac Studio 关机或 Ollama 未运行时，Chroma/Dify KB/Memory 检索全部失败，仅剩网页搜索。 |
| 4 | **浏览器 TabPool 偶发启动失败** | `core/search_bing.py`, `core/search_baidu.py` | 🟡 中 | 端口 9223/9226 被残留 chromium 进程占用时，出现 `NoneType` / `list index out of range` 错误。 |
| 5 | **Community 摘要偶发 JSON 解析失败** | `core/graphrag/community.py` `summarize_community()` | 🟢 低 | LLM 返回空或截断 JSON，已有异常捕获兜底（返回"未知主题"）。 |
| 6 | **Entity-Detail 别名回查边界** | `core/graphrag/graph_store.py` `get_entity()` | 🟢 低 | "变压器"搜索能找到实体，但 `get_entity("变压器")` 返回未找到，需用精确名如"电力变压器"。 |
| 7 | **api/health.py 版本号不同步** | `api/health.py` | 🟢 低 | 硬编码 0.2.1，与 main.py 0.4.0 不同，不影响功能。 |

---

## 四、下一步选项（由用户选择）

| 选项 | 工作项 | 当前状态 | 建议 |
|------|--------|---------|------|
| **A** | Dify 侧 GraphRAG Tool 接入 | 未开始 | 在 Dify 创建 `graphrag_query` 自定义 Tool。需 Dify 先启动。 |
| **B** | Synthesize + GraphRAG 集成 | 🔄 **进行中，未完成** | 核心逻辑（graph_context 注入）已完成，但 **Batch 抽取 Bug 必须修复** 才算稳定。 |
| **C** | Phase 5: 调优与硬化 | 未开始 | 压力测试、浏览器内存泄漏、记忆遗忘策略。 |
| **D** | 补文档/整理 | 未开始 | 更新设计文档至 v0.4.0、部署手册。 |
| **E** | 修复 Batch 抽取 Bug | 🔄 **当前阻塞项** | 可单独作为一步，修复后再继续 B 或其他选项。 |
| **F** | 其他用户指定工作 | — | — |

**建议优先级**: 先选 **E**（修复 Batch 抽取），或回滚 batch 改为纯单条抽取（牺牲一点速度换取稳定性），然后再继续 **A/B/C/D**。

---

## 五、必须上传的文件清单

新 Kimi 必须拿到以下文件才能准确接管。请用户从 `D:\precision_agent\` 打包上传：

### 5.1 核心逻辑层
- `core/synthesize.py`（v0.4.4，含 graph_context 注入）
- `core/citation_validator.py`
- `core/llm.py`
- `core/config.py`
- `core/rewrite.py`
- `core/fusion.py`
- `core/chroma_client.py`
- `core/memory/ledger.py`
- `core/memory/profile.py`
- `core/memory/views.py`
- `core/memory/policy.py`
- `core/memory/search.py`
- `core/graphrag/extractor.py`（⚠️ **含未修复 Bug 的 batch 函数**）
- `core/graphrag/graph_store.py`
- `core/graphrag/community.py`（v0.4.4，已并行化）
- `core/graphrag/query_engine.py`

### 5.2 API 层
- `api/synthesize.py`（v0.4.4，含并行化和 graph_context 自动注入）
- `api/graphrag.py`（v0.4.4，含强制后台阈值 20）
- `api/retrieve.py`（v0.4.4，含后台 build 批量抽取）
- `api/planner.py`
- `api/health.py`
- `api/memory.py`
- `api/citation_validator.py`

### 5.3 入口与配置
- `main.py`
- `.env`
- `requirements.txt`（如有）

### 5.4 测试与文档
- `test_phase4_e2e_graphrag.py`
- `Logos_Design_Document_v0.3.0.docx`（或用户最新版本）
- **本交接文档**（`handover_v0.4.4.md`）

### 5.5 可选但建议上传
- `core/search_bing.py`
- `core/search_baidu.py`
- `core/search_chroma.py`
- `core/search_dify_kb.py`

---

## 六、新 Kimi 注意事项

1. **不要假设知识库里有新能源汽车、市场营销、SWOT 分析等内容**。
2. **不要建议用户"补充新能源汽车知识库"来修复 missing_citation**。
3. **不要修改已稳定的 Planner / Memory / Citation Validator 核心代码**，除非用户明确要求。
4. **不要生成任何与电力运维无关的测试用例**。
5. **不要恢复 `api/retrieve.py` 中被注释的 Bing/Baidu 搜索任务**（它们已经被恢复了）。
6. **不要修改 `core/graphrag/` 中的核心算法逻辑**（如 Louvain 社区发现、去重阈值 0.85），除非用户明确要求优化。
7. **修改 extractor.py 时，不要删除原有的单条抽取函数**（`extract_entities_relations` / `_extract_single`），batch 函数是新增在文件末尾的，修复时应保持向后兼容。
8. **测试前必须确认 Mac Studio Ollama bge-m3 已启动**，否则测试结果不可信（检索层会全灭）。
9. **测试前建议杀掉残留 chromium 进程**：`Get-Process | Where-Object {$_.ProcessName -like "*chrome*"} | Stop-Process -Force`
10. **Dify 当前未运行**，任何涉及 Dify KB 的测试都会返回 0 条，这是预期行为。

---

## 七、环境信息

- **外部引擎部署**: 机械革命 Windows 开发机
- **Tailscale IP**: `100.97.236.112:8000`
- **Mac Studio**: `100.120.218.98`（Ollama + ComfyUI）
- **Ollama 地址**: `http://100.120.218.98:11434`，模型 `bge-m3`
- **Dify 地址**: `http://127.0.0.1`（当前未运行）
- **DeepSeek API**: `https://api.deepseek.com`
- **Chroma 路径**: `.\chroma_db`
- **GraphRAG 存储**: `D:\precision_agent\data\graphrag\`
- **Ledger 存储**: `D:\precision_agent\data\ledger\`
- **Profile DB**: `D:\precision_agent\data\profiles\profiles.db`

---

*交接完成。新 Kimi 请从"确认已阅读本交接文档"开始。*
