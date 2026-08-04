# D:\precision_agent\core\graphrag\community.py
"""
GraphRAG 社区发现与摘要
基于 Louvain 算法 + LLM 摘要生成
"""
import asyncio
import json
import os
import pickle
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

try:
    import networkx as nx
    NX_AVAILABLE = True
except ImportError:
    nx = None
    NX_AVAILABLE = False

from core.llm import call_llm
from core.graphrag.graph_store import KnowledgeGraph, get_knowledge_graph, COMMUNITY_PICKLE_PATH


# ───────────────────────────────────────────────
# Prompt 模板
# ───────────────────────────────────────────────

_COMMUNITY_SUMMARY_PROMPT = """你是一个知识图谱分析专家。请根据以下社区内的实体和关系，生成结构化摘要。

【任务】
1. 总结该社区的核心主题（1-2句话）
2. 列出社区内的关键实体（3-5个）
3. 描述社区内的主要关系模式
4. 评估该社区的知识完整性（high/medium/low）

【输出格式】
严格按以下 JSON 输出，不要有任何额外解释：

{
  "theme": "社区主题",
  "key_entities": ["实体1", "实体2"],
  "relation_pattern": "关系模式描述",
  "completeness": "high",
  "description": "社区整体描述（100字以内）"
}"""


# ───────────────────────────────────────────────
# CommunityEngine 类
# ───────────────────────────────────────────────

