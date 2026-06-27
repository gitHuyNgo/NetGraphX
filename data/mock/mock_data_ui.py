import logging
import random
from data.mock.mock_core_builder import BaseTopologyGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

class UITestingTopologyGenerator(BaseTopologyGenerator):
    def inject_ui_anomalies(self, topology_nodes):
        logger.info("[UI Testing] Injecting precisely 2 loops, 3 VLAN mismatches, and 2 rogue devices...")
        
        all_dists = topology_nodes.get("dist", [])
        all_access = topology_nodes.get("access", [])
        all_hosts = topology_nodes.get("endpoint", [])

        if not all_access or not all_hosts or len(all_access) < 2:
            logger.error("Topology too small to inject UI anomalies.")
            return

        # 1. Inject exactly 2 loops (STP / Parallel links)
        for i in range(2):
            acc1 = random.choice(all_access)
            acc2 = random.choice(all_access)
            # Create a parallel link between two access switches (or same switch for parallel loops)
            self._connect_devices(acc1.id, acc2.id)
            logger.info(f"  -> Injected Loop {i+1} between {acc1.name} and {acc2.name}")

        # 2. Inject exactly 3 VLAN mismatches
        for i in range(3):
            host = random.choice(all_hosts)
            # Find the interface on the host and change its VLAN to 999
            interfaces = list(self.nb.dcim.interfaces.filter(device_id=host.id))
            if interfaces:
                interf = interfaces[0]
                interf.untagged_vlan = self.vlan_anomaly.id
                interf.save()
                logger.info(f"  -> Injected VLAN Mismatch {i+1} on {host.name} ({interf.name} -> VLAN 999)")

        # 3. Inject exactly 2 Rogue Devices
        # Vector 1: Unauthorized Hub connected to an access switch
        rogue1_name = "ROGUE-001"
        acc_target = random.choice(all_access)
        target_site_id = acc_target.site.id if getattr(acc_target, 'site', None) else self.sites[0].id
        
        rogue1 = self._get_or_create_device(rogue1_name, self.switch_type.id, self.role_unknown.id, target_site_id)
        self._connect_devices(rogue1.id, acc_target.id)
        # Connect some fake hosts to the rogue hub
        for h_idx in range(3):
            fake_host = self._get_or_create_device(f"FAKE-HOST-1-{h_idx}", self.host_type.id, self.role_endpoint.id, target_site_id)
            self._connect_devices(rogue1.id, fake_host.id)
        logger.info(f"  -> Injected Rogue 1 ({rogue1_name}) acting as unauthorized hub off {acc_target.name}")

        # Vector 2: Distribution Bypass (connected to access and dist)
        rogue2_name = "ROGUE-002"
        acc_target2 = random.choice(all_access)
        dist_target = random.choice(all_dists)
        target_site_id2 = acc_target2.site.id if getattr(acc_target2, 'site', None) else self.sites[0].id
        
        rogue2 = self._get_or_create_device(rogue2_name, self.switch_type.id, self.role_unknown.id, target_site_id2)
        self._connect_devices(rogue2.id, acc_target2.id)
        self._connect_devices(rogue2.id, dist_target.id)
        logger.info(f"  -> Injected Rogue 2 ({rogue2_name}) bypassing from {acc_target2.name} to {dist_target.name}")

        logger.info("[UI Testing] Successfully injected all UI anomalies.")

def main():
    logger.info("==================================================")
    logger.info("   INITIALIZING UI TESTING TOPOLOGY (k=6)         ")
    logger.info("==================================================")
    
    # k=6, num_sites=1 creates around ~259 standard devices
    generator = UITestingTopologyGenerator(k=6, num_sites=1)
    
    # 1. Clear old data
    generator.clear_old_topology()
    
    # Clear Neo4j completely as well to ensure a totally fresh start
    logger.info("[Purge Engine] Wiping Neo4j Database for a clean slate...")
    from neo4j import GraphDatabase
    from config.settings import neo4j_config
    try:
        driver = GraphDatabase.driver(neo4j_config.NEO4J_URI, auth=(neo4j_config.NEO4J_USER, neo4j_config.NEO4J_PASSWORD))
        with driver.session() as session:
            session.run("MATCH (n) DETACH DELETE n")
            session.run("CALL apoc.schema.assert({}, {}, true) YIELD label RETURN label")
        driver.close()
        logger.info("[Purge Engine] Neo4j cleared successfully.")
    except Exception as e:
        logger.error(f"[Purge Engine] Failed to clear Neo4j: {e}")
    logger.info("")
    
    # 2. Build the standard k=6 topology
    topology_nodes = generator.generate_compliance_topology()
    
    # 3. Inject precisely the requested anomalies
    generator.inject_ui_anomalies(topology_nodes)
    
    logger.info("\n==================================================")
    logger.info("   UI MOCK INJECTION COMPLETED SUCCESSFULLY       ")
    logger.info("==================================================")

if __name__ == "__main__":
    main()
