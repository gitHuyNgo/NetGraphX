"""
Task 4: Hybrid Retrieval Engine
================================
Dispatches parsed intents to the correct retrieval strategy:

  scan_errors  → Parameterised Cypher audit queries (prepared templates)
  node_info    → K-hop neighborhood traversal (2-hop: device + interfaces + neighbours)
  general      → ANN vector similarity search on the Neo4j vector index

All strategies return a unified RetrievalResult.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from neo4j import Driver

from src.rag.query_parser import ParsedIntent, ParsedQuery

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class RetrievalResult:
    intent: ParsedIntent
    strategy: str                            # "cypher_audit" | "khop" | "vector"
    context_nodes: List[Dict[str, Any]] = field(default_factory=list)
    context_text: str = ""                   # Human-readable context string for LLM


# ---------------------------------------------------------------------------
# Cypher templates for scan_errors (Task 4-A)
# All queries use parameterised inputs — never string-interpolated user data.
# ---------------------------------------------------------------------------

_CYPHER_SPOF = """
MATCH (d:Device {is_SPOF: true})
RETURN d.name AS name, d.description AS description,
       d.role AS role, d.site AS site, d.vendor AS vendor
ORDER BY d.name
"""

_CYPHER_LOOP = """
MATCH (d:Device {is_loop: true})
RETURN d.name AS name, d.description AS description,
       d.role AS role, d.site AS site
ORDER BY d.name
"""

_CYPHER_VLAN_MISMATCH = """
MATCH (src:Interface)-[link:CONNECTED_TO {has_vlan_mismatch: true}]-(tgt:Interface)
MATCH (src)-[:BELONGS_TO]->(sd:Device)
MATCH (tgt)-[:BELONGS_TO]->(td:Device)
WHERE elementId(src) < elementId(tgt)
RETURN sd.name AS source_device, src.name AS source_interface,
       td.name AS target_device, tgt.name AS target_interface,
       link.vlan_mismatch_detail AS mismatch_detail
ORDER BY sd.name
"""

_CYPHER_TOPOLOGY_VIOLATION = """
MATCH (d:Device {has_topology_violation: true})
RETURN d.name AS name, d.description AS description,
       d.topology_violation_reason AS reason
ORDER BY d.name
"""

_CYPHER_ALL_ERRORS = """
MATCH (d:Device)
WHERE d.is_SPOF = true OR d.is_loop = true OR d.has_topology_violation = true
RETURN d.name AS name,
       d.description AS description,
       d.is_SPOF AS is_spof,
       d.is_loop AS is_loop,
       d.has_topology_violation AS has_violation,
       d.topology_violation_reason AS violation_reason
ORDER BY d.name
"""

_CYPHER_TEMPLATES: Dict[str, str] = {
    "SPOF": _CYPHER_SPOF,
    "loop": _CYPHER_LOOP,
    "vlan_mismatch": _CYPHER_VLAN_MISMATCH,
    "topology_violation": _CYPHER_TOPOLOGY_VIOLATION,
    "all": _CYPHER_ALL_ERRORS,
}

# Cypher for k-hop neighborhood (Task 4-B)
# $name is safely parameterised
_CYPHER_KHOP = """
MATCH (d:Device {name: $name})
OPTIONAL MATCH (d)<-[:BELONGS_TO]-(i:Interface)
OPTIONAL MATCH (i)-[link:CONNECTED_TO]-(peer_if:Interface)-[:BELONGS_TO]->(neighbor:Device)
RETURN
    d.name          AS device_name,
    d.description   AS device_description,
    d.role          AS role,
    d.vendor        AS vendor,
    d.model         AS model,
    d.site          AS site,
    d.rack          AS rack,
    d.primary_ip    AS primary_ip,
    d.status        AS status,
    d.is_SPOF       AS is_spof,
    d.is_loop       AS is_loop,
    d.has_topology_violation AS has_violation,
    d.topology_violation_reason AS violation_reason,
    collect(DISTINCT {
        interface: i.name,
        mode: i.mode,
        is_loop: i.is_loop,
        has_vlan_mismatch: i.has_vlan_mismatch,
        description: i.description
    }) AS interfaces,
    collect(DISTINCT {
        neighbor: neighbor.name,
        neighbor_role: neighbor.role,
        via_interface: i.name,
        via_peer_interface: peer_if.name,
        link_has_vlan_mismatch: link.has_vlan_mismatch,
        link_is_loop: link.is_loop
    }) AS connections
