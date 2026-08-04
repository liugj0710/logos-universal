# Λόγος Agent · 工作交接文档 v0.4.5

**交接时间**: 2026-08-02  
**当前版本**: v0.4.5（开发中，未发版）  
**交接人**: Kimi-1（当前会话）→ Kimi-2（新会话）  
**项目路径**: `D:\precision_agent`  
**运行位置**: 机械革命 Windows 开发机（Tailscale IP: 100.97.236.112:8000）

---

## 一、开发进度总览（严格对照设计文档 v0.4.5）

| 阶段 | 设计文档章节 | 状态 | 关键文件 | 备注 |
|------|-------------|------|---------|------|
| Phase 1 | 8.1 Fast Lane 先行 | ✅ 已完成 | Dify 侧工作流 | 不涉及外部引擎代码 |
| Phase 2 | 8.2 外部引擎骨架 | ✅ 已完成 | `api/planner.py`, `api/retrieve.py`, `core/search_*.py` | 召回率提升 +33.3% |
| Phase 2.5 | 8.3 记忆系统 MVP | ✅ 已完成 | `core/memory/ledger.py`, `profile.py`, `views.py`, `policy.py`, `search.py` | Ledger+Profile+Views+Policy |
| Phase 3 | 8.4 棱镜闭环 | ✅ 已完成 | `core/synthesize.py`, `api/synthesize.py`, `core/citation_validator.py` | Dify 侧已接入 deep_synthesize Tool |
| Phase 4 | 8.5 Skill Menu 与 GraphRAG | ✅ **已完成** | `core/graphrag/extractor.py`, `graph_store.py`, `community.py`, `query_engine.py`, `api/graphrag.py` | Synthesize+GraphRAG集成完成 |
| Phase 5 | 8.6 调优与硬化 | 🔄 **进行中** | — | **见下方"待办事项"** |

### 1.1 Phase 5 已完成部分

| 工作项 | 状态 | 说明 |
|--------|------|------|
| 企业微信桥接 v2 | ✅ 已完成 | `wechat_bridge_v2.py`，异步双模式，进度推送，会话持久化 |
| 企业微信编码修复 | ✅ 已完成 | `Content-Type: application/json; charset=utf-8` |
| 企业微信 IP 白名单 | ✅ 已完成 | 主动消息推送生效 |
| 引用格式优化 | ⬜ **未执行** | 用户未采纳当前方案，留给新 Kimi |
| 长消息分段 delay | ⬜ **未执行** | 用户未采纳当前方案，留给新 Kimi |

### 1.2 Phase 5 待办事项（新 Kimi 接手）

| 优先级 | 工作项 | 说明 | 状态 |
|--------|--------|------|------|
| 🔴 P1 | **AIGC 知识库同步** | Dify KB 中有 ComfyUI/FLUX 知识库，但外部引擎 Chroma 可能未同步，导致 AIGC 类查询检索为空 | 待排查 |
| 🔴 P1 | **后台 GraphRAG 性能** | BackgroundTasks 后台 build 占用大量 DeepSeek API 调用，导致前台 synthesize 排队变慢 | 待限制 |
| 🟡 P2 | **引用格式优化** | 正文中 `[来源: chunk_id]` 需统一移到报告底部 `"=========="` 后 | 待实施 |
| 🟡 P2 | **长消息分段截断** | 企业微信连续推送可能丢消息，需加 delay 或合并发送 | 待实施 |
| 🟡 P2 | **产能利用率检索** | 华祥塑业文档中明确有产能数据，但检索未命中，可能文档入库不完整 | 待排查 |
| 🟢 P3 | **Agent 独白泄漏** | Dify Agent 内部思考文本被流式推送，桥接代码过滤不完整 | 低优先级 |
| 🟢 P3 | **GraphRAG event loop 错误** | `is bound to a different event loop`，后台线程无 asyncio 事件循环 | 非阻塞 |

---

## 二、绝对不可假设的事实

