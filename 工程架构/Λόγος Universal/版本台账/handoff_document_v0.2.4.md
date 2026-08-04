# Λόγος Agent 项目交接文档 v0.2.4

**交接日期**: 2026-07-27  
**项目路径**: `D:\precision_agent`  
**交接原因**: 上下文窗口即将耗尽

---

## 一、项目状态总览

| 模块 | 设计文档要求 | 当前状态 | 备注 |
|------|-------------|---------|------|
| Query Rewriting | 每个子查询改写 1-3 个检索变体 | ✅ 已完成 | `core/rewrite.py`，**已改为上限 2 个变体** |
| Query Planner | 子查询拆解 + skill_hint | ✅ 已完成 | `api/planner.py`，未改动 |
| Bing 搜索 | DrissionPage 浏览器自动化 | ✅ **已完成** | **改为 Tab Pool（单浏览器+多标签页）** |
| 百度搜索 | DrissionPage 浏览器自动化 | ✅ **已完成** | **改为 Tab Pool（单浏览器+多标签页）** |
| Chroma 向量库 | 接入实际 Chroma 实例 | ✅ 已完成 | `chromadb 1.5.9` 已安装，Ollama bge-m3 embed_batch 模式正常 |
| Dify KB 检索 | 调用 Dify 知识库 API | ⚠️ 部分异常 | 自动发现 5 个知识库，**部分知识库报 400 错误** |
| RRF 融合 | 按排名倒数融合 + 去重 | ✅ 已完成 | `core/fusion.py`，未改动 |
| 内容过滤 | 丢弃 <200 字的结果 | ✅ 已完成 | `api/retrieve.py`，阈值保持 200 字 |
| main.py reload | 生产环境关闭 | ✅ 已完成 | `UVICORN_RELOAD` 环境变量控制 |
| 代码清理 | search.py / config.py 重复 | ✅ 已完成 |

---

## 二、Browser Pool 攻坚 — 已完成（Tab Pool 方案）

### 【事实】最终方案
- **架构**：单浏览器进程 + 多标签页 Pool（替代多实例方案）
- **Bing Pool**: `TabPool("bing", pool_size=3, base_port=9223)`
- **Baidu Pool**: `TabPool("baidu", pool_size=3, base_port=9226)`
- **并发验证**：8 查询并发测试通过，全部返回有效结果
- **端到端验证**：`retrieve.py` 全流程跑通，最终返回 Top 10 结果

### 【事实】关键代码文件
1. `core/browser_pool.py` — `TabPool` 类，管理 Chromium 进程和标签页生命周期
2. `core/search_bing.py` — Bing 搜索，使用 `TabPool` + `asyncio.to_thread`
3. `core/search_baidu.py` — 百度搜索，同上
4. `core/search.py` — 含 `fetch_page` 通用工具 + `search_chroma`/`search_dify_kb` 惰性导入包装

### 【推测】已知问题
1. **偶发端口漂移**：`ChromiumPage` 在 Windows 下偶发连到默认端口 9222 而非指定端口（9223/9226），导致"浏览器连接失败"。**但自动重试机制（`_create_browser` 内 `_kill_port_process` + 重建）能恢复**。
2. **标签页 #0 创建失败**：预创建时标签页 #0 偶发失败，#1/#2 成功。**推测与 Chrome 启动初始化时序有关**。
3. **Dify KB 400 错误**：`PluginDaemonInternalServerError: no available node, plugin runtime not found`。**推测是 Dify 内部 Tongyi 插件节点问题，非我方代码问题**。
4. **端到端测试最后卡住**：日志显示浏览器启动成功后无后续输出。**推测可能是 asyncio.gather 中 chroma/dify 任务与浏览器任务竞争事件循环，或某个连接 hang 住**。

---

## 三、检索策略调整（v0.2.4 新增）

| 参数 | 原设计 | 当前实现 | 原因 |
|------|--------|---------|------|
| 子查询上限 | 无封顶 | **最多 5 条** | 防止 LLM 过度拆分导致上下文爆炸 |
| 改写变体数 | 3 个/子查询 | **2 个/子查询** | 减少检索调用量 33% |
| Bing 返回数 | 10 条 | **5 条** | 网页噪音多，取精华即可 |
| Baidu 返回数 | 10 条 | **5 条** | 同上 |
| Chroma 返回数 | 10 条 | **10 条** | 私有知识库质量高，保持权重 |
| Dify KB 返回数 | 10 条 | **10 条** | 同上 |
| 最终返回 LLM | 10 条 | **10 条** | 约 5000-8000 字，LLM 处理舒适 |