LIMIT 1
"""

# Cypher for vector ANN search (Task 4-C)
_CYPHER_VECTOR = """
CALL db.index.vector.queryNodes($index_name, $top_k, $embedding)
YIELD node, score
RETURN node.name AS name, node.description AS description, score
ORDER BY score DESC
"""


# ---------------------------------------------------------------------------
# Retriever class
# ---------------------------------------------------------------------------


class HybridRetriever:
    """
    Routes each ParsedIntent to the appropriate retrieval strategy and
    returns a list of RetrievalResult objects ready for the synthesizer.
    """

    def __init__(self, driver: Driver, embedder=None) -> None:
        """
        Args:
            driver: Active Neo4j driver.
            embedder: Optional NodeEmbedder instance (needed for vector search).
                      If None, vector search will be skipped with a warning.
        """
        self._driver = driver
        self._embedder = embedder

    def retrieve(self, parsed_query: ParsedQuery) -> List[RetrievalResult]:
        """Dispatch all intents and collect results."""
        results = []
        for intent in parsed_query.intents:
            if intent.type == "scan_errors":
                results.append(self._retrieve_audit(intent))
            elif intent.type == "node_info":
                results.append(self._retrieve_khop(intent))
            else:
                results.append(self._retrieve_vector(intent))
        return results

    # ------------------------------------------------------------------
    # Strategy A: Cypher audit scan
    # ------------------------------------------------------------------

    def _retrieve_audit(self, intent: ParsedIntent) -> RetrievalResult:
        target = (intent.target or "all").strip()
        if target not in _CYPHER_TEMPLATES:
            logger.info(f"[Retriever] Unknown scan_errors target '{target}' — falling back to 'all'.")
            target = "all"

        cypher = _CYPHER_TEMPLATES[target]
        with self._driver.session() as session:
            rows = session.run(cypher).data()

        context_text = self._format_audit_context(target, rows)
        return RetrievalResult(
            intent=intent,
            strategy="cypher_audit",
            context_nodes=rows,
            context_text=context_text,
        )

    @staticmethod
    def _format_audit_context(target: str, rows: List[Dict[str, Any]]) -> str:
        if not rows:
            label_map = {
                "SPOF": "điểm thất bại đơn lẻ (SPOF)",
                "loop": "vòng lặp mạng",
                "vlan_mismatch": "lỗi VLAN mismatch",
                "topology_violation": "vi phạm cấu trúc topology",
                "all": "lỗi bất kỳ",
            }
            return f"✅ Không tìm thấy thiết bị nào có {label_map.get(target, target)}."

        parts = [f"📋 Kết quả quét lỗi [{target}] — tìm thấy {len(rows)} kết quả:\n"]
        for row in rows:
            # Format each result row into readable text
            parts.append("---")
            desc = row.get("description") or row.get("mismatch_detail") or ""
            if desc:
                parts.append(desc)
            # Append any extra fields not captured in description
            extras = {k: v for k, v in row.items() if k not in ("description", "name") and v}
            if extras:
                parts.append(json.dumps(extras, ensure_ascii=False))

        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Strategy B: K-hop neighbourhood traversal
    # ------------------------------------------------------------------

    def _retrieve_khop(self, intent: ParsedIntent) -> RetrievalResult:
        device_name = (intent.target or "").strip()
        if not device_name:
            return RetrievalResult(
                intent=intent,
                strategy="khop",
                context_text="❌ Không có tên thiết bị nào được cung cấp.",
            )

        with self._driver.session() as session:
            rows = session.run(_CYPHER_KHOP, name=device_name).data()

        if not rows:
            return RetrievalResult(
                intent=intent,
                strategy="khop",
                context_text=f"❌ Không tìm thấy thiết bị '{device_name}' trong knowledge graph.",
            )

        row = rows[0]
        context_text = self._format_khop_context(row)
        return RetrievalResult(
            intent=intent,
            strategy="khop",
            context_nodes=rows,
            context_text=context_text,
        )

    @staticmethod
    def _format_khop_context(row: Dict[str, Any]) -> str:
        lines = [
            f"🔍 Thông tin thiết bị: {row.get('device_name')}",
            "",
            row.get("device_description") or "(Không có mô tả)",
            "",
        ]

        interfaces = [i for i in (row.get("interfaces") or []) if i.get("interface")]
        if interfaces:
            lines.append(f"📡 Danh sách cổng ({len(interfaces)} cổng):")
            for iface in interfaces:
                status_parts = []
                if iface.get("is_loop"):
                    status_parts.append("🔄 loop")
                if iface.get("has_vlan_mismatch"):
                    status_parts.append("⚠️ VLAN mismatch")
                status_str = " | ".join(status_parts) if status_parts else "✅ bình thường"
                lines.append(
                    f"  • {iface.get('interface')} "
                    f"[mode={iface.get('mode') or 'N/A'}] — {status_str}"
                )

        connections = [
            c for c in (row.get("connections") or []) if c.get("neighbor")
        ]
        if connections:
            lines.append(f"\n🔗 Kết nối láng giềng ({len(connections)} kết nối):")
            for conn in connections:
                link_status = []
                if conn.get("link_is_loop"):
                    link_status.append("🔄 loop link")
                if conn.get("link_has_vlan_mismatch"):
                    link_status.append("⚠️ VLAN mismatch")
                link_str = " | ".join(link_status) if link_status else "✅ bình thường"
                lines.append(
                    f"  • {conn.get('neighbor')} ({conn.get('neighbor_role') or 'N/A'}) "
                    f"qua {conn.get('via_interface')} ↔ {conn.get('via_peer_interface')} — {link_str}"
                )

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Strategy C: Vector ANN search
    # ------------------------------------------------------------------

    def _retrieve_vector(
        self, intent: ParsedIntent, top_k: int = 5
    ) -> RetrievalResult:
        if self._embedder is None:
            return RetrievalResult(
                intent=intent,
                strategy="vector",
                context_text="[Vector search không khả dụng — embedder chưa được khởi tạo.]",
            )

        query_vector = self._embedder.encode_text(intent.clean_query)

        with self._driver.session() as session:
            rows = session.run(
                _CYPHER_VECTOR,
                index_name="device_embedding_index",
                top_k=top_k,
                embedding=query_vector,
            ).data()

        if not rows:
            return RetrievalResult(
                intent=intent,
                strategy="vector",
                context_text="Không tìm thấy thông tin liên quan trong knowledge graph.",
            )

        lines = [f"🔎 Kết quả tìm kiếm ngữ nghĩa (top {top_k}):\n"]
        context_nodes = []
        for row in rows:
            score = row.get("score", 0)
            name = row.get("name", "?")
            desc = row.get("description", "")
            lines.append(f"[{score:.3f}] {name}: {desc}")
            context_nodes.append(row)

        return RetrievalResult(
            intent=intent,
            strategy="vector",
            context_nodes=context_nodes,
            context_text="\n".join(lines),
        )
