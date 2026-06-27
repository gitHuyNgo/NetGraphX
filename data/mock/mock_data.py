import logging
from data.mock.mock_core_builder import BaseTopologyGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

class CampusStarTopologyGenerator(BaseTopologyGenerator):
    def inject_structural_anomalies(self, layers):
        logger.info("[Anomaly Injection] Simulating active network degradation vectors...")
        
        # Vector 1: VLAN Mismatch (anomaly on an endpoint port)
        if layers["endpoint"]:
            host = layers["endpoint"][0]
            logger.info(f" -> Injecting VLAN mismatch on link to {host.name}...")
            # The interface on the access switch connected to this host
            host_ifs = list(self.nb.dcim.interfaces.filter(device_id=host.id))
            if host_ifs and getattr(host_ifs[0], "cable", None):
                cable_id = host_ifs[0].cable.id
                cable = self.nb.dcim.cables.get(cable_id)
                if cable:
                    term_a = cable.a_terminations[0]
                    term_b = cable.b_terminations[0]
                    target_if_id = term_a.object_id if term_b.object_id == host_ifs[0].id else term_b.object_id
                    
                    target_if = self.nb.dcim.interfaces.get(target_if_id)
                    if target_if:
                        target_if.mode = "access"
                        target_if.untagged_vlan = self.vlan_anomaly.id  
                        target_if.save()

        # Vector 2: L2 Loop (horizontal link between two access switches)
        if len(layers["access"]) >= 2:
            acc1 = layers["access"][0]
            acc2 = layers["access"][1]
            logger.info(f" -> Deploying illegal horizontal connection between {acc1.name} and {acc2.name}...")
            self._connect_devices(acc1.id, acc2.id)

        logger.info("[Anomaly Injection] Anomalies successfully injected.")

def main():
    logger.info("==================================================")
    logger.info("   INITIALIZING CAMPUS STAR TOPOLOGY INJECTION    ")
    logger.info("==================================================")
    
    generator = CampusStarTopologyGenerator(k=6)
    generator.clear_old_topology()
    logger.info("")
    
    layers = generator.generate_compliance_topology()
    generator.inject_structural_anomalies(layers)
    
    logger.info("\n==================================================")
    logger.info("   DATA INJECTION PIPELINE COMPLETED SUCCESSFULLY ")
    logger.info("==================================================")

if __name__ == "__main__":
    main()