# Λόγος Agent · P2 Fast Lane 工作记忆扩展 — Dify 侧配置说明

**版本**: v0.4.5.2
**日期**: 2026-08-03
**改动位置**: Dify Agent 工作流 + 系统提示词

---

## 一、外部引擎变更（已部署）

### 1.1 新增端点：`POST /api/v1/fast_retrieve`

**功能**：Fast Lane 轻量检索，并行查询 Memory + Dify KB，低延迟（< 5s）。

**请求体**：
```json
{
  "query": "用户问题",
  "user_id": "企业微信UserID",
  "top_k": 5,
  "include_memory": true,
  "include_dify_kb": true
}
```

**响应体**：
```json
{
  "query": "用户问题",
  "memory_results": [
    {
      "content": "记忆内容...",
      "source": "memory",
      "score": 0.92,
      "metadata": {...}
    }
  ],
  "dify_kb_results": [
    {
      "title": "文档名",
      "url": "dify://dataset/...",
      "content": "文档片段...",
      "source": "dify_kb",
      "score": 0.85
    }
  ],
  "total_results": 2,
  "latency_ms": 1234.56
}
```

**特点**：
- 不走网页搜索（Bing/Baidu）
- 不走 Query Rewriting
- 不走 RRF 融合
- 不走内容质量过滤（≥200字）
- 总超时 8 秒，适合 Fast Lane 8 秒响应要求

---

## 二、Dify 工作流配置步骤

### 步骤 1：配置 API Tool（search_memory）

在 Dify → 工具 → 自定义工具 → 创建自定义工具：

| 配置项 | 值 |
|--------|-----|
| 名称 | `search_memory` |
| 描述 | 检索用户历史记忆和画像 |
| 请求方法 | POST |
| URL | `http://127.0.0.1:8000/api/v1/fast_retrieve` |
| 认证方式 | 无（内网直连） |

**请求 Schema**：
```json
{
  "type": "object",
  "properties": {
    "query": {"type": "string", "description": "检索 query"},
    "user_id": {"type": "string", "description": "用户ID"},
    "top_k": {"type": "integer", "default": 5},
    "include_memory": {"type": "boolean", "default": true},
    "include_dify_kb": {"type": "boolean", "default": false}
  },
  "required": ["query", "user_id"]
}
```

> **注意**：`include_dify_kb` 设为 `false`，因为 Dify KB 用内置节点查，不走外部引擎。

**响应 Schema**（简化版，Dify 只需读取 `memory_results`）：
```json
{
  "type": "object",
  "properties": {
    "memory_results": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "content": {"type": "string"},
          "score": {"type": "number"}
        }
      }
    }
  }
}
```

### 步骤 2：配置知识库检索（search_dify_kb）

Dify 内置功能，无需额外配置：
- 在 Agent 工作流中直接添加「知识库检索」节点
- 选择对应知识库（AIGC/享界/华祥塑业）
- 检索模式：混合检索（hybrid_search）
- Top K：5

### 步骤 3：更新 Agent 系统提示词

将系统提示词替换为 `Logos_Agent_System_Prompt_v0.4.5.2.md`（已生成）。

关键变更点：
1. Fast Lane 定义扩展为「工作记忆」
2. 可用工具增加 `search_memory` 和 `search_dify_kb`
3. 明确 Fast Lane 中禁止调用网页搜索和深度检索工具
4. 增加工作记忆扩展的五项快思考职能说明

### 步骤 4：更新 Agent 工作流（Fast Lane 分支）

在 Dify Agent 的 Fast Lane 处理分支中：

```
用户消息 → Hybrid Router → Fast Lane
    ↓
[条件判断] 是否需要记忆？
    ├─ 是 → 调用 search_memory API Tool
    │         ↓
    │      将 memory_results 注入上下文
    │
    ├─ [条件判断] 是否涉及 AIGC/享界/华祥塑业？
    │    ├─ 是 → 调用 Dify 内置知识库检索
    │    │         ↓
    │    │      将检索结果注入上下文
    │    │
    │    └─ 否 → 跳过
    │
    ↓
生成回答（1-3 句话）
```

---

## 三、测试验证

### 3.1 直接测试外部引擎端点

在机械革命上执行：

```bash
cd D:\precision_agent
# 确保外部引擎已运行（端口 8000）

# 测试 1：只查 Memory
curl -X POST http://127.0.0.1:8000/api/v1/fast_retrieve \
  -H "Content-Type: application/json" \
  -d '{"query":"上次讨论的变压器方案","user_id":"test_user","include_memory":true,"include_dify_kb":false}'

# 测试 2：只查 Dify KB
curl -X POST http://127.0.0.1:8000/api/v1/fast_retrieve \
  -H "Content-Type: application/json" \
  -d '{"query":"FLUX 提示词技巧","user_id":"test_user","include_memory":false,"include_dify_kb":true}'

# 测试 3：同时查两者
curl -X POST http://127.0.0.1:8000/api/v1/fast_retrieve \
  -H "Content-Type: application/json" \
  -d '{"query":"享界电力运维","user_id":"test_user","include_memory":true,"include_dify_kb":true}'
```

**预期结果**：
- latency_ms < 5000（正常内网 < 2000ms）
- memory_results 按 user_id 隔离（父子不串）
- dify_kb_results 包含 AIGC/享界/华祥塑业文档片段

### 3.2 端到端测试（通过企业微信）

发送以下消息，验证 Fast Lane 工作记忆扩展：

| 测试消息 | 预期行为 |
|----------|----------|
| "上次那个方案后来怎么处理的？" | 调用 search_memory，返回历史记忆 |
| "帮我写个 FLUX 提示词" | 调用 search_dify_kb（AIGC 知识库），返回提示词模板 |
| "这个怎么样？"（前文讨论过某设备） | 指代消解：回溯 L0 窗口 + search_memory 补全 |
| "变压器巡检周期是多久？" | 调用 search_dify_kb（享界电力运维知识库） |

---

## 四、回滚方案

若出现问题：
1. 外部引擎：还原 `api/retrieve.py` 到 v0.4.5 版本
2. Dify 侧：还原系统提示词到 v0.4.5 版本
3. Dify 工作流：移除 `search_memory` API Tool 调用节点

---

## 五、Epistemic Agency 检查

| 维度 | 检查项 | 结果 |
|------|--------|------|
| 来源意识 | Fast Lane 回答是否标注了来源（memory/dify_kb）？ | ✅ 结果中带有 source 和 score |
| 过程介入 | 用户能否在 Fast Lane 中拒绝记忆检索？ | ✅ 由 Dify 工作流条件判断控制 |
| 错误归属 | 记忆检索失败时是否明确告知？ | ✅ 异常时返回空列表，Agent 说"暂无法获取" |

*循逻辑之影，叩真理之声。*
