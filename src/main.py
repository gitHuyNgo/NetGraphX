from config.settings import neo4j_config
from src.data.netbox_client import NetBoxClient
from src.engine.graph_builder import NetworkGraphBuilder
from src.engine.rule_audit import (
    detect_network_loops,
    detect_single_points_of_failure,
    detect_vlan_mismatch,
    findings_error_nodes,
    findings_vlan_mismatch_details,
    run_all_analytics,
)
from src.models.topology import TopologyData
from src.persistence.neo4j_store import Neo4jTopologyStore


def _print_findings(findings, success_message: str) -> None:
    if findings:
        for finding in findings:
            print(f"    {finding.severity}: {finding.description}")
    else:
        print(f"    SUCCESS: {success_message}")


def main():
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

    print("\n[Step 3] Running compliance checking rules...")
    print(" -> Executing Network Loop Analysis...")
    loop_findings = detect_network_loops(builder.G)
    _print_findings(loop_findings, "The network is secure, with no circuit loops.")

    print(" -> Executing Single Point of Failure Scan...")
    spof_findings = detect_single_points_of_failure(builder.G)
    _print_findings(
        spof_findings,
        "The network system meets standards and has no SPOF nodes",
    )

    print(" -> Executing Cross-Port VLAN Match Verification...")
    vlan_findings = detect_vlan_mismatch(builder.G, topology.interfaces)
    if vlan_findings:
        print("    CRITICAL: Out of sync parameters found on links:")
        for item in findings_vlan_mismatch_details(vlan_findings):
            print(f"       ↳ Link {item['connection']}: {item['detail']}")
    else:
        print("    SUCCESS: VLAN configuration is synchronized across all cable routes.")

    findings = run_all_analytics(builder.G, topology.interfaces)

    if neo4j_store:
        print("\n[Step 3b] Applying analytics flags to Neo4j nodes...")
        try:
            neo4j_store.apply_findings(findings)
            print(f"[Neo4j] Applied flags from {len(findings)} finding(s).")
        except Exception as exc:
            print(f"[Neo4j] Finding flag sync failed: {exc}")

    if neo4j_store:
        neo4j_store.close()

    print("\n[Step 4] Synchronizing metadata to Pyvis UI element layer...")
    spof_nodes = findings_error_nodes(spof_findings)
    mismatch_details = findings_vlan_mismatch_details(vlan_findings) or None

    builder.generate_html_visualization(
        filename="topology.html",
        mismatch_list=mismatch_details,
        bottlenecks_list=spof_nodes,
    )

    print("\n==================================================")
    print(" PROCESSING COMPLETED: Please open 'topology.html' ")
    print(" to inspect your network graph mapping layout.")
    print("==================================================")


if __name__ == "__main__":
    main()
