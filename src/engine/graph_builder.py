import networkx as nx
from pyvis.network import Network
from typing import List, Dict, Any

class NetworkGraphBuilder:
    def __init__(self):
        """
        Initializes an undirected NetworkX graph instance to handle network topology mechanics.
        """
        self.G = nx.Graph()
        
    def build_topology(self, devices: List[Dict[str, Any]], cables: List[Dict[str, Any]]):
        """
        Populates NetworkX Nodes (Devices) and Edges (Cables) extracted from the NetBox Layer.
        """
        # 1. Map devices to graph nodes along with metadata attributes
        for device in devices:
            self.G.add_node(
                device["name"],
                role=device["role"],
                manufacturer=device["manufacturer"],
                primary_ip=device["primary_ip"],
                status=device["status"]
            )
            
        # 2. Map physical cable infrastructure connections to graph edges
        for cable in cables:
            self.G.add_edge(
                cable["source_device"],
                cable["target_device"],
                cable_id=cable["cable_id"],
                source_interface=cable["source_interface"],
                target_interface=cable["target_interface"],
                status=cable["status"]
            )
        print(f"[Graph] Successfully constructed graph structure with {self.G.number_of_nodes()} nodes and {self.G.number_of_edges()} edges.")

    def generate_html_visualization(self, filename: str = "topology.html", mismatch_list: List[Dict[str, Any]] = None, bottlenecks_list: List[str] = None):
        """
        Translates the NetworkX topology maps into an interactive Pyvis UI environment.
        Consumes analysis data directly from rule_audit.py to handle dynamic coloring.
        """
        net = Network(notebook=False, height="750px", width="100%", bgcolor="#222222", font_color="white")
        
        # Parse mismatch pairs safely from the rule engine string formatting to prevent KeyErrors
        mismatch_pairs = set()
        if mismatch_list:
            for item in mismatch_list:
                connection_str = item.get("connection", "")
                if " <-> " in connection_str:
                    nodes = connection_str.split(" <-> ")
                    if len(nodes) == 2:
                        node_a, node_b = nodes[0], nodes[1]
                        mismatch_pairs.add((node_a, node_b))
                        mismatch_pairs.add((node_b, node_a))

        # 1. Synchronize Nodes from NetworkX to Pyvis with descriptive attributes
        for node, node_data in self.G.nodes(data=True):
            if "Core" in node_data.get("role", ""):
                node_color = "#f44336"  # Crimson Red for Core Devices
                node_size = 35
            else:
                node_color = "#2196f3"  # Blue for Access Layer Devices
                node_size = 25
                
            hover_title = (
                f"<b>Device:</b> {node}<br>"
                f"Role: {node_data.get('role')}<br>"
                f"IP: {node_data.get('primary_ip')}<br>"
                f"Status: {node_data.get('status')}"
            )
            
            # Apply design overrides if node matches single point of failure calculations
            if bottlenecks_list and node in bottlenecks_list:
                node_color = "#ffea00"  # Bright Yellow Coded Casing
                node_size = 45
                hover_title += "<br><span style='color:red;'><b>CRITICAL WARNING: SINGLE POINT OF FAILURE</b></span>"
                label_text = f"{node} [BOTTLENECK]"
            else:
                label_text = node
            
            net.add_node(
                n_id=node,
                label=label_text,
                title=hover_title,
                color=node_color,
                size=node_size
            )

        # 2. Synchronize Edges from NetworkX to Pyvis and apply link overrides
        for u, v, edge_data in self.G.edges(data=True):
            src_inf = edge_data.get("source_interface", "Unknown")
            tgt_inf = edge_data.get("target_interface", "Unknown")
            
            link_label = f"{src_inf} <-> {tgt_inf}"
            hover_title = f"Cable ID: {edge_data.get('cable_id')}<br>Connection: {u} [{src_inf}] <-> {v} [{tgt_inf}]"
            
            edge_color = "#97c2fc"  # Uniform structural interface link color
            edge_width = 2
            
            # Recolor cable to high-visibility red if the link hosts a configuration error
            if (u, v) in mismatch_pairs:
                edge_color = "#ff1744"  # Warning Red Link
                edge_width = 5
                link_label += " [VLAN MISMATCH]"

            net.add_edge(
                source=u,
                to=v,
                label=link_label,
                title=hover_title,
                color=edge_color,
                width=edge_width
            )

        net.toggle_physics(True)
        net.write_html(filename)
        print(f"[Visualization] Interactive network map layer generated successfully: '{filename}'")