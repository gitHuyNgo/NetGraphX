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
# vis.js HTML builder (module-level — used by both file writer & dynamic render)
# ---------------------------------------------------------------------------

_VIS_CDN   = "https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"
_VIS_LOCAL = "lib/vis-9.1.2/vis-network.min.js"


def build_vis_html(
    vis_nodes: List[Dict],
    vis_edges: List[Dict],
    meta: Optional[Dict] = None,
    highlight_node: Optional[str] = None,
    node_scale: float = 1.0,
) -> str:
    """
    Build a self-contained vis.js hierarchical topology HTML string.

    Parameters
    ----------
    vis_nodes      : list of vis.js node dicts
    vis_edges      : list of vis.js edge dicts
    meta           : optional dict with spof_count / mismatch_count
    highlight_node : node id to focus + highlight on load
    node_scale     : scale factor applied to all node sizes (1.0 = default)
    """
    if meta is None:
        meta = {}

    # Apply node scale
    if node_scale != 1.0:
        scaled_nodes = []
        for n in vis_nodes:
            scaled = dict(n)
            scaled["size"] = round(n.get("size", 24) * node_scale, 1)
            scaled_nodes.append(scaled)
        vis_nodes = scaled_nodes

    layer_labels_json = json.dumps({str(k): v for k, v in _LAYER_LABELS.items()})
    layer_colors_json = json.dumps({str(k): v for k, v in _NODE_COLORS.items()})
    highlight_json    = json.dumps(highlight_node)

    return _HTML_TEMPLATE.format(
        vis_local=_VIS_LOCAL,
        vis_cdn=_VIS_CDN,
        nodes_json=json.dumps(vis_nodes, ensure_ascii=False),
        edges_json=json.dumps(vis_edges, ensure_ascii=False),
        meta_json=json.dumps(meta),
        layer_labels_json=layer_labels_json,
        layer_colors_json=layer_colors_json,
        highlight_node_json=highlight_json,
    )


_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>NetGraphX — Network Topology</title>
  <script src="{vis_cdn}"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: 'Inter', 'Segoe UI', sans-serif;
      background: #0d1117;
      color: #c9d1d9;
      height: 100vh;
      display: flex;
      flex-direction: column;
      overflow: hidden;
    }}
    #topbar {{
      display: flex;
      align-items: center;
      gap: 16px;
      padding: 7px 14px;
      background: #161b22;
      border-bottom: 1px solid #30363d;
      flex-wrap: wrap;
      flex-shrink: 0;
      box-shadow: 0 1px 4px rgba(0,0,0,0.2);
    }}
    .legend-row {{
      display: flex;
      align-items: center;
      gap: 14px;
      flex-wrap: wrap;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      gap: 5px;
      font-size: 11px;
      color: #8b949e;
      font-weight: 500;
    }}
    .legend-dot {{
      width: 10px; height: 10px;
      border-radius: 50%;
      flex-shrink: 0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.5);
    }}
    .legend-line {{
      width: 20px; height: 4px;
      border-radius: 2px;
      flex-shrink: 0;
    }}
    .ctrl-group {{
      display: flex;
      gap: 6px;
      margin-left: auto;
    }}
    .btn {{
      padding: 4px 12px;
      border-radius: 6px;
      border: 1px solid #30363d;
      background: #21262d;
      color: #c9d1d9;
      font-size: 11px;
      font-weight: 500;
      cursor: pointer;
      transition: all 0.15s;
    }}
    .btn:hover {{ background: #30363d; border-color: #8b949e; }}
    #network-wrap {{
      flex: 1;
      position: relative;
      overflow: hidden;
      background: #0d1117;
    }}
    #mynetwork {{ width: 100%; height: 100%; }}
    #layer-overlay {{
      position: absolute;
      left: 10px;
      top: 8px;
      display: flex;
      flex-direction: column;
      gap: 3px;
      pointer-events: none;
    }}
    .layer-badge {{
      font-size: 10px;
      font-weight: 700;
      color: #8b949e;
      background: rgba(22,27,34,0.88);
      padding: 2px 7px;
      border-radius: 4px;
      border-left: 3px solid;
      letter-spacing: 0.3px;
      box-shadow: 0 1px 4px rgba(0,0,0,0.3);
    }}
    #floatip {{
      position: absolute;
      background: #161b22f5;
      border: 1px solid #30363d;
      border-radius: 8px;
      padding: 9px 13px;
      font-size: 11.5px;
      color: #c9d1d9;
      pointer-events: none;
      display: none;
      max-width: 270px;
      line-height: 1.65;
      z-index: 100;
      box-shadow: 0 4px 18px rgba(0,0,0,0.4);
    }}
    #statusbar {{
      padding: 4px 14px;
      background: #161b22;
      border-top: 1px solid #30363d;
      font-size: 10.5px;
      color: #8b949e;
      display: flex;
      gap: 18px;
      flex-shrink: 0;
    }}
    #statusbar b {{ color: #c9d1d9; font-weight: 600; }}
    #search-inner {{
      padding: 4px 10px;
      border-radius: 6px;
      border: 1px solid #30363d;
      background: #0d1117;
      color: #c9d1d9;
      font-size: 11px;
      width: 165px;
    }}
    #search-inner:focus {{ outline: none; border-color: #58a6ff; background: #0d1117; }}
  </style>
