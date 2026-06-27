import logging
import sys

from config.settings import neo4j_config
from src.data_pipeline.netbox_client import NetBoxClient
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
from src.ui.vis_component.renderer import generate_html_visualization
from src.core.topology import TopologyData
from src.data_pipeline.neo4j_store import Neo4jTopologyStore


logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")


def _print_audit_result(rule_name: str, result: dict) -> None:
    logger.info(f" -> {rule_name}")
    logger.info(f"    Status: {'PASSED' if result['is_passed'] else 'FAILED'}")
    logger.info(f"    Summary: {result['global_compliance_summary']}")

    if not result["is_passed"]:
        for device_name, node_data in result["node_compliance_data"].items():
            if node_data["compliance_status"] != "compliant":
                logger.info(
                    f"    Device {device_name} "
                    f"[{node_data['compliance_status']}]: {node_data['audit_knowledge']}"
                )


import argparse
import subprocess

def run_engine(skip_embed: bool):
    audit_config_path = str(DEFAULT_AUDIT_CONFIG_PATH)

    logger.info("==================================================")
    logger.info("   RUNNING NETGRAPHX ENGINE - VIETTEL LABS        ")
    logger.info("==================================================\n")

    logger.info("[Step 1] Fetching raw inventory data from NetBox API...")
    netbox = NetBoxClient()
    topology = TopologyData.from_netbox(netbox)

    if not topology.is_valid:
        logger.error("[Abort] Insufficient data to construct topology graph parameters.")
        return

    neo4j_store = None
    if neo4j_config.NEO4J_ENABLED:
        logger.info("\n[Step 2a] Synchronizing topology knowledge graph to Neo4j...")
        try:
            neo4j_store = Neo4jTopologyStore()
            neo4j_store.sync_topology(topology)
            logger.info("[Neo4j] Topology graph stored successfully.")
        except RuntimeError as exc:
            logger.error(f"[Neo4j] Topology sync skipped due to error: {exc}")
            if neo4j_store:
                neo4j_store.close()
            neo4j_store = None
    else:
        logger.info("\n[Step 2a] Neo4j sync disabled (NEO4J_ENABLED=false).")

    logger.info("\n[Step 2b] Building topology framework using NetworkX mapping...")
    builder = NetworkGraphBuilder()
    builder.build_topology(topology.devices, topology.cables)

    logger.info("\n[Step 3] Running compliance audit engine...")
    logger.info(f"    Configuration: {audit_config_path}")

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
    logger.info("\n[Step 3 Summary] Merged compliance result")
    logger.info(f"    Status: {'PASSED' if compliance['is_passed'] else 'FAILED'}")
    logger.info(f"    Summary: {compliance['global_compliance_summary']}")

    if neo4j_store:
        logger.info("\n[Step 3b] Applying audit flags to Neo4j graph model...")
        try:
            neo4j_store.apply_compliance(
                builder.G,
                topology.interfaces,
                loop_result,
                spof_result,
                star_result,
                audit_config_path,
            )
            logger.info("[Neo4j] Device, interface, and link audit flags updated successfully.")
        except RuntimeError as exc:
            logger.error(f"[Neo4j] Compliance sync failed: {exc}")

    if neo4j_store and not skip_embed:
        logger.info("\n[Step 3c] Building vector embeddings for RAG pipeline (Task 2)...")
        logger.info("    Tip: Run with --skip-embed to skip this step for faster iterations.")
        neo4j_store.build_vector_index()
    elif skip_embed:
        logger.info("\n[Step 3c] Skipping vector embedding (--skip-embed flag set).")

    if neo4j_store:
        neo4j_store.close()

    logger.info("\n[Step 4] Generating vis.js topology map and companion metadata...")
    mismatch_details = vlan_mismatch_visualization_details(
        builder.G,
        topology.interfaces,
    ) or None

    spof_list = spof_devices(compliance)

    vis_nodes, vis_edges, meta = builder.build_vis_data(mismatch_details, spof_list)

    generate_html_visualization(
        filename="static/topology.html",
        vis_nodes=vis_nodes,
        vis_edges=vis_edges,
        meta=meta,
    )

    builder.save_topology_metadata(
        filename="data/storage/topology_data.json",
        mismatch_list=mismatch_details,
        bottlenecks_list=spof_list,
    )

    logger.info("\n==================================================")
    logger.info(" PROCESSING COMPLETED:")
    logger.info("   topology.html      — open in browser for standalone view")
    logger.info("   topology_data.json — consumed by Streamlit dashboard")
    logger.info("==================================================")


def main():
    parser = argparse.ArgumentParser(description="NetGraphX Main Entrypoint")
    parser.add_argument("--run-engine", action="store_true", help="Run the backend graph engine and generate topology.")
    parser.add_argument("--run-ui", action="store_true", help="Run the Streamlit frontend dashboard.")
    parser.add_argument("--skip-embed", action="store_true", help="Skip Neo4j vector embedding when running engine.")
    
    args = parser.parse_args()

    if args.run_ui:
        logger.info("Starting NetGraphX Streamlit UI...")
        try:
            subprocess.run([sys.executable, "-m", "streamlit", "run", "src/ui/app.py"])
        except KeyboardInterrupt:
            logger.info("UI stopped by user.")
    elif args.run_engine:
        run_engine(args.skip_embed)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