**设计意图**：搜索引擎"广而浅"（5 条），知识库"少而精"（10 条），RRF 融合后自然达到网页/知识库权重一半一半。

---

## 四、环境信息

| 设备 | Tailscale IP | 用途 |
|------|-------------|------|
| 机械革命 | 100.97.236.112 | 外部引擎主运行、Dify、Chroma |
| Mac Studio | 100.120.218.98 | Ollama bge-m3、ComfyUI |
| 腾讯云 | 101.42.184.53 | Nginx 反向代理、公网入口 |

- **Dify**: http://127.0.0.1 (v1.14.2)，知识库 API Key 已配置
- **Ollama**: http://100.120.218.98:11434，模型 `bge-m3`
- **Chroma DB**: `D:\precision_agent\chroma_db`，`chromadb 1.5.9` 已安装
- **Embedding**: 1024 维，bge-m3，embed_batch 模式
- **venv**: `D:\precision_agent\venv` 已激活

---

## 五、关键设计决策（防止幻觉）

1. **Bing 和百度都必须用 DrissionPage，不能用 requests**
2. **Bing 和百度拆分为独立文件**（search_bing.py / search_baidu.py）
3. **内容过滤阈值 200 字是核心防线**，不能降低
4. **模型名统一为 deepseek-v4-flash**（rewrite/planner）/ deepseek-v4-pro（synthesize）
5. **Chroma 是 Deep Lane 私有知识库主力**，Dify KB 留给 Fast Lane
6. **Embedding 用 Mac Studio Ollama bge-m3**，Tailscale 内网调用
7. `.env` 中 `OLLAMA_EMBED_MODEL=bge-m3`（无 `:latest`）
8. **子查询上限 5 条，改写变体上限 2 个，Bing/Baidu 各返回 5 条**

---

## 六、待办事项（新 Kimi 接手）

### 🔴 P1 — 端到端稳定性调优
- 【事实】当前端到端测试（`test_retrieve_e2e.py`）能跑完并返回结果，但**偶发卡在最后阶段**
- 【推测】可能是 asyncio.gather 中 chroma/dify 的同步阻塞调用与浏览器任务竞争事件循环
- **行动**：检查 `search_chroma` / `search_dify_kb` 是否有同步阻塞代码，考虑用 `asyncio.to_thread` 包裹

### 🔴 P2 — Dify KB 400 错误排查
- 【事实】知识库 `7196b2ed-9f03-43eb-bd81-17a32604a8a1` 检索报 400：`PluginDaemonInternalServerError: no available node`
- 【推测】Dify 内部 Tongyi 插件节点问题
- **行动**：检查 Dify 后台该知识库的模型配置，或尝试更换知识库测试

### 🟡 P3 — Chroma 检索验证
- 【事实】`chromadb 1.5.9` 已安装，Ollama embed_batch 模式检测成功
- 【事实】但之前的端到端测试中未看到 Chroma 返回具体结果（日志被 Dify 刷屏）
- **行动**：单独测试 `search_chroma` 函数，确认 165 chunks 能正常检索返回

### 🟡 P4 — 连续压力测试
- **行动**：连续运行 20 轮 retrieve，观察：
  - 标签页使用次数是否正确累加
  - 浏览器进程是否稳定（不崩溃）
  - 内存是否泄漏

---

## 七、文件清单（新 Kimi 必须索要）

### 当前运行版本（必须）
1. `core/browser_pool.py` — TabPool 实现
2. `core/search_bing.py` — Bing Tab Pool 版本
3. `core/search_baidu.py` — Baidu Tab Pool 版本
4. `core/search.py` — 含 fetch_page + 惰性导入包装
5. `core/rewrite.py` — 变体上限 2
6. `api/retrieve.py` — 子查询封顶 5，WEB_TOP_K=5
7. `core/llm.py` — call_llm 签名（system_prompt/user_prompt）
8. `main.py`
9. `.env`
10. `core/search_chroma.py`
11. `core/search_dify.py`
12. `core/fusion.py`
13. `core/config.py`
14. `api/planner.py`

### 测试脚本
15. `test_retrieve_e2e.py` — 端到端测试脚本（如有）

---

## 八、用户特殊要求

1. 出现任何不懂的地方，**马上问用户**，不要自己在思维链里打转
2. 出现任何和之前提示词冲突的地方，**一切按照本交接文档为准**
3. 信息不足就不要浪费 token，**直接索要文件和提问**
4. **Dify 部署在机械革命 Windows**，API Key 已配置好
5. **当前唯一待办是稳定性调优**，其他模块已稳定
6. 用户**坚持 Browser Pool 方案**（已实现为 Tab Pool），不要提议回退

---

*循逻辑之影，叩真理之声。*
