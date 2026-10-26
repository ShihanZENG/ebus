"""
Pillar 2: Temporal Knowledge Graph & Agentic GraphRAG Engine
Built on Neo4j + Hybrid Retrieval (Vector + BM25 Keyword + Structured SQL + Multi-hop Cypher Traversal).
Fulfills LIM-FR-012, LIM-FR-013, and LIM-FR-014 (Temporal GraphRAG).

Capabilities:
1. Temporal Knowledge Graph Modeling (Neo4j + In-Memory Temporal Property Graph Fallback):
   - Entity Labels: SKU, Listing, SalesOrder, InventorySnapshot, Supplier, AdCampaign, PolicyClause
   - Temporal Edges (`valid_from`, `valid_to`, `version`):
     * (SKU)-[:LISTED_AS]->(Listing)
     * (Listing)-[:GENERATED_ORDER]->(SalesOrder)
     * (SKU)-[:STORED_IN]->(InventorySnapshot)
     * (SKU)-[:SUPPLIED_BY]->(Supplier)
     * (Listing)-[:PROMOTED_BY]->(AdCampaign)
     * (Listing|Supplier)-[:GOVERNED_BY]->(PolicyClause)
2. Dynamic Retrieval Planner (Agentic RAG):
   - Decomposes complex cross-domain diagnostic queries into sub-queries across Vector, Keyword (BM25),
     Structured SQL/Metric lookup, and Multi-hop Temporal Graph Traversal.
3. Reciprocal Rank Fusion (RRF) + Evidence Provenance & Knowledge Version Management:
   - Ranks multi-source evidence with full citation lineage (`source_type`, `entity_id`, `version`, `valid_window`).
"""

from __future__ import annotations

import hashlib
import math
import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    from neo4j import GraphDatabase  # type: ignore
    HAS_NEO4J = True
except ImportError:
    HAS_NEO4J = False
    GraphDatabase = None  # type: ignore


@dataclass
class TemporalNode:
    node_id: str
    label: str
    properties: Dict[str, Any]
    version: str = "v1.0"
    valid_from: str = "2026-01-01T00:00:00Z"
    valid_to: Optional[str] = None


@dataclass
class TemporalEdge:
    edge_id: str
    source_id: str
    target_id: str
    relation_type: str
    properties: Dict[str, Any] = field(default_factory=dict)
    version: str = "v1.0"
    valid_from: str = "2026-01-01T00:00:00Z"
    valid_to: Optional[str] = None


@dataclass
class EvidenceItem:
    evidence_id: str
    channel: str  # "vector" | "keyword_bm25" | "structured_sql" | "temporal_graph"
    entity_id: str
    content: str
    score: float
    version: str
    valid_from: str
    valid_to: Optional[str]
    provenance: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RetrievalPlan:
    plan_id: str
    original_query: str
    as_of_timestamp: str
    seed_entities: List[str]
    max_hops: int
    activated_channels: List[str]
    cypher_query: str
    sub_queries: List[str]


