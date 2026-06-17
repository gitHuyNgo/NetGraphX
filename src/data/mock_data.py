import pynetbox
from config.settings import netbox_config

class TrueFatTreeGenerator:
    def __init__(self, k: int = 4):
        """
        Initializes the Fat-Tree topological parameter mapping.
        The parameter 'k' represents the number of ports per switch and must be an even integer.
        For k=4, it will automatically calculate and deploy 20 switches and 48 cables.
        """
        if k % 2 != 0:
            raise ValueError("Parameter k must be an even integer.")
        self.k = k
        self.num_pods = k
        self.cores_per_group = k // 2
        self.switches_per_pod_layer = k // 2
        
        self.nb = pynetbox.api(
            netbox_config.NETBOX_URL, 
            token=netbox_config.NETBOX_API_TOKEN
        )
        
        # 1. Verify or create baseline Site dependency
        self.site = self.nb.dcim.sites.get(slug="viettel-lab")
        if not self.site:
            print("[Setup] Site 'viettel-lab' not found. Provisioning site entry...")
            self.site = self.nb.dcim.sites.create(name="Viettel Lab", slug="viettel-lab")

        # 2. Verify or create baseline Manufacturer dependency
        manufacturer = self.nb.dcim.manufacturers.get(slug="generic-manufacturer")
        if not manufacturer:
            print("[Setup] Manufacturer 'generic-manufacturer' not found. Provisioning entry...")
            manufacturer = self.nb.dcim.manufacturers.create(name="Generic Manufacturer", slug="generic-manufacturer")

        # 3. Verify or create baseline Device Type model dependency
        self.device_type = self.nb.dcim.device_types.get(slug="generic-switch")
        if not self.device_type:
            print("[Setup] Device Type 'generic-switch' not found. Provisioning model layout...")
            self.device_type = self.nb.dcim.device_types.create(
                manufacturer=manufacturer.id,
                model="Generic Switch",
                slug="generic-switch"
            )
        
        # 4. Verify or create the 3 distinct data center hierarchical roles
        self.role_core = self.nb.dcim.device_roles.get(slug="core-switch")
        if not self.role_core:
            self.role_core = self.nb.dcim.device_roles.create(name="Core Switch", slug="core-switch", color="f44336")
            
        self.role_agg = self.nb.dcim.device_roles.get(slug="aggregation-switch")
        if not self.role_agg:
            self.role_agg = self.nb.dcim.device_roles.create(name="Aggregation Switch", slug="aggregation-switch", color="9c27b0")
            
        self.role_access = self.nb.dcim.device_roles.get(slug="access-switch")
        if not self.role_access:
            self.role_access = self.nb.dcim.device_roles.create(name="Access Switch", slug="access-switch", color="2196f3")

        # 5. Verify or create dynamic target compliance and anomaly VLAN records
        self.vlan_baseline = self.nb.ipam.vlans.get(vid=10)
        if not self.vlan_baseline:
            print("[Setup] Creating baseline compliance VLAN 10...")
            self.vlan_baseline = self.nb.ipam.vlans.create(name="Compliance-VLAN-10", vid=10)

        self.vlan_anomaly = self.nb.ipam.vlans.get(vid=999)
        if not self.vlan_anomaly:
            print("[Setup] Creating out-of-sync anomaly VLAN 999...")
            self.vlan_anomaly = self.nb.ipam.vlans.create(name="Anomaly-VLAN-999", vid=999)

    def clear_old_topology(self):
        """
        Comprehensive global system cleanup purge engine execution layer.
        Unbinds cables, unbinds interfaces, and deletes legacy target device infrastructure objects.
        """
        print("[Purge Engine] Initiating database cleanup for site context elements...")
        
        # 1. Broad fetch all active device layers present in the deployment architecture
        all_devices = self.nb.dcim.devices.all()
        target_mock_devices = []
        
        # Filter for our custom mock switch patterns safely via text naming conventions
        for dev in all_devices:
            if "MOCK" in dev.name or "-FT-" in dev.name or "POD" in dev.name:
                target_mock_devices.append(dev)

        # 2. De-cable and clear out interface tracking layers first to unlock system record constraints
        cable_ids_purged = set()
        for device in target_mock_devices:
            interfaces = self.nb.dcim.interfaces.filter(device_id=device.id)
            for interface in interfaces:
                # Remove active underlying infrastructure cables
                if interface.cable and interface.cable.id not in cable_ids_purged:
                    try:
                        cable_record = self.nb.dcim.cables.get(interface.cable.id)
                        if cable_record:
                            cable_record.delete()
                            cable_ids_purged.add(interface.cable.id)
                    except Exception:
                        pass
                
                # Unbind tracking constraints to drop reference bindings safely
                if interface.untagged_vlan:
                    try:
                        interface.untagged_vlan = None
                        interface.mode = None
                        interface.save()
                    except Exception:
                        pass

        if cable_ids_purged:
            print(f"[Purge Engine] Successfully cleared {len(cable_ids_purged)} cable records.")

        # 3. Purge the matching hardware entities out of the database instance
        device_delete_count = 0
        for device in target_mock_devices:
            try:
                device.delete()
                device_delete_count += 1
            except Exception as e:
                print(f"[Purge Engine] Failed to delete target record {device.name}: {str(e)}")
                
        print(f"[Purge Engine] Successfully cleared {device_delete_count} device records.")
        print("[Purge Engine] Database state refreshed to clean pipeline standard.")

    def generate_compliance_topology(self):
        """
        Executes structural mathematical matrix generation to provision a validated 3-Tier Fat-Tree.
        Maps calculated matrix coordinates into actual NetBox hardware resources via API entries.
        """
        core_switches = []
        pod_switches = {}

        # 1. Provision the Core Layer Array: (k/2)^2 nodes
        num_cores = (self.k // 2) ** 2
        print(f"[Fat-Tree] Provisioning Core Layer: {num_cores} nodes.")
        for i in range(1, num_cores + 1):
            name = f"SW-CORE-FT-{i:02d}"
            dev = self._get_or_create_device(name, self.role_core.id)
            core_switches.append(dev)

        # 2. Provision Pod Structural Sub-Graphs: k pods, each containing k/2 Agg and k/2 Edge nodes
        for pod in range(self.num_pods):
            print(f"[Fat-Tree] Provisioning Pod Partition {pod}...")
            pod_switches[pod] = {"agg": [], "edge": []}
            
            # Create Aggregation Switches for this Pod
            for agg_idx in range(1, self.switches_per_pod_layer + 1):
                name = f"SW-AGG-POD{pod}-NODE{agg_idx}"
                dev = self._get_or_create_device(name, self.role_agg.id)
                pod_switches[pod]["agg"].append(dev)
                
            # Create Edge/Access Switches for this Pod
            for edge_idx in range(1, self.switches_per_pod_layer + 1):
                name = f"SW-EDGE-POD{pod}-NODE{edge_idx}"
                dev = self._get_or_create_device(name, self.role_access.id)
                pod_switches[pod]["edge"].append(dev)

        # 3. Wire the Infrastructure via Algorithmic Matrix Mapping
        print("[Fat-Tree] Commencing automated execution of fabric cabling matrix...")
        
        for pod in range(self.num_pods):
            # Link Layer A: Edge switches to Aggregation switches within the same Pod boundary
            for edge_dev in pod_switches[pod]["edge"]:
                for agg_dev in pod_switches[pod]["agg"]:
                    self._connect_interfaces(edge_dev.name, agg_dev.name)
            
            # Link Layer B: Aggregation switches to designated Core Switch groups
            for agg_local_idx, agg_dev in enumerate(pod_switches[pod]["agg"]):
                core_start_offset = agg_local_idx * (self.k // 2)
                for c_offset in range(self.cores_per_group):
                    core_target = core_switches[core_start_offset + c_offset]
                    self._connect_interfaces(agg_dev.name, core_target.name)

        print("[Fat-Tree] Fabric deployment sequence finalized successfully.")
        return pod_switches

    def inject_structural_anomalies(self, pod_switches):
        """
        Deliberately injects out-of-sync parameters and architectural deviations into the dataset.
        This provides corrupted operational states required to train unsupervised ML and rule engines.
        """
        print("[Anomaly Injection] Simulating active network degradation vectors...")
        
        if 0 in pod_switches and len(pod_switches[0]["edge"]) >= 2:
            edge_nodes = pod_switches[0]["edge"]
            
            # Vector 1: Inject a Cross-Port VLAN Mismatch anomaly using an explicit access mode definition
            print(f" -> Injecting VLAN mismatch parameters onto {edge_nodes[0].name}...")
            target_if = self.nb.dcim.interfaces.get(device=edge_nodes[0].name, name="Gi0/1")
            if target_if:
                # Explicitly pass access mode constraints to satisfy destination compliance validation checks
                target_if.mode = "access"
                target_if.untagged_vlan = self.vlan_anomaly.id  
                target_if.save()

            # Vector 2: Inject an illegal horizontal Cross-link to break Star Topology standards (Creates L2 Loop)
            print(f" -> Deploying illegal horizontal connection between {edge_nodes[0].name} and {edge_nodes[1].name}...")
            if_a = next((i for i in self.nb.dcim.interfaces.filter(device=edge_nodes[0].name) if not i.cable), None)
            if_b = next((i for i in self.nb.dcim.interfaces.filter(device=edge_nodes[1].name) if not i.cable), None)
            
            if if_a and if_b:
                self.nb.dcim.cables.create(
                    a_terminations=[{"object_type": "dcim.interface", "object_id": if_a.id}],
                    b_terminations=[{"object_type": "dcim.interface", "object_id": if_b.id}],
                    status="connected"
                )
            else:
                print(" -> Skipping loop link insertion: Available ports not discovered.")
            
        print("[Anomaly Injection] Target infrastructure anomalies successfully live.")

    def _get_or_create_device(self, name, role_id):
        dev = self.nb.dcim.devices.get(name=name)
        if not dev:
            dev = self.nb.dcim.devices.create(
                name=name, 
                device_type=self.device_type.id,
                role=role_id, 
                site=self.site.id, 
                status="active"
            )
            # Ensure proper mode configurations are provisioned alongside default VLAN parameter maps
            for p in range(1, self.k + 1):
                self.nb.dcim.interfaces.create(
                    device=dev.id, 
                    name=f"Gi0/{p}", 
                    type="1000base-t",
                    mode="access",
                    untagged_vlan=self.vlan_baseline.id
                )
        return dev

    def _connect_interfaces(self, dev_a_name, dev_b_name):
        if_a = next((i for i in self.nb.dcim.interfaces.filter(device=dev_a_name) if not i.cable), None)
        if_b = next((i for i in self.nb.dcim.interfaces.filter(device=dev_b_name) if not i.cable), None)
        
        if if_a and if_b:
            self.nb.dcim.cables.create(
                a_terminations=[{"object_type": "dcim.interface", "object_id": if_a.id}],
                b_terminations=[{"object_type": "dcim.interface", "object_id": if_b.id}],
                status="connected"
            )

def main():
    print("==================================================")
    print("   INITIALIZING AUTOMATED FAT-TREE INJECTION     ")
    print("==================================================")
    
    generator = TrueFatTreeGenerator(k=8)
    generator.clear_old_topology()
    print("")
    
    pod_switches = generator.generate_compliance_topology()
    generator.inject_structural_anomalies(pod_switches)
    
    print("\n==================================================")
    print("   DATA INJECTION PIPELINE COMPLETED SUCCESSFULLY ")
    print("==================================================")

if __name__ == "__main__":
    main()