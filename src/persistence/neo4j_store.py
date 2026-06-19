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


# ---------------------------------------------------------------------------
# Vietnamese description builders (Task 1)
# ---------------------------------------------------------------------------

def _build_device_description(
    name: str,
    role: Optional[str],
    vendor: Optional[str],
    model: Optional[str],
    site: Optional[str],
    rack: Optional[str],
    primary_ip: Optional[str],
    status: Optional[str],
    is_spof: bool = False,
    is_loop: bool = False,
    has_topology_violation: bool = False,
    topology_violation_reason: Optional[str] = None,
) -> str:
    """
    Builds a rich Vietnamese natural-language description for a Device node.
    Encodes all structural and audit fields into a single searchable text blob.
    """
    role_str = role or "thiết bị mạng không xác định"
    vendor_str = vendor or "hãng không xác định"
    model_str = model or "không rõ model"
    site_str = site or "vị trí không xác định"
    ip_str = primary_ip or "chưa gán"

    rack_part = f", tủ rack {rack}" if rack else ""
    status_map = {
        "active": "đang hoạt động bình thường",
        "planned": "đang trong giai đoạn lên kế hoạch",
        "staged": "đã được triển khai, chờ kích hoạt",
        "failed": "đã gặp sự cố và ngừng hoạt động",
        "decommissioning": "đang trong quá trình gỡ bỏ",
        "inventory": "đang được lưu kho",
        "offline": "đang offline",
    }
    status_detail = status_map.get(status or "", f"trạng thái: {status or 'không rõ'}")

    # Build error summary section
    errors = []
    if is_spof:
        errors.append("⚠️ SPOF (Điểm thất bại đơn lẻ - Single Point of Failure): thiết bị này là nút cổ chai quan trọng, nếu gặp sự cố toàn bộ kết nối phụ thuộc sẽ bị gián đoạn")
    if is_loop:
        errors.append("🔄 Vòng lặp mạng (Network Loop): thiết bị tham gia vào một vòng lặp L2 bất hợp lệ có thể gây broadcast storm")
    if has_topology_violation:
        reason_str = topology_violation_reason or "vi phạm cấu trúc mạng"
        errors.append(f"❌ Vi phạm cấu trúc (Topology Violation): {reason_str}")

    if errors:
        error_summary = "Các lỗi đang tồn tại: " + "; ".join(errors) + "."
    else:
        error_summary = "✅ Thiết bị an toàn, không phát hiện lỗi cấu trúc."

    return (
        f"Thiết bị {name} là một {role_str} thuộc hãng {vendor_str}, model {model_str}. "
        f"Vị trí: {site_str}{rack_part}. "
        f"Địa chỉ IP chính: {ip_str}. "
        f"Trạng thái hiện tại: {status_detail}. "
        f"{error_summary}"
    )