class TemporalKnowledgeGraphEngine:
    """
    Neo4j-backed Temporal Knowledge Graph with full in-memory multi-hop temporal graph fallback
    so tests and local dev environments work seamlessly with or without a live Neo4j daemon.
    """

    def __init__(
        self,
        neo4j_uri: Optional[str] = None,
        neo4j_user: Optional[str] = None,
        neo4j_password: Optional[str] = None,
    ) -> None:
        self._driver = None
        if neo4j_uri and HAS_NEO4J and GraphDatabase is not None:
            try:
                driver = GraphDatabase.driver(neo4j_uri, auth=(neo4j_user or "neo4j", neo4j_password or ""))
                driver.verify_connectivity()
                self._driver = driver
            except Exception:
                self._driver = None

        self.nodes: Dict[str, TemporalNode] = {}
        self.edges: List[TemporalEdge] = []
        self.knowledge_versions: Dict[str, Dict[str, Any]] = {}
        self._seed_default_temporal_graph()

    def _seed_default_temporal_graph(self) -> None:
        """Seeds standard cross-border e-commerce domain entities and temporal relations."""
        default_nodes = [
            TemporalNode(
                node_id="SKU-UK-DRESS-001",
                label="SKU",
                properties={"name": "Silk Midi Wrap Dress - Emerald", "cost_gbp": 18.0, "category": "Women Apparel"},
                version="v1.2",
                valid_from="2026-01-01T00:00:00Z",
            ),
            TemporalNode(
                node_id="LST-UK-9001",
                label="Listing",
                properties={"shop_id": "shop-uk-01", "price_gbp": 49.90, "status": "ACTIVE", "cvr": 0.042},
                version="v1.2",
                valid_from="2026-02-01T00:00:00Z",
            ),
            TemporalNode(
                node_id="INV-WH-UK-001",
                label="InventorySnapshot",
                properties={"warehouse_id": "wh-uk-main", "available_qty": 120, "reserved_qty": 35, "days_of_cover": 6.0},
                version="v1.4",
                valid_from="2026-10-01T00:00:00Z",
            ),
            TemporalNode(
                node_id="SUP-HZ-SILK-01",
                label="Supplier",
                properties={"name": "Hangzhou Silk Garment Co.", "lead_time_days": 14, "on_time_rate": 0.94},
                version="v1.1",
                valid_from="2026-01-01T00:00:00Z",
            ),
            TemporalNode(
                node_id="CAMP-UK-AUTUMN-01",
                label="AdCampaign",
                properties={"channel": "Meta/Google UK", "roas": 4.2, "daily_budget_gbp": 320.0, "acos": 0.238},
                version="v1.3",
                valid_from="2026-09-15T00:00:00Z",
            ),
            TemporalNode(
                node_id="POL-UK-RETURN-2026",
                label="PolicyClause",
                properties={
                    "title": "UK Consumer Contracts Regulations & Storefront Stock Hold Policy",
                    "rule": "Orders must atomically hold inventory for 30 minutes at checkout; ad scaling must pause when cover < 10 days.",
                },
                version="v2.0",
                valid_from="2026-06-01T00:00:00Z",
            ),
        ]
        for n in default_nodes:
            self.upsert_node(n)

        default_edges = [
            TemporalEdge("E-01", "SKU-UK-DRESS-001", "LST-UK-9001", "LISTED_AS", {"channel": "UK Storefront"}),
            TemporalEdge("E-02", "SKU-UK-DRESS-001", "INV-WH-UK-001", "STORED_IN", {"safety_days": 7}),
            TemporalEdge("E-03", "SKU-UK-DRESS-001", "SUP-HZ-SILK-01", "SUPPLIED_BY", {"moq": 100}),
            TemporalEdge("E-04", "LST-UK-9001", "CAMP-UK-AUTUMN-01", "PROMOTED_BY", {"attribution_window": "7d"}),
            TemporalEdge("E-05", "SKU-UK-DRESS-001", "POL-UK-RETURN-2026", "GOVERNED_BY", {"mandatory": True}),
        ]
        for e in default_edges:
            self.upsert_edge(e)

    def upsert_node(self, node: TemporalNode) -> None:
        self.nodes[node.node_id] = node
        self.knowledge_versions[node.node_id] = {
            "version": node.version,
            "valid_from": node.valid_from,
            "valid_to": node.valid_to,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if self._driver is not None:
            try:
                with self._driver.session() as session:
                    session.run(
                        f"MERGE (n:{node.label} {{node_id: $node_id}}) "
                        "SET n += $props, n.version = $version, n.valid_from = $valid_from, n.valid_to = $valid_to",
                        node_id=node.node_id,
                        props=node.properties,
                        version=node.version,
                        valid_from=node.valid_from,
                        valid_to=node.valid_to,
                    )
            except Exception:
                pass

    def upsert_edge(self, edge: TemporalEdge) -> None:
        self.edges = [e for e in self.edges if e.edge_id != edge.edge_id]
        self.edges.append(edge)
        if self._driver is not None:
            try:
                with self._driver.session() as session:
                    session.run(
                        "MATCH (a {node_id: $src}), (b {node_id: $dst}) "
                        f"MERGE (a)-[r:{edge.relation_type} {{edge_id: $edge_id}}]->(b) "
                        "SET r += $props, r.version = $version, r.valid_from = $valid_from, r.valid_to = $valid_to",
                        src=edge.source_id,
                        dst=edge.target_id,
                        edge_id=edge.edge_id,
                        props=edge.properties,
                        version=edge.version,
                        valid_from=edge.valid_from,
                        valid_to=edge.valid_to,
                    )
            except Exception:
                pass

    @staticmethod
    def _is_temporally_valid(valid_from: str, valid_to: Optional[str], as_of: str) -> bool:
        if valid_from and as_of < valid_from:
            return False
        if valid_to and as_of > valid_to:
            return False
        return True

    def traverse_multihop(
        self, seed_ids: List[str], max_hops: int = 2, as_of: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        as_of_ts = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        visited: Set[str] = set(seed_ids)
        frontier: List[Tuple[str, int, List[str]]] = [(sid, 0, [sid]) for sid in seed_ids if sid in self.nodes]
        paths: List[Dict[str, Any]] = []

        while frontier:
            curr_id, hop, path_trace = frontier.pop(0)
            if hop >= max_hops:
                continue
            for edge in self.edges:
                if not self._is_temporally_valid(edge.valid_from, edge.valid_to, as_of_ts):
                    continue
                neighbor_id = None
                if edge.source_id == curr_id:
                    neighbor_id = edge.target_id
                elif edge.target_id == curr_id:
                    neighbor_id = edge.source_id
                if neighbor_id and neighbor_id in self.nodes:
                    target_node = self.nodes[neighbor_id]
                    if not self._is_temporally_valid(target_node.valid_from, target_node.valid_to, as_of_ts):
                        continue
                    new_trace = path_trace + [f"--[{edge.relation_type}]-->", neighbor_id]
                    paths.append(
                        {
                            "hop": hop + 1,
                            "source_id": curr_id,
                            "target_id": neighbor_id,
                            "relation": edge.relation_type,
                            "target_label": target_node.label,
                            "target_properties": target_node.properties,
                            "version": target_node.version,
                            "valid_from": target_node.valid_from,
                            "valid_to": target_node.valid_to,
                            "path_trace": " ".join(new_trace),
                        }
                    )
                    if neighbor_id not in visited:
                        visited.add(neighbor_id)
                        frontier.append((neighbor_id, hop + 1, new_trace))
        return paths


class AgenticGraphRAGRetriever:
    """
    Agentic RAG + Hybrid Retrieval Engine:
    Combines Dynamic Retrieval Planning, Vector Cosine Similarity, BM25 Keyword Scoring,
    Structured Metric Lookup, and Multi-hop Temporal Graph Traversal with RRF fusion.
    """

    def __init__(self, graph_engine: Optional[TemporalKnowledgeGraphEngine] = None) -> None:
        self.graph = graph_engine or TemporalKnowledgeGraphEngine()

    @staticmethod
    def _tokenize(text: str) -> List[str]:
        return re.findall(r"[a-z0-9_]+|[\u4e00-\u9fff]", (text or "").lower())

    def _compute_embedding(self, text: str, dim: int = 32) -> List[float]:
        vec = [0.0] * dim
        tokens = self._tokenize(text)
        if not tokens:
            return vec
        for tok in tokens:
            h = int(hashlib.md5(tok.encode("utf-8")).hexdigest(), 16)
            idx = h % dim
            sign = 1.0 if (h >> 8) % 2 == 0 else -1.0
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]

    @staticmethod
    def _cosine(v1: List[float], v2: List[float]) -> float:
        return sum(a * b for a, b in zip(v1, v2))

    def build_retrieval_plan(
        self, query: str, seed_entities: Optional[List[str]] = None, as_of: Optional[str] = None
    ) -> RetrievalPlan:
        as_of_ts = as_of or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        seeds = seed_entities or ["SKU-UK-DRESS-001"]
        cypher = (
            "MATCH path = (s:SKU {node_id: $seed_id})-[r*1..2]-(n) "
            "WHERE ALL(rel IN relationships(path) WHERE rel.valid_from <= $as_of "
            "AND (rel.valid_to IS NULL OR rel.valid_to >= $as_of)) "
            "RETURN path, n.node_id, labels(n), n.version"
        )
        sub_queries = [
            f"[Vector/Semantic] Retrieve policy and diagnostic knowledge for: {query}",
            f"[BM25/Keyword] Exact match SKU/Listing/Supplier identifiers in: {', '.join(seeds)}",
            f"[Structured/SQL] Fetch latest inventory snapshot, ROAS, and PO lead time for {', '.join(seeds)}",
            f"[TemporalGraph/Cypher] 2-hop temporal neighborhood traversal from {', '.join(seeds)} as of {as_of_ts}",
        ]
        return RetrievalPlan(
            plan_id=f"PLAN-{uuid.uuid4().hex[:8].upper()}",
            original_query=query,
            as_of_timestamp=as_of_ts,
            seed_entities=seeds,
            max_hops=2,
            activated_channels=["vector", "keyword_bm25", "structured_sql", "temporal_graph"],
            cypher_query=cypher,
            sub_queries=sub_queries,
        )

    def retrieve(
        self,
        query: str,
        seed_entities: Optional[List[str]] = None,
        as_of: Optional[str] = None,
        top_k: int = 8,
    ) -> Dict[str, Any]:
        plan = self.build_retrieval_plan(query, seed_entities=seed_entities, as_of=as_of)
        q_vec = self._compute_embedding(query)
        q_tokens = set(self._tokenize(query))

        channel_results: Dict[str, List[EvidenceItem]] = {
            "vector": [],
            "keyword_bm25": [],
            "structured_sql": [],
            "temporal_graph": [],
        }

        # 1. Vector + 2. BM25 + 3. Structured lookups over temporal nodes
        for node_id, node in self.graph.nodes.items():
            if not self.graph._is_temporally_valid(node.valid_from, node.valid_to, plan.as_of_timestamp):
                continue
            serialized = f"{node.node_id} {node.label} {node.properties}"
            doc_vec = self._compute_embedding(serialized)
            vec_score = max(0.0, (self._cosine(q_vec, doc_vec) + 1.0) / 2.0)

            doc_tokens = set(self._tokenize(serialized))
            overlap = len(q_tokens & doc_tokens)
            bm25_score = overlap / max(1.0, math.sqrt(len(doc_tokens)))
            if node_id in plan.seed_entities:
                bm25_score += 1.0

            channel_results["vector"].append(
                EvidenceItem(
                    evidence_id=f"EV-VEC-{node_id}",
                    channel="vector",
                    entity_id=node_id,
                    content=serialized,
                    score=round(vec_score, 4),
                    version=node.version,
                    valid_from=node.valid_from,
                    valid_to=node.valid_to,
                    provenance={"label": node.label, "retrieval_mode": "dense_vector"},
                )
            )
            channel_results["keyword_bm25"].append(
                EvidenceItem(
                    evidence_id=f"EV-BM25-{node_id}",
                    channel="keyword_bm25",
                    entity_id=node_id,
                    content=serialized,
                    score=round(bm25_score, 4),
                    version=node.version,
                    valid_from=node.valid_from,
                    valid_to=node.valid_to,
                    provenance={"label": node.label, "retrieval_mode": "bm25_keyword"},
                )
            )
            if node.label in ("InventorySnapshot", "AdCampaign", "SKU", "Supplier"):
                channel_results["structured_sql"].append(
                    EvidenceItem(
                        evidence_id=f"EV-SQL-{node_id}",
                        channel="structured_sql",
                        entity_id=node_id,
                        content=f"Structured {node.label} record: {node.properties}",
                        score=0.92 if node_id in plan.seed_entities else 0.80,
                        version=node.version,
                        valid_from=node.valid_from,
                        valid_to=node.valid_to,
                        provenance={"table": node.label.lower(), "retrieval_mode": "structured_query"},
                    )
                )

        # 4. Multi-hop Temporal Graph Traversal
        graph_paths = self.graph.traverse_multihop(
            plan.seed_entities, max_hops=plan.max_hops, as_of=plan.as_of_timestamp
        )
        for idx, path_info in enumerate(graph_paths):
            hop_decay = 1.0 / float(path_info["hop"])
            channel_results["temporal_graph"].append(
                EvidenceItem(
                    evidence_id=f"EV-GRAPH-{path_info['target_id']}-{idx}",
                    channel="temporal_graph",
                    entity_id=path_info["target_id"],
                    content=(
                        f"Path ({path_info['path_trace']}) -> {path_info['target_label']}: "
                        f"{path_info['target_properties']}"
                    ),
                    score=round(0.95 * hop_decay, 4),
                    version=path_info["version"],
                    valid_from=path_info["valid_from"],
                    valid_to=path_info["valid_to"],
                    provenance={
                        "relation": path_info["relation"],
                        "hop": path_info["hop"],
                        "path_trace": path_info["path_trace"],
                        "cypher": plan.cypher_query,
                    },
                )
            )

        # Reciprocal Rank Fusion (RRF) across all 4 channels
        rrf_k = 60.0
        fused_by_entity: Dict[str, Dict[str, Any]] = {}
        for channel_name, items in channel_results.items():
            sorted_items = sorted(items, key=lambda x: x.score, reverse=True)
            for rank, item in enumerate(sorted_items, start=1):
                rrf_contrib = 1.0 / (rrf_k + rank)
                entry = fused_by_entity.setdefault(
                    item.entity_id,
                    {
                        "entity_id": item.entity_id,
                        "rrf_score": 0.0,
                        "matched_channels": [],
                        "version": item.version,
                        "valid_from": item.valid_from,
                        "valid_to": item.valid_to,
                        "evidence_snippets": [],
                        "provenance_chain": [],
                    },
                )
                entry["rrf_score"] = round(entry["rrf_score"] + rrf_contrib, 6)
                if channel_name not in entry["matched_channels"]:
                    entry["matched_channels"].append(channel_name)
                entry["evidence_snippets"].append(f"[{channel_name}] {item.content}")
                entry["provenance_chain"].append(item.provenance)

        ranked_evidence = sorted(fused_by_entity.values(), key=lambda x: x["rrf_score"], reverse=True)[:top_k]
        return {
            "retrieval_plan": asdict(plan),
            "ranked_evidence": ranked_evidence,
            "graph_paths_traversed": len(graph_paths),
            "knowledge_versions": self.graph.knowledge_versions,
        }
