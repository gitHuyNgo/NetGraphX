import logging
import random
from data.mock.mock_core_builder import BaseTopologyGenerator

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(message)s")

class MassiveRogueTopologyGenerator(BaseTopologyGenerator):
    def _disconnect_devices(self, dev_a_id, dev_b_id):
        ifs_a = list(self.nb.dcim.interfaces.filter(device_id=dev_a_id))
        for if_a in ifs_a:
            if getattr(if_a, "cable", None):
                cable = self.nb.dcim.cables.get(if_a.cable.id)
                if cable:
                    term_a = cable.a_terminations[0]
                    term_b = cable.b_terminations[0]
                    target_if_id = term_a.object_id if term_b.object_id == if_a.id else term_b.object_id
                    target_if = self.nb.dcim.interfaces.get(target_if_id)
                    if target_if and target_if.device.id == dev_b_id:
                        cable.delete()
                        logger.info(f"Disconnected {dev_a_id} and {dev_b_id}")
                        return

    def inject_random_rogues(self, num_rogues, topology_nodes):
        logger.info(f"[Rogue Injection] Simulating {num_rogues} highly diverse rogue devices...")
        
        # Avoid 'Rogue' role to prevent data leakage. Disguise as normal devices.
        roles = [self.role_unknown.id, self.role_endpoint.id, self.role_access.id]
        
        all_cores = topology_nodes.get("core", [])
        all_dists = topology_nodes.get("dist", [])
        all_access = topology_nodes.get("access", [])
        all_hosts = topology_nodes.get("endpoint", [])

        if not all_access or not all_hosts:
            logger.error("Topology too small to inject rogues.")
            return

        for i in range(1, num_rogues + 1):
            rogue_name = f"ROGUE-{i:03d}"
            chosen_role = random.choice(roles)
            vector = random.randint(1, 5)
            
            if vector == 1:
                # Vector 1: Unauthorized Hub
                acc = random.choice(all_access)
                target_site_id = acc.site.id if getattr(acc, 'site', None) else self.sites[0].id
                rogue = self._get_or_create_device(rogue_name, self.switch_type.id, chosen_role, target_site_id)
                self._connect_devices(rogue.id, acc.id)
                for h_idx in range(random.randint(1, 4)):
                    fake_host = self._get_or_create_device(f"FAKE-HOST-{i}-{h_idx}", self.host_type.id, self.role_endpoint.id, target_site_id)
                    self._connect_devices(rogue.id, fake_host.id)
                    
            elif vector == 2:
                # Vector 2: Parallel Links
                acc = random.choice(all_access)
                target_site_id = acc.site.id if getattr(acc, 'site', None) else self.sites[0].id
                rogue = self._get_or_create_device(rogue_name, self.switch_type.id, chosen_role, target_site_id)
                self._connect_devices(rogue.id, acc.id)
                self._connect_devices(rogue.id, acc.id)
                
            elif vector == 3:
                # Vector 3: Distribution By-pass
                acc = random.choice(all_access)
                dist = random.choice(all_dists) if all_dists else random.choice(all_cores)
                target_site_id = acc.site.id if getattr(acc, 'site', None) else self.sites[0].id
                rogue = self._get_or_create_device(rogue_name, self.switch_type.id, chosen_role, target_site_id)
                self._connect_devices(rogue.id, acc.id)
                self._connect_devices(rogue.id, dist.id)
                
            elif vector == 4:
                # Vector 4: Host Interception
                host = random.choice(all_hosts)
                acc = random.choice(all_access)
                target_site_id = host.site.id if getattr(host, 'site', None) else self.sites[0].id
                rogue = self._get_or_create_device(rogue_name, self.switch_type.id, chosen_role, target_site_id)
                self._connect_devices(rogue.id, host.id)
                self._connect_devices(rogue.id, acc.id)
                
            else:
                # Vector 5: Rogue mesh
                host = random.choice(all_hosts)
                target_site_id = host.site.id if getattr(host, 'site', None) else self.sites[0].id
                rogue = self._get_or_create_device(rogue_name, self.switch_type.id, chosen_role, target_site_id)
                for _ in range(random.randint(2, 4)):
                    h = random.choice(all_hosts)
                    self._connect_devices(rogue.id, h.id)

        logger.info(f"[Rogue Injection] Successfully injected {num_rogues} disguised rogue devices.")

def main():
    logger.info("==================================================")
    logger.info("   INITIALIZING MASSIVE ROGUE TOPOLOGY INJECTION  ")
    logger.info("==================================================")
    
    # Scale up k and num_sites to generate >1000 devices
    generator = MassiveRogueTopologyGenerator(k=6, num_sites=4)
    generator.clear_old_topology()
    logger.info("")
    
    topology_nodes = generator.generate_compliance_topology()
    
    # Inject 25 random rogue devices with diverse attack vectors (approx 2% of ~1250 devices)
    generator.inject_random_rogues(25, topology_nodes)
    
    logger.info("\n==================================================")
    logger.info("   DATA INJECTION PIPELINE COMPLETED SUCCESSFULLY ")
    logger.info("==================================================")

if __name__ == "__main__":
    main()
