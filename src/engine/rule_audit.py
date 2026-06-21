import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TypedDict

import networkx as nx

DEFAULT_AUDIT_CONFIG_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "network_audit_rules.json"
)


class NodeComplianceData(TypedDict):
    compliance_status: str
    audit_knowledge: str


class AuditResult(TypedDict):
    is_passed: bool
    global_compliance_summary: str
    node_compliance_data: Dict[str, NodeComplianceData]


def load_audit_config(config_path: Optional[str] = None) -> Dict[str, Any]:
    path = Path(config_path) if config_path else DEFAULT_AUDIT_CONFIG_PATH
    with path.open(encoding="utf-8") as config_file:
        return json.load(config_file)


def _compliant_node(
    device_name: str,
    rule_config: Dict[str, Any],
    template_key: str = "pass",
    **format_kwargs: Any,
) -> NodeComplianceData:
    template = rule_config["node_knowledge_template"][template_key]
    return {
        "compliance_status": rule_config["compliance_status"]["pass"],
        "audit_knowledge": template.format(device_name=device_name, **format_kwargs),
    }


def _non_compliant_node(
    device_name: str,
    rule_config: Dict[str, Any],
    template_key: str = "fail",
    **format_kwargs: Any,
) -> NodeComplianceData:
    template = rule_config["node_knowledge_template"][template_key]
    return {
        "compliance_status": rule_config["compliance_status"]["fail"],
        "audit_knowledge": template.format(device_name=device_name, **format_kwargs),
    }


def _initialize_node_compliance(
    G: nx.Graph,
    rule_config: Dict[str, Any],
    template_key: str = "pass",
    **format_kwargs: Any,
) -> Dict[str, NodeComplianceData]:
    return {
        node: _compliant_node(node, rule_config, template_key, **format_kwargs)
        for node in G.nodes()
    }


def _format_cycle_path(cycle_edges: List[Tuple[Any, ...]]) -> str:
    if not cycle_edges:
        return "unknown"

    ordered_nodes = [cycle_edges[0][0]]
    for edge in cycle_edges:
        ordered_nodes.append(edge[1])

    return " -> ".join(str(node) for node in ordered_nodes)


def collect_loop_edges(
    G: nx.Graph,
    config_path: Optional[str] = None,
) -> Dict[str, Any]:
    audit_config = load_audit_config(config_path)
    rule_config = audit_config["network_loop"]

    try:
        orientation = rule_config["metrics"]["cycle_orientation"]
        cycle_edges = nx.find_cycle(G, orientation=orientation)
        loop_id = _format_cycle_path(cycle_edges)
        edges: List[Dict[str, Any]] = []

        for edge in cycle_edges:
            source_device = edge[0]
            target_device = edge[1]
            edge_data = G.edges[source_device, target_device]
            edges.append(
                {
                    "source_device": source_device,
                    "target_device": target_device,
                    "source_interface": edge_data.get("source_interface"),
                    "target_interface": edge_data.get("target_interface"),
                    "cable_id": edge_data.get("cable_id"),
                }
            )

        loop_devices = sorted(
            {edge[0] for edge in cycle_edges} | {edge[1] for edge in cycle_edges}
        )
        return {
            "loop_id": loop_id,
            "edges": edges,
            "devices": loop_devices,
        }
    except nx.NetworkXNoCycle:
        return {
            "loop_id": None,
            "edges": [],
            "devices": [],
        }


