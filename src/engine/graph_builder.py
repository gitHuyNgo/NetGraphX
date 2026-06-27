"""
engine/graph_builder.py
-----------------------
Builds the NetworkX topology graph from NetBox data and generates an
interactive HTML visualization using vis.js with a hierarchical layout.

Layout strategy
---------------
Devices are assigned to vertical layers based on their role field:
    Level 0 (top)    — Core / Backbone / Spine
    Level 1          — Distribution / Aggregation / Collapsed-Core
    Level 2          — Access / Edge / Leaf / TOR
    Level 3 (bottom) — Server / Endpoint / Host / AP / OOB

Within each layer, devices are grouped horizontally by their site/rack so
related equipment stays visually clustered (pod grouping).

The generated topology.html is self-contained and uses the vis.js Network
library bundled in lib/vis-9.1.2/ (CDN fallback included).

A companion topology_data.json is also written, consumed by the Streamlit
dashboard for dynamic filtering, device inspection, and metric panels.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import networkx as nx

# ---------------------------------------------------------------------------
# Layer assignment
# ---------------------------------------------------------------------------

_ROLE_LAYER_MAP: Dict[str, int] = {
    # Level 0 — Core
    "core": 0,
    "backbone": 0,
    "spine": 0,
    "core router": 0,
    "core-router": 0,
    "core switch": 0,
    "core-switch": 0,
    "wan router": 0,
    # Level 1 — Distribution
    "distribution": 1,
    "aggregation": 1,
    "collapsed-core": 1,
    "collapsed core": 1,
    "distribution switch": 1,
    "distribution-switch": 1,
    "aggregation switch": 1,
    "aggregation-switch": 1,
    # Level 2 — Access
    "access": 2,
    "edge": 2,
    "leaf": 2,
    "tor": 2,
    "top-of-rack": 2,
    "access switch": 2,
    "access-switch": 2,
    "edge router": 2,
    "edge-router": 2,
    # Level 3 — Endpoints
    "server": 3,
    "endpoint": 3,
    "host": 3,
    "ap": 3,
    "access point": 3,
    "access-point": 3,
    "oob": 3,
    "out-of-band": 3,
    "management": 3,
}

_LAYER_LABELS = {
    0: "Core / Spine",
    1: "Distribution",
    2: "Access / Edge",
    3: "Endpoints",
}

_NODE_COLORS = {
    0: "#c62828",   # Deep red — Core (visible on white)
    1: "#e65100",   # Deep orange — Distribution
    2: "#1565c0",   # Deep blue — Access
    3: "#2e7d32",   # Deep green — Endpoints
}

_NODE_SIZES = {0: 40, 1: 32, 2: 26, 3: 20}

_SPOF_COLOR = "#f57f17"    # Amber — visible on white (yellow replaced)
_SPOF_SIZE = 48
_MISMATCH_EDGE_COLOR = "#b71c1c"
_DEFAULT_EDGE_COLOR = "#78909c"


def _assign_layer(role: Optional[str]) -> int:
    """Map a NetBox role string to a hierarchy level (0-3). Unknown → level 2."""
    if not role:
        return 2
    return _ROLE_LAYER_MAP.get(role.lower().strip(), 2)


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# NetworkGraphBuilder
# ---------------------------------------------------------------------------

class NetworkGraphBuilder:
    def __init__(self):
        """Initializes an undirected NetworkX graph instance."""
        self.G = nx.Graph()

    def build_topology(
        self,
        devices: List[Dict[str, Any]],
        cables: List[Dict[str, Any]],
    ) -> None:
        """Populates NetworkX nodes (devices) and edges (cables) from NetBox data."""
        for device in devices:
            self.G.add_node(
                device["name"],
                role=device["role"],
                manufacturer=device.get("manufacturer"),
                primary_ip=device.get("primary_ip"),
                status=device.get("status"),
                site=device.get("site"),
                rack=device.get("rack"),
            )

        for cable in cables:
            self.G.add_edge(
                cable["source_device"],
                cable["target_device"],
                cable_id=cable["cable_id"],
                source_interface=cable["source_interface"],
                target_interface=cable["target_interface"],
                status=cable.get("status"),
            )

        print(
            f"[Graph] Constructed graph with {self.G.number_of_nodes()} nodes "
            f"and {self.G.number_of_edges()} edges."
        )

    # ------------------------------------------------------------------
    # Build vis.js node/edge lists (shared between file-write and inline render)
    # ------------------------------------------------------------------

    def build_vis_data(
        self,
        mismatch_list: Optional[List[Dict[str, Any]]] = None,
        bottlenecks_list: Optional[List[str]] = None,
    ):
        """Return (vis_nodes, vis_edges, meta) from current graph state."""
        mismatch_pairs: set = set()
        if mismatch_list:
            for item in mismatch_list:
                conn = item.get("connection", "")
                if " <-> " in conn:
                    parts = conn.split(" <-> ")
                    if len(parts) == 2:
                        mismatch_pairs.add((parts[0], parts[1]))
                        mismatch_pairs.add((parts[1], parts[0]))

        spof_set = set(bottlenecks_list or [])

        vis_nodes = []
        for node, data in self.G.nodes(data=True):
            role  = data.get("role") or ""
            layer = _assign_layer(role)

            is_spof = node in spof_set
            color   = _NODE_COLORS.get(layer, "#1e88e5")
            size    = _SPOF_SIZE  if is_spof else _NODE_SIZES.get(layer, 26)
            label   = f"{node}\n[SPOF]" if is_spof else node

            site = data.get("site") or ""
            rack = data.get("rack") or ""
            manufacturer = data.get("manufacturer") or ""

            title_html = (
                f"<b>{node}</b><br>"
                f"<span style='color:#8b949e'>Role:</span> {role or '—'}<br>"
                f"<span style='color:#8b949e'>IP:</span> {data.get('primary_ip') or '—'}<br>"
                f"<span style='color:#8b949e'>Status:</span> {data.get('status') or '—'}<br>"
                f"<span style='color:#8b949e'>Vendor:</span> {manufacturer or '—'}<br>"
                f"<span style='color:#8b949e'>Site:</span> {site or '—'}<br>"
                f"<span style='color:#8b949e'>Rack:</span> {rack or '—'}"
            )
            if is_spof:
                title_html += (
                    "<br><span style='color:#ff1744;font-weight:700;'>ĐIỂM THẤT BẠI ĐƠN LẺ (SPOF)</span>"
                )

            vis_nodes.append({
                "id":    node,
                "label": label,
                "title": title_html,
                "color": {
                    "background": color,
                    "border":     "#000000",
                    "highlight":  {"background": "#ffffff", "border": "#58a6ff"},
                    "hover":      {"background": "#eceff1", "border": "#546e7a"},
                },
                "size":  size,
                "level": layer,
                "group": layer,
                "font":  {"color": "#ffffff", "size": 11 if not is_spof else 13},
                # Extra fields for Streamlit UI consumption
                "_role": role,
                "_layer": layer,
                "_site": site,
                "_rack": rack,
                "_ip": data.get("primary_ip") or "",
                "_status": data.get("status") or "",
                "_vendor": manufacturer,
                "_is_spof": is_spof,
                "_is_predicted_rogue": False,
                "_anomaly_score": 0.0,
                "_human_reviewed": False,
                "_is_confirmed_rogue": None,
            })

        vis_edges = []
        mismatched_cables = 0
        for u, v, edata in self.G.edges(data=True):
            src_inf     = edata.get("source_interface", "?")
            tgt_inf     = edata.get("target_interface", "?")
            is_mismatch = (u, v) in mismatch_pairs

            color = _MISMATCH_EDGE_COLOR if is_mismatch else _DEFAULT_EDGE_COLOR
            width = 4 if is_mismatch else 1.5
            label_text = f"{src_inf} ↔ {tgt_inf}" + (" Lỗi VLAN" if is_mismatch else "")

            title_html = (
                f"Cable ID: {edata.get('cable_id', '—')}<br>"
                f"{u} [{src_inf}] ↔ {v} [{tgt_inf}]"
            )
            if is_mismatch:
                title_html += "<br><span style='color:#ff1744;font-weight:700;'>KHÔNG KHỚP VLAN</span>"
                mismatched_cables += 1

            vis_edges.append({
                "from":   u,
                "to":     v,
                "label":  label_text,
                "title":  title_html,
                "color":  {"color": color, "highlight": "#ffffff", "hover": "#b0bec5"},
                "width":  width,
                "dashes": False,
                # Extra fields
                "_src_if": src_inf,
                "_tgt_if": tgt_inf,
                "_cable_id": edata.get("cable_id"),
                "_mismatch": is_mismatch,
            })

        meta = {
            "spof_count":     len(spof_set),
            "mismatch_count": mismatched_cables,
        }

        return vis_nodes, vis_edges, meta

    # ------------------------------------------------------------------
    # Save topology metadata JSON (consumed by Streamlit for dynamic UI)
    # ------------------------------------------------------------------

    def save_topology_metadata(
        self,
        filename: str = "topology_data.json",
        mismatch_list: Optional[List[Dict[str, Any]]] = None,
        bottlenecks_list: Optional[List[str]] = None,
    ) -> None:
        """
        Write topology_data.json alongside topology.html.

        The Streamlit dashboard reads this file to power:
        - Dynamic graph filtering (by layer, site, SPOF, VLAN)
        - Device inspector panel
        - Metrics cards
        """
        vis_nodes, vis_edges, meta = self.build_vis_data(mismatch_list, bottlenecks_list)

        payload = {
            "nodes":     vis_nodes,
            "edges":     vis_edges,
            "meta":      meta,
            "spof":      list(set(bottlenecks_list or [])),
            "vlan_mismatches": [
                item.get("connection", "") for item in (mismatch_list or [])
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(filename, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        print(f"[Graph] Topology metadata saved: '{filename}'")

    # ------------------------------------------------------------------
    # HTML visualization (writes to file)
    # ------------------------------------------------------------------

