# Λόγος Agent 项目交接文档 v0.2.2

**交接日期**: 2026-07-26  
**项目路径**: `D:\precision_agent`  
**交接原因**: 上下文窗口即将耗尽

---

## 一、项目状态总览

| 模块 | 设计文档要求 | 当前状态 | 备注 |
|------|-------------|---------|------|
| Query Rewriting | 每个子查询改写 1-3 个检索变体 | ✅ 已完成 | `core/rewrite.py` |
| Query Planner | 子查询拆解 + skill_hint | ✅ 已完成 | `api/planner.py` |
| Bing 搜索 | DrissionPage 浏览器自动化 | ⚠️ 功能正常，并发冲突 | 单例复用，6查询并发时元素失效 |
| 百度搜索 | DrissionPage 浏览器自动化 | ⚠️ 功能正常，并发冲突 | 同上 |
| Chroma 向量库 | 接入实际 Chroma 实例 | ✅ 已完成 | 165 chunks 已入库，Ollama bge-m3 |
| Dify KB 检索 | 调用 Dify 知识库 API | ✅ **已完成** | 自动发现 5 个知识库，检索正常 |
| RRF 融合 | 按排名倒数融合 + 去重 | ✅ 已完成 | `core/fusion.py` |
| 内容过滤 | 丢弃 <200 字的结果 | ✅ 已完成 | `api/retrieve.py` |
| main.py reload | 生产环境关闭 | ✅ 已完成 | `UVICORN_RELOAD` 环境变量控制 |
| 代码清理 | search.py / config.py 重复 | ✅ 已完成 | 后半部分重复内容已删除 |

---

## 二、当前最高优先级问题

### 🔴 P1 — Browser Pool 并发方案（攻坚中）

**问题描述**：
`retrieve.py` 对每个改写后的子查询并行调用 `search_bing` + `search_baidu`。
6 个子查询 = 12 个浏览器任务同时争抢单例实例，导致 DrissionPage 元素引用大量失效（"元素对象已失效"、"与页面的连接已断开"）。

**已尝试方案及结果**：

| 方案 | 实施状态 | 结果 | 失败原因 |
|------|---------|------|---------|
| 单例 + asyncio.Lock | 未实施 | — | 用户担心串行速度太慢（~30s），否决 |
| 每个查询新开浏览器 | 已尝试 | ❌ 失败 | DrissionPage 多实例端口冲突，"连接已断开" |
| Browser Pool (3实例, auto_port) | 已尝试 | ❌ 失败 | `auto_port(True)` 在 Windows 上报 `not enough values to unpack` |
| Browser Pool (3实例, user-data-dir) | 已尝试 | ⚠️ 部分成功 | 实例能创建，但仍有元素失效 + 60s 超时 |

**当前代码状态**：
- 项目中 `search_bing.py` / `search_baidu.py` 仍是**单例版本**（有并发问题）
- `browser_pool.py` **未纳入项目**（作为参考代码存在，需继续调试）
- **用户决策**：继续攻坚 Pool 方案，不放弃（"大厂面试题，不能轻言放弃"）

**推荐调试路径**（供新 Kimi 参考）：
1. 硬编码调试端口（9223/9224/9225）替代 `auto_port`
2. 为每个 Pool 实例增加独立 `--remote-debugging-port`
3. 在 `_do_search` 中增加详细时间戳日志，定位卡点和元素失效时机
4. Pool size 从 1 开始验证，逐步增加到 2、3
5. 检查 `asyncio.to_thread` 与 DrissionPage 的线程兼容性（DrissionPage 的 CDP 连接是否线程安全？）
6. 备选：如 Pool 实在调不通，向用户提议回退到"单例+Lock+限制查询数"务实方案

---

## 三、环境信息

| 设备 | Tailscale IP | 用途 |
|------|-------------|------|
| 机械革命 | 100.97.236.112 | 外部引擎主运行、Dify、Chroma |
| Mac Studio | 100.120.218.98 | Ollama bge-m3、ComfyUI |
| 腾讯云 | 101.42.184.53 | Nginx 反向代理、公网入口 |

- **Dify**: http://127.0.0.1 (v1.14.2)，知识库 API Key 已配置
- **Ollama**: http://100.120.218.98:11434，模型 `bge-m3`
- **Chroma DB**: `D:\precision_agent\chroma_db`
- **Embedding**: 1024 维，bge-m3

---

## 四、关键设计决策（防止幻觉）

1. **Bing 和百度都必须用 DrissionPage，不能用 requests**
2. **Bing 和百度拆分为独立文件**（search_bing.py / search_baidu.py）
3. **内容过滤阈值 200 字是核心防线**，不能降低
4. **模型名统一为 deepseek-v4-flash**
5. **Chroma 是 Deep Lane 私有知识库主力**，Dify KB 留给 Fast Lane
6. **Embedding 用 Mac Studio Ollama bge-m3**，Tailscale 内网调用
7. `.env` 中 `OLLAMA_EMBED_MODEL=bge-m3`（无 `:latest`）

---

## 五、文件清单（新 Kimi 必须索要）

### 项目中的实际文件（当前运行状态）
1. `core/search_bing.py` —— 当前单例版本，有并发问题
2. `core/search_baidu.py` —— 当前单例版本，有并发问题
3. `core/search_dify.py` —— 已采纳，Dify KB 检索实现
4. `core/search.py` —— 已清理重复内容，统一入口
5. `core/config.py` —— 已清理重复内容
6. `api/retrieve.py` —— 已更新，接入 Dify KB
7. `main.py` —— 已更新，reload 环境变量控制
8. `.env` —— 已更新，Dify 配置正确
9. `core/chroma_client.py`
10. `core/search_chroma.py`

### 参考代码（未采纳，作为调试起点）
11. `core/browser_pool.py` —— 需继续调试的 Pool 实现（如用户未保存，需向用户索要或重写）

### 测试脚本
12. `test_dify.py` —— 用于验证 retrieve 端点（如有）

---

## 六、用户特殊要求

1. 出现任何不懂的地方，**马上问用户**，不要自己在思维链里打转
2. 出现任何和之前提示词冲突的地方，**一切按照本交接文档为准**
3. 信息不足就不要浪费 token，**直接索要文件和提问**
4. **Dify 部署在机械革命 Windows**，API Key 已配置好，不需要再指导获取
5. **Bing/百度并发问题是当前唯一攻坚点**，其他模块已稳定
6. 用户**坚持 Browser Pool 方案**，但如实在调不通可提议务实方案（单例+Lock）

---

*循逻辑之影，叩真理之声。*