def loop_participating_interfaces(
    loop_edges: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    interfaces: List[Dict[str, str]] = []
    for edge in loop_edges:
        if edge.get("source_interface"):
            interfaces.append(
                {
                    "device_name": edge["source_device"],
                    "interface_name": edge["source_interface"],
                }
            )
        if edge.get("target_interface"):
            interfaces.append(
                {
                    "device_name": edge["target_device"],
                    "interface_name": edge["target_interface"],
                }
            )
    return interfaces


def devices_with_compliance_status(
    result: AuditResult,
    status: str,
) -> List[str]:
    return [
        device_name
        for device_name, node_data in result["node_compliance_data"].items()
        if node_data["compliance_status"] == status
    ]


def device_topology_violations(star_result: AuditResult) -> Dict[str, str]:
    star_status = load_audit_config()["star_topology"]["compliance_status"]["fail"]
    violations: Dict[str, str] = {}
    for device_name, node_data in star_result["node_compliance_data"].items():
        if node_data["compliance_status"] == star_status:
            violations[device_name] = node_data["audit_knowledge"]
    return violations


def collect_vlan_mismatch_edges(
    G: nx.Graph,
    interfaces_list: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    vlan_lookup = {
        (interface["device_name"], interface["interface_name"]): interface["vlan_id"]
        for interface in interfaces_list
    }
    mismatches: List[Dict[str, Any]] = []

    for source, target, edge_data in G.edges(data=True):
        source_interface = edge_data.get("source_interface")
        target_interface = edge_data.get("target_interface")
        source_vlan = vlan_lookup.get((source, source_interface))
        target_vlan = vlan_lookup.get((target, target_interface))

        if (
            source_vlan is not None
            and target_vlan is not None
            and source_vlan != target_vlan
        ):
            mismatches.append(
                {
                    "source_device": source,
                    "target_device": target,
                    "source_interface": source_interface,
                    "target_interface": target_interface,
                    "source_vlan_id": source_vlan,
                    "target_vlan_id": target_vlan,
                    "cable_id": edge_data.get("cable_id"),
                }
            )

    return mismatches


def detect_network_loops(
    G: nx.Graph,
    config_path: Optional[str] = None,
) -> AuditResult:
    audit_config = load_audit_config(config_path)
    rule_config = audit_config["network_loop"]
    node_compliance_data = _initialize_node_compliance(G, rule_config)

    try:
        orientation = rule_config["metrics"]["cycle_orientation"]
        cycle_edges = nx.find_cycle(G, orientation=orientation)
        cycle_devices = sorted(
            {edge[0] for edge in cycle_edges} | {edge[1] for edge in cycle_edges}
        )
        cycle_path = _format_cycle_path(cycle_edges)

        for device_name in cycle_devices:
            node_compliance_data[device_name] = _non_compliant_node(
                device_name,
                rule_config,
                cycle_path=cycle_path,
                cycle_devices=", ".join(cycle_devices),
            )

        return {
            "is_passed": False,
            "global_compliance_summary": rule_config["global_summary"]["fail"],
            "node_compliance_data": node_compliance_data,
        }
    except nx.NetworkXNoCycle:
        return {
            "is_passed": True,
            "global_compliance_summary": rule_config["global_summary"]["pass"],
            "node_compliance_data": node_compliance_data,
        }


def detect_single_points_of_failure(
    G: nx.Graph,
    config_path: Optional[str] = None,
) -> AuditResult:
    audit_config = load_audit_config(config_path)
    rule_config = audit_config["single_point_of_failure"]
    node_compliance_data = _initialize_node_compliance(G, rule_config)

    try:
        spof_nodes = list(nx.articulation_points(G))

        for device_name in spof_nodes:
            adjacent_devices = ", ".join(sorted(G.neighbors(device_name)))
            node_compliance_data[device_name] = _non_compliant_node(
                device_name,
                rule_config,
                adjacent_devices=adjacent_devices or "none",
            )

        return {
            "is_passed": len(spof_nodes) == 0,
            "global_compliance_summary": rule_config["global_summary"][
                "pass" if not spof_nodes else "fail"
            ],
            "node_compliance_data": node_compliance_data,
        }
    except Exception as exc:
        return {
            "is_passed": False,
            "global_compliance_summary": (
                f"Single point of failure analysis encountered a technical error: {exc}"
            ),
            "node_compliance_data": node_compliance_data,
        }


def detect_vlan_mismatch(
    G: nx.Graph,
    interfaces_list: List[Dict[str, Any]],
    config_path: Optional[str] = None,
) -> AuditResult:
    audit_config = load_audit_config(config_path)
    rule_config = audit_config["vlan_mismatch"]
    node_compliance_data = _initialize_node_compliance(G, rule_config)
    mismatches = collect_vlan_mismatch_edges(G, interfaces_list)

    device_violations: Dict[str, List[str]] = {node: [] for node in G.nodes()}

    for mismatch in mismatches:
        source_device = mismatch["source_device"]
        target_device = mismatch["target_device"]
        violation_summary = (
            f"{source_device}[{mismatch['source_interface']}] VLAN "
            f"{mismatch['source_vlan_id']} vs {target_device}["
            f"{mismatch['target_interface']}] VLAN {mismatch['target_vlan_id']}"
        )
        device_violations[source_device].append(violation_summary)
        device_violations[target_device].append(violation_summary)

        node_compliance_data[source_device] = _non_compliant_node(
            source_device,
            rule_config,
            local_interface=mismatch["source_interface"],
            peer_device=target_device,
            peer_interface=mismatch["target_interface"],
            local_vlan_id=mismatch["source_vlan_id"],
            peer_vlan_id=mismatch["target_vlan_id"],
            cable_id=mismatch["cable_id"],
        )
        node_compliance_data[target_device] = _non_compliant_node(
            target_device,
            rule_config,
            local_interface=mismatch["target_interface"],
            peer_device=source_device,
            peer_interface=mismatch["source_interface"],
            local_vlan_id=mismatch["target_vlan_id"],
            peer_vlan_id=mismatch["source_vlan_id"],
            cable_id=mismatch["cable_id"],
        )

    for device_name, summaries in device_violations.items():
        if len(summaries) > 1:
            node_compliance_data[device_name] = {
                "compliance_status": rule_config["compliance_status"]["fail"],
                "audit_knowledge": (
                    f"Device {device_name} has multiple VLAN mismatches: "
                    + "; ".join(summaries)
                ),
            }

    return {
        "is_passed": len(mismatches) == 0,
        "global_compliance_summary": rule_config["global_summary"][
            "pass" if not mismatches else "fail"
        ],
        "node_compliance_data": node_compliance_data,
    }


def verify_star_topology(
    G: nx.Graph,
    config_path: Optional[str] = None,
) -> AuditResult:
    audit_config = load_audit_config(config_path)
    rule_config = audit_config["star_topology"]
    metrics = rule_config["metrics"]
    allowed_roles = metrics.get("allowed_roles", ["core_switch", "distribution_switch", "access_switch", "endpoint"])
    
    node_compliance_data: Dict[str, NodeComplianceData] = {}
    
    core_switches = []
    for n, d in G.nodes(data=True):
        raw_r = d.get("role")
        r = raw_r.lower().replace(" ", "_").replace("-", "_") if raw_r else ""
        if r == "core_switch":
            core_switches.append(n)
    
    for device_name, data in G.nodes(data=True):
        role_raw = data.get("role")
        role = role_raw.lower().replace(" ", "_").replace("-", "_") if role_raw else ""
        reasons = []
        
        # 8. Unknown/unsupported role
        if role not in allowed_roles:
            reasons.append(f"Vai trò thiết bị không hợp lệ hoặc không được hỗ trợ: {role_raw}")
        
        expected_parent_role = None
        if role == "distribution_switch":
            expected_parent_role = "core_switch"
        elif role == "access_switch":
            expected_parent_role = "distribution_switch"
        elif role == "endpoint":
            expected_parent_role = "access_switch"
            
        upstream_parents = []
        
        # Check connections
        for neighbor in G.neighbors(device_name):
            neighbor_role_raw = G.nodes[neighbor].get("role")
            neighbor_role = neighbor_role_raw.lower().replace(" ", "_").replace("-", "_") if neighbor_role_raw else ""
            edge_data = G.edges[device_name, neighbor]
            
            # Check 1, 3, 4: Adjacency rules
            if role == "core_switch":
                if neighbor_role not in ["distribution_switch", "core_switch"]:
                    reasons.append(f"Kết nối không hợp lệ tới lớp {neighbor_role}: {neighbor}")
            elif role == "distribution_switch":
                if neighbor_role == "core_switch":
                    upstream_parents.append(neighbor)
                elif neighbor_role == "access_switch":
                    pass
                elif neighbor_role == "distribution_switch":
                    status = edge_data.get("status", "").lower()
                    if status not in ["redundancy", "redundant"]:
                        reasons.append(f"Kết nối ngang hàng giữa các distribution_switch không được đánh dấu là redundancy: tới {neighbor}")
                else:
                    reasons.append(f"Kết nối không hợp lệ tới lớp {neighbor_role}: {neighbor}")
            elif role == "access_switch":
                if neighbor_role == "distribution_switch":
                    upstream_parents.append(neighbor)
                elif neighbor_role == "endpoint":
                    pass
                elif neighbor_role == "access_switch":
                    reasons.append(f"Kết nối ngang hàng không hợp lệ giữa các access_switch: tới {neighbor}")
                else:
                    reasons.append(f"Kết nối không hợp lệ tới lớp {neighbor_role}: {neighbor}")
            elif role == "endpoint":
                if neighbor_role == "access_switch":
                    upstream_parents.append(neighbor)
                else:
                    reasons.append(f"Kết nối không hợp lệ tới lớp {neighbor_role}: {neighbor}")

        # 5. Exactly one upstream parent
        if expected_parent_role:
            if len(upstream_parents) == 0:
                reasons.append(f"Thiết bị không có parent ({expected_parent_role}) hợp lệ.")
            elif len(upstream_parents) > 1:
                reasons.append(f"Thiết bị có nhiều parent hợp lệ ({len(upstream_parents)}), yêu cầu chính xác 1.")
                
        # 2. Endpoints must be leaf nodes
        if role == "endpoint" and G.degree(device_name) > 1:
            reasons.append(f"Endpoint không được phép có thiết bị con (bậc {G.degree(device_name)} > 1).")
            
        # 6. Valid path to core switch
        if role != "core_switch" and core_switches:
            path_found = False
            for core in core_switches:
                if nx.has_path(G, device_name, core):
                    path_found = True
                    break
            if not path_found:
                reasons.append("Không có đường truyền hợp lệ tới bất kỳ core_switch nào.")
        elif role != "core_switch" and not core_switches:
            reasons.append("Không có đường truyền hợp lệ tới bất kỳ core_switch nào.")
                
        if reasons:
            node_compliance_data[device_name] = _non_compliant_node(
                device_name,
                rule_config,
                reason="; ".join(reasons)
            )
        else:
            node_compliance_data[device_name] = _compliant_node(
                device_name,
                rule_config
            )

    # 7. Topology must not contain loops
    try:
        cycles = nx.cycle_basis(G)
        if cycles:
            for cycle in cycles:
                for device_name in cycle:
                    if node_compliance_data[device_name]["compliance_status"] == rule_config["compliance_status"]["pass"]:
                        node_compliance_data[device_name] = _non_compliant_node(
                            device_name,
                            rule_config,
                            reason="Thiết bị tham gia vào vòng lặp mạng không hợp lệ."
                        )
                    else:
                        current_knowledge = node_compliance_data[device_name]["audit_knowledge"]
                        if "vòng lặp" not in current_knowledge:
                            node_compliance_data[device_name]["audit_knowledge"] = current_knowledge.rstrip(".") + "; Thiết bị tham gia vào vòng lặp mạng không hợp lệ."
    except Exception:
        pass
        
    is_passed = all(
        node["compliance_status"] == rule_config["compliance_status"]["pass"]
        for node in node_compliance_data.values()
    )

    return {
        "is_passed": is_passed,
        "global_compliance_summary": rule_config["global_summary"][
            "pass" if is_passed else "fail"
        ],
        "node_compliance_data": node_compliance_data,
    }


def merge_compliance_results(
    results: List[AuditResult],
    config_path: Optional[str] = None,
) -> AuditResult:
    audit_config = load_audit_config(config_path)
    merged_config = audit_config["global"]["merged_compliance"]
    priority = audit_config["global"]["compliance_status_priority"]
    default_status = audit_config["global"]["default_compliance_status"]

    all_nodes = set()
    for result in results:
        all_nodes.update(result["node_compliance_data"].keys())

    merged_nodes: Dict[str, NodeComplianceData] = {}
    for device_name in sorted(all_nodes):
        node_entries = [
            result["node_compliance_data"][device_name]
            for result in results
            if device_name in result["node_compliance_data"]
        ]
        statuses = [entry["compliance_status"] for entry in node_entries]

        final_status = default_status
        for candidate_status in priority:
            if candidate_status in statuses:
                final_status = candidate_status
                break

        if final_status == default_status:
            merged_nodes[device_name] = {
                "compliance_status": default_status,
                "audit_knowledge": merged_config["pass_knowledge_template"].format(
                    device_name=device_name
                ),
            }
        else:
            violation_knowledge = [
                entry["audit_knowledge"]
                for entry in node_entries
                if entry["compliance_status"] != default_status
            ]
            merged_nodes[device_name] = {
                "compliance_status": final_status,
                "audit_knowledge": " | ".join(violation_knowledge),
            }

    is_passed = all(result["is_passed"] for result in results)
    return {
        "is_passed": is_passed,
        "global_compliance_summary": merged_config[
            "global_pass_summary" if is_passed else "global_fail_summary"
        ],
        "node_compliance_data": merged_nodes,
    }


def run_all_compliance_audits(
    G: nx.Graph,
    interfaces_list: List[Dict[str, Any]],
    config_path: Optional[str] = None,
) -> AuditResult:
    results = [
        detect_network_loops(G, config_path),
        detect_single_points_of_failure(G, config_path),
        detect_vlan_mismatch(G, interfaces_list, config_path),
        verify_star_topology(G, config_path),
    ]
    return merge_compliance_results(results, config_path)


def non_compliant_devices(result: AuditResult) -> List[str]:
    return [
        device_name
        for device_name, node_data in result["node_compliance_data"].items()
        if node_data["compliance_status"] != "compliant"
    ]


def spof_devices(result: AuditResult) -> List[str]:
    return [
        device_name
        for device_name, node_data in result["node_compliance_data"].items()
        if node_data["compliance_status"] == "non_compliant_spof"
    ]


def vlan_mismatch_visualization_details(
    G: nx.Graph,
    interfaces_list: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    details: List[Dict[str, str]] = []
    for mismatch in collect_vlan_mismatch_edges(G, interfaces_list):
        details.append(
            {
                "connection": (
                    f"{mismatch['source_device']} <-> {mismatch['target_device']}"
                ),
                "detail": (
                    f"Port {mismatch['source_device']} [{mismatch['source_interface']}] "
                    f"VLAN {mismatch['source_vlan_id']} connected to "
                    f"{mismatch['target_device']} [{mismatch['target_interface']}] "
                    f"VLAN {mismatch['target_vlan_id']}"
                ),
            }
        )
    return details
