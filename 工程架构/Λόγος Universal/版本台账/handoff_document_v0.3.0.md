# Λόγος Agent 项目交接文档 v0.3.0

**交接日期**: 2026-07-27  
**项目路径**: `D:\precision_agent`  
**设计文档版本**: v0.3.0（记忆系统增补 · 搜索层重构）  
**交接原因**: 上下文窗口即将耗尽

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

### ⬜ Phase 2.5: 记忆系统 MVP — 架构已定，代码未写

| 模块 | 设计文档位置 | 当前状态 | 说明 |
|------|-------------|---------|------|
| Ledger (JSONL) | 5.3.1 | ⬜ 未开始 | 原始事件日志追加写入 |
| Profile (SQLite/JSON) | 5.3.1 | ⬜ 未开始 | 用户结构化档案卡 |
| Views (生成器) | 5.3.1 | ⬜ 未开始 | 从 Ledger 生成摘要和档案 |
| Policy (规则引擎) | 5.3.1 | ⬜ 未开始 | 控制读写、遗忘、隐私过滤 |
| Memory Search (Chroma) | 5.3.1 | ⬜ 未开始 | `logos_memory` collection 语义检索 |
| API (`api/memory.py`) | 5.3.1 | ⬜ 未开始 | `/memory/profile` (读) + `/memory/ledger` (写) |
| Dify 集成 | 5.3.4 | ⬜ 未开始 | Planner 前读记忆、对话结束后写 Ledger |

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
| `fetch_page` SSL/Timeout 噪音 | 日志噪音大，不影响结果 | CSDN 加 `verify=False`，超时 5s→8s（可选） |
| Dify KB 400 错误 | 特定知识库 `7196b2ed-...` 偶发 | Dify 内部 Tongyi 插件节点问题，非代码问题 |
| 标签页使用次数 | 单次请求刷到 3 次，50 次上限可能几轮用完 | 有自动淘汰和应急创建机制，不会崩 |
| FastAPI `on_event` 弃用 | DeprecationWarning | 建议换 `lifespan`（可选） |

---

## 三、关键设计决策（防止幻觉）

1. **SearXNG 已永久废弃**，搜索层使用 Bing + 百度混合搜索
2. **Bing 和百度都必须用 DrissionPage**，不能用 requests
3. **内容过滤阈值 200 字是核心防线**，不能降低
4. **模型名统一为 deepseek-v4-flash**（rewrite/planner）/ deepseek-v4-pro（synthesize）
5. **Chroma 是 Deep Lane 私有知识库主力**，Dify KB 留给 Fast Lane
6. **Embedding 用 Mac Studio Ollama bge-m3**，Tailscale 内网调用
7. **子查询上限 5 条，改写变体上限 2 个，Bing/百度各返回 5 条**
8. **记忆系统放在外部引擎**，不是 Dify 侧
9. **记忆检索作为改写输入注入**，不参与 RRF 融合（避免父子领域交叉污染）
10. **Ledger 用 JSONL**，只追加不修改
11. **父子双用户场景**，领域完全隔离，retrieve 需增加 `user_id`

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

---

## 五、文件清单（新 Kimi 必须索要）

### 当前运行版本（必须）
1. `core/browser_pool.py` — TabPool 实现
2. `core/search_bing.py` — Bing Tab Pool 版本
3. `core/search_baidu.py` — Baidu Tab Pool 版本
4. `core/search.py` — 通用工具 + 惰性导入包装
5. `core/search_chroma.py` — Chroma 向量检索
6. `core/search_dify.py` — Dify KB 检索
7. `core/rewrite.py` — Query Rewriting（json_mode + 四层 fallback）
8. `core/fusion.py` — RRF 融合 + 语义去重
9. `core/llm.py` — DeepSeek API 封装
10. `core/chroma_client.py` — Chroma 客户端 + Ollama Embedding
11. `core/config.py` — 配置管理
12. `api/retrieve.py` — retrieve API（子查询封顶 5，分层超时）
13. `api/planner.py` — planner API
14. `api/health.py` — 健康检查
15. `main.py` — FastAPI 入口
16. `.env` — 环境变量

### 设计文档（必须）
17. `Logos_Design_Document_v0.3.0.md` — 当前设计文档
18. `logos_architecture_v3.png` — 架构图

### 测试脚本（如有）
19. `test_retrieve_e2e.py` — 端到端测试脚本

---

## 六、用户特殊要求

1. 出现任何不懂的地方，**马上问用户**，不要自己在思维链里打转
2. 出现任何和之前提示词冲突的地方，**一切按照本交接文档为准**
3. 信息不足就不要浪费 token，**直接索要文件和提问**
4. **Dify 部署在机械革命 Windows**，API Key 已配置好
5. **当前待办是 Phase 2.5 记忆系统 MVP**，其他模块已稳定
6. 用户**坚持 Browser Pool 方案**（已实现为 Tab Pool），不要提议回退
7. 用户是**父子双用户场景**（市场营销 vs 国企管理），领域必须隔离
8. **不要建议购买任何付费服务**
9. **任何架构变更必须经用户确认**

---

*循逻辑之影，叩真理之声。*
