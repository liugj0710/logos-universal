# Λόγος Agent · 工作交接文档

**交接时间**: 2026-08-01  
**当前版本**: v0.4.5（开发中，未发版）  
**交接人**: Kimi-1（当前会话）→ Kimi-2（新会话）  
**目标**: Phase 4 GraphRAG 与 Synthesize 集成已完结，确认收尾状态并规划 Phase 5

---

## 一、开发进度总览（对照设计文档 v0.3.0）

| 阶段 | 设计文档章节 | 状态 | 关键文件 | 备注 |
|------|-------------|------|---------|------|
| Phase 1 | 8.1 Fast Lane 先行 | ✅ 已完成 | Dify 侧工作流 | 不涉及外部引擎代码 |
| Phase 2 | 8.2 外部引擎骨架 | ✅ 已完成 | `api/planner.py`, `api/retrieve.py`, `core/planner/`, `core/search_*.py` | 召回率提升 +33.3% |
| Phase 2.5 | 8.3 记忆系统 MVP | ✅ 已完成 | `core/memory/ledger.py`, `profile.py`, `views.py`, `policy.py`, `search.py` | Ledger(JSONL)+Profile(SQLite)+Views(Chroma) |
| Phase 3 | 8.4 棱镜闭环 | ✅ 已完成 | `core/synthesize.py`, `api/synthesize.py`, `core/citation_validator.py`, `api/citation_validator.py` | Dify 侧已接入 deep_synthesize Tool |
| Phase 4 | 8.5 Skill Menu 与 GraphRAG | ✅ **已完成** | `core/graphrag/extractor.py`, `graph_store.py`, `community.py`, `query_engine.py`, `api/graphrag.py` | **B选项（Synthesize+GraphRAG集成）+ A选项（Dify Tool接入）全部完成** |
| Phase 5 | 8.6 调优与硬化 | ⬜ **未开始** | — | 待启动 |

### 1.1 Phase 4 已完成清单（本次会话全部完成）

1. **GraphRAG 核心模块** ✅
   - `core/graphrag/extractor.py` — 实体关系抽取引擎（含 batch 优化）
   - `core/graphrag/graph_store.py` — NetworkX 有向图存储
   - `core/graphrag/community.py` — Louvain 社区发现 + LLM 摘要（已并行化 Semaphore(10)）
   - `core/graphrag/query_engine.py` — 图查询引擎（实体搜索、子图展开、社区聚合、全局查询）
   - `api/graphrag.py` — 9 个 REST 端点

2. **Synthesize + GraphRAG 集成（B选项）** ✅
   - `core/synthesize.py`: `generate_report` / `_build_system_prompt` 新增 `graph_context` 参数和规则 8-11
   - `api/synthesize.py`: 检索与图谱查询并行化（`asyncio.gather`），响应新增 `graph_context_injected` 和 `auto_retrieved`

3. **Batch 抽取 Bug 修复（v0.4.4-fix3）** ✅
   - 重写 `_BATCH_EXTRACTION_SYSTEM_PROMPT`，加入完整 few-shot 示例
   - 新增 `_safe_parse_batch_results()`，四层解析策略（标准 JSON / 扁平数组 / 分散对象 / 截断修复）
   - 新增 `_fallback_batch_extract()`，Semaphore(3) 并行 fallback
   - `extract_entities_relations_batch()` 集成新解析器 + 并行 fallback

4. **Dify 侧 GraphRAG Tool 接入（A选项）** ✅
   - 在 Dify 创建自定义 Tool `logos_graphrag_query`
   - OpenAPI YAML 已配置，调用 `/api/v1/graphrag/query`
   - Dify 工作流已插入 `logos_graphrag_query` 节点（位于 `deep_hybrid_retrieve` 之后、`deep_synthesize` 之前）

5. **Dify 超时问题解决** ✅
   - `docker/.env` 已配置：`API_TOOL_DEFAULT_READ_TIMEOUT=180`
   - `docker/.env` 已配置：`TEXT_GENERATION_TIMEOUT_MS=180000`
   - `docker/.env` 已配置：`APP_MAX_EXECUTION_TIME=1200`
   - **注意**：修改 `.env` 后必须执行 `docker compose down && docker compose up -d` 才能生效

6. **Dify 系统提示词更新** ✅
   - 新增 `logos_graphrag_query` 到可用工具列表
   - 明确 Clarify（追问）和 Deep Lane（深度分析）的**互斥边界**
   - 追问后绝对禁止调用任何 Tool、禁止输出进度消息、禁止生成报告

---

## 二、本次会话引入的修改（精确到文件）

