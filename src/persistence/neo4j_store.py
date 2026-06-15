from typing import List, Tuple

from neo4j import GraphDatabase

from config.settings import neo4j_config
from src.models.finding import Finding
from src.models.topology import TopologyData


class Neo4jTopologyStore:
    """Persists NetBox topology and analytics findings to Neo4j."""

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

    def apply_findings(self, findings: List[Finding]) -> None:
        with self._driver.session() as session:
            session.execute_write(self._write_finding_flags, findings)

    @staticmethod
    def _canonical_cable_endpoints(cable: dict) -> Tuple[str, str, str, str]:
        """Order device pair consistently so each cable is one undirected link."""
        source = cable["source_device"]
        target = cable["target_device"]
        source_if = cable.get("source_interface") or ""
        target_if = cable.get("target_interface") or ""

        if source <= target:
            return source, target, source_if, target_if
        return target, source, target_if, source_if

    @staticmethod
    def _write_topology(tx, topology: TopologyData) -> None:
        tx.run("MATCH (:Device)-[r:CONNECTED_TO]->(:Device) DELETE r")
        tx.run("MATCH (:Device)-[r:PHYSICAL_LINK]->(:Device) DELETE r")
        tx.run("MATCH (l:Link) DETACH DELETE l")
        tx.run("MATCH (f:Finding) DETACH DELETE f")

        for device in topology.devices:
            tx.run(
                """
                MERGE (d:Device {name: $name})
                SET d.netbox_id = $id,
                    d.role = $role,
                    d.manufacturer = $manufacturer,
                    d.primary_ip = $primary_ip,
                    d.status = $status,
                    d.has_spof = false,
                    d.has_loop = false,
                    d.has_vlan_mismatch = false
                """,
                name=device["name"],
                id=device.get("id"),
                role=device.get("role"),
                manufacturer=device.get("manufacturer"),
                primary_ip=device.get("primary_ip"),
                status=device.get("status"),
            )

        for cable in topology.cables:
            device_a, device_b, interface_a, interface_b = (
                Neo4jTopologyStore._canonical_cable_endpoints(cable)
            )
            tx.run(
                """
                MATCH (a:Device {name: $device_a})
                MATCH (b:Device {name: $device_b})
                MERGE (a)-[link:PHYSICAL_LINK {cable_id: $cable_id}]->(b)
                SET link.device_a = $device_a,
                    link.device_b = $device_b,
                    link.interface_a = $interface_a,
                    link.interface_b = $interface_b,
                    link.netbox_source_device = $netbox_source_device,
                    link.netbox_target_device = $netbox_target_device,
                    link.netbox_source_interface = $netbox_source_interface,
                    link.netbox_target_interface = $netbox_target_interface,
                    link.status = $status,
                    link.has_vlan_mismatch = false,
                    link.vlan_mismatch_detail = null
                """,
                device_a=device_a,
                device_b=device_b,
                cable_id=cable["cable_id"],
                interface_a=interface_a,
                interface_b=interface_b,
                netbox_source_device=cable["source_device"],
                netbox_target_device=cable["target_device"],
                netbox_source_interface=cable.get("source_interface"),
                netbox_target_interface=cable.get("target_interface"),
                status=cable.get("status"),
            )

    @staticmethod
    def _write_finding_flags(tx, findings: List[Finding]) -> None:
        tx.run(
            """
            MATCH (d:Device)
            SET d.has_spof = false,
                d.has_loop = false,
                d.has_vlan_mismatch = false
            """
        )
        tx.run(
            """
            MATCH ()-[link:PHYSICAL_LINK]->()
            SET link.has_vlan_mismatch = false,
                link.vlan_mismatch_detail = null
            """
        )

        loop_nodes: List[str] = []
        spof_nodes: List[str] = []
        vlan_device_nodes: List[str] = []
        vlan_links: List[dict] = []

        for finding in findings:
            if finding.type == "LOOP":
                loop_nodes.extend(finding.affected_nodes)
            elif finding.type == "SPOF":
                spof_nodes.extend(finding.affected_nodes)
            elif finding.type == "VLAN_MISMATCH":
                vlan_device_nodes.extend(finding.affected_nodes)
                for link in finding.affected_links:
                    if link.cable_id is not None:
                        vlan_links.append(
                            {
                                "cable_id": link.cable_id,
                                "detail": finding.description,
                            }
                        )

        if loop_nodes:
            tx.run(
                """
                UNWIND $nodes AS node_name
                MATCH (d:Device {name: node_name})
                SET d.has_loop = true
                """,
                nodes=list(set(loop_nodes)),
            )

        if spof_nodes:
            tx.run(
                """
                UNWIND $nodes AS node_name
                MATCH (d:Device {name: node_name})
                SET d.has_spof = true
                """,
                nodes=list(set(spof_nodes)),
            )

        if vlan_device_nodes:
            tx.run(
                """
                UNWIND $nodes AS node_name
                MATCH (d:Device {name: node_name})
                SET d.has_vlan_mismatch = true
                """,
                nodes=list(set(vlan_device_nodes)),
            )

        if vlan_links:
            tx.run(
                """
                UNWIND $links AS item
                MATCH (a:Device)-[link:PHYSICAL_LINK {cable_id: item.cable_id}]-(b:Device)
                SET link.has_vlan_mismatch = true,
                    link.vlan_mismatch_detail = item.detail
                """,
                links=vlan_links,
            )