</head>
<body>

<div id="topbar">
  <div class="legend-row">
    <div class="legend-item"><div class="legend-dot" style="background:#c62828"></div>Core</div>
    <div class="legend-item"><div class="legend-dot" style="background:#e65100"></div>Distribution</div>
    <div class="legend-item"><div class="legend-dot" style="background:#1565c0"></div>Access</div>
    <div class="legend-item"><div class="legend-dot" style="background:#2e7d32"></div>Endpoints</div>
    <div class="legend-item"><div class="legend-dot" style="background:#f57f17"></div>SPOF</div>
    <div class="legend-item"><div class="legend-line" style="background:#b71c1c"></div>VLAN Mismatch</div>
  </div>
  <div class="ctrl-group">
    <input id="search-inner" type="text" placeholder="Find device..." />
    <button class="btn" onclick="fitAll()">Fit All</button>
    <button class="btn" onclick="togglePhysics()">Physics</button>
    <button class="btn" onclick="resetHier()">Reset</button>
  </div>
</div>

<div id="network-wrap">
  <div id="mynetwork"></div>
  <div id="layer-overlay"></div>
  <div id="floatip"></div>
</div>

<div id="statusbar">
  Nodes: <b id="nc">0</b>
  &nbsp;|&nbsp; Edges: <b id="ec">0</b>
  &nbsp;|&nbsp; SPOFs: <b id="sc">0</b>
  &nbsp;|&nbsp; VLAN Mismatches: <b id="mc">0</b>
</div>

<script>
const NODES_DATA  = {nodes_json};
const EDGES_DATA  = {edges_json};
const GRAPH_META  = {meta_json};
const LAYER_NAMES = {layer_labels_json};
const LAYER_CLR   = {layer_colors_json};
const HIGHLIGHT   = {highlight_node_json};

