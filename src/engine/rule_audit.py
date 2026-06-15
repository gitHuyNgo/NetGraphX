import networkx as nx
from typing import Any, Dict, List

from src.models.finding import AffectedLink, Finding


def detect_network_loops(G: nx.Graph) -> List[Finding]:
    try:
        loops = nx.find_cycle(G, orientation="ignore")
        affected_nodes = list({edge[0] for edge in loops} | {edge[1] for edge in loops})
        affected_links = [
            AffectedLink(
                source=edge[0],
                target=edge[1],
                cable_id=G.edges[edge[0], edge[1]].get("cable_id"),
                source_interface=G.edges[edge[0], edge[1]].get("source_interface"),
                target_interface=G.edges[edge[0], edge[1]].get("target_interface"),
            )
            for edge in loops
        ]
        return [
            Finding(
                type="LOOP",
                severity="HIGH",
                affected_nodes=affected_nodes,
                affected_links=affected_links,
                description=f"Dangerous loops detected passing through devices: {loops}",
            )
        ]
    except nx.NetworkXNoCycle:
        return []


def detect_single_points_of_failure(G: nx.Graph) -> List[Finding]:
    try:
        spof_nodes = list(nx.articulation_points(G))
        if not spof_nodes:
            return []

        affected_links = []
        for node in spof_nodes:
            for neighbor in G.neighbors(node):
                edge_data = G.edges[node, neighbor]
                affected_links.append(
                    AffectedLink(
                        source=node,
                        target=neighbor,
                        cable_id=edge_data.get("cable_id"),
                        source_interface=edge_data.get("source_interface"),
                        target_interface=edge_data.get("target_interface"),
                    )
                )

        return [
            Finding(
                type="SPOF",
                severity="CRITICAL",
                affected_nodes=spof_nodes,
                affected_links=affected_links,
                description=(
                    f"High risk warning! The following devices are SPOF devices: {spof_nodes}. "
                    "A backup connection is needed."
                ),
            )
        ]
    except Exception as exc:
        return [
            Finding(
                type="SPOF",
                severity="INFO",
                affected_nodes=[],
                affected_links=[],
                description=f"Technical error in calculating SPOF: {exc}",
            )
        ]


def detect_vlan_mismatch(G: nx.Graph, interfaces_list: List[Dict[str, Any]]) -> List[Finding]:
    vlan_lookup = {
        (inf["device_name"], inf["interface_name"]): inf["vlan_id"]
        for inf in interfaces_list
    }

    findings: List[Finding] = []

    for u, v, data in G.edges(data=True):
        src_inf = data.get("source_interface")
        tgt_inf = data.get("target_interface")

        vlan_a = vlan_lookup.get((u, src_inf))
        vlan_b = vlan_lookup.get((v, tgt_inf))

        if vlan_a is not None and vlan_b is not None and vlan_a != vlan_b:
            findings.append(
                Finding(
                    type="VLAN_MISMATCH",
                    severity="CRITICAL",
                    affected_nodes=[u, v],
                    affected_links=[
                        AffectedLink(
                            source=u,
                            target=v,
                            cable_id=data.get("cable_id"),
                            source_interface=src_inf,
                            target_interface=tgt_inf,
                        )
                    ],
                    description=(
                        f"Port {u} [{src_inf}] belongs to VLAN {vlan_a} but connects to "
                        f"port {v} [{tgt_inf}] which belongs to VLAN {vlan_b}."
                    ),
                )
            )

    return findings


def run_all_analytics(G: nx.Graph, interfaces_list: List[Dict[str, Any]]) -> List[Finding]:
    findings: List[Finding] = []
    findings.extend(detect_network_loops(G))
    findings.extend(detect_single_points_of_failure(G))
    findings.extend(detect_vlan_mismatch(G, interfaces_list))
    return findings


def findings_error_nodes(findings: List[Finding]) -> List[str]:
    nodes: List[str] = []
    for finding in findings:
        nodes.extend(finding.affected_nodes)
    return list(set(nodes))


def findings_vlan_mismatch_details(findings: List[Finding]) -> List[Dict[str, str]]:
    details: List[Dict[str, str]] = []
    for finding in findings:
        if finding.type != "VLAN_MISMATCH":
            continue
        for link in finding.affected_links:
            details.append(
                {
                    "connection": f"{link.source} <-> {link.target}",
                    "detail": finding.description,
                }
            )
    return details