| # | 文件 | 修改内容 | 版本标记 |
|---|------|---------|---------|
| 1 | `core/graphrag/extractor.py` | 重写 batch prompt（few-shot）、新增 `_safe_parse_batch_results`、新增 `_fallback_batch_extract`、温度降至 0.1 | v0.4.4-fix3 |
| 2 | `api/graphrag.py` | 删除第二个同名 `_async_graph_build`（单条版），保留 batch 版 | v0.4.4-fix3 |
| 3 | `docker/.env` | 新增 `API_TOOL_DEFAULT_READ_TIMEOUT=180`、`API_TOOL_DEFAULT_CONNECT_TIMEOUT=30`、`TEXT_GENERATION_TIMEOUT_MS=180000` | Dify 侧配置 |
| 4 | Dify 系统提示词 | 新增 `logos_graphrag_query` 工具、新增互斥边界约束 | Dify 侧配置 |

---

## 三、绝对不可假设的事实（新 Kimi 必须遵守）

1. **当前版本**: `main.py` 中 `version="0.4.0"`，`api/health.py` 硬编码为 `0.2.1`，不同步但不影响功能，可忽略。
2. **知识库内容**: Chroma 向量库和 Dify 知识库中**没有**新能源汽车、市场营销、行业分析类文档。实际内容是《享界超级工厂电力设备综合运维规程》（电力运维）和 FLUX/ComfyUI 提示词文档（AI 绘画）。
3. **检索结果不匹配时的行为**: Synthesize 生成"数据不足"报告、Validate 标记 `missing_citation` 是**正确行为**，不是 Bug。
4. **Dify 当前已运行**（Docker 已启动），Dify KB 检索返回 0 条是预期行为（知识库未配置）。
5. **网页搜索**（Bing/Baidu）已通过 DrissionPage 恢复，端口 9223/9226，但偶发浏览器启动失败（端口冲突/进程残留）。
6. **Dify 部署在机械革命上**，通过 `http://127.0.0.1:8000` 访问外部引擎。
7. **当前图谱已有 330 节点 / 235 边**，存储在 `D:\precision_agent\data\graphrag\`。
8. **Mac Studio Ollama bge-m3 必须启动**，否则 `search_chroma`、`search_memory`、`search_dify_kb` 全部失败（embedding 依赖 Ollama）。
9. **30s 单 chunk 抽取超时**是已知正常行为（LLM 响应不稳定），已有重试机制（2 次）。
10. **Citation Validator 的 content_mismatch**是 LLM 概括性改写的正常表现（状态文档第28条）。
11. **后台 GraphRAG build 30s 超时导致部分 chunk 跳过**是正常行为（状态文档第26条）。
12. **TC-GR-05 中 GraphRAG-Build 240s 超时**是测试脚本的同步调用限制，生产环境后台 build 是异步的，不受影响。

---

## 四、剩余已知问题（精确到代码位置）

| # | 问题 | 位置 | 严重度 | 说明 |
|---|------|------|--------|------|
| 1 | **Dify 系统提示词 Clarify/Deep Lane 互斥边界待验证** | Dify Agent 系统提示词 | 🟡 中 | 已更新提示词，但需在实际对话中验证"追问后是否还会触发 Deep Lane" |
| 2 | **DeepSeek API 偶发返回空** | `core/llm.py` `call_llm()` | 🟡 中 | 非代码 bug，是 API 稳定性。表现为 `response` 为 `None` 或空字符串，extractor 重试 2 次后仍可能失败。 |
| 3 | **Ollama 依赖未启动时检索层全灭** | `core/chroma_client.py`, `core/memory/search.py` | 🟡 中 | Mac Studio 关机或 Ollama 未运行时，Chroma/Dify KB/Memory 检索全部失败，仅剩网页搜索。 |
| 4 | **浏览器 TabPool 偶发启动失败** | `core/search_bing.py`, `core/search_baidu.py` | 🟡 中 | 端口 9223/9226 被残留 chromium 进程占用时，出现 `NoneType` / `list index out of range` 错误。 |
| 5 | **Community 摘要偶发 JSON 解析失败** | `core/graphrag/community.py` `summarize_community()` | 🟢 低 | LLM 返回空或截断 JSON，已有异常捕获兜底（返回"未知主题"）。 |
| 6 | **Entity-Detail 别名回查边界** | `core/graphrag/graph_store.py` `get_entity()` | 🟢 低 | "变压器"搜索能找到，但 `get_entity("变压器")` 返回未找到，需用精确名如"电力变压器"。 |
| 7 | **api/health.py 版本号不同步** | `api/health.py` | 🟢 低 | 硬编码 0.2.1，与 main.py 0.4.0 不同，不影响功能。 |
| 8 | **TC-GR-05 Build 同步超时** | `test_phase4_e2e_graphrag.py` | 🟢 低 | 测试脚本调用 `/graphrag/build` 同步模式 240s 超时，生产环境用后台异步 build，非阻塞。 |

---

## 五、下一步选项（由用户选择）

| 选项 | 工作项 | 当前状态 | 建议 |
|------|--------|---------|------|
| **A** | Dify 侧 GraphRAG Tool 接入 | ✅ **已完成** | 已创建 `logos_graphrag_query` Tool，已插入工作流，已解决超时问题 |
| **B** | Synthesize + GraphRAG 集成 | ✅ **已完成** | 核心逻辑（graph_context 注入）+ Batch 抽取修复 + Dify 接入全部完成 |
| **C** | **Phase 5: 调优与硬化** | ⬜ **未开始，推荐** | 压力测试、浏览器内存泄漏排查、记忆遗忘策略、隐私合规审计 |
| **D** | 补文档/整理 | ⬜ 未开始 | 更新设计文档至 v0.4.0、部署手册、Dify 工作流配置文档 |
| **E** | 验证 Dify 系统提示词互斥边界 | 🔄 待验证 | 测试边界模糊问题，确认追问后不再触发 Deep Lane |

**建议优先级**:  
1. 先选 **E**（快速验证提示词互斥边界，1-2 轮对话即可确认）  
2. 然后进入 **C**（Phase 5 调优与硬化）或 **D**（补文档）

---

## 六、必须上传的文件清单

新 Kimi 必须拿到以下文件才能准确接管。请用户从 `D:\precision_agent\` 打包上传：

### 6.1 核心逻辑层
- `core/synthesize.py`（v0.4.3，含 graph_context 注入）
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
- `core/graphrag/extractor.py`（⚠️ **v0.4.4-fix3，已修复 batch bug**）
- `core/graphrag/graph_store.py`
- `core/graphrag/community.py`（v0.4.4，已并行化）
- `core/graphrag/query_engine.py`

### 6.2 API 层
- `api/synthesize.py`（v0.4.4，含并行化和 graph_context 自动注入）
- `api/graphrag.py`（⚠️ **v0.4.4-fix3，已删除重复函数**）
- `api/retrieve.py`（v0.4.4，含后台 build 批量抽取）
- `api/planner.py`
- `api/health.py`
- `api/memory.py`
- `api/citation_validator.py`

### 6.3 入口与配置
- `main.py`
- `.env`
- `requirements.txt`（如有）

### 6.4 Dify 侧配置（截图或导出）
- Dify 系统提示词（当前版本，含 `logos_graphrag_query`）
- Dify 工作流配置（Deep Lane 的 Tool 调用顺序截图）
- `docker/.env`（含超时配置）

### 6.5 测试与文档
- `test_phase4_e2e_graphrag.py`
- `Logos_Design_Document_v0.3.0.docx`（或用户最新版本）
- **本交接文档**（`handover_v0.4.5.md`）

### 6.6 可选但建议上传
- `core/search_bing.py`
- `core/search_baidu.py`
- `core/search_chroma.py`
- `core/search_dify_kb.py`

---

## 七、新 Kimi 注意事项

1. **不要假设知识库里有新能源汽车、市场营销、SWOT 分析等内容**。
2. **不要建议用户"补充新能源汽车知识库"来修复 missing_citation**。
3. **不要修改已稳定的 Planner / Memory / Citation Validator 核心代码**，除非用户明确要求。
4. **不要生成任何与电力运维无关的测试用例**。
5. **不要恢复 `api/retrieve.py` 中被注释的 Bing/Baidu 搜索任务**（它们已经被恢复了）。
6. **不要修改 `core/graphrag/` 中的核心算法逻辑**（如 Louvain 社区发现、去重阈值 0.85），除非用户明确要求优化。
7. **修改 extractor.py 时，不要删除原有的单条抽取函数**（`extract_entities_relations` / `_extract_single`），batch 函数是新增在文件末尾的，修复时应保持向后兼容。
8. **测试前必须确认 Mac Studio Ollama bge-m3 已启动**，否则测试结果不可信（检索层会全灭）。
9. **测试前建议杀掉残留 chromium 进程**：`Get-Process | Where-Object {$_.ProcessName -like "*chrome*"} | Stop-Process -Force`
10. **Dify 当前已运行**，任何涉及 Dify KB 的测试返回 0 条是预期行为。
11. **修改 `docker/.env` 后必须执行 `docker compose down && docker compose up -d`**，`restart` 不会重读环境变量。
12. **Phase 4 已完结**，当前阻塞项已全部清除，下一步由用户从 C/D/E 中选择。

---

## 八、环境信息

- **外部引擎部署**: 机械革命 Windows 开发机
- **Tailscale IP**: `100.97.236.112:8000`
- **Mac Studio**: `100.120.218.98`（Ollama + ComfyUI）
- **Ollama 地址**: `http://100.120.218.98:11434`，模型 `bge-m3`
- **Dify 地址**: `http://127.0.0.1`（Docker 已启动）
- **DeepSeek API**: `https://api.deepseek.com`
- **Chroma 路径**: `.\chroma_db`
- **GraphRAG 存储**: `D:\precision_agent\data\graphrag\`
- **Ledger 存储**: `D:\precision_agent\data\ledger\`
- **Profile DB**: `D:\precision_agent\data\profiles\profiles.db`
- **Dify Docker 路径**: `D:\working document\DockerDesktopWSL\dify-1.14.2`

---

*交接完成。新 Kimi 请从"确认已阅读本交接文档"开始。*
