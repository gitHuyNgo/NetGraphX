import pynetbox
from config.settings import netbox_config

class CampusStarTopologyGenerator:
    def __init__(self, k: int = 2):
        """
        Initializes the Campus Star Topology.
        The parameter 'k' represents the fanout scale for the hierarchy.
        For k=2: 1 Core, 2 Dist, 4 Access, 8 Endpoints = 15 total devices.
        """
        self.k = k
        self.nb = pynetbox.api(
            netbox_config.NETBOX_URL, 
            token=netbox_config.NETBOX_API_TOKEN
        )
        
        # 1. Site
        self.site = self.nb.dcim.sites.get(slug="viettel-lab")
        if not self.site:
            self.site = self.nb.dcim.sites.create(name="Viettel Lab", slug="viettel-lab")

        # 2. Manufacturer
        manufacturer = self.nb.dcim.manufacturers.get(slug="generic-manufacturer")
        if not manufacturer:
            manufacturer = self.nb.dcim.manufacturers.create(name="Generic Manufacturer", slug="generic-manufacturer")

        # 3. Device Types
        self.switch_type = self.nb.dcim.device_types.get(slug="generic-switch")
        if not self.switch_type:
            self.switch_type = self.nb.dcim.device_types.create(
                manufacturer=manufacturer.id, model="Generic Switch", slug="generic-switch"
            )
            
        self.host_type = self.nb.dcim.device_types.get(slug="generic-host")
        if not self.host_type:
            self.host_type = self.nb.dcim.device_types.create(
                manufacturer=manufacturer.id, model="Generic Host", slug="generic-host"
            )

        # 4. Roles
        self.role_core = self._get_or_create_role("Core Switch", "core-switch", "f44336")
        self.role_dist = self._get_or_create_role("Distribution Switch", "distribution-switch", "ff9800")
        self.role_access = self._get_or_create_role("Access Switch", "access-switch", "2196f3")
        self.role_endpoint = self._get_or_create_role("Endpoint", "endpoint", "4caf50")

        # 5. VLANs
        self.vlan_baseline = self.nb.ipam.vlans.get(vid=10)
        if not self.vlan_baseline:
            self.vlan_baseline = self.nb.ipam.vlans.create(name="Compliance-VLAN-10", vid=10)

        self.vlan_anomaly = self.nb.ipam.vlans.get(vid=999)
        if not self.vlan_anomaly:
            self.vlan_anomaly = self.nb.ipam.vlans.create(name="Anomaly-VLAN-999", vid=999)

    def _get_or_create_role(self, name, slug, color):
        role = self.nb.dcim.device_roles.get(slug=slug)
        if not role:
            role = self.nb.dcim.device_roles.create(name=name, slug=slug, color=color)
        return role

    def clear_old_topology(self):
        print("[Purge Engine] Initiating database cleanup for mock devices...")
        all_devices = self.nb.dcim.devices.all()
        target_mock_devices = [
            dev for dev in all_devices 
            if "MOCK" in dev.name or "-FT-" in dev.name or "POD" in dev.name 
            or "SW-CORE-" in dev.name or "SW-DIST-" in dev.name or "SW-ACC-" in dev.name or "HOST-" in dev.name
        ]
        
        cable_ids_purged = set()
        for device in target_mock_devices:
            interfaces = self.nb.dcim.interfaces.filter(device_id=device.id)
            for interface in interfaces:
                if interface.cable and interface.cable.id not in cable_ids_purged:
                    try:
                        cable_record = self.nb.dcim.cables.get(interface.cable.id)
                        if cable_record:
                            cable_record.delete()
                            cable_ids_purged.add(interface.cable.id)
                    except Exception:
                        pass
                
                if interface.untagged_vlan:
                    try:
                        interface.untagged_vlan = None
                        interface.mode = None
                        interface.save()
                    except Exception:
                        pass

        if cable_ids_purged:
            print(f"[Purge Engine] Successfully cleared {len(cable_ids_purged)} cable records.")

        device_delete_count = 0
        for device in target_mock_devices:
            try:
                device.delete()
                device_delete_count += 1
            except Exception as e:
                print(f"[Purge Engine] Failed to delete target record {device.name}: {str(e)}")
                
        print(f"[Purge Engine] Successfully cleared {device_delete_count} device records.")

    def generate_compliance_topology(self):
        print(f"[Campus Star] Generating hierarchy with fanout k={self.k}...")
        
        # 1. Core
        core = self._get_or_create_device("SW-CORE-1", self.switch_type.id, self.role_core.id)
        
        # 2. Distribution, Access, Endpoints
        endpoint_nodes = []
        access_nodes = []
        
        dist_count = 0
        acc_count = 0
        host_count = 0
        
        for d in range(1, self.k + 1):
            dist_count += 1
            dist_name = f"SW-DIST-{dist_count}"
            dist = self._get_or_create_device(dist_name, self.switch_type.id, self.role_dist.id)
            self._connect_devices(core.id, dist.id)
            
            for a in range(1, self.k + 1):
                acc_count += 1
                acc_name = f"SW-ACC-{acc_count}"
                acc = self._get_or_create_device(acc_name, self.switch_type.id, self.role_access.id)
                access_nodes.append(acc)
                self._connect_devices(dist.id, acc.id)
                
                for h in range(1, self.k + 1):
                    host_count += 1
                    host_name = f"HOST-{host_count}"
                    host = self._get_or_create_device(host_name, self.host_type.id, self.role_endpoint.id)
                    endpoint_nodes.append(host)
                    self._connect_devices(acc.id, host.id)

        print(f"[Campus Star] Fabric deployed: 1 Core, {dist_count} Dist, {acc_count} Access, {host_count} Endpoints.")
        return {"access": access_nodes, "endpoint": endpoint_nodes}

    def inject_structural_anomalies(self, layers):
        print("[Anomaly Injection] Simulating active network degradation vectors...")
        
        # Vector 1: VLAN Mismatch (anomaly on an endpoint port)
        if layers["endpoint"]:
            host = layers["endpoint"][0]
            print(f" -> Injecting VLAN mismatch on link to {host.name}...")
            # The interface on the access switch connected to this host
            host_ifs = list(self.nb.dcim.interfaces.filter(device_id=host.id))
            if host_ifs and host_ifs[0].cable:
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
            print(f" -> Deploying illegal horizontal connection between {acc1.name} and {acc2.name}...")
            self._connect_devices(acc1.id, acc2.id)

        print("[Anomaly Injection] Anomalies successfully injected.")

    def _get_or_create_device(self, name, device_type_id, role_id):
        dev = self.nb.dcim.devices.get(name=name)
        if not dev:
            dev = self.nb.dcim.devices.create(
                name=name, 
                device_type=device_type_id,
                role=role_id, 
                site=self.site.id, 
                status="active"
            )
        return dev

    def _connect_devices(self, dev_a_id, dev_b_id):
        """Dynamically creates interfaces and connects them."""
        dev_a = self.nb.dcim.devices.get(dev_a_id)
        dev_b = self.nb.dcim.devices.get(dev_b_id)
        
        ifs_a = list(self.nb.dcim.interfaces.filter(device_id=dev_a_id))
        ifs_b = list(self.nb.dcim.interfaces.filter(device_id=dev_b_id))
        
        idx_a = len(ifs_a) + 1
        idx_b = len(ifs_b) + 1
        
        if_a = self.nb.dcim.interfaces.create(
            device=dev_a_id, name=f"Gi0/{idx_a}", type="1000base-t",
            mode="access", untagged_vlan=self.vlan_baseline.id
        )
        if_b = self.nb.dcim.interfaces.create(
            device=dev_b_id, name=f"Gi0/{idx_b}", type="1000base-t",
            mode="access", untagged_vlan=self.vlan_baseline.id
        )
        
        self.nb.dcim.cables.create(
            a_terminations=[{"object_type": "dcim.interface", "object_id": if_a.id}],
            b_terminations=[{"object_type": "dcim.interface", "object_id": if_b.id}],
            status="connected"
        )

def main():
    print("==================================================")
    print("   INITIALIZING CAMPUS STAR TOPOLOGY INJECTION    ")
    print("==================================================")
    
    generator = CampusStarTopologyGenerator(k=6)
    generator.clear_old_topology()
    print("")
    
    layers = generator.generate_compliance_topology()
    generator.inject_structural_anomalies(layers)
    
    print("\n==================================================")
    print("   DATA INJECTION PIPELINE COMPLETED SUCCESSFULLY ")
    print("==================================================")

if __name__ == "__main__":
    main()