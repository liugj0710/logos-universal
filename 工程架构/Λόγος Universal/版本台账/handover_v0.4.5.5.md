# Λόγος Agent · 工作交接文档 v0.4.5.5

**交接时间**: 2026-08-04
**当前版本**: v0.4.5.5（开发中，未发版）
**交接人**: Kimi-1（当前会话）→ Kimi-2（新会话）
**项目路径**: `D:\precision_agent`
**运行位置**: 机械革命 Windows 开发机（Tailscale IP: 100.97.236.112:8000）

---

## 一、开发进度总览（严格对照设计文档 v0.4.5.1 + 本次会话变更）

### Phase 1 ~ Phase 4：全部已完成（无变更）

| 阶段 | 设计文档章节 | 状态 | 关键文件 | 备注 |
|------|-------------|------|---------|------|
| Phase 1 | 8.1 Fast Lane 先行 | ✅ 已完成 | Dify 侧工作流 | 不涉及外部引擎代码 |
| Phase 2 | 8.2 外部引擎骨架 | ✅ 已完成 | `api/planner.py`, `api/retrieve.py`, `core/search_*.py` | 召回率提升 +33.3% |
| Phase 2.5 | 8.3 记忆系统 MVP | ✅ 已完成 | `core/memory/ledger.py`, `profile.py`, `views.py`, `policy.py`, `search.py` | Ledger+Profile+Views+Policy |
| Phase 3 | 8.4 棱镜闭环 | ✅ 已完成 | `core/synthesize.py`, `api/synthesize.py`, `core/citation_validator.py` | Dify 侧已接入 deep_synthesize Tool |
| Phase 4 | 8.5 Skill Menu 与 GraphRAG | ✅ 已完成 | `core/graphrag/extractor.py`, `graph_store.py`, `community.py`, `query_engine.py`, `api/graphrag.py` | Synthesize+GraphRAG集成完成 |

### Phase 5.1：已完成（3/3）

| 工作项 | 状态 | 说明 | 关键文件 |
|--------|------|------|---------|
| AIGC 检索为空修复 | ✅ 已完成 | 200字硬过滤→分层过滤 | `core/search_dify.py` |
| 后台 GraphRAG 并发限制 | ✅ 已完成 | `Semaphore(2)` + `new_event_loop()` | `api/retrieve.py` |
| Citation 实时锚定 | ✅ 已完成（但本次会话已决定弃用） | 段落级来源卡片 | `core/synthesize.py` `_inject_citation_anchors` |

> **【本次会话变更】** Citation 实时锚定已决定弃用，改为文末统一参考文献列表。新代码已生成但未部署。

### Phase 5.2：待办事项状态（8项）

| 优先级 | 工作项 | 文档状态 | 实际状态 | 说明 |
|--------|--------|---------|---------|------|
| 🔴 P0 | Deep Lane 协作中断点 | 待启动 | ⬜ **未实施** | 用户确认延期至阿尔法版本 |
| 🔴 P1 | Clarify 框架选项 | 待启动 | ⬜ **未实施** | 用户确认延期至阿尔法版本 |
| 🟡 P2 | Fast Lane 工作记忆扩展 | 待启动 | ✅ **已部分实施** | `api/retrieve.py` 已有 `fast_retrieve` 端点，Dify 侧接入状态待确认 |
| 🟡 P3 | GraphRAG 可视化查询 | 待启动 | ⬜ 未实施 | — |
| 🟢 P4 | 长消息分段 + 延迟 | 待启动 | ✅ **已实施但有 Bug** | `wechat_bridge_v2.py` v2.1 已实装，但存在超时/截断/推送失败问题（见"事实问题"） |
| 🟢 P5 | 引用格式统一 | 待启动 | 🔄 **本次会话已修改** | 新代码和提示词已生成，**尚未部署** |
| 🟢 P6 | 产能利用率检索 | 待启动 | ⬜ 待排查 | — |
| 🟢 P7 | Agent 独白泄漏 | 待启动 | ✅ **已部分实施** | `filter_react_thoughts` 已实装，但过滤不够完整（非标准 Thought 格式漏过） |
| 🟢 P8 | api/health.py 版本号同步 | 待启动 | ✅ **已修复** | `api/health.py` 已同步为 `0.4.0` |

