# Λόγος Universal v5.0

> **Λόγος**（逻各斯）— 认识论代理权驱动的认知协作系统  
> *Nous Lab presents*

[![Version](https://img.shields.io/badge/version-v5.0-blue)]()
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-green)]()
[![Dify](https://img.shields.io/badge/Dify-1.14.2-orange)]()

---

## 一、项目简介

Λόγος Universal 是一套面向企业场景的**双轨认知代理系统**，通过 **Fast Lane（快思考）** 与 **Deep Lane（慢思考）** 的协同，为用户提供从即时问答到深度分析的全谱系智能服务。

系统以 **Epistemic Agency（认识论代理权）** 为第一性原理，确保用户始终保有：
- **来源意识** — 知道结论来自哪里
- **过程介入** — 能在关键节点改变方向
- **错误归属** — 出问题时明确是人还是系统的偏差

---

## 二、核心特性

### 双轨认知架构
| 维度 | Fast Lane · 工作记忆 | Deep Lane · 棱镜系统 |
|------|---------------------|---------------------|
| **响应速度** | 1-3 句话，8 秒内 | 30-90 秒深度报告 |
| **处理能力** | 指代消解、记忆再认、领域快查 | 多源检索、结构化分析、报告生成 |
| **工具集** | `search_memory` / `search_dify_kb` / `write_ledger` | `deep_query_planner` / `deep_hybrid_retrieve` / `logos_graphrag_query` / `deep_synthesize` |
| **模型** | DeepSeek-V4 Flash | DeepSeek-V4 Pro |

### 记忆系统（Mnemosyne）
- **Ledger** — 只追加事件日志，真相源
- **Profile** — SQLite 结构化用户档案
- **Views** — 异步摘要生成，自动归档到 Chroma
- **Policy** — 隐私过滤与写入策略

### 知识图谱（GraphRAG）
- 基于 NetworkX 的实体关系网络
- LLM 批量抽取 + Louvain 社区发现
- 后台异步构建，Semaphore(2) 限流
- 当前规模：约 **530 节点 / 419 边**

### 企业微信桥接
- 被动回复（5 秒超时）+ 主动推送双模式
- 长消息自动分段（700 字符/段）
- 会话持久化 + 重置指令支持

---

## 三、系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                    企业微信用户                              │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│  Nous 层（Dify ReAct Agent）                                │
│  ├── Clarify Router — 问题澄清与框架提供                     │
│  └── Hybrid Router — Fast Lane / Deep Lane 路由             │
└──────────────────────┬──────────────────────────────────────┘
                       │
        ┌──────────────┴──────────────┐
        ▼                             ▼
┌──────────────────┐        ┌──────────────────────────────┐
│ Fast Lane        │        │ Deep Lane · 棱镜系统          │
│ ├─ search_memory │        │ ├─ deep_query_planner        │
│ ├─ search_dify_kb│        │ ├─ deep_hybrid_retrieve      │
│ ├─ write_ledger  │        │ ├─ logos_graphrag_query      │
│ └─ 直接回答       │        │ └─ deep_synthesize           │
└──────────────────┘        └──────────────┬───────────────┘
                                           │
┌──────────────────────────────────────────▼────────────────┐
│              外部引擎（FastAPI · 机械革命）                 │
│  ├─ 检索层：Bing + 百度 + Chroma + Dify KB                 │
│  ├─ 记忆层：Ledger / Profile / Views / Policy              │
│  ├─ 图谱层：GraphRAG（NetworkX + LLM 摘要）                 │
│  └─ 生成层：DeepSeek-V4 Pro 结构化报告                      │
└───────────────────────────────────────────────────────────┘
```

---

## 四、快速开始

### 4.1 环境要求

| 组件 | 版本/配置 |
|------|----------|
| Python | 3.10+ |
| OS | Windows 10/11（机械革命）/ macOS（Mac Studio） |
| GPU | RTX 4060 8GB（推理辅助） |
| 内存 | 16GB+（机械革命）/ 128GB（Mac Studio） |

### 4.2 安装依赖

```bash
cd D:\precision_agent
pip install -r requirements.txt
```

### 4.3 环境变量（.env）

```env
# DeepSeek API
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
DEEPSEEK_BASE_URL=https://api.deepseek.com

# Dify
DIFY_API_KEY=app-OEDNpbufKiczr1W2uuzUDqR3
DIFY_BASE_URL=http://127.0.0.1
DIFY_DATASET_IDS=your_dataset_id_1,your_dataset_id_2

# Chroma & Embedding
CHROMA_PERSIST_DIR=D:\precision_agent\chroma_db
EMBEDDING_MODEL=bge-m3
OLLAMA_HOST=http://100.120.218.98:11434

# 记忆系统
LEDGER_DIR=D:\precision_agent\data\ledger
PROFILE_DB_PATH=D:\precision_agent\data\profiles\profiles.db
MEMORY_COLLECTION_NAME=logos_memory

# 企业微信（可选，不配则仅支持被动回复）
WECHAT_SECRET=your_corp_secret

# 服务端口
HOST=0.0.0.0
PORT=9000
```

### 4.4 启动服务

**Mac Studio（Ollama Embedding）**
```bash
ollama run bge-m3
```

**windows（外部引擎）**
```bash
cd D:\precision_agent
python main.py
```

**企业微信桥接（另开终端）**
```bash
cd "D:\precision_agent\桥接服务和AIGC"
python wechat_bridge_v2.py
```

---

## 五、部署指南

### 5.1 Dify 侧配置

1. **导入自定义工具**（OpenAPI Schema）
   - `deep_query_planner` → `POST /api/v1/planner`
   - `deep_hybrid_retrieve` → `POST /api/v1/retrieve`
   - `logos_graphrag_query` → `POST /api/v1/graphrag/query`
   - `deep_synthesize` → `POST /api/v1/synthesize`
   - `search_memory` → `POST /api/v1/fast_retrieve`（`include_memory=true`）
   - `search_dify_kb` → `POST /api/v1/fast_retrieve`（`include_dify_kb=true`）
   - `write_ledger` → `POST /api/v1/memory/ledger`

2. **配置系统提示词**  
   将 `system_prompt_v0.4.5.5_fastlane_fix.txt` 粘贴到 Dify Agent 的系统提示词框。

3. **勾选工具**  
   在 Agent 工具面板中启用全部 7 个自定义工具。

### 5.2 网络拓扑

| 设备 | Tailscale IP | 服务 | 端口 |
|------|-------------|------|------|
| 机械革命 | 100.97.236.112 | 外部引擎 / Dify / Chroma / 桥接 | 9000 / 5000 |
| Mac Studio | 100.120.218.98 | Ollama bge-m3 / ComfyUI | 11434 |
| 腾讯云 | 101.42.184.53 | Nginx 反向代理 | 80 / 443 |

---

## 六、项目结构

```
D:\precision_agent/
├── main.py                          # FastAPI 入口
├── .env                             # 环境变量（勿提交 Git）
├── requirements.txt                 # Python 依赖
│
├── core/                            # 核心逻辑层
│   ├── synthesize.py               # 深度报告生成（v0.4.5.5）
│   ├── llm.py                      # DeepSeek API 封装
│   ├── config.py                   # 配置管理
│   ├── rewrite.py                  # 查询改写
│   ├── fusion.py                   # RRF 融合 + 语义去重
│   ├── chroma_client.py            # Chroma 向量客户端
│   ├── citation_validator.py     # 引用验证
│   ├── search.py                   # 搜索统一入口
│   ├── search_bing.py              # Bing 搜索（DrissionPage）
│   ├── search_baidu.py             # 百度搜索（DrissionPage）
│   ├── search_chroma.py            # Chroma 向量检索
│   ├── search_dify.py              # Dify KB 检索（分层过滤）
│   ├── browser_pool.py             # 浏览器池管理
│   │
│   ├── memory/                     # 记忆系统
│   │   ├── ledger.py               # 只追加事件日志
│   │   ├── profile.py              # SQLite 用户档案
│   │   ├── views.py                # 异步摘要生成
│   │   ├── policy.py               # 隐私过滤策略
│   │   └── search.py               # Chroma 记忆检索
│   │
│   └── graphrag/                   # 知识图谱
│       ├── extractor.py            # 实体关系抽取
│       ├── graph_store.py          # NetworkX 存储
│       ├── community.py            # Louvain 社区发现
│       └── query_engine.py         # 图谱查询引擎
│
├── api/                             # API 层（FastAPI Router）
│   ├── planner.py                  # 问题拆解
│   ├── retrieve.py                 # 多源检索（含 fast_retrieve）
│   ├── synthesize.py               # 报告生成接口
│   ├── graphrag.py                 # 图谱查询接口
│   ├── memory.py                   # 记忆读写接口
│   ├── citation_validator.py     # 引用验证接口
│   └── health.py                   # 健康检查
│
├── wechat_bridge_v2.py            # 企业微信桥接（v2.2）
├── user_sessions.json             # 会话持久化
│
├── data/                            # 数据目录
│   ├── graphrag/                   # 图谱存储（pickle + GEXF）
│   ├── ledger/                     # JSONL 事件日志
│   └── profiles/                   # SQLite 档案库
│
├── chroma_db/                       # Chroma 向量数据库
│   ├── logos_private_kb            # 私有知识库
│   └── logos_memory                # 用户记忆库
│
└── docs/                            # 文档
    ├── Logos_Engineering_Document_v0.4.5.1.docx
    ├── CHANGELOG_v0.4.5.5.md
    └── handover_v0.4.5.5.md
```

---

## 七、使用示例

### 7.1 Fast Lane — 记忆再认
```
用户：我之前告诉你我喜欢用什么模型做视频生成？

Λόγος：[调用 search_memory] → 查到记录
      → "你之前提到常用 LTX 2.3 模型，偏好中文提示词。"
```

### 7.2 Fast Lane — 设定上下文
```
用户：我主要做 ComfyUI，常用 Wan 2.1，以后默认用这个上下文。

Λόγος："已记下。以后回答 AIGC 问题时默认以 ComfyUI + Wan 2.1 为上下文。"
      [调用 write_ledger 归档]
```

### 7.3 Deep Lane — 深度分析
```
用户：分析一下 LTX-Video 在剧烈人物动作生成上的优化策略。

Λόγος："正在启动棱镜系统..."
      → [deep_query_planner] 拆解子查询
      → [deep_hybrid_retrieve] 多源检索
      → [logos_graphrag_query] 图谱上下文
      → [deep_synthesize] 生成结构化报告
      → 分 3 段推送至企业微信
```

---

## 八、记忆系统说明

### 数据流
```
用户对话 → Dify Agent → write_ledger → 外部引擎 /api/v1/memory/ledger
                                    ↓
                              Ledger（JSONL，按日分文件）
                                    ↓
                              Views（异步摘要，LLM 生成）
                                    ↓
                              logos_memory（Chroma 向量库）
                                    ↓
                              用户查询 → search_memory → 语义检索
```

### 隐私保护
- 自动脱敏：API Key、手机号、身份证号等敏感信息写入前自动过滤
- 用户隔离：所有记忆按 `user_id` 严格隔离
- TTL 策略：Ledger 热数据保留 30 天，支持归档压缩

---

## 九、企业微信桥接

### 双模式架构
| 模式 | 触发条件 | 特点 |
|------|---------|------|
| **被动回复** | 用户消息 → Dify 5 秒内返回 | 超时 3 秒，1000 字截断保护 |
| **主动推送** | Deep Lane 异步任务完成 | 分段推送（700 字/段），1.5 秒间隔 |

### 指令
- `重置` / `清空` / `清除记忆` / `new` — 清空当前会话
- `结果` / `报告` / `status` — 查询异步任务状态

---

## 十、设计哲学

> **老瓦匠与学徒工**  
> AI 不是自动砌墙机，而是递砖、调水平、提醒"这里基层含水率高"的学徒工。最终砌墙的是老瓦匠——用户自己。没有老瓦匠的方向感，给再多先进工具也砌不好墙。

### Epistemic Agency 三问
1. 这个改动让用户更清楚信息的来源了吗？
2. 这个改动让用户能在关键节点改变方向吗？
3. 这个改动让错误更容易被归因到人还是系统吗？

---

## 十一、版本信息

- **当前版本**: v5.0 (Λόγος Universal)
- **基础版本**: v0.4.5.5
- **发布日期**: 2026-08-04
- **状态**: 正式版

---

## 十二、致谢

- **DeepSeek** — 大语言模型支持
- **Dify** — Agent 编排框架
- **Chroma** — 向量数据库
- **NetworkX** — 图算法与存储
- **DrissionPage** — 浏览器自动化

---

*循逻辑之影，叩真理之声。*
