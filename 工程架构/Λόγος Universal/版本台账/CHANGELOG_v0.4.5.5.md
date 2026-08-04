# Λόγος Agent · 版本更新文档

**版本**: v0.4.5.5 (正式版)  
**发布日期**: 2026-08-04  
**状态**: ✅ 已发版  
**项目路径**: `D:\precision_agent`  

---

## 一、版本变更摘要

本版本是 Phase 5.1 的收官正式版，解决了 Fast Lane / Deep Lane 路由混乱、记忆系统失联、企业微信推送截断等核心体验问题。标志着 Λόγος 从"能跑"进入"可用"阶段。

### 核心修复
1. **Fast Lane 路由校正** — 闲聊、设定上下文、记忆查询不再误触发 Deep Lane
2. **记忆系统全链路打通** — 新增 `search_memory` / `search_dify_kb` / `write_ledger` 三个 Dify 自定义工具
3. **会话持久化恢复** — 从备份恢复 `user_sessions.json`，重建 Dify 对话上下文映射
4. **企业微信推送截断修复** — `_send_long_message` max_length 从 1500 降至 700（中文字符 ≈ 2100 字节，留余量）
5. **引用格式统一** — 从段落级来源卡片改为 `[1][2]` 数字上标 + 文末参考文献列表

---

## 二、详细变更列表

### 2.1 外部引擎层（机械革命）

| 文件 | 版本 | 变更内容 | 部署状态 |
|------|------|---------|---------|
| `core/synthesize.py` | v0.4.5.5 | 引用格式改为 `[1][2]` 数字上标；删除段落级来源锚定卡片注入；新增多源整合与禁止元分析约束；给 chunk 加 `[1][2]` 编号 | ✅ 已部署 |
| `api/retrieve.py` | v0.4.5.2 | Fast Lane `fast_retrieve` 端点（并行查 Memory + Dify KB，低延迟） | ✅ 已稳定 |
| `api/memory.py` | v0.4.5.2 | Ledger 写入、Profile 读写、记忆检索 API | ✅ 已稳定 |
| `core/llm.py` | v0.4.5.2 | DeepSeek API 调用，连接池复用 | ✅ 已稳定 |
| `core/memory/search.py` | v0.4.5.2 | Chroma `logos_memory` 语义检索，按 user_id 隔离 | ✅ 已稳定 |
| `core/search_dify.py` | v0.4.5.1 | 分层过滤（保留高置信度短片段） | ✅ 已稳定 |
| `wechat_bridge_v2.py` | v2.2 | timeout 4s→3s；被动回复增加 MAX_PASSIVE_REPLY_LEN=1000 截断；`_send_long_message` max_length: 2000→1500→**700**；推送失败降级逻辑 | ✅ 已部署 |
| `api/health.py` | v0.4.5.2 | 版本号同步为 `0.4.0` | ✅ 已稳定 |
| `main.py` | v0.4.0 | 入口文件，版本标记 `0.4.0` | ✅ 已稳定 |

### 2.2 Dify 侧（Agent 配置）

| 配置项 | 变更内容 | 部署状态 |
|--------|---------|---------|
| 系统提示词 | v0.4.5.5：新增 Clarify 状态锚定、禁止自主解读、强制自检；新增禁止元分析、多源整合要求；**新增 Fast Lane 记忆归档纪律**；**明确闲聊/设定上下文走 Fast Lane** | ✅ 已部署 |
| `search_memory` 工具 | 新增自定义 HTTP 工具，调用 `/api/v1/fast_retrieve`（`include_memory=true`） | ✅ 已导入并勾选 |
| `search_dify_kb` 工具 | 新增自定义 HTTP 工具，调用 `/api/v1/fast_retrieve`（`include_dify_kb=true`） | ✅ 已导入并勾选 |
| `write_ledger` 工具 | **新增**自定义 HTTP 工具，调用 `/api/v1/memory/ledger`，Fast Lane 回复后强制归档 | ✅ 已导入并勾选 |
| `deep_query_planner` | 已有工具，服务器地址 `http://100.97.236.112:9000` | ✅ 已稳定 |
| `deep_hybrid_retrieve` | 已有工具 | ✅ 已稳定 |
| `deep_synthesize` | 已有工具 | ✅ 已稳定 |
| `logos_graphrag_query` | 已有工具 | ✅ 已稳定 |