---

## 二、本次会话引入的变更（精确到文件，未更新至设计文档）

| # | 文件 | 修改内容 | 版本标记 | 部署状态 |
|---|------|---------|---------|---------|
| 1 | `wechat_bridge_v2.py` | Fast Lane timeout: 4s → 3s；被动回复增加 MAX_PASSIVE_REPLY_LEN=1000 截断；`_send_long_message` max_length: 2000 → 1500；推送失败降级逻辑 | v2.2 | **未部署** |
| 2 | `core/synthesize.py` | 引用格式从 `[来源: chunk_id]` 改为 `[1][2]` 数字上标；删除段落级来源锚定卡片注入；新增多源整合与禁止元分析约束；给 chunk 加 `[1][2]` 编号 | v0.4.5.5 | **未部署** |
| 3 | Dify 系统提示词 | 新增 Clarify 状态锚定、禁止自主解读、强制自检；新增禁止元分析、多源整合要求 | v0.4.5.5 | **未部署** |
| 4 | 网络拓扑 | 外部引擎代理端口从 8000 改为 9000（MSL 占用） | — | **已生效，但腾讯云安全组未加规则** |

---

## 三、绝对不可假设的事实（新 Kimi 必须遵守）

1. **当前版本**: `main.py` 中 `version="0.4.0"`，`api/health.py` 已同步为 `0.4.0`。
2. **知识库内容**: Chroma 向量库和 Dify 知识库中**没有**新能源汽车、市场营销、行业分析类文档。实际内容是《享界超级工厂电力设备综合运维规程》（电力运维）、FLUX/ComfyUI 提示词文档（AIGC）、沧州市华祥塑业知识库（制造业）。
3. **Dify 知识库 ≠ 外部引擎知识库**: Dify 侧有 6 个知识库，但外部引擎的 Chroma `logos_private_kb` 中可能**未同步** AIGC 类文档。Deep Lane 检索走的是外部引擎，不直接查 Dify KB。
4. **missing_citation 不是 Bug**: 当检索结果与问题不相关时，Synthesize 生成"数据不足"报告、Validate 标记 `missing_citation` 是**正确行为**。
5. **网页搜索**（Bing/Baidu）已通过 DrissionPage 恢复，端口 9223/9226，但偶发浏览器启动失败（端口冲突/进程残留）。
6. **Dify 部署在机械革命上**，通过 `http://127.0.0.1:8000` 访问外部引擎。
7. **当前图谱**: 约 530 节点 / 419 边，存储在 `D:\precision_agent\data\graphrag\`。
8. **Mac Studio Ollama bge-m3 必须启动**，否则 `search_chroma`、`search_memory`、`search_dify_kb` 全部失败。
9. **30s 单 chunk 抽取超时**是已知正常行为，已有重试机制（2 次）。
10. **Citation Validator 的 content_mismatch**是 LLM 概括性改写的正常表现（阈值已降至 0.3）。
11. **后台 GraphRAG build 30s 超时导致部分 chunk 跳过**是正常行为。
12. **企业微信桥接服务当前运行中**，端口 5000。
13. **任何架构变更必须经用户确认**。
14. **不要建议购买任何付费服务**。
15. **用户删除了 `user_sessions.json`**，导致 Dify 对话上下文（conversation_id）丢失。这是本次会话中发生的，新 Kimi 接手时可能需要重建会话持久化。

---

## 四、已知事实问题（精确到现象，不含推测）

| # | 现象 | 位置 | 严重度 | 已确认的根因 |
|---|------|------|--------|-------------|
| 1 | 企业微信主动推送全部失败，errcode 60020 | `wechat_bridge_v2.py` `send_app_message` | 🔴 高 | 机械革命出网 IP `124.238.79.236` 未在企业微信后台"企业可信 IP"白名单中 |
| 2 | Fast Lane 回复偶发"消失"（企业微信无显示） | `wechat_bridge_v2.py` `call_dify_quick` | 🔴 高 | 企业微信被动回复 5 秒超时。`timeout=4` 加上加密/传输总耗时可能超过 5 秒 |
| 3 | 被动回复超长被截断 | `wechat_bridge_v2.py` `build_reply` | 🔴 高 | 企业微信被动回复加密后约 2048 字节上限。长报告走被动回复时超出上限被静默截断 |
| 4 | 用户发送"结果"查询时，Agent 说"没有之前对话记录" | `wechat_bridge_v2.py` 会话持久化 | 🟡 中 | **用户主动删除了 `user_sessions.json`**，conversation_id 丢失，Dify 创建全新会话 |
| 5 | 长回答（Fast Lane）被截断在句子中间 | `core/llm.py` + 桥接层 | 🟡 中 | Fast Lane 的 LLM `max_tokens=500` 限制，加上桥接层未对 Fast Lane 长回答做分段 |
| 6 | Agent 在 Clarify 后自行继续分析 | Dify Agent 系统提示词 | 🟡 中 | ReAct Agent 机制下，LLM 在同一次 thought 中自主解读用户意图并调用 Tool。提示词约束可能不足 |
| 7 | 报告大篇幅写"资料不足"、"信息存在缺口" | `core/synthesize.py` 系统提示词 | 🟡 中 | 提示词过度强调"诚实披露"，LLM 面对弱相关结果时只敢用单条强相关资料，然后写免责说明 |
| 8 | 引用格式混乱（段落卡片打断阅读） | `core/synthesize.py` `_inject_citation_anchors` | 🟡 中 | 代码自动在每个段落后注入 `📎 来源锚定` 卡片，与 LLM 输出的 `[来源: chunk_id]` 格式不统一 |
| 9 | 腾讯云安全组未开放 9000 端口 | 腾讯云控制台 | 🟡 中 | 用户将代理端口从 8000 改为 9000，但未在腾讯云安全组添加入站规则 |
| 10 | `user_sessions.json` 权限拒绝 | `wechat_bridge_v2.py` `save_sessions` | 🟢 低 | 文件权限问题，已有回退到用户目录的修复方案 |

---

## 五、推测（未验证，需新 Kimi 确认）

| # | 推测 | 依据 | 验证方式 |
|---|------|------|---------|
| 1 | Fast Lane 长回答截断是因为 `max_tokens=500` 限制 | `core/llm.py` 默认 `max_tokens=500`，Fast Lane 回答可能超过 500 tokens | 查看 Fast Lane 被截断的回答长度，对比 token 数 |
| 2 | 指代消解失败（"这一时间"理解错）主因是会话丢失，次因是 Agent 未强制调用 `search_memory` | 用户删除 `user_sessions.json` 后，Dify 会话历史为空；提示词虽有指代消解规则，但无"会话为空时强制查记忆"的约束 | 恢复会话后测试相同问题，观察是否正确引用历史 |
| 3 | Clarify 失效可能是 Dify ReAct 的 Tool Calling 机制导致，仅靠提示词约束不够 | ReAct Agent 在一次推理中可能同时做"追问"和"调用 Tool"两个 action | 查看 Dify Agent 执行日志，确认 Clarify 后是否有独立的 thought 节点 |
| 4 | `_send_long_message` 的 `max_length=1500` 仍可能触发企业微信单条推送隐式限制 | 企业微信文档未明确说明主动推送的字节上限，但实测有截断现象 | 逐步降低 max_length 到 1200/1000，观察是否仍截断 |
| 5 | 当前生成的 v0.4.5.5 代码和提示词可能引入新的副作用 | 任何提示词修改都可能改变 Agent 行为边界 | 部署后分别测试 Clarify、Fast Lane、Deep Lane 三条路径 |

---

## 六、必须上传给新 Kimi 的文件

### 6.1 核心逻辑层（必须）
- `core/synthesize.py`（⚠️ **v0.4.5.5 已修改，未部署。旧版本在 v0.4.5.4**）
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
- `core/graphrag/extractor.py`（v0.4.4-fix3）
- `core/graphrag/graph_store.py`
- `core/graphrag/community.py`（v0.4.4）
- `core/graphrag/query_engine.py`

### 6.2 API 层（必须）
- `api/synthesize.py`（v0.4.4）
- `api/graphrag.py`（v0.4.4-fix3）
- `api/retrieve.py`（v0.4.5.2，含 Fast Lane `fast_retrieve` 端点）
- `api/planner.py`
- `api/health.py`（v0.4.5.2，已同步版本号）
- `api/memory.py`
- `api/citation_validator.py`

### 6.3 搜索层（必须）
- `core/search_bing.py`
- `core/search_baidu.py`
- `core/search_chroma.py`
- `core/search_dify.py`（v0.4.5.1，分层过滤）
- `core/browser_pool.py`
- `core/search.py`

### 6.4 桥接层（必须）
- `wechat_bridge_v2.py`（⚠️ **当前运行版本为 v2.1，v2.2 已生成但未部署**）

### 6.5 入口与配置（必须）
- `main.py`
- `.env`
- `requirements.txt`

### 6.6 本次会话生成的新文件（必须上传，供新 Kimi 参考）
- `synthesize_v0.4.5.5.py`（本次会话生成的新版本）
- `system_prompt_v0.4.5.5.txt`（本次会话生成的新版本）
- `wechat_bridge_v2_v2.2.py`（本次会话生成的新版本）
- **本交接文档**

### 6.7 测试与文档（必须）
- `test_phase4_e2e_graphrag.py`
- `Logos_Engineering_Document_v0.4.5.1.docx`（设计文档）
- `handover_v0.4.5_final.md`（上次交接文档）

---

## 七、新 Kimi 注意事项

1. **不要假设知识库里有新能源汽车、市场营销、行业分析等内容**。
2. **不要建议用户"补充新能源汽车知识库"来修复 missing_citation**。
3. **不要修改已稳定的 Planner / Memory / Citation Validator / GraphRAG 核心代码**，除非用户明确要求。
4. **不要生成任何与电力运维/AIGC/制造业无关的测试用例**。
5. **不要恢复 `api/retrieve.py` 中被注释的 Bing/Baidu 搜索任务**（它们已经被恢复了）。
6. **不要修改 `core/graphrag/` 中的核心算法逻辑**（如 Louvain 社区发现、去重阈值 0.85），除非用户明确要求优化。
7. **修改 extractor.py 时，不要删除原有的单条抽取函数**（`extract_entities_relations` / `_extract_single`），batch 函数是新增在文件末尾的。
8. **测试前必须确认 Mac Studio Ollama bge-m3 已启动**，否则测试结果不可信（检索层会全灭）。
9. **测试前建议杀掉残留 chromium 进程**：`Get-Process | Where-Object {$_.ProcessName -like "*chrome*"} | Stop-Process -Force`
10. **Dify 当前运行中**，但部分知识库偶发 400 错误（Dify 内部插件节点问题）。
11. **企业微信桥接服务当前运行中**，端口 5000。
12. **任何架构变更必须经用户确认**。
13. **不要建议购买任何付费服务**。
14. **本次会话已生成但未部署的代码**：`synthesize_v0.4.5.5.py`、`system_prompt_v0.4.5.5.txt`、`wechat_bridge_v2_v2.2.py`。新 Kimi 接手后需先确认用户是否已部署，如未部署则协助部署。
15. **用户删除了 `user_sessions.json`**，这是当前会话中发生的事实。新 Kimi 需协助用户恢复会话持久化（重建文件或调整权限）。

---

## 八、环境信息（无变更）

| 设备 | Tailscale IP | 用途 |
|------|-------------|------|
| 机械革命 | 100.97.236.112:8000 / 9000 | 外部引擎主运行、Dify、Chroma、桥接服务 |
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

*循逻辑之影，叩真理之声。*
*AI 不是替你思考，而是让你的思考更清晰。*
