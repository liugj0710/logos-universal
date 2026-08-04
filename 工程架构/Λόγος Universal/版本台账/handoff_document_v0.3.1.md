# Λόγος Agent 项目交接文档 v0.3.1

**交接日期**: 2026-07-28  
**项目路径**: `D:\precision_agent`  
**设计文档版本**: v0.3.0（用户已修正 8.3 节矛盾）  
**交接原因**: Phase 2.5 MVP 代码完成，进入 Dify 集成验证阶段

---

## 一、项目状态总览（对照设计文档 v0.3.0）

### ✅ Phase 1: Fast Lane 先行 — 已完成

### ✅ Phase 2: 外部引擎骨架 — 已验收

| 模块 | 设计文档要求 | 当前状态 | 备注 |
|------|-------------|---------|------|
| Query Rewriting | 每个子查询改写 1-2 个检索变体 | ✅ 已完成 | `core/rewrite.py`，json_mode=True，四层 fallback 解析 |
| Query Planner | 子查询拆解 + skill_hint | ✅ 已完成 | `api/planner.py` |
| Bing 搜索 | DrissionPage 浏览器自动化 | ✅ 已完成 | `core/search_bing.py`，Tab Pool（端口 9223） |
| 百度搜索 | DrissionPage 浏览器自动化 | ✅ 已完成 | `core/search_baidu.py`，Tab Pool（端口 9226） |
| Chroma 向量库 | 接入实际 Chroma 实例 | ✅ 已完成 | `chromadb 1.5.9`，165 chunks 已入库，`logos_private_kb` collection |
| Dify KB 检索 | 调用 Dify 知识库 API | ✅ 已完成 | 自动发现 5 个知识库，超时 10s + 1 次重试 |
| RRF 融合 | 按排名倒数融合 + 去重 | ✅ 已完成 | `core/fusion.py`，语义相似度去重阈值 0.85 |
| 内容过滤 | 丢弃 <200 字的结果 | ✅ 已完成 | `api/retrieve.py` |
| main.py reload | 生产环境关闭 | ✅ 已完成 | `UVICORN_RELOAD` 环境变量控制 |

### ✅ Phase 2.5: 记忆系统 MVP — 代码已完成，E2E 测试通过

| 模块 | 设计文档位置 | 当前状态 | 说明 |
|------|-------------|---------|------|
| Ledger (JSONL) | 5.3.1 | ✅ 已完成 | `core/memory/ledger.py`，按 user_id/日期 分文件，只追加 |
| Profile (SQLite/JSON) | 5.3.1 | ✅ 已完成 | `core/memory/profile.py`，深度合并 JSON 字段 |
| Views (生成器) | 5.3.1 | ✅ 已完成 | `core/memory/views.py`，DeepSeek-V4 Flash 生成摘要 |
| Policy (规则引擎) | 5.3.1 | ✅ 已完成 | `core/memory/policy.py`，隐私过滤 + 事件类型白名单 |
| Memory Search (Chroma) | 5.3.1 | ✅ 已完成 | `core/memory/search.py`，`logos_memory` collection，user_id 隔离 |
| API (`api/memory.py`) | 5.3.1 | ✅ 已完成 | `/memory/profile` (读) + `/memory/ledger` (写) + `/memory/search` + `/memory/summarize` |
| Dify 集成（Planner前读记忆） | 5.3.4 | ✅ 代码已完成 | `api/planner.py` 和 `api/retrieve.py` 已内置记忆注入逻辑 |
| Dify 集成（对话结束后写Ledger） | 5.3.4 | ✅ 代码已完成 | planner/retrieve 调用时自动异步写 Ledger |

**⚠️ 待验证项**：
- Dify Tool `user_id` 参数默认值 `{{#sys.user_id#}}` 配置后，需验证企业微信渠道下 user_id 是否正确透传
- 企业微信实际对话中观察 `main.py` 终端是否出现 `[planner] 记忆注入 (UserID): ...` 日志

### ⬜ Phase 3: 棱镜闭环 — 未开始

| 模块 | 状态 | 说明 |
|------|------|------|
| `/api/v1/synthesize` | ⬜ 未开始 | 外部引擎直接生成结构化报告 |
| `citation_validator` | ⬜ 未开始 | 引用验证规则引擎 |

### ⬜ Phase 4-5: 远期 — 未开始

---

## 二、已知问题（遗留，非阻塞）

| 问题 | 影响 | 处理建议 |
|------|------|----------|
| `fetch_page` SSL/Timeout 噪音 | 日志噪音大，不影响结果 | CSDN 加 `verify=False`，超时 5s→8s（可选，P1） |
| Dify KB 400 错误 | 特定知识库 `7196b2ed-...` 偶发 | Dify 内部 Tongyi 插件节点问题，非代码问题 |
| 标签页使用次数 | 单次请求刷到 3 次，50 次上限可能几轮用完 | 有自动淘汰和应急创建机制，不会崩 |
| FastAPI `on_event` 弃用 | DeprecationWarning | **已修复**：main.py 已换 lifespan（v0.3.0） |

---

## 三、关键设计决策（防止幻觉）

