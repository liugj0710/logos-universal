# Λόγος Agent 工作交接文档

**交接时间**: 2026-07-24  
**交接原因**: 上下文窗口即将耗尽  
**当前版本**: v0.2.1（Query Rewriting 已集成）  
**工程文档**: Logos_Design_Document_v0.2.1.md（已锁定）

---

## 一、当前开发进度（严格对照工程文档）

### ✅ Phase 1: Fast Lane 先行 — 已完成
- **Dify Agent 系统提示词**: 已部署，含 Clarify Router + Hybrid Router + Fast Lane 戒律 + Deep Lane Phase 1 临时约束
- **可用工具（Dify 侧）**: TavilySearch、maths(eval_expression)、time、openweather、pdf_process、regex、json_process、code
- **模型**: DeepSeek-V4 Flash，temperature=0.3，Top P=0.9，思考模式需确认是否已关闭
- **验收状态**: 已通过
  - Fast Lane 简单查询 ≤8 秒 ✅
  - Clarify 追问自然 ≤20 字 ✅
  - Deep Lane 正确识别复杂问题 ✅
  - 计算调用 maths 工具 ✅

### 🔄 Phase 2: 外部引擎骨架 — 进行中（约 70%）

**已完成部分:**
- FastAPI 服务部署在机械革命 `D:\precision_agent`，端口 8000
- `/api/v1/health` 正常返回 `{"status":"ok"}`
- `/api/v1/planner` 正常：DeepSeek-V4 Flash 驱动，JSON 输出，子查询拆解正确
  - 测试输入: "帮我分析一下新能源汽车行业的SWOT"
  - 输出: 2 个子查询 + target_entity + skill_hint(market_swot) + reasoning
- Query Rewriting 模块已集成（core/rewrite.py）
  - DeepSeek-V4 Flash 改写，temperature=0.3
  - 每个子查询生成 1-3 个检索变体
  - 已验证改写逻辑正确
- RRF 融合 + 去重逻辑已编写（core/fusion.py）

**未完成部分:**
- ❌ SearXNG 403 Forbidden（最高优先级堵点）
- ❌ Chroma 向量库未初始化
- ❌ deep_hybrid_retrieve 返回空 retrieved_chunks（因搜索源问题）
- ❌ Dify 侧未接入外部引擎自定义 Tool
- ❌ Phase 2 验收标准未达成

### ⏳ Phase 3-5: 未开始

---

## 二、当前堵点与问题（按优先级排序）

### 🔴 P0: SearXNG 403 Forbidden
**现象**: 容器内和外部请求 `localhost:8080/search?q=xxx&format=json` 均返回 403  
**已尝试**: 
1. 创建 `settings.yml` 设置 `limiter: false` 和 `botdetection.ip_limit.enabled: false`
2. Docker volume 挂载（Windows 路径问题）
3. 重建容器（`docker rm -f` + `docker run`）
4. 带 User-Agent 头请求
**均无效**。

**用户约束**: Tavily 额度宝贵（50次/月免费），不能用于外部引擎调试。必须解决 SearXNG 或找到替代本地搜索方案。

**建议排查方向**:
1. 检查 SearXNG 镜像版本是否过旧（7周前部署），尝试 `docker pull searxng/searxng:latest` 后重建
2. 检查 Windows Docker 的 volume 挂载是否真正生效：`docker exec searxng cat /etc/searxng/settings.yml`
3. 如果 SearXNG 实在无法解决，考虑用 `duckduckgo-search` Python 库作为本地搜索替代（pip install duckduckgo-search）
4. 或者使用 Bing Search API（需申请 Key，但比 Tavily 便宜）

### 🟡 P1: Chroma 向量库未初始化
**状态**: 代码已编写（core/search.py），但 `D:\precision_agent\chroma_db` 目录为空，未导入任何文档  
**影响**: retrieve 接口的 Chroma 搜索始终返回空列表  
**解决**: Phase 2 可先不依赖 Chroma，但需在验收前确认 Chroma 客户端能正常创建 collection