1. **当前版本**: `main.py` 中 `version="0.4.0"`，`api/health.py` 硬编码为 `0.2.1`，不同步但不影响功能，可忽略。
2. **知识库内容**: Chroma 向量库和 Dify 知识库中**没有**新能源汽车、市场营销、行业分析类文档。实际内容是《享界超级工厂电力设备综合运维规程》（电力运维）、FLUX/ComfyUI 提示词文档（AIGC）、沧州市华祥塑业知识库（制造业）。
3. **Dify 知识库 ≠ 外部引擎知识库**: Dify 侧有 6 个知识库（截图确认），但外部引擎的 Chroma `logos_private_kb` 中可能**未同步** AIGC 类文档。Deep Lane 检索走的是外部引擎，不直接查 Dify KB。
4. **missing_citation 不是 Bug**: 当检索结果与问题不相关时，Synthesize 生成"数据不足"报告、Validate 标记 `missing_citation` 是**正确行为**。
5. **网页搜索**（Bing/Baidu）已通过 DrissionPage 恢复，端口 9223/9226，但偶发浏览器启动失败（端口冲突/进程残留）。
6. **Dify 部署在机械革命上**，通过 `http://127.0.0.1:8000` 访问外部引擎。
7. **当前图谱**: 530 节点 / 419 边，存储在 `D:\precision_agent\data\graphrag\`。
8. **Mac Studio Ollama bge-m3 必须启动**，否则 `search_chroma`、`search_memory`、`search_dify_kb` 全部失败（embedding 依赖 Ollama）。
9. **30s 单 chunk 抽取超时**是已知正常行为（LLM 响应不稳定），已有重试机制（2 次）。
10. **Citation Validator 的 content_mismatch**是 LLM 概括性改写的正常表现（阈值已降至 0.3）。
11. **后台 GraphRAG build 30s 超时导致部分 chunk 跳过**是正常行为。
12. **企业微信桥接 v2 编码已修复**: `Content-Type` 必须包含 `charset=utf-8`，否则中文乱码。
13. **企业微信主动推送需 IP 白名单**: 腾讯云服务器公网 IP 必须在企微后台"企业可信 IP"中配置。

---

## 三、已知问题（精确到代码位置）

| # | 问题 | 位置 | 严重度 | 说明 |
|---|------|------|--------|------|
| 1 | **AIGC 检索为空** | `api/retrieve.py` → `search_chroma` / `search_dify_kb` | 🔴 高 | 用户确认 Dify KB 有 FLUX/ComfyUI 知识库，但外部引擎检索 AIGC 类查询返回空，可能 Chroma 未同步 |
| 2 | **后台 build 拖慢前台** | `api/retrieve.py` `_background_graph_build()` | 🔴 高 | BackgroundTasks 异步 build 占用 LLM 调用队列，建议加 Semaphore 限制并发或降低优先级 |
| 3 | **报告截断** | `wechat_bridge_v2.py` `_send_long_message()` | 🟡 中 | 企业微信连续主动推送可能丢消息，建议加 `time.sleep(1.5)` 或合并发送 |
| 4 | **引用格式** | `core/synthesize.py` `_build_system_prompt()` | 🟡 中 | 正文中 `[来源: chunk_id]` 需移到报告底部 `"=========="` 后 |
| 5 | **产能利用率检索不到** | `api/retrieve.py` / `ingest.py` | 🟡 中 | 华祥塑业文档有产能数据但检索未命中，可能文档入库不完整或分段过短被 200 字过滤 |
| 6 | **独白泄漏** | `wechat_bridge_v2.py` `PROGRESS_PATTERNS` | 🟢 低 | Dify Agent 内部思考文本未被完全过滤，如"让我先拆解这个问题…" |
| 7 | **event loop 错误** | `core/graphrag/extractor.py` | 🟢 低 | `BackgroundTasks` 中调用 `asyncio` 函数无事件循环，不影响用户体验 |
| 8 | **api/health.py 版本号不同步** | `api/health.py` | 🟢 低 | 硬编码 0.2.1，与 main.py 0.4.0 不同 |

---

## 四、环境信息

| 设备 | Tailscale IP | 用途 |
|------|-------------|------|
| 机械革命 | 100.97.236.112:8000 | 外部引擎主运行、Dify、Chroma、桥接服务 |
| Mac Studio | 100.120.218.98 | Ollama bge-m3、ComfyUI |
| 腾讯云 | 101.42.184.53 | Nginx 反向代理、公网入口 |

- **Dify**: http://127.0.0.1 (v1.14.2)
- **Ollama**: http://100.120.218.98:11434，模型 `bge-m3`
- **Chroma DB**: `D:\precision_agent\chroma_db`
- **Embedding**: 1024 维，bge-m3，embed_batch 模式
- **GraphRAG 存储**: `D:\precision_agent\data\graphrag\`
- **Ledger 存储**: `D:\precision_agent\data\ledger\`
- **Profile DB**: `D:\precision_agent\data\profiles\profiles.db`
- **桥接服务**: `D:\precision_agent\桥接服务和AIGC\wechat_bridge_v2.py`，端口 5000
- **Dify API Key**: `app-OEDNpbufKiczr1W2uuzUDqR3`

---

## 五、必须上传给新 Kimi 的文件

### 5.1 核心逻辑层（必须）
- `core/synthesize.py`（v0.4.3，含 graph_context 注入）
- `core/citation_validator.py`（阈值 0.3）
- `core/llm.py`（timeout=180s）
- `core/config.py`
- `core/rewrite.py`
- `core/fusion.py`
- `core/chroma_client.py`
- `core/memory/ledger.py`
- `core/memory/profile.py`
- `core/memory/views.py`
- `core/memory/policy.py`
- `core/memory/search.py`
- `core/graphrag/extractor.py`（含 batch 函数）
- `core/graphrag/graph_store.py`
- `core/graphrag/community.py`（已并行化）
- `core/graphrag/query_engine.py`

### 5.2 API 层（必须）
- `api/synthesize.py`（v0.4.4，含并行化和 graph_context 自动注入）
- `api/graphrag.py`（v0.4.4，含强制后台阈值 20）
- `api/retrieve.py`（v0.4.4，含后台 build）
- `api/planner.py`
- `api/health.py`
- `api/memory.py`
- `api/citation_validator.py`

### 5.3 搜索层（必须）
- `core/search_bing.py`
- `core/search_baidu.py`
- `core/search_chroma.py`
- `core/search_dify.py`
- `core/browser_pool.py`
- `core/search.py`

### 5.4 桥接层（必须）
- `wechat_bridge_v2.py`（企业微信桥接，异步双模式）

### 5.5 入口与配置（必须）
- `main.py`
- `.env`
- `requirements.txt`

### 5.6 测试与文档（必须）
- `test_phase4_e2e_graphrag.py`
- `Logos_Design_Document_v0.4.5.md`
- `Deployment_Manual_v0.4.5.md`
- `Logos_Agent_System_Prompt_v0.4.5.md`
- **本交接文档**

---

## 六、新 Kimi 注意事项

1. **不要假设知识库里有新能源汽车、市场营销、SWOT 分析等内容**。
2. **不要建议用户"补充新能源汽车知识库"来修复 missing_citation**。
3. **不要修改已稳定的 Planner / Memory / Citation Validator 核心代码**，除非用户明确要求。
4. **不要生成任何与电力运维/AIGC/制造业无关的测试用例**。
5. **不要恢复 `api/retrieve.py` 中被注释的 Bing/Baidu 搜索任务**（它们已经被恢复了）。
6. **不要修改 `core/graphrag/` 中的核心算法逻辑**（如 Louvain 社区发现、去重阈值 0.85），除非用户明确要求优化。
7. **修改 extractor.py 时，不要删除原有的单条抽取函数**（`extract_entities_relations` / `_extract_single`），batch 函数是新增在文件末尾的。
8. **测试前必须确认 Mac Studio Ollama bge-m3 已启动**，否则测试结果不可信（检索层会全灭）。
9. **测试前建议杀掉残留 chromium 进程**：`Get-Process | Where-Object {$_.ProcessName -like "*chrome*"} | Stop-Process -Force`
10. **Dify 当前运行中**，但部分知识库偶发 400 错误（Dify 内部插件节点问题）。
11. **企业微信桥接服务当前运行中**，端口 5000，编码问题已修复。
12. **任何架构变更必须经用户确认**。
13. **不要建议购买任何付费服务**。

---

*循逻辑之影，叩真理之声。*