class CommunityEngine:
    """社区发现与摘要引擎"""

    def __init__(self, kg: KnowledgeGraph = None):
        if not NX_AVAILABLE:
            raise ImportError("networkx 未安装")
        self.kg = kg or get_knowledge_graph()
        self._communities: Dict[int, Dict[str, Any]] = {}
        self._community_assignments: Dict[str, int] = {}  # entity_name -> community_id

    def detect_communities(self, resolution: float = 1.0) -> Dict[int, List[str]]:
        """
        使用 Louvain 算法发现社区
        返回: {community_id: [entity_names]}
        """
        G = self.kg.graph
        if G.number_of_nodes() == 0:
            return {}

        # 转换为无向图进行社区发现
        undirected = G.to_undirected()

        try:
            # NetworkX >= 2.8 内置 Louvain
            communities = nx.community.louvain_communities(
                undirected, resolution=resolution, seed=42
            )
        except AttributeError:
            # 回退：使用 python-louvain
            try:
                import community as community_louvain
                partition = community_louvain.best_partition(
                    undirected, resolution=resolution
                )
                comm_map = {}
                for node, comm_id in partition.items():
                    comm_map.setdefault(comm_id, set()).add(node)
                communities = list(comm_map.values())
            except ImportError:
                print("[CommunityEngine] Louvain 算法不可用，"
                      "请执行: pip install python-louvain 或升级 networkx>=2.8")
                return {}

        # 整理结果
        result = {}
        self._community_assignments = {}

        for idx, comm in enumerate(communities):
            nodes = list(comm)
            result[idx] = nodes
            for node in nodes:
                self._community_assignments[node] = idx

        return result

    async def summarize_community(self, community_id: int,
                                  nodes: List[str]) -> Dict[str, Any]:
        """为社区生成摘要"""
        G = self.kg.graph

        # 收集社区内的实体信息
        entity_descriptions = []
        for node in nodes:
            data = G.nodes.get(node, {})
            desc = data.get("description", "")
            etype = data.get("type", "UNKNOWN")
            entity_descriptions.append(f"- {node} ({etype}): {desc}")

        # 收集社区内的关系
        relations = []
        for i, src in enumerate(nodes):
            for tgt in nodes[i + 1:]:
                if G.has_edge(src, tgt):
                    edge = G[src][tgt]
                    relations.append(
                        f"- {src} --[{edge.get('relation_type')}]--> {tgt}: "
                        f"{edge.get('description', '')}"
                    )
                if G.has_edge(tgt, src):
                    edge = G[tgt][src]
                    relations.append(
                        f"- {tgt} --[{edge.get('relation_type')}]--> {src}: "
                        f"{edge.get('description', '')}"
                    )

        context = f"""【社区实体】({len(nodes)}个)
{chr(10).join(entity_descriptions[:15])}

【社区关系】({len(relations)}条)
{chr(10).join(relations[:20])}"""

        try:
            response = await call_llm(
                model="deepseek-v4-flash",
                system_prompt=_COMMUNITY_SUMMARY_PROMPT,
                user_prompt=context,
                temperature=0.3,
                max_tokens=600,
                json_mode=True
            )
            summary = json.loads(response)
        except Exception as e:
            print(f"[CommunityEngine] 社区 {community_id} 摘要生成失败: {e}")
            summary = {
                "theme": "未知主题",
                "key_entities": nodes[:5],
                "relation_pattern": "无法解析",
                "completeness": "low",
                "description": "摘要生成失败"
            }

        # 计算社区密度
        subgraph = G.subgraph(nodes)
        density = nx.density(subgraph) if NX_AVAILABLE else 0

        return {
            "community_id": community_id,
            "size": len(nodes),
            "density": round(density, 4),
            "nodes": nodes,
            **summary
        }

    async def build_all_summaries(self, resolution: float = 1.0) -> Dict[int, Dict[str, Any]]:
        """构建所有社区的摘要（v0.4.4 并行化）"""
        communities = self.detect_communities(resolution)
        if not communities:
            return {}

        self._communities = {}
        sem = asyncio.Semaphore(10)  # 限制并发，避免 DeepSeek 限流

        async def _summarize_with_limit(comm_id: int, nodes: List[str]):
            async with sem:
                return await self.summarize_community(comm_id, nodes)

        tasks = [
            _summarize_with_limit(comm_id, nodes)
            for comm_id, nodes in communities.items()
        ]

        summaries = await asyncio.gather(*tasks, return_exceptions=True)

        for comm_id, summary in zip(communities.keys(), summaries):
            if isinstance(summary, Exception):
                print(f"[CommunityEngine] 社区 {comm_id} 摘要异常: {summary}")
                summary = {
                    "community_id": comm_id,
                    "size": len(communities[comm_id]),
                    "theme": "未知主题",
                    "key_entities": list(communities[comm_id])[:5],
                    "relation_pattern": "无法解析",
                    "completeness": "low",
                    "description": "摘要生成失败"
                }
            self._communities[comm_id] = summary

        self.save()
        return self._communities

    def get_community(self, community_id: int) -> Optional[Dict[str, Any]]:
        """获取社区摘要"""
        return self._communities.get(community_id)

    def get_entity_community(self, entity_name: str) -> Optional[int]:
        """获取实体所属社区"""
        return self._community_assignments.get(entity_name)

    def get_all_communities(self) -> Dict[int, Dict[str, Any]]:
        """获取所有社区"""
        return self._communities

    def get_inter_community_relations(self) -> List[Dict[str, Any]]:
        """获取社区间关系"""
        G = self.kg.graph
        relations = []

        for src, tgt, data in G.edges(data=True):
            src_comm = self._community_assignments.get(src)
            tgt_comm = self._community_assignments.get(tgt)

            if (src_comm is not None and tgt_comm is not None
                    and src_comm != tgt_comm):
                relations.append({
                    "source_community": src_comm,
                    "target_community": tgt_comm,
                    "source_entity": src,
                    "target_entity": tgt,
                    "relation_type": data.get("relation_type"),
                    "weight": data.get("weight", 1)
                })

        # 合并相同社区对的关系
        merged = {}
        for r in relations:
            key = (r["source_community"], r["target_community"])
            if key not in merged:
                merged[key] = {
                    "source_community": r["source_community"],
                    "target_community": r["target_community"],
                    "relations": [],
                    "total_weight": 0
                }
            merged[key]["relations"].append(r)
            merged[key]["total_weight"] += r["weight"]

        return list(merged.values())

    def save(self) -> bool:
        """保存社区数据"""
        try:
            with open(COMMUNITY_PICKLE_PATH, "wb") as f:
                pickle.dump({
                    "communities": self._communities,
                    "assignments": self._community_assignments
                }, f)
            return True
        except Exception as e:
            print(f"[CommunityEngine] 保存失败: {e}")
            return False

    def load(self) -> bool:
        """加载社区数据"""
        if not os.path.exists(COMMUNITY_PICKLE_PATH):
            return False
        try:
            with open(COMMUNITY_PICKLE_PATH, "rb") as f:
                data = pickle.load(f)
                self._communities = data.get("communities", {})
                self._community_assignments = data.get("assignments", {})
            return True
        except Exception as e:
            print(f"[CommunityEngine] 加载失败: {e}")
            return False


# ───────────────────────────────────────────────
# 全局单例
# ───────────────────────────────────────────────

_community_engine = None

def get_community_engine() -> CommunityEngine:
    """获取社区引擎单例"""
    global _community_engine
    if _community_engine is None:
        _community_engine = CommunityEngine()
        _community_engine.load()
    return _community_engine
