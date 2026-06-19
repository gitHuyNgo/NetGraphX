import sys

from config.settings import neo4j_config
from src.data.netbox_client import NetBoxClient
from src.engine.graph_builder import NetworkGraphBuilder
from src.engine.rule_audit import (
    DEFAULT_AUDIT_CONFIG_PATH,
    detect_network_loops,
    detect_single_points_of_failure,
    detect_vlan_mismatch,
    run_all_compliance_audits,
    spof_devices,
    verify_star_topology,
    vlan_mismatch_visualization_details,
)
from src.models.topology import TopologyData
from src.persistence.neo4j_store import Neo4jTopologyStore


def _print_audit_result(rule_name: str, result: dict) -> None:
    print(f" -> {rule_name}")
    print(f"    Status: {'PASSED' if result['is_passed'] else 'FAILED'}")
    print(f"    Summary: {result['global_compliance_summary']}")

    if not result["is_passed"]:
        for device_name, node_data in result["node_compliance_data"].items():
            if node_data["compliance_status"] != "compliant":
                print(
                    f"    Device {device_name} "
                    f"[{node_data['compliance_status']}]: {node_data['audit_knowledge']}"
                )


def main():
    audit_config_path = str(DEFAULT_AUDIT_CONFIG_PATH)
    skip_embed = "--skip-embed" in sys.argv

    print("==================================================")
    print("   RUNNING NETGRAPHX ENGINE - VIETTEL LABS        ")
    print("==================================================\n")

    print("[Step 1] Fetching raw inventory data from NetBox API...")
    netbox = NetBoxClient()
    topology = TopologyData.from_netbox(netbox)

    if not topology.is_valid:
        print("[Abort] Insufficient data to construct topology graph parameters.")
        return

    neo4j_store = None
    if neo4j_config.NEO4J_ENABLED:
        print("\n[Step 2a] Synchronizing topology knowledge graph to Neo4j...")
        try:
            neo4j_store = Neo4jTopologyStore()
            neo4j_store.sync_topology(topology)
            print("[Neo4j] Topology graph stored successfully.")
        except Exception as exc:
            print(f"[Neo4j] Topology sync skipped due to error: {exc}")
            if neo4j_store:
                neo4j_store.close()
            neo4j_store = None
    else:
        print("\n[Step 2a] Neo4j sync disabled (NEO4J_ENABLED=false).")

    print("\n[Step 2b] Building topology framework using NetworkX mapping...")
    builder = NetworkGraphBuilder()
    builder.build_topology(topology.devices, topology.cables)

    print("\n[Step 3] Running compliance audit engine...")
    print(f"    Configuration: {audit_config_path}")

    loop_result = detect_network_loops(builder.G, audit_config_path)
    _print_audit_result("Network Loop Detection", loop_result)

    spof_result = detect_single_points_of_failure(builder.G, audit_config_path)
    _print_audit_result("Single Point of Failure Analysis", spof_result)

    vlan_result = detect_vlan_mismatch(
        builder.G,
        topology.interfaces,
        audit_config_path,
    )
    _print_audit_result("VLAN Consistency Validation", vlan_result)

    star_result = verify_star_topology(builder.G, audit_config_path)
    _print_audit_result("Star Topology Validation", star_result)

    compliance = run_all_compliance_audits(
        builder.G,
        topology.interfaces,
        audit_config_path,
    )
    print("\n[Step 3 Summary] Merged compliance result")
    print(f"    Status: {'PASSED' if compliance['is_passed'] else 'FAILED'}")
    print(f"    Summary: {compliance['global_compliance_summary']}")

    if neo4j_store:
        print("\n[Step 3b] Applying audit flags to Neo4j graph model...")
        try:
            neo4j_store.apply_compliance(
                builder.G,
                topology.interfaces,
                loop_result,
                spof_result,
                star_result,
                audit_config_path,
            )
            print("[Neo4j] Device, interface, and link audit flags updated successfully.")
        except Exception as exc:
            print(f"[Neo4j] Compliance sync failed: {exc}")

    if neo4j_store and not skip_embed:
        print("\n[Step 3c] Building vector embeddings for RAG pipeline (Task 2)...")
        print("    Tip: Run with --skip-embed to skip this step for faster iterations.")
        neo4j_store.build_vector_index()
    elif skip_embed:
        print("\n[Step 3c] Skipping vector embedding (--skip-embed flag set).")

    if neo4j_store:
        neo4j_store.close()

    print("\n[Step 4] Synchronizing metadata to Pyvis UI element layer...")
    mismatch_details = vlan_mismatch_visualization_details(
        builder.G,
        topology.interfaces,
    ) or None

    builder.generate_html_visualization(
        filename="topology.html",
        mismatch_list=mismatch_details,
        bottlenecks_list=spof_devices(compliance),
    )

    print("\n==================================================")
    print(" PROCESSING COMPLETED: Please open 'topology.html' ")
    print(" to inspect your network graph mapping layout.")
    print("==================================================")


if __name__ == "__main__":
    main()