def _build_interface_description(
    name: str,
    device_name: str,
    mode: Optional[str],
    untagged_vlan: Optional[Dict[str, Any]],
    tagged_vlans: Optional[List[Dict[str, Any]]],
    is_loop: bool = False,
    has_vlan_mismatch: bool = False,
) -> str:
    """
    Builds a Vietnamese natural-language description for an Interface node.
    """
    mode_map = {
        "access": "access (kết nối thiết bị đầu cuối, mang một VLAN duy nhất)",
        "tagged": "trunk (mang nhiều VLAN có gán nhãn)",
        "tagged-all": "trunk toàn bộ VLAN",
        "q-in-q": "Q-in-Q (VLAN lồng nhau)",
    }
    mode_str = mode_map.get(mode or "", f"chế độ {mode or 'không xác định'}")

    vlan_parts = []
    if untagged_vlan:
        vid = untagged_vlan.get("vid")
        vname = untagged_vlan.get("name", "")
        vlan_parts.append(f"VLAN không gán nhãn: {vid} ({vname})")
    if tagged_vlans:
        vids = ", ".join(str(v.get("vid")) for v in tagged_vlans if v.get("vid"))
        vlan_parts.append(f"VLAN gán nhãn: {vids}")

    vlan_str = "; ".join(vlan_parts) if vlan_parts else "chưa gán VLAN"

    errors = []
    if is_loop:
        errors.append("🔄 Tham gia vòng lặp mạng L2")
    if has_vlan_mismatch:
        errors.append("⚠️ Có sự không khớp VLAN với cổng đầu đối diện")

    error_str = " | Lỗi: " + "; ".join(errors) if errors else " | ✅ Không có lỗi."

    return (
        f"Cổng {name} thuộc thiết bị {device_name}. "
        f"Chế độ hoạt động: {mode_str}. "
        f"{vlan_str}."
        f"{error_str}"
    )


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
            print("[Neo4j] Vector index built and embeddings stored successfully.")
        except ImportError as exc:
            print(f"[Neo4j] Embedder not available (sentence-transformers not installed?): {exc}")
        except Exception as exc:
            print(f"[Neo4j] Vector index build failed: {exc}")

    # -----------------------------------------------------------------------
    # Write helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _write_topology(tx, topology: TopologyData) -> None:
        tx.run("MATCH (n) DETACH DELETE n")

        # Build a quick lookup: device_id -> device dict for interface descriptions
        device_by_id: Dict[int, Dict[str, Any]] = {}

        for device in topology.devices:
            # Build initial description (no audit flags yet — they come later)
            description = _build_device_description(
                name=device.get("name", ""),
                role=device.get("role"),
                vendor=device.get("vendor"),
                model=device.get("model"),
                site=device.get("site"),
                rack=device.get("rack"),
                primary_ip=device.get("primary_ip"),
                status=device.get("status"),
            )
            tx.run(
                """
                MERGE (d:Device {id: $id})
                SET d.name = $name,
                    d.model = $model,
                    d.vendor = $vendor,
                    d.role = $role,
                    d.site = $site,
                    d.rack = $rack,
                    d.primary_ip = $primary_ip,
                    d.status = $status,
                    d.is_SPOF = false,
                    d.is_loop = false,
                    d.has_topology_violation = false,
                    d.topology_violation_reason = null,
                    d.description = $description
                """,
                id=device.get("id"),
                name=device.get("name"),
                model=device.get("model"),
                vendor=device.get("vendor"),
                role=device.get("role"),
                site=device.get("site"),
                rack=device.get("rack"),
                primary_ip=device.get("primary_ip"),
                status=device.get("status"),
                description=description,
            )
            device_by_id[device.get("id")] = device

        vlan_records = Neo4jTopologyStore._collect_vlan_records(topology.interfaces)
        for vlan in vlan_records:
            vid = vlan.get("vid")
            vname = vlan.get("name") or f"VLAN-{vid}"
            tx.run(
                """
                MERGE (v:VLAN {vid: $vid})
                SET v.name = $name,
                    v.description = $description
                """,
                vid=vid,
                name=vname,
                description=f"VLAN {vid} ({vname}): phân đoạn mạng logic dùng để cô lập lưu lượng.",
            )

        for interface in topology.interfaces:
            dev_id = interface.get("device_id")
            dev = device_by_id.get(dev_id, {})
            device_name = dev.get("name") or interface.get("device_name") or "không rõ"

            iface_description = _build_interface_description(
                name=interface.get("name", ""),
                device_name=device_name,
                mode=interface.get("mode"),
                untagged_vlan=interface.get("untagged_vlan"),
                tagged_vlans=interface.get("tagged_vlans"),
            )
            tx.run(
                """
                MATCH (d:Device {id: $device_id})
                MERGE (i:Interface {id: $id})
                SET i.name = $name,
                    i.mac_address = $mac_address,
                    i.mode = $mode,
                    i.is_loop = false,
                    i.has_vlan_mismatch = false,
                    i.description = $description
                MERGE (i)-[:BELONGS_TO]->(d)
                """,
                id=interface.get("id"),
                name=interface.get("name"),
                mac_address=interface.get("mac_address"),
                mode=interface.get("mode"),
                device_id=dev_id,
                description=iface_description,
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

        # --- Apply SPOF flags ---
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

        # --- Apply loop flags ---
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
                    MATCH (source)-[link:CONNECTED_TO {cable_id: $cable_id}]-(target)
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

        # --- Apply topology violation flags ---
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

        # --- Apply VLAN mismatch flags to interfaces and links ---
        mismatch_interface_names = set()
        for mismatch in collect_vlan_mismatch_edges(graph, interfaces_list):
            detail = link_template.format(**mismatch)
            tx.run(
                """
                MATCH (source:Interface {name: $source_interface})-[:BELONGS_TO]->(:Device {name: $source_device})
                MATCH (target:Interface {name: $target_interface})-[:BELONGS_TO]->(:Device {name: $target_device})
                MATCH (source)-[link:CONNECTED_TO {cable_id: $cable_id}]-(target)
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
            mismatch_interface_names.add(
                (mismatch["source_interface"], mismatch["source_device"])
            )
            mismatch_interface_names.add(
                (mismatch["target_interface"], mismatch["target_device"])
            )

        for iface_name, dev_name in mismatch_interface_names:
            tx.run(
                """
                MATCH (i:Interface {name: $iface_name})-[:BELONGS_TO]->(d:Device {name: $dev_name})
                SET i.has_vlan_mismatch = true
                """,
                iface_name=iface_name,
                dev_name=dev_name,
            )

        # -------------------------------------------------------------------
        # Task 1: Rebuild Vietnamese descriptions now that all flags are set.
        # We read back updated flags from Neo4j and regenerate the description.
        # -------------------------------------------------------------------
        tx.run(
            """
            MATCH (d:Device)
            SET d.description = 
                'Thiết bị ' + d.name + 
                ' là một ' + coalesce(d.role, 'thiết bị mạng') + 
                ' thuộc hãng ' + coalesce(d.vendor, 'không rõ') + 
                ', model ' + coalesce(d.model, 'không rõ') + '. ' +
                'Vị trí: ' + coalesce(d.site, 'không xác định') + 
                CASE WHEN d.rack IS NOT NULL THEN ', tủ rack ' + d.rack ELSE '' END + '. ' +
                'Địa chỉ IP chính: ' + coalesce(d.primary_ip, 'chưa gán') + '. ' +
                'Trạng thái: ' + coalesce(d.status, 'không rõ') + '. ' +
                CASE 
                    WHEN d.is_SPOF AND d.is_loop THEN '⚠️ Lỗi SPOF và vòng lặp mạng đang tồn tại.'
                    WHEN d.is_SPOF THEN '⚠️ Lỗi SPOF: thiết bị là điểm thất bại đơn lẻ.'
                    WHEN d.is_loop THEN '🔄 Lỗi vòng lặp mạng L2 đang tồn tại.'
                    ELSE '✅ Thiết bị an toàn, không phát hiện lỗi cấu trúc.'
                END +
                CASE 
                    WHEN d.has_topology_violation THEN ' ❌ Vi phạm cấu trúc: ' + coalesce(d.topology_violation_reason, 'không rõ lý do') + '.'
                    ELSE ''
                END
            """
        )

        # Rebuild interface descriptions with updated loop/mismatch flags
        tx.run(
            """
            MATCH (i:Interface)-[:BELONGS_TO]->(d:Device)
            SET i.description =
                'Cổng ' + i.name + ' thuộc thiết bị ' + d.name + '. ' +
                'Chế độ: ' + coalesce(i.mode, 'không xác định') + '. ' +
                CASE 
                    WHEN i.is_loop AND i.has_vlan_mismatch THEN '🔄 Tham gia vòng lặp mạng. ⚠️ VLAN mismatch.'
                    WHEN i.is_loop THEN '🔄 Tham gia vòng lặp mạng L2.'
                    WHEN i.has_vlan_mismatch THEN '⚠️ Có sự không khớp VLAN với cổng đầu đối diện.'
                    ELSE '✅ Cổng hoạt động bình thường.'
                END
            """
        )