### 🟡 P1: Dify 侧未接入外部引擎
**状态**: FastAPI 服务在机械革命本地运行，Dify 尚未配置自定义 Tool 调用 `localhost:8000`  
**注意**: Dify 和外部引擎在同一台机器（机械革命）上，Dify 调用 `http://localhost:8000` 应该可以直接访问

### 🟢 P2: 思考模式 Token 消耗
**状态**: 计算查询仍消耗 ~5.7k token，可能思考模式未完全关闭  
**解决**: 确认 Dify 模型设置中"思考模式"为 False

---

## 三、项目文件位置

### 设计文档（用户已持有）
- `Logos_Design_Document_v0.2.1.md` — 主设计文档
- `logos_architecture_v2.png` — 架构图
- `Logos_Design_Document_v0.2(1).docx` — 原始 docx 版本

### 外部引擎代码（机械革命 D:\precision_agent）
```
D:\precision_agent\
├── main.py              # FastAPI 入口，uvicorn 启动
├── .env                 # 环境变量（含 DeepSeek Key）
├── requirements.txt     # 依赖
├── api\
│   ├── __init__.py
│   ├── health.py        # /api/v1/health
│   ├── planner.py       # /api/v1/planner (DeepSeek Flash)
│   └── retrieve.py      # /api/v1/retrieve (含 Query Rewriting)
├── core\
│   ├── __init__.py
│   ├── llm.py           # DeepSeek API 封装
│   ├── rewrite.py       # Query Rewriting 模块
│   ├── search.py        # 搜索层（当前 Tavily fallback）
│   ├── fusion.py        # RRF + 去重
│   └── config.py        # 配置管理
├── skills\              # Skill Menu 模板（Markdown）
│   ├── market_swot.md
│   ├── tech_timeline.md
│   ├── competitive_matrix.md
│   └── default_deep.md
└── tests\               # 测试脚本（待补充）
```

### Dify 配置
- Agent 名称: Λόγος Agent（或类似）
- 模型: DeepSeek-V4 Flash
- 系统提示词: 见下方"需上传文件"

---

## 四、下一步必须完成的动作（按顺序）

1. **解决搜索源问题**（P0）
   - 方案 A: 修复 SearXNG 403
   - 方案 B: 替换为 duckduckgo-search Python 库
   - 方案 C: 接入 Bing Search API
   - **目标**: retrieve 接口返回非空 retrieved_chunks

2. **初始化 Chroma**（P1）
   - 创建 collection
   - 确认 search_chroma 返回空列表但不报错（当前已满足）

3. **Dify 接入外部引擎**（P1）
   - 在 Dify 创建两个自定义 Tool:
     - `deep_query_planner`: POST http://localhost:8000/api/v1/planner
     - `deep_hybrid_retrieve`: POST http://localhost:8000/api/v1/retrieve
   - 更新 Agent 系统提示词，将 Deep Lane 流程改为调用外部引擎

4. **Phase 2 验收**
   - Dify 能成功调用 Planner → Retrieve 全流程
   - Retrieve 返回结果包含 `rewritten_queries` 和 `source_stats`
   - 召回率对比无改写基线提升 ≥8%

---

## 五、给新 Kimi 的约束（防幻觉）

1. **严格遵循 v0.2.1 设计文档**，任何架构变更必须经用户确认并标注
2. **不要建议用户购买/升级任何服务**（如 Tavily Pro、OpenWeather 付费等）
3. **所有代码必须适配 Windows 路径**（使用 `\` 或 `os.path.join`）
4. **所有 API 调用必须验证后再告诉用户"通了"**，不要假设
5. **如果 SearXNG 实在解决不了，不要死磕**，立刻提供 duckduckgo-search 替代方案
6. **Token 成本控制**: 提醒用户关闭思考模式，监控 DeepSeek API 消耗
7. **不要修改已锁定的设计决策**（如 Clarify 前置、Reflection 方案 B、Ollama 备用等）
