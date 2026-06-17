from typing import Any, Dict, List, Optional

import networkx as nx
from neo4j import GraphDatabase

from config.settings import neo4j_config
from src.engine.rule_audit import (
    AuditResult,
    collect_loop_edges,
    collect_vlan_mismatch_edges,
    device_topology_violations,
    devices_with_compliance_status,
    load_audit_config,
    loop_participating_interfaces,
)
from src.models.topology import TopologyData

TRUNK_MODES = frozenset({"tagged", "tagged-all", "q-in-q"})


class Neo4jTopologyStore:
    """Persists NetBox topology and audit flags to Neo4j."""

    def __init__(self):
        self._driver = GraphDatabase.driver(
            neo4j_config.NEO4J_URI,
            auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD),
        )

    def close(self) -> None:
        self._driver.close()

    def sync_topology(self, topology: TopologyData) -> None:
        with self._driver.session() as session:
            session.execute_write(self._write_topology, topology)

    def apply_compliance(
        self,
        graph: nx.Graph,
        interfaces_list: List[Dict[str, Any]],
        loop_result: AuditResult,
        spof_result: AuditResult,
        star_result: AuditResult,
        config_path: Optional[str] = None,
    ) -> None:
        with self._driver.session() as session:
            session.execute_write(
                self._write_compliance,
                graph,
                interfaces_list,
                loop_result,
                spof_result,
                star_result,
                config_path,
            )

    @staticmethod
    def _write_topology(tx, topology: TopologyData) -> None:
        tx.run("MATCH (n) DETACH DELETE n")

        for device in topology.devices:
            tx.run(
                """
                MERGE (d:Device {id: $id})
                SET d.name = $name,
                    d.model = $model,
                    d.vendor = $vendor,
                    d.role = $role,
                    d.site = $site,
                    d.rack = $rack,
                    d.is_SPOF = false,
                    d.is_loop = false,
                    d.has_topology_violation = false,
                    d.topology_violation_reason = null
                """,
                id=device.get("id"),
                name=device.get("name"),
                model=device.get("model"),
                vendor=device.get("vendor"),
                role=device.get("role"),
                site=device.get("site"),
                rack=device.get("rack"),
            )

        vlan_records = Neo4jTopologyStore._collect_vlan_records(topology.interfaces)
        for vlan in vlan_records:
            tx.run(
                """
                MERGE (v:VLAN {vid: $vid})
                SET v.name = $name
                """,
                vid=vlan["vid"],
                name=vlan.get("name"),
            )

        for interface in topology.interfaces:
            tx.run(
                """
                MATCH (d:Device {id: $device_id})
                MERGE (i:Interface {id: $id})
                SET i.name = $name,
                    i.mac_address = $mac_address,
                    i.mode = $mode,
                    i.is_loop = false
                MERGE (i)-[:BELONGS_TO]->(d)
                """,
                id=interface.get("id"),
                name=interface.get("name"),
                mac_address=interface.get("mac_address"),
                mode=interface.get("mode"),
                device_id=interface.get("device_id"),
            )

            Neo4jTopologyStore._write_vlan_memberships(tx, interface)

        for cable in topology.cables:
            tx.run(
                """
                MATCH (source:Interface {id: $source_interface_id})
                MATCH (target:Interface {id: $target_interface_id})
                MERGE (source)-[link:CONNECTED_TO {cable_id: $cable_id}]->(target)
                SET link.status = $status,
                    link.is_loop = false,
                    link.loop_id = null,
                    link.has_vlan_mismatch = false,
                    link.vlan_mismatch_detail = null
                """,
                source_interface_id=cable.get("source_interface_id"),
                target_interface_id=cable.get("target_interface_id"),
                cable_id=cable.get("cable_id"),
                status=cable.get("status"),
            )

    @staticmethod
    def _collect_vlan_records(interfaces: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        vlan_index: Dict[int, Dict[str, Any]] = {}
        for interface in interfaces:
            untagged_vlan = interface.get("untagged_vlan")
            if untagged_vlan and untagged_vlan.get("vid") is not None:
                vlan_index[untagged_vlan["vid"]] = untagged_vlan

            for tagged_vlan in interface.get("tagged_vlans") or []:
                if tagged_vlan.get("vid") is not None:
                    vlan_index[tagged_vlan["vid"]] = tagged_vlan

        return list(vlan_index.values())

    @staticmethod
    def _write_vlan_memberships(tx, interface: Dict[str, Any]) -> None:
        interface_id = interface.get("id")
        mode = interface.get("mode")

        untagged_vlan = interface.get("untagged_vlan")
        is_trunk = mode in TRUNK_MODES
        if untagged_vlan and untagged_vlan.get("vid") is not None:
            tx.run(
                """
                MATCH (i:Interface {id: $interface_id})
                MATCH (v:VLAN {vid: $vid})
                MERGE (i)-[membership:MEMBER_OF]->(v)
                SET membership.tagged = $tagged
                """,
                interface_id=interface_id,
                vid=untagged_vlan["vid"],
                tagged=is_trunk,
            )

        for tagged_vlan in interface.get("tagged_vlans") or []:
            if tagged_vlan.get("vid") is None:
                continue
            tx.run(
                """
                MATCH (i:Interface {id: $interface_id})
                MATCH (v:VLAN {vid: $vid})
                MERGE (i)-[membership:MEMBER_OF]->(v)
                SET membership.tagged = $tagged
                """,
                interface_id=interface_id,
                vid=tagged_vlan["vid"],
                tagged=is_trunk,
            )

    @staticmethod
    def _write_compliance(
        tx,
        graph: nx.Graph,
        interfaces_list: List[Dict[str, Any]],
        loop_result: AuditResult,
        spof_result: AuditResult,
        star_result: AuditResult,
        config_path: Optional[str],
    ) -> None:
        audit_config = load_audit_config(config_path)
        loop_status = audit_config["network_loop"]["compliance_status"]["fail"]
        spof_status = audit_config["single_point_of_failure"]["compliance_status"]["fail"]
        vlan_rule = audit_config["vlan_mismatch"]
        link_template = vlan_rule["link_knowledge_template"]

        tx.run(
            """
            MATCH (d:Device)
            SET d.is_SPOF = false,
                d.is_loop = false,
                d.has_topology_violation = false,
                d.topology_violation_reason = null
            """
        )
        tx.run("MATCH (i:Interface) SET i.is_loop = false")
        tx.run(
            """
            MATCH ()-[link:CONNECTED_TO]->()
            SET link.is_loop = false,
                link.loop_id = null,
                link.has_vlan_mismatch = false,
                link.vlan_mismatch_detail = null
            """
        )

        spof_devices = devices_with_compliance_status(spof_result, spof_status)
        if spof_devices:
            tx.run(
                """
                UNWIND $device_names AS device_name
                MATCH (d:Device {name: device_name})
                SET d.is_SPOF = true
                """,
                device_names=spof_devices,
            )

        loop_devices = devices_with_compliance_status(loop_result, loop_status)
        loop_context = collect_loop_edges(graph, config_path)
        loop_id = loop_context["loop_id"]

        if loop_devices:
            tx.run(
                """
                UNWIND $device_names AS device_name
                MATCH (d:Device {name: device_name})
                SET d.is_loop = true
                """,
                device_names=loop_devices,
            )

        loop_interfaces = loop_participating_interfaces(loop_context["edges"])
        for interface_ref in loop_interfaces:
            tx.run(
                """
                MATCH (i:Interface {name: $interface_name})-[:BELONGS_TO]->(d:Device {name: $device_name})
                SET i.is_loop = true
                """,
                interface_name=interface_ref["interface_name"],
                device_name=interface_ref["device_name"],
            )

        if loop_id:
            for edge in loop_context["edges"]:
                tx.run(
                    """
                    MATCH (source:Interface {name: $source_interface})-[:BELONGS_TO]->(:Device {name: $source_device})
                    MATCH (target:Interface {name: $target_interface})-[:BELONGS_TO]->(:Device {name: $target_device})
                    MATCH (source)-[link:CONNECTED_TO {cable_id: $cable_id}]->(target)
                    SET link.is_loop = true,
                        link.loop_id = $loop_id
                    """,
                    source_device=edge["source_device"],
                    target_device=edge["target_device"],
                    source_interface=edge["source_interface"],
                    target_interface=edge["target_interface"],
                    cable_id=edge["cable_id"],
                    loop_id=loop_id,
                )

        topology_violations = device_topology_violations(star_result)
        if topology_violations:
            tx.run(
                """
                UNWIND $violations AS violation
                MATCH (d:Device {name: violation.device_name})
                SET d.has_topology_violation = true,
                    d.topology_violation_reason = violation.reason
                """,
                violations=[
                    {"device_name": device_name, "reason": reason}
                    for device_name, reason in topology_violations.items()
                ],
            )

        for mismatch in collect_vlan_mismatch_edges(graph, interfaces_list):
            detail = link_template.format(**mismatch)
            tx.run(
                """
                MATCH (source:Interface {name: $source_interface})-[:BELONGS_TO]->(:Device {name: $source_device})
                MATCH (target:Interface {name: $target_interface})-[:BELONGS_TO]->(:Device {name: $target_device})
                MATCH (source)-[link:CONNECTED_TO {cable_id: $cable_id}]->(target)
                SET link.has_vlan_mismatch = true,
                    link.vlan_mismatch_detail = $detail
                """,
                source_device=mismatch["source_device"],
                target_device=mismatch["target_device"],
                source_interface=mismatch["source_interface"],
                target_interface=mismatch["target_interface"],
                cable_id=mismatch["cable_id"],
                detail=detail,
            )
