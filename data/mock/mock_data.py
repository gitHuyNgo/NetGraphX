import logging
from data.mock.mock_core_builder import BaseTopologyGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

class CampusStarTopologyGenerator(BaseTopologyGenerator):
    
    def _create_vlan_mismatch(self, dev1_name: str, dev2_name: str):
        logger.info(f" -> Injecting VLAN mismatch between {dev1_name} and {dev2_name}...")
        dev1 = self.nb.dcim.devices.get(name=dev1_name)
        dev2 = self.nb.dcim.devices.get(name=dev2_name)
        if not dev1 or not dev2:
            logger.warning(f"    Missing {dev1_name} or {dev2_name}")
            return
            
        # Find the cable connecting them
        dev1_ifs = self.nb.dcim.interfaces.filter(device_id=dev1.id)
        target_if = None
        for interface in dev1_ifs:
            if getattr(interface, "cable", None):
                cable = self.nb.dcim.cables.get(interface.cable.id)
                term_a = getattr(cable, "a_terminations", [])
                term_b = getattr(cable, "b_terminations", [])
                
                # Check if it connects to dev2
                connects_to_dev2 = False
                for t in (term_a + term_b):
                    if t.object_type == "dcim.interface":
                        peer_if = self.nb.dcim.interfaces.get(t.object_id)
                        if peer_if and peer_if.device.id == dev2.id:
                            connects_to_dev2 = True
                            target_if = peer_if # We mismatch the dev2 side
                            break
                if connects_to_dev2:
                    break
        
        if target_if:
            target_if.mode = "access"
            target_if.untagged_vlan = self.vlan_anomaly.id  
            target_if.save()
            logger.info(f"    Set VLAN {self.vlan_anomaly.vid} on {target_if.name}")

    def _create_loop(self, dev1_name: str, dev2_name: str):
        logger.info(f" -> Deploying illegal horizontal connection between {dev1_name} and {dev2_name}...")
        dev1 = self.nb.dcim.devices.get(name=dev1_name)
        dev2 = self.nb.dcim.devices.get(name=dev2_name)
        if dev1 and dev2:
            self._connect_devices(dev1.id, dev2.id)

    def inject_structural_anomalies(self, layers):
        logger.info("[Anomaly Injection] Simulating active network degradation vectors...")
        
        # 1. Loops
        self._create_loop("SW-ACC-1", "SW-ACC-2")
        self._create_loop("HOST-9", "HOST-10")
        
        # 2. VLAN Mismatches
        self._create_vlan_mismatch("SW-ACC-2", "HOST-7")
        self._create_vlan_mismatch("SW-DIST-4", "SW-ACC-3")
        
        # 3. Rogue and Fake Nodes
        # (Omitted per user request for this step)
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