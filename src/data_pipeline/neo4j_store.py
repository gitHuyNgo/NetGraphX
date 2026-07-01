from typing import Any, Dict, List, Optional

import logging

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
    build_device_description,
    build_interface_description,
)
from src.core.topology import TopologyData

TRUNK_MODES = frozenset({"tagged", "tagged-all", "q-in-q"})
logger = logging.getLogger(__name__)



# ---------------------------------------------------------------------------
# Main store class
# ---------------------------------------------------------------------------

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

    def build_vector_index(self) -> None:
        """Task 2: Generate sentence embeddings for all nodes and create Neo4j vector index."""
        try:
            from src.rag.embedder import NodeEmbedder
            embedder = NodeEmbedder()
            embedder.embed_all_nodes(self._driver)
            logger.info("[Neo4j] Vector index built and embeddings stored successfully.")
        except ImportError as exc:
            logger.error(f"[Neo4j] Embedder not available (sentence-transformers not installed?): {exc}")
        except Exception as exc:
            logger.error(f"[Neo4j] Vector index build failed: {exc}")

    # -----------------------------------------------------------------------
    # Write helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _write_topology(tx, topology: TopologyData) -> None:
        tx.run("MATCH (n) DETACH DELETE n")

        # Build a quick lookup: device_id -> device dict for interface descriptions
        device_by_id: Dict[int, Dict[str, Any]] = {}
        device_params = []
        for device in topology.devices:
            # Build initial description (no audit flags yet — they come later)
            description = build_device_description(
                name=device.get("name", ""),
                role=device.get("role"),
                vendor=device.get("vendor"),
                model=device.get("model"),
                site=device.get("site"),
                rack=device.get("rack"),
                primary_ip=device.get("primary_ip"),
                status=device.get("status"),
            )
            device_by_id[device.get("id")] = device
            device_params.append({
                "id": device.get("id"),
                "name": device.get("name"),
                "model": device.get("model"),
                "vendor": device.get("vendor"),
                "role": device.get("role"),
                "site": device.get("site"),
                "rack": device.get("rack"),
                "primary_ip": device.get("primary_ip"),
                "status": device.get("status"),
                "description": description,
            })
            
        if device_params:
            tx.run(
                """
                UNWIND $devices AS dev
                MERGE (d:Device {id: dev.id})
                SET d.name = dev.name,
                    d.model = dev.model,
                    d.vendor = dev.vendor,
                    d.role = dev.role,
                    d.site = dev.site,
                    d.rack = dev.rack,
                    d.primary_ip = dev.primary_ip,
                    d.status = dev.status,
                    d.is_SPOF = false,
                    d.is_loop = false,
                    d.has_topology_violation = false,
                    d.topology_violation_reason = null,
                    d.description = dev.description
                """,
                devices=device_params,
            )

        vlan_records = Neo4jTopologyStore._collect_vlan_records(topology.interfaces)
        vlan_params = []
        for vlan in vlan_records:
            vid = vlan.get("vid")
            vname = vlan.get("name") or f"VLAN-{vid}"
            vlan_params.append({
                "vid": vid,
                "name": vname,
                "description": f"VLAN {vid} ({vname}): phân đoạn mạng logic dùng để cô lập lưu lượng."
            })
            
        if vlan_params:
            tx.run(
                """
                UNWIND $vlans AS vlan
                MERGE (v:VLAN {vid: vlan.vid})
                SET v.name = vlan.name,
                    v.description = vlan.description
                """,
                vlans=vlan_params,
            )

        interface_params = []
        for interface in topology.interfaces:
            dev_id = interface.get("device_id")
            dev = device_by_id.get(dev_id, {})
            device_name = dev.get("name") or interface.get("device_name") or "không rõ"

            iface_description = build_interface_description(
                name=interface.get("name", ""),
                device_name=device_name,
                mode=interface.get("mode"),
                untagged_vlan=interface.get("untagged_vlan"),
                tagged_vlans=interface.get("tagged_vlans"),
            )
            interface_params.append({
                "id": interface.get("id"),
                "name": interface.get("name"),
                "mac_address": interface.get("mac_address"),
                "mode": interface.get("mode"),
                "device_id": dev_id,
                "description": iface_description
            })

        if interface_params:
            tx.run(
                """
                UNWIND $interfaces AS iface
                MATCH (d:Device {id: iface.device_id})
                MERGE (i:Interface {id: iface.id})
                SET i.name = iface.name,
                    i.mac_address = iface.mac_address,
                    i.mode = iface.mode,
                    i.is_loop = false,
                    i.has_vlan_mismatch = false,
                    i.description = iface.description
                MERGE (i)-[:BELONGS_TO]->(d)
                """,
                interfaces=interface_params,
            )

        Neo4jTopologyStore._write_vlan_memberships(tx, topology.interfaces)

        cable_params = []
        for cable in topology.cables:
            cable_params.append({
                "source_interface_id": cable.get("source_interface_id"),
                "target_interface_id": cable.get("target_interface_id"),
                "cable_id": cable.get("cable_id"),
                "status": cable.get("status"),
            })
            
        if cable_params:
            tx.run(
                """
                UNWIND $cables AS cable
                MATCH (source:Interface {id: cable.source_interface_id})
                MATCH (target:Interface {id: cable.target_interface_id})
                MERGE (source)-[link:CONNECTED_TO {cable_id: cable.cable_id}]->(target)
                SET link.status = cable.status,
                    link.is_loop = false,
                    link.loop_id = null,
                    link.has_vlan_mismatch = false,
                    link.vlan_mismatch_detail = null
                """,
                cables=cable_params,
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
    def _write_vlan_memberships(tx, interfaces: List[Dict[str, Any]]) -> None:
        untagged_params = []
        tagged_params = []
        
        for interface in interfaces:
            interface_id = interface.get("id")
            mode = interface.get("mode")
            is_trunk = mode in TRUNK_MODES
            
            untagged_vlan = interface.get("untagged_vlan")
            if untagged_vlan and untagged_vlan.get("vid") is not None:
                untagged_params.append({
                    "interface_id": interface_id,
                    "vid": untagged_vlan["vid"],
                    "tagged": is_trunk
                })

            for tagged_vlan in interface.get("tagged_vlans") or []:
                if tagged_vlan.get("vid") is not None:
                    tagged_params.append({
                        "interface_id": interface_id,
                        "vid": tagged_vlan["vid"],
                        "tagged": is_trunk
                    })

        if untagged_params:
            tx.run(
                """
                UNWIND $params AS param
                MATCH (i:Interface {id: param.interface_id})
                MATCH (v:VLAN {vid: param.vid})
                MERGE (i)-[membership:MEMBER_OF]->(v)
                SET membership.tagged = param.tagged
                """,
                params=untagged_params,
            )

        if tagged_params:
            tx.run(
                """
                UNWIND $params AS param
                MATCH (i:Interface {id: param.interface_id})
                MATCH (v:VLAN {vid: param.vid})
                MERGE (i)-[membership:MEMBER_OF]->(v)
                SET membership.tagged = param.tagged
                """,
                params=tagged_params,
            )


    @staticmethod
    def _apply_spof_flags(tx, spof_result: AuditResult, spof_status: str) -> None:
        spof_device_names = devices_with_compliance_status(spof_result, spof_status)
        if spof_device_names:
            tx.run(
                """
                UNWIND $device_names AS device_name
                MATCH (d:Device {name: device_name})
                SET d.is_SPOF = true
                """,
                device_names=spof_device_names,
            )

    @staticmethod
    def _apply_loop_flags(tx, graph, config_path: str, loop_result: AuditResult, loop_status: str) -> list:
        loop_devices = devices_with_compliance_status(loop_result, loop_status)
        loop_contexts = collect_loop_edges(graph, config_path)

        if loop_devices:
            tx.run(
                """
                UNWIND $device_names AS device_name
                MATCH (d:Device {name: device_name})
                SET d.is_loop = true
                """,
                device_names=loop_devices,
            )

        loop_iface_params = []
        loop_link_params = []
        for loop_context in loop_contexts:
            loop_id = loop_context["loop_id"]
            loop_interfaces = loop_participating_interfaces(loop_context["edges"])
            
            for interface_ref in loop_interfaces:
                loop_iface_params.append({
                    "interface_name": interface_ref["interface_name"],
                    "device_name": interface_ref["device_name"],
                })

            if loop_id:
                for edge in loop_context["edges"]:
                    loop_link_params.append({
                        "source_device": edge["source_device"],
                        "target_device": edge["target_device"],
                        "source_interface": edge["source_interface"],
                        "target_interface": edge["target_interface"],
                        "cable_id": edge["cable_id"],
                        "loop_id": loop_id,
                    })
                    
        if loop_iface_params:
            tx.run(
                """
                UNWIND $interfaces AS iface
                MATCH (i:Interface {name: iface.interface_name})-[:BELONGS_TO]->(d:Device {name: iface.device_name})
                SET i.is_loop = true
                """,
                interfaces=loop_iface_params,
            )
            
        if loop_link_params:
            tx.run(
                """
                UNWIND $links AS link_param
                MATCH (source:Interface {name: link_param.source_interface})-[:BELONGS_TO]->(:Device {name: link_param.source_device})
                MATCH (target:Interface {name: link_param.target_interface})-[:BELONGS_TO]->(:Device {name: link_param.target_device})
                MATCH (source)-[link:CONNECTED_TO {cable_id: link_param.cable_id}]-(target)
                SET link.is_loop = true,
                    link.loop_id = link_param.loop_id
                """,
                links=loop_link_params,
            )
        return loop_contexts

    @staticmethod
    def _apply_topology_violation_flags(tx, star_result: AuditResult) -> None:
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

    @staticmethod
    def _apply_vlan_mismatch_flags(tx, graph, interfaces_list: list, link_template: str) -> set:
        mismatch_interface_names = set()
        mismatch_link_params = []
        for mismatch in collect_vlan_mismatch_edges(graph, interfaces_list):
            detail = link_template.format(**mismatch)
            mismatch_link_params.append({
                "source_device": mismatch["source_device"],
                "target_device": mismatch["target_device"],
                "source_interface": mismatch["source_interface"],
                "target_interface": mismatch["target_interface"],
                "cable_id": mismatch["cable_id"],
                "detail": detail,
            })
            mismatch_interface_names.add(
                (mismatch["source_interface"], mismatch["source_device"])
            )
            mismatch_interface_names.add(
                (mismatch["target_interface"], mismatch["target_device"])
            )
            
        if mismatch_link_params:
            tx.run(
                """
                UNWIND $links AS link_param
                MATCH (source:Interface {name: link_param.source_interface})-[:BELONGS_TO]->(:Device {name: link_param.source_device})
                MATCH (target:Interface {name: link_param.target_interface})-[:BELONGS_TO]->(:Device {name: link_param.target_device})
                MATCH (source)-[link:CONNECTED_TO {cable_id: link_param.cable_id}]-(target)
                SET link.has_vlan_mismatch = true,
                    link.vlan_mismatch_detail = link_param.detail
                """,
                links=mismatch_link_params,
            )

        if mismatch_interface_names:
            mismatch_iface_params = [
                {"iface_name": i, "dev_name": d} for i, d in mismatch_interface_names
            ]
            tx.run(
                """
                UNWIND $interfaces AS iface
                MATCH (i:Interface {name: iface.iface_name})-[:BELONGS_TO]->(d:Device {name: iface.dev_name})
                SET i.has_vlan_mismatch = true
                """,
                interfaces=mismatch_iface_params,
            )
        return mismatch_interface_names

    @staticmethod
    def _rebuild_descriptions_with_python(tx, interfaces_list: list, loop_interfaces: list, mismatch_interface_names: set) -> None:
        devices_data = tx.run(
            """
            MATCH (d:Device)
            RETURN d.name as name, d.role as role, d.vendor as vendor, d.model as model,
                   d.site as site, d.rack as rack, d.primary_ip as primary_ip, d.status as status,
                   d.is_SPOF as is_spof, d.is_loop as is_loop, d.has_topology_violation as has_violation,
                   d.topology_violation_reason as reason
            """
        ).data()

        dev_params = []
        for d in devices_data:
            desc = build_device_description(
                name=d["name"],
                role=d["role"],
                vendor=d["vendor"],
                model=d["model"],
                site=d["site"],
                rack=d["rack"],
                primary_ip=d["primary_ip"],
                status=d["status"],
                is_spof=bool(d.get("is_spof")),
                is_loop=bool(d.get("is_loop")),
                has_topology_violation=bool(d.get("has_violation")),
                topology_violation_reason=d.get("reason")
            )
            dev_params.append({"name": d["name"], "desc": desc})
            
        if dev_params:
            tx.run(
                """
                UNWIND $devices AS dev
                MATCH (d:Device {name: dev.name}) 
                SET d.description = dev.desc
                """,
                devices=dev_params,
            )

        loop_ifaces_set = {(ref["interface_name"], ref["device_name"]) for ref in loop_interfaces}
        iface_params = []
        for interface in interfaces_list:
            iface_name = interface.get("name", "")
            dev_name = interface.get("device_name", "không rõ")
            iface_key = (iface_name, dev_name)

            is_loop_iface = iface_key in loop_ifaces_set
            has_mismatch_iface = iface_key in mismatch_interface_names

            desc = build_interface_description(
                name=iface_name,
                device_name=dev_name,
                mode=interface.get("mode"),
                untagged_vlan=interface.get("untagged_vlan"),
                tagged_vlans=interface.get("tagged_vlans"),
                is_loop=is_loop_iface,
                has_vlan_mismatch=has_mismatch_iface,
            )
            iface_params.append({
                "iface_name": iface_name,
                "dev_name": dev_name,
                "desc": desc,
            })
            
        if iface_params:
            tx.run(
                """
                UNWIND $interfaces AS iface
                MATCH (i:Interface {name: iface.iface_name})-[:BELONGS_TO]->(d:Device {name: iface.dev_name})
                SET i.description = iface.desc
                """,
                interfaces=iface_params,
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

        # Reset all flags
        tx.run(
            """
            MATCH (d:Device)
            SET d.is_SPOF = false,
                d.is_loop = false,
                d.has_topology_violation = false,
                d.topology_violation_reason = null
            """
        )
        tx.run("MATCH (i:Interface) SET i.is_loop = false, i.has_vlan_mismatch = false")
        tx.run(
            """
            MATCH ()-[link:CONNECTED_TO]->()
            SET link.is_loop = false,
                link.loop_id = null,
                link.has_vlan_mismatch = false,
                link.vlan_mismatch_detail = null
            """
        )

        Neo4jTopologyStore._apply_spof_flags(tx, spof_result, spof_status)
        loop_contexts = Neo4jTopologyStore._apply_loop_flags(tx, graph, config_path, loop_result, loop_status)
        Neo4jTopologyStore._apply_topology_violation_flags(tx, star_result)
        mismatch_interface_names = Neo4jTopologyStore._apply_vlan_mismatch_flags(tx, graph, interfaces_list, link_template)

        all_loop_interfaces = []
        for lc in loop_contexts:
            all_loop_interfaces.extend(loop_participating_interfaces(lc["edges"]))
        Neo4jTopologyStore._rebuild_descriptions_with_python(tx, interfaces_list, all_loop_interfaces, mismatch_interface_names)
