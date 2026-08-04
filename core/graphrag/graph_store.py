# D:\precision_agent\core\graphrag\graph_store.py
"""
GraphRAG 图存储引擎 — NetworkX 实现
支持实体去重、关系合并、增量更新、持久化
v0.4.1 修复：GEXF 导出前清理列表/字典等复杂属性，避免 write_gexf 崩溃
"""

import os
import pickle
import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
from difflib import SequenceMatcher

try:
    import networkx as nx
    NX_AVAILABLE = True
except ImportError:
    nx = None
    NX_AVAILABLE = False

from core.config import get_settings

settings = get_settings()

# ───────────────────────────────────────────────
# 持久化路径
# ───────────────────────────────────────────────

GRAPH_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "graphrag"
)
os.makedirs(GRAPH_DIR, exist_ok=True)

GRAPH_PICKLE_PATH = os.path.join(GRAPH_DIR, "knowledge_graph.pkl")
GRAPH_GEXF_PATH = os.path.join(GRAPH_DIR, "knowledge_graph.gexf")
COMMUNITY_PICKLE_PATH = os.path.join(GRAPH_DIR, "communities.pkl")


# ───────────────────────────────────────────────
# KnowledgeGraph 类
# ───────────────────────────────────────────────

class KnowledgeGraph:
    """知识图谱 — NetworkX 有向图"""

    def __init__(self):
        if not NX_AVAILABLE:
            raise ImportError(
                "networkx 未安装，请执行: pip install networkx"
            )
        self._graph = nx.DiGraph()
        self._entity_aliases: Dict[str, str] = {}  # alias -> canonical_name

    @property
    def graph(self):
        return self._graph

    def _canonical_name(self, name: str) -> str:
        """获取实体的规范名称（处理别名）"""
        return self._entity_aliases.get(name, name)

    def _similarity(self, a: str, b: str) -> float:
        """计算两个名称的相似度"""
        if not a or not b:
            return 0.0
        ca = a.lower().strip()
        cb = b.lower().strip()
        if ca == cb:
            return 1.0
        return SequenceMatcher(None, ca, cb).ratio()

    def find_similar_entity(self, name: str, entity_type: str = None,
                            threshold: float = 0.85) -> Optional[str]:
        """查找相似实体，用于去重"""
        for node, data in self._graph.nodes(data=True):
            if entity_type and data.get("type") != entity_type:
                continue
            if self._similarity(name, node) >= threshold:
                return node
        return None

    def add_entity(self, name: str, entity_type: str, description: str = "",
                   confidence: float = 1.0, source_chunk: str = None) -> Optional[str]:
        """
        添加/更新实体。如果存在相似实体则合并。
        返回规范名称。
        """
        name = name.strip()
        if not name:
            return None

        # 检查是否已有精确匹配
        canonical = self._canonical_name(name)
        if canonical in self._graph:
            # 更新现有实体
            data = self._graph.nodes[canonical]
            data["mention_count"] = data.get("mention_count", 1) + 1
            data["last_seen"] = datetime.now(timezone.utc).isoformat()
            if source_chunk and source_chunk not in data.get("source_chunks", []):
                data.setdefault("source_chunks", []).append(source_chunk)
            if description and len(description) > len(data.get("description", "")):
                data["description"] = description
            if confidence > data.get("confidence", 0):
                data["confidence"] = confidence
            return canonical

        # 检查模糊匹配
        similar = self.find_similar_entity(name, entity_type)
        if similar:
            # 注册别名
            self._entity_aliases[name] = similar
            # 更新现有实体
            data = self._graph.nodes[similar]
            data["mention_count"] = data.get("mention_count", 1) + 1
            data["last_seen"] = datetime.now(timezone.utc).isoformat()
            if source_chunk and source_chunk not in data.get("source_chunks", []):
                data.setdefault("source_chunks", []).append(source_chunk)
            # 合并别名
            aliases = set(data.get("aliases", []))
            aliases.add(name)
            data["aliases"] = list(aliases)
            return similar

        # 新建实体
        now = datetime.now(timezone.utc).isoformat()
        self._graph.add_node(
            name,
            name=name,
            type=entity_type,
            description=description,
            confidence=confidence,
            first_seen=now,
            last_seen=now,
            mention_count=1,
            source_chunks=[source_chunk] if source_chunk else [],
            aliases=[]
        )
        return name

    def add_relation(self, source: str, target: str, relation_type: str,
                     description: str = "", confidence: float = 1.0,
                     source_chunk: str = None) -> bool:
        """添加/更新关系。如果关系已存在则合并（权重累加）"""
        source = self._canonical_name(source.strip())
        target = self._canonical_name(target.strip())

        if not source or not target:
            return False
        if source not in self._graph or target not in self._graph:
            return False

        # 检查是否已有相同关系
        if self._graph.has_edge(source, target):
            edge_data = self._graph[source][target]
            if edge_data.get("relation_type") == relation_type:
                # 合并：权重累加，置信度取高
                edge_data["weight"] = edge_data.get("weight", 1) + 1
                edge_data["confidence"] = max(
                    edge_data.get("confidence", 0.5), confidence
                )
                edge_data["last_seen"] = datetime.now(timezone.utc).isoformat()
                if source_chunk and source_chunk not in edge_data.get("source_chunks", []):
                    edge_data.setdefault("source_chunks", []).append(source_chunk)
                if description and len(description) > len(edge_data.get("description", "")):
                    edge_data["description"] = description
                return True

        # 新建关系
        now = datetime.now(timezone.utc).isoformat()
        self._graph.add_edge(
            source, target,
            relation_type=relation_type,
            description=description,
            confidence=confidence,
            weight=1,
            first_seen=now,
            last_seen=now,
            source_chunks=[source_chunk] if source_chunk else []
        )
        return True

    def add_entities_relations(self, entities: List[Dict], relations: List[Dict],
                               source_chunk: str = None):
        """批量添加实体和关系"""
        entity_name_map = {}

        # 先添加所有实体
        for e in entities:
            ename = str(e.get("name", "")).strip()
            if not ename:
                continue
            canonical = self.add_entity(
                name=ename,
                entity_type=e.get("type", "CONCEPT"),
                description=e.get("description", ""),
                confidence=e.get("confidence", 0.5),
                source_chunk=source_chunk
            )
            if canonical:
                entity_name_map[ename] = canonical

        # 再添加关系
        for r in relations:
            src = entity_name_map.get(r.get("source", ""), r.get("source", ""))
            tgt = entity_name_map.get(r.get("target", ""), r.get("target", ""))
            self.add_relation(
                source=src,
                target=tgt,
                relation_type=r.get("relation_type", "connects_to"),
                description=r.get("description", ""),
                confidence=r.get("confidence", 0.5),
                source_chunk=source_chunk
            )

    def get_entity(self, name: str) -> Optional[Dict[str, Any]]:
        """获取实体详情（支持别名回查）"""
        canonical = self._canonical_name(name)
        if canonical not in self._graph:
            # v0.4.2: 别名回查 — 如果规范名找不到，尝试在别名中查找
            for alias, target in self._entity_aliases.items():
                if alias.lower() == name.lower() and target in self._graph:
                    canonical = target
                    break
            else:
                return None
        data = dict(self._graph.nodes[canonical])
        data["name"] = canonical
        data["degree"] = self._graph.degree(canonical)
        data["in_degree"] = self._graph.in_degree(canonical)
        data["out_degree"] = self._graph.out_degree(canonical)
        return data

    def get_neighbors(self, name: str, direction: str = "both") -> List[Dict[str, Any]]:
        """获取实体的邻居"""
        canonical = self._canonical_name(name)
        if canonical not in self._graph:
            return []

        results = []
        if direction in ("both", "out"):
            for _, target, data in self._graph.out_edges(canonical, data=True):
                results.append({
                    "direction": "out",
                    "entity": target,
                    "relation_type": data.get("relation_type"),
                    "description": data.get("description"),
                    "weight": data.get("weight", 1),
                    "confidence": data.get("confidence", 0.5)
                })
        if direction in ("both", "in"):
            for source, _, data in self._graph.in_edges(canonical, data=True):
                results.append({
                    "direction": "in",
                    "entity": source,
                    "relation_type": data.get("relation_type"),
                    "description": data.get("description"),
                    "weight": data.get("weight", 1),
                    "confidence": data.get("confidence", 0.5)
                })
        return results

    def search_entities(self, query: str, top_k: int = 10) -> List[Dict[str, Any]]:
        """基于名称相似度搜索实体"""
        query_lower = query.lower().strip()
        scored = []

        for node, data in self._graph.nodes(data=True):
            name = node.lower()
            desc = (data.get("description") or "").lower()

            name_score = SequenceMatcher(None, query_lower, name).ratio()
            desc_score = SequenceMatcher(None, query_lower, desc).ratio() if desc else 0

            score = max(name_score, desc_score * 0.5)
            if score > 0.3:
                scored.append((score, node, data))

        scored.sort(reverse=True)
        results = []
        for score, node, data in scored[:top_k]:
            item = dict(data)
            item["name"] = node
            item["match_score"] = round(score, 4)
            results.append(item)
        return results

    def get_subgraph(self, center: str, depth: int = 2) -> Dict[str, Any]:
        """获取以某实体为中心的子图"""
        canonical = self._canonical_name(center)
        if canonical not in self._graph:
            return {"nodes": [], "edges": []}

        nodes = {canonical}
        edges = []

        current_layer = {canonical}
        for _ in range(depth):
            next_layer = set()
            for node in current_layer:
                for neighbor in self._graph.successors(node):
                    if neighbor not in nodes:
                        next_layer.add(neighbor)
                        nodes.add(neighbor)
                        edges.append({
                            "source": node,
                            "target": neighbor,
                            **self._graph[node][neighbor]
                        })
                for neighbor in self._graph.predecessors(node):
                    if neighbor not in nodes:
                        next_layer.add(neighbor)
                        nodes.add(neighbor)
                        edges.append({
                            "source": neighbor,
                            "target": node,
                            **self._graph[neighbor][node]
                        })
            current_layer = next_layer

        node_list = []
        for n in nodes:
            d = dict(self._graph.nodes[n])
            d["name"] = n
            node_list.append(d)

        return {
            "center": canonical,
            "depth": depth,
            "nodes": node_list,
            "edges": edges
        }

    def get_stats(self) -> Dict[str, Any]:
        """获取图统计信息"""
        if self._graph.number_of_nodes() == 0:
            return {
                "node_count": 0,
                "edge_count": 0,
                "density": 0,
                "avg_degree": 0,
                "entity_type_distribution": {},
                "relation_type_distribution": {}
            }

        type_dist = {}
        for _, data in self._graph.nodes(data=True):
            t = data.get("type", "UNKNOWN")
            type_dist[t] = type_dist.get(t, 0) + 1

        rel_dist = {}
        for _, _, data in self._graph.edges(data=True):
            t = data.get("relation_type", "unknown")
            rel_dist[t] = rel_dist.get(t, 0) + 1

        degrees = list(dict(self._graph.degree()).values())
        avg_degree = round(sum(degrees) / len(degrees), 2) if degrees else 0

        return {
            "node_count": self._graph.number_of_nodes(),
            "edge_count": self._graph.number_of_edges(),
            "density": round(nx.density(self._graph), 4),
            "avg_degree": avg_degree,
            "entity_type_distribution": type_dist,
            "relation_type_distribution": rel_dist
        }

    def _clean_for_gexf(self, value: Any) -> Any:
        """
        将属性值清理为 GEXF 兼容的简单类型。
        GEXF 只支持: str, int, float, bool, list（特定格式）
        我们将列表/字典序列化为 JSON 字符串。
        """
        if value is None:
            return ""
        if isinstance(value, (str, int, float, bool)):
            return value
        # 列表、字典、元组等复杂类型 → JSON 字符串
        return json.dumps(value, ensure_ascii=False)

    def save(self) -> bool:
        """保存图到磁盘（pickle 为主，GEXF 为辅可视化）"""
        try:
            # 1. pickle 持久化（核心，保留所有数据类型）
            with open(GRAPH_PICKLE_PATH, "wb") as f:
                pickle.dump({
                    "graph": self._graph,
                    "aliases": self._entity_aliases
                }, f)
            print(f"[KnowledgeGraph] pickle 已保存: {GRAPH_PICKLE_PATH}")

            # 2. GEXF 导出（仅用于可视化，清理复杂属性）
            try:
                clean_graph = nx.DiGraph()
                for node, data in self._graph.nodes(data=True):
                    clean_data = {k: self._clean_for_gexf(v) for k, v in data.items()}
                    clean_graph.add_node(node, **clean_data)

                for src, tgt, data in self._graph.edges(data=True):
                    clean_data = {k: self._clean_for_gexf(v) for k, v in data.items()}
                    clean_graph.add_edge(src, tgt, **clean_data)

                nx.write_gexf(clean_graph, GRAPH_GEXF_PATH)
                print(f"[KnowledgeGraph] GEXF 已导出: {GRAPH_GEXF_PATH}")
            except Exception as e:
                print(f"[KnowledgeGraph] GEXF 导出失败（非阻塞，pickle 已保存）: {e}")

            return True
        except Exception as e:
            print(f"[KnowledgeGraph] 保存失败: {e}")
            import traceback
            traceback.print_exc()
            return False

    def load(self) -> bool:
        """从磁盘加载图"""
        if not os.path.exists(GRAPH_PICKLE_PATH):
            print(f"[KnowledgeGraph] 无现有图谱文件: {GRAPH_PICKLE_PATH}")
            return False
        try:
            with open(GRAPH_PICKLE_PATH, "rb") as f:
                data = pickle.load(f)
                self._graph = data["graph"]
                self._entity_aliases = data.get("aliases", {})
            print(f"[KnowledgeGraph] 已加载现有图谱: {self.get_stats()}")
            return True
        except Exception as e:
            print(f"[KnowledgeGraph] 加载失败: {e}")
            import traceback
            traceback.print_exc()
            return False


# ───────────────────────────────────────────────
# 全局单例
# ───────────────────────────────────────────────

_kg_instance = None

def get_knowledge_graph() -> KnowledgeGraph:
    """获取知识图谱单例"""
    global _kg_instance
    if _kg_instance is None:
        _kg_instance = KnowledgeGraph()
        if os.path.exists(GRAPH_PICKLE_PATH):
            _kg_instance.load()
    return _kg_instance
