# D:\precision_agent\core\graphrag\query_engine.py
"""
GraphRAG 查询引擎
支持实体检索、子图展开、社区摘要查询、全局查询
"""

from typing import List, Dict, Any, Optional

from core.graphrag.graph_store import get_knowledge_graph, KnowledgeGraph
from core.graphrag.community import get_community_engine, CommunityEngine


class GraphQueryEngine:
    """图查询引擎"""

    def __init__(self, kg: KnowledgeGraph = None, ce: CommunityEngine = None):
        self.kg = kg or get_knowledge_graph()
        self.ce = ce or get_community_engine()

    def query_entity(self, entity_name: str,
                     include_neighbors: bool = True) -> Dict[str, Any]:
        """查询单个实体的完整信息"""
        entity = self.kg.get_entity(entity_name)
        if not entity:
            return {"found": False, "message": f"实体 '{entity_name}' 不存在"}

        result = {
            "found": True,
            "entity": entity,
            "community_id": self.ce.get_entity_community(entity_name)
        }

        if include_neighbors:
            result["neighbors"] = self.kg.get_neighbors(entity_name)
            result["subgraph"] = self.kg.get_subgraph(entity_name, depth=2)

        return result

    def search_entities(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """搜索实体"""
        return self.kg.search_entities(query, top_k)

    def query_subgraph(self, entity_names: List[str],
                       depth: int = 2) -> Dict[str, Any]:
        """查询多实体的联合子图"""
        all_nodes = set()
        all_edges = []

        for name in entity_names:
            subgraph = self.kg.get_subgraph(name, depth)
            for node in subgraph.get("nodes", []):
                all_nodes.add(node["name"])
            all_edges.extend(subgraph.get("edges", []))

        # 去重边
        seen_edges = set()
        unique_edges = []
        for e in all_edges:
            key = (e.get("source"), e.get("target"), e.get("relation_type"))
            if key not in seen_edges:
                seen_edges.add(key)
                unique_edges.append(e)

        # 获取节点详情
        node_details = []
        for n in all_nodes:
            d = self.kg.get_entity(n)
            if d:
                node_details.append(d)

        return {
            "seed_entities": entity_names,
            "depth": depth,
            "nodes": node_details,
            "edges": unique_edges,
            "node_count": len(node_details),
            "edge_count": len(unique_edges)
        }

    def query_community(self, community_id: int) -> Dict[str, Any]:
        """查询社区详情"""
        comm = self.ce.get_community(community_id)
        if not comm:
            return {"found": False, "message": f"社区 {community_id} 不存在"}

        # 获取社区内所有实体的详情
        nodes_detail = []
        for node_name in comm.get("nodes", []):
            entity = self.kg.get_entity(node_name)
            if entity:
                nodes_detail.append(entity)

        return {
            "found": True,
            "community": comm,
            "entities": nodes_detail
        }

    def get_communities(self) -> List[Dict[str, Any]]:
        """获取所有社区列表"""
        return list(self.ce.get_all_communities().values())

    def get_inter_community_relations(self) -> List[Dict[str, Any]]:
        """获取社区间关系"""
        return self.ce.get_inter_community_relations()

    def global_query(self, query: str, top_k_entities: int = 5,
                     depth: int = 2) -> Dict[str, Any]:
        """
        全局查询：先搜索相关实体，然后展开子图，最后聚合社区信息
        返回可用于 Synthesize 的 answer_context
        """
        # 1. 搜索相关实体
        matched_entities = self.search_entities(query, top_k_entities)
        if not matched_entities:
            return {
                "query": query,
                "matched_entities": [],
                "subgraph": {"nodes": [], "edges": []},
                "relevant_communities": [],
                "answer_context": "未在知识图谱中找到相关实体。"
            }

        entity_names = [e["name"] for e in matched_entities]

        # 2. 展开联合子图
        subgraph = self.query_subgraph(entity_names, depth)

        # 3. 收集相关社区
        community_ids = set()
        for name in entity_names:
            cid = self.ce.get_entity_community(name)
            if cid is not None:
                community_ids.add(cid)

        communities = []
        for cid in community_ids:
            comm = self.ce.get_community(cid)
            if comm:
                communities.append(comm)

        # 4. 构建回答上下文
        context_parts = []

        # 实体信息
        for e in matched_entities:
            context_parts.append(
                f"【实体】{e['name']} ({e.get('type', 'UNKNOWN')}): "
                f"{e.get('description', '')}"
            )

        # 关系信息（限制数量避免上下文爆炸）
        for edge in subgraph.get("edges", [])[:10]:
            context_parts.append(
                f"【关系】{edge['source']} --{edge.get('relation_type', '')}--> "
                f"{edge['target']}: {edge.get('description', '')}"
            )

        # 社区摘要
        for comm in communities:
            context_parts.append(
                f"【主题社区】{comm.get('theme', '未知')}: "
                f"{comm.get('description', '')}"
            )

        return {
            "query": query,
            "matched_entities": matched_entities,
            "subgraph": subgraph,
            "relevant_communities": communities,
            "answer_context": "\n".join(context_parts)
        }


# ───────────────────────────────────────────────
# 全局单例
# ───────────────────────────────────────────────

_query_engine = None

def get_query_engine() -> GraphQueryEngine:
    """获取查询引擎单例"""
    global _query_engine
    if _query_engine is None:
        _query_engine = GraphQueryEngine()
    return _query_engine