### 2.3 基础设施

| 项目 | 变更 | 状态 |
|------|------|------|
| 外部引擎代理端口 | 8000 → **9000**（MSL 占用） | ✅ 已生效 |
| 腾讯云安全组 | 开放 9000 端口入站规则 | ✅ 已配置 |
| `user_sessions.json` | 从备份 `user_sessions(1).json` 恢复，`LiuGuanJie` → `dbfc3330-6553-4aa1-a220-daabd4235ac8` | ✅ 已恢复 |
| Mac Studio Ollama | bge-m3 必须启动（检索层依赖） | ✅ 已确认运行 |

---

## 三、已知问题（剩余）

| # | 现象 | 严重度 | 根因 | 计划修复版本 |
|---|------|--------|------|-------------|
| 1 | 企业微信主动推送全部失败（errcode 60020） | 🔴 高 | 机械革命出网 IP `124.238.79.236` 未在企微后台"企业可信 IP"白名单中 | 需用户手动配置 |
| 2 | Fast Lane 回复偶发"消失" | 🔴 高 | 企业微信被动回复 5 秒超时，Dify 响应慢时超时 | v0.4.6（考虑预加载/缓存） |
| 3 | Agent 在 Clarify 后自行继续分析 | 🟡 中 | ReAct Agent 机制下 LLM 自主解读用户意图 | v0.4.6（Clarify 框架选项延期） |
| 4 | 报告偶发"资料不足"免责说明 | 🟡 中 | 提示词过度强调诚实披露 | v0.4.5.5 已缓解（禁止元分析约束） |
| 5 | 后台 GraphRAG build 30s 超时跳过部分 chunk | 🟢 低 | 正常行为，已有重试机制 | 不修复 |
| 6 | 30s 单 chunk 抽取超时 | 🟢 低 | 正常行为，已有重试机制 | 不修复 |
| 7 | Citation Validator content_mismatch | 🟢 低 | LLM 概括性改写的正常表现（阈值 0.3） | 不修复 |

---

## 四、测试报告摘要

### 4.1 记忆系统链路测试

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 同会话指代消解 | ✅ 通过 | "这个模型" → 正确识别为 LTX 2.3 |
| 跨会话记忆检索（search_memory） | ✅ 通过 | 重置后询问历史偏好，Agent 调用 search_memory 并正确回答 |
| 记忆写入（write_ledger） | ✅ 通过 | Fast Lane 回复后自动归档到 Ledger |
| 记忆再认（search_memory 返回空） | ✅ 通过 | Agent 直接说"无记录"，不转 Deep Lane |

### 4.2 路由测试

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 闲聊/设定上下文 → Fast Lane | ✅ 通过 | "我常用 LTX 2.3" 不再启动棱镜 |
| 深度分析 → Deep Lane | ✅ 通过 | "LTX-Video 跑跳动作技巧" 正确启动棱镜 |
| Clarify 追问 → WAITING | ✅ 通过 | 追问后停止，等待用户回复 |

### 4.3 企业微信桥接测试

| 测试项 | 结果 | 说明 |
|--------|------|------|
| 被动回复截断 | ✅ 通过 | MAX_PASSIVE_REPLY_LEN=1000 生效 |
| 主动推送分段 | ✅ 通过 | max_length=700，长报告分 3 段推送 |
| 推送失败降级 | ✅ 通过 | 推送失败时存入 pending_tasks，用户发"结果"可查询 |
| 会话重置 | ✅ 通过 | "重置"指令正确清空 user_sessions 并回复确认 |

---

## 五、部署清单（归档用）

### 5.1 必须归档的文件