1. **SearXNG 已永久废弃**，搜索层使用 Bing + 百度混合搜索
2. **Bing 和百度都必须用 DrissionPage**，不能用 requests
3. **内容过滤阈值 200 字是核心防线**，不能降低
4. **模型名统一为 deepseek-v4-flash**（rewrite/planner/memory）/ deepseek-v4-pro（synthesize）
5. **Chroma 是 Deep Lane 私有知识库主力**，Dify KB 留给 Fast Lane
6. **Embedding 用 Mac Studio Ollama bge-m3**，Tailscale 内网调用
7. **子查询上限 5 条，改写变体上限 2 个，Bing/百度各返回 5 条**
8. **记忆系统放在外部引擎**，不是 Dify 侧
9. **记忆检索作为改写输入注入**，**不参与 RRF 融合**（设计文档 10.8 节，已修正 8.3 节矛盾）
10. **Ledger 用 JSONL**，只追加不修改
11. **父子双用户场景**，领域完全隔离，retrieve 需增加 `user_id`
12. **Chroma metadata 只支持标量值**，list/dict 必须序列化为 JSON 字符串（`core/memory/search.py` `_clean_meta`）

---

## 四、环境信息

| 设备 | Tailscale IP | 用途 |
|------|-------------|------|
| 机械革命 | 100.97.236.112 | 外部引擎主运行、Dify、Chroma |
| Mac Studio | 100.120.218.98 | Ollama bge-m3、ComfyUI |
| 腾讯云 | 101.42.184.53 | Nginx 反向代理、公网入口 |

- **Dify**: http://127.0.0.1 (v1.14.2)
- **Ollama**: http://100.120.218.98:11434，模型 `bge-m3`
- **Chroma DB**: `D:\precision_agent\chroma_db`
- **Embedding**: 1024 维，bge-m3，embed_batch 模式
- **venv**: `D:\precision_agent\venv`
- **Ledger**: `D:\precision_agent\data\ledger\`
- **Profile DB**: `D:\precision_agent\data\profiles\profiles.db`

---

## 五、文件清单（新 Kimi 必须索要）

### 当前运行版本（必须）
1. `core/browser_pool.py` — TabPool 实现
2. `core/search_bing.py` — Bing Tab Pool 版本
3. `core/search_baidu.py` — Baidu Tab Pool 版本
4. `core/search.py` — 通用工具 + 惰性导入包装
5. `core/search_chroma.py` — Chroma 向量检索（logos_private_kb）
6. `core/search_dify.py` — Dify KB 检索
7. `core/rewrite.py` — Query Rewriting（v0.3.0 新增 context 参数支持记忆注入）
8. `core/fusion.py` — RRF 融合 + 语义去重
9. `core/llm.py` — DeepSeek API 封装
10. `core/chroma_client.py` — Chroma 客户端 + Ollama Embedding（v0.3.0 新增 get_memory_collection）
11. `core/config.py` — 配置管理（v0.3.0 新增 Memory 配置项）
12. `core/memory/__init__.py` — Memory Service 包入口
13. `core/memory/ledger.py` — JSONL 追加写入
14. `core/memory/profile.py` — SQLite 用户档案卡
15. `core/memory/views.py` — 从 Ledger 生成摘要
16. `core/memory/policy.py` — 读写策略 + 隐私过滤
17. `core/memory/search.py` — Chroma logos_memory 语义检索
18. `api/memory.py` — /memory/* API 端点
19. `api/retrieve.py` — retrieve API（v0.3.0 新增 user_id + memory 注入）
20. `api/planner.py` — planner API（v0.3.0 新增 user_id + memory 注入）
21. `api/health.py` — 健康检查
22. `main.py` — FastAPI 入口（v0.3.0 新增 memory router + lifespan）
23. `.env` — 环境变量（需追加 Memory 配置）

### 设计文档（必须）
24. `Logos_Design_Document_v0.3.0.md` — 当前设计文档（用户已修正 8.3 节）
25. `logos_architecture_v3.png` — 架构图

### 测试脚本
26. `test_memory_e2e.py` — Phase 2.5 E2E 测试
27. `test_retrieve_e2e.py` — Phase 2 端到端测试脚本（如有）

---

## 六、用户特殊要求

1. 出现任何不懂的地方，**马上问用户**，不要自己在思维链里打转
2. 出现任何和之前提示词冲突的地方，**一切按照本交接文档为准**
3. 信息不足就不要浪费 token，**直接索要文件和提问**
4. **Dify 部署在机械革命 Windows**，API Key 已配置好
5. **当前待办是验证 Dify user_id 透传**，其他模块已稳定
6. 用户**坚持 Browser Pool 方案**（已实现为 Tab Pool），不要提议回退
7. 用户是**父子双用户场景**（市场营销 vs 国企管理），领域必须隔离
8. **不要建议购买任何付费服务**
9. **任何架构变更必须经用户确认**
10. **企业微信 user_id 透传验证**：Dify Tool 参数默认值需填 `{{#sys.user_id#}}`，但**尚未验证**企业微信渠道下是否生效，需新 Kimi 协助验证

---

*循逻辑之影，叩真理之声。*