function initGraph() {{
  if (typeof vis === 'undefined') {{
    setTimeout(initGraph, 50);
    return;
  }}
  const container = document.getElementById('mynetwork');
  const nodes = new vis.DataSet(NODES_DATA);
  const edges = new vis.DataSet(EDGES_DATA);

  const options = {{
    layout: {{
      hierarchical: {{
        enabled: true,
        direction: 'UD',
        sortMethod: 'directed',
        levelSeparation: 150,
        nodeSpacing: 120,
        treeSpacing: 160,
        blockShifting: true,
        edgeMinimization: true,
        parentCentralization: true,
      }}
    }},
    physics: {{
      enabled: false,
      hierarchicalRepulsion: {{
        centralGravity: 0.0,
        springLength: 130,
        springConstant: 0.01,
        nodeDistance: 150,
        damping: 0.09,
      }},
      solver: 'hierarchicalRepulsion',
    }},
    nodes: {{
      shape: 'dot',
      borderWidth: 2,
      borderWidthSelected: 4,
      font: {{
        color: '#c9d1d9',
        size: 11,
        face: 'Inter, Segoe UI, sans-serif',
        strokeWidth: 3,
        strokeColor: 'rgba(0,0,0,0.8)',
      }},
      shadow: {{ enabled: true, color: 'rgba(0,0,0,0.6)', size: 8, x: 1, y: 2 }},
    }},
    edges: {{
      smooth: {{ type: 'cubicBezier', forceDirection: 'vertical', roundness: 0.35 }},
      font: {{ color: '#8b949e', size: 9.5, align: 'middle', background: '#0d1117',
               strokeWidth: 0 }},
      arrows: {{ to: false }},
      selectionWidth: 3,
    }},
    interaction: {{
      hover: true,
      tooltipDelay: 0,
      navigationButtons: false,
      keyboard: {{ enabled: true, bindToWindow: false }},
      zoomView: true,
      multiselect: false,
    }},
  }};

  const network = new vis.Network(container, {{ nodes, edges }}, options);

  // Status bar
  document.getElementById('nc').textContent = NODES_DATA.length;
  document.getElementById('ec').textContent = EDGES_DATA.length;
  document.getElementById('sc').textContent = GRAPH_META.spof_count || 0;
  document.getElementById('mc').textContent = GRAPH_META.mismatch_count || 0;

  // Layer overlay
  const overlay = document.getElementById('layer-overlay');
  Object.entries(LAYER_NAMES).forEach(([lvl, name]) => {{
    const d = document.createElement('div');
    d.className = 'layer-badge';
    d.style.borderColor = LAYER_CLR[lvl] || '#484f58';
    d.textContent = 'L' + lvl + ' ' + name;
    overlay.appendChild(d);
  }});

  // Floating tooltip
  const tip = document.getElementById('floatip');
  network.on('hoverNode', p => {{
    const n = nodes.get(p.node);
    if (n) {{ tip.innerHTML = n.title || n.label; tip.style.display = 'block'; }}
  }});
  network.on('blurNode', () => {{ tip.style.display = 'none'; }});
  network.on('hoverEdge', p => {{
    const e = edges.get(p.edge);
    if (e) {{ tip.innerHTML = e.title || ''; tip.style.display = 'block'; }}
  }});
  network.on('blurEdge', () => tip.style.display = 'none');
  container.addEventListener('mousemove', e => {{
    tip.style.left = (e.offsetX + 16) + 'px';
    tip.style.top  = (e.offsetY + 16) + 'px';
  }});

  // Handle click to send to Streamlit
  network.on('click', function(params) {{
    if (window.parent.sendNodeClick) {{
      if (params.nodes.length > 0) {{
        window.parent.sendNodeClick(params.nodes[0]);
      }} else {{
        window.parent.sendNodeClick("");
      }}
    }}
  }});

  // highlight handled by setTimeout

  // In-graph search
  document.getElementById('search-inner').addEventListener('input', function() {{
    const q = this.value.toLowerCase().trim();
    if (!q) {{ network.unselectAll(); return; }}
    const hits = NODES_DATA.filter(n => (n.label||'').toLowerCase().includes(q)).map(n => n.id);
    if (hits.length) {{
      network.selectNodes(hits);
      network.focus(hits[0], {{ scale: 1.4, animation: {{ duration: 500 }} }});
    }}
  }});

  let physOn = false;
  window.fitAll        = () => network.fit({{ animation: {{ duration: 600 }} }});
  window.togglePhysics = () => {{ physOn = !physOn; network.setOptions({{ physics: {{ enabled: physOn }} }}); }};
  window.resetHier     = () => {{ network.setOptions({{ layout: {{ hierarchical: {{ enabled: true }} }} }}); network.fit({{ animation: true }}); }};

  window.highlightNode = function(nodeId) {{
    if (!nodeId) {{
        network.unselectAll();
        return;
    }}
    network.selectNodes([nodeId]);
    network.focus(nodeId, {{ scale: 1.5, animation: {{ duration: 700, easingFunction: 'easeInOutQuad' }} }});
  }};

  // Initial highlight if provided
  if (HIGHLIGHT) {{
      setTimeout(() => window.highlightNode(HIGHLIGHT), 500);
  }}

  network.once('stabilized', () => network.fit({{ animation: {{ duration: 800 }} }}));
}}
initGraph();
</script>
</body>
</html>
"""


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

    def _build_vis_data(
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
        vis_nodes, vis_edges, meta = self._build_vis_data(mismatch_list, bottlenecks_list)

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

    def generate_html_visualization(
        self,
        filename: str = "topology.html",
        mismatch_list: Optional[List[Dict[str, Any]]] = None,
        bottlenecks_list: Optional[List[str]] = None,
    ) -> None:
        """
        Render an interactive hierarchical topology HTML page using vis.js,
        and also save the companion topology_data.json for the dashboard.
        """
        vis_nodes, vis_edges, meta = self._build_vis_data(mismatch_list, bottlenecks_list)

        html = build_vis_html(vis_nodes, vis_edges, meta)

        with open(filename, "w", encoding="utf-8") as f:
            f.write(html)

        print(
            f"[Visualization] Hierarchical topology map generated: '{filename}' "
            f"({len(vis_nodes)} nodes, {len(vis_edges)} edges)"
        )

        # Also save companion metadata
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
        metadata_file = filename.replace(".html", "_data.json")
        with open(metadata_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        print(f"[Graph] Companion metadata saved: '{metadata_file}'")