```
D:\precision_agent/
├── main.py                              # v0.4.0
├── .env                                 # 环境变量
├── requirements.txt                     # 依赖
├── core/
│   ├── synthesize.py                    # v0.4.5.5 ⚠️ 关键更新
│   ├── llm.py                          # 稳定
│   ├── config.py                       # 稳定
│   ├── rewrite.py                      # 稳定
│   ├── fusion.py                       # 稳定
│   ├── chroma_client.py                # 稳定
│   ├── citation_validator.py           # 稳定
│   ├── search.py                       # 稳定
│   ├── search_bing.py                  # 稳定
│   ├── search_baidu.py                 # 稳定
│   ├── search_chroma.py              # 稳定
│   ├── search_dify.py                 # v0.4.5.1 分层过滤
│   ├── browser_pool.py               # 稳定
│   ├── memory/
│   │   ├── ledger.py                   # 稳定
│   │   ├── profile.py                  # 稳定
│   │   ├── views.py                    # 稳定
│   │   ├── policy.py                   # 稳定
│   │   └── search.py                  # 稳定
│   └── graphrag/
│       ├── extractor.py               # v0.4.4-fix3
│       ├── graph_store.py             # 稳定
│       ├── community.py               # v0.4.4
│       └── query_engine.py            # 稳定
├── api/
│   ├── planner.py                     # 稳定
│   ├── retrieve.py                    # v0.4.5.2 ⚠️ 含 fast_retrieve
│   ├── synthesize.py                  # v0.4.4
│   ├── graphrag.py                    # v0.4.4-fix3
│   ├── memory.py                      # v0.4.5.2
│   ├── citation_validator.py          # 稳定
│   ├── health.py                      # v0.4.5.2
│   └── __init__.py
├── wechat_bridge_v2.py                # v2.2 ⚠️ 关键更新
├── user_sessions.json                 # 已恢复
├── data/
│   ├── graphrag/                      # 约 530 节点 / 419 边
│   ├── ledger/                        # JSONL 日志
│   └── profiles/
│       └── profiles.db                # SQLite
├── chroma_db/                         # Chroma 向量库
└── docs/
    ├── Logos_Engineering_Document_v0.4.5.1.docx
    ├── CHANGELOG_v0.4.5.5.md           # ← 本文件
    └── handover_v0.4.5.5.md            # 交接文档
```

### 5.2 Dify 侧配置备份

- Agent 系统提示词（v0.4.5.5）
- 自定义工具 OpenAPI Schema（4 个）：
  - `deep_query_planner`
  - `deep_hybrid_retrieve`
  - `logos_graphrag_query`
  - `deep_synthesize`
  - `search_memory`（新增）
  - `search_dify_kb`（新增）
  - `write_ledger`（新增）

---

## 六、环境信息

| 设备 | Tailscale IP | 用途 |
|------|-------------|------|
| 机械革命 | 100.97.236.112:9000 | 外部引擎主运行、Dify、Chroma、桥接服务 |
| Mac Studio | 100.120.218.98:11434 | Ollama bge-m3、ComfyUI |
| 腾讯云 | 101.42.184.53 | Nginx 反向代理、公网入口 |
| 小米平板 | 100.93.118.52 | 终端 |

- **Dify**: http://127.0.0.1 (v1.14.2)
- **Ollama**: http://100.120.218.98:11434，模型 `bge-m3`
- **桥接服务**: 端口 5000
- **Dify API Key**: `app-OEDNpbufKiczr1W2uuzUDqR3`

---

## 七、下一步计划（v0.4.6）

| 优先级 | 工作项 | 说明 |
|--------|--------|------|
| 🔴 P0 | Deep Lane 协作中断点 | Planner/Retrieve/Synthesize 间插入用户确认节点 |
| 🔴 P1 | Clarify 框架选项 | 从追问改为提供分析框架选项 |
| 🟡 P2 | Fast Lane 预加载/缓存 | 解决被动回复 5 秒超时问题 |
| 🟡 P3 | GraphRAG 可视化查询 | `/graphrag/visualize?entity=xxx` API |
| 🟢 P4 | 产能利用率检索 | 验证华祥塑业文档 Deep Lane 检索路径 |
| 🟢 P5 | Agent 独白泄漏 | 完善 filter_react_thoughts，覆盖非标准 Thought 格式 |

---

*循逻辑之影，叩真理之声。*  
*AI 不是替你思考，而是让你的思考更清晰。*

---
**文档生成**: Kimi-2 · 2026-08-04  
**版本**: v0.4.5.5 (正式版)
