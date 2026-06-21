import pynetbox
import time
from config.settings import netbox_config

class RogueTopologyGenerator:
    def __init__(self, k: int = 6):
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
        self.role_rogue = self._get_or_create_role("Rogue", "rogue", "000000")

        # 5. VLANs
        self.vlan_baseline = self.nb.ipam.vlans.get(vid=10)
        if not self.vlan_baseline:
            self.vlan_baseline = self.nb.ipam.vlans.create(name="Compliance-VLAN-10", vid=10)

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
            or "ROGUE-" in dev.name or "FAKE-HOST-" in dev.name
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
        return if_a, if_b

    def _disconnect_devices(self, dev_a_id, dev_b_id):
        # find the cable connecting dev_a and dev_b and delete it
        ifs_a = list(self.nb.dcim.interfaces.filter(device_id=dev_a_id))
        for if_a in ifs_a:
            if if_a.cable:
                cable = self.nb.dcim.cables.get(if_a.cable.id)
                if cable:
                    term_a = cable.a_terminations[0]
                    term_b = cable.b_terminations[0]
                    target_if_id = term_a.object_id if term_b.object_id == if_a.id else term_b.object_id
                    target_if = self.nb.dcim.interfaces.get(target_if_id)
                    if target_if and target_if.device.id == dev_b_id:
                        cable.delete()
                        print(f"Disconnected {dev_a_id} and {dev_b_id}")
                        return

    def generate_compliance_topology(self):
        print(f"[Campus Star] Generating clean hierarchy with fanout k={self.k}...")
        
        core = self._get_or_create_device("SW-CORE-1", self.switch_type.id, self.role_core.id)
        
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
        return {"core": core, "access": access_nodes, "endpoint": endpoint_nodes}

    def inject_rogues(self):
        print("[Rogue Injection] Simulating rogue devices...")
        
        # ROGUE-01: connect to dist switch 1 and dist switch 2
        r1 = self._get_or_create_device("ROGUE-01", self.switch_type.id, self.role_rogue.id)
        d1 = self.nb.dcim.devices.get(name="SW-DIST-1")
        d2 = self.nb.dcim.devices.get(name="SW-DIST-2")
        self._connect_devices(r1.id, d1.id)
        self._connect_devices(r1.id, d2.id)

        # ROGUE-02: connect to core switch and one random access switch
        r2 = self._get_or_create_device("ROGUE-02", self.switch_type.id, self.role_rogue.id)
        c1 = self.nb.dcim.devices.get(name="SW-CORE-1")
        a1 = self.nb.dcim.devices.get(name="SW-ACC-1")
        self._connect_devices(r2.id, c1.id)
        self._connect_devices(r2.id, a1.id)

        # ROGUE-03: connect to 1 random access switch, create 3 fake endpoints
        r3 = self._get_or_create_device("ROGUE-03", self.switch_type.id, self.role_rogue.id)
        a2 = self.nb.dcim.devices.get(name="SW-ACC-2")
        self._connect_devices(r3.id, a2.id)
        for i in range(1, 4):
            fhost = self._get_or_create_device(f"FAKE-HOST-{i}", self.host_type.id, self.role_endpoint.id)
            self._connect_devices(r3.id, fhost.id)

        # ROGUE-04: unplug 2 connection from endpoints to the linked access switch
        # then connect that 2 endpoints to the ROGUE-04, then connect ROGUE-04 to that access switch
        r4 = self._get_or_create_device("ROGUE-04", self.switch_type.id, self.role_rogue.id)
        a3 = self.nb.dcim.devices.get(name="SW-ACC-3")
        h13 = self.nb.dcim.devices.get(name="HOST-13")
        h14 = self.nb.dcim.devices.get(name="HOST-14")
        self._disconnect_devices(h13.id, a3.id)
        self._disconnect_devices(h14.id, a3.id)
        self._connect_devices(r4.id, h13.id)
        self._connect_devices(r4.id, h14.id)
        self._connect_devices(r4.id, a3.id)

        # ROGUE-05 connect it to 2 different access switch
        r5 = self._get_or_create_device("ROGUE-05", self.switch_type.id, self.role_rogue.id)
        a4 = self.nb.dcim.devices.get(name="SW-ACC-4")
        a5 = self.nb.dcim.devices.get(name="SW-ACC-5")
        self._connect_devices(r5.id, a4.id)
        self._connect_devices(r5.id, a5.id)

        # ROGUE-06: delete the connection from 1 endpoint to access switch then ROGUE-06 will connect to that endpoints and access switch.
        r6 = self._get_or_create_device("ROGUE-06", self.switch_type.id, self.role_rogue.id)
        a6 = self.nb.dcim.devices.get(name="SW-ACC-6")
        h31 = self.nb.dcim.devices.get(name="HOST-31")
        self._disconnect_devices(h31.id, a6.id)
        self._connect_devices(r6.id, h31.id)
        self._connect_devices(r6.id, a6.id)

        # ROGUE-07: connect it with 3 random endpoints
        r7 = self._get_or_create_device("ROGUE-07", self.switch_type.id, self.role_rogue.id)
        h32 = self.nb.dcim.devices.get(name="HOST-32")
        h33 = self.nb.dcim.devices.get(name="HOST-33")
        h34 = self.nb.dcim.devices.get(name="HOST-34")
        self._connect_devices(r7.id, h32.id)
        self._connect_devices(r7.id, h33.id)
        self._connect_devices(r7.id, h34.id)

        # ROGUE-08: connect paralle egdes to 1 access switch
        r8 = self._get_or_create_device("ROGUE-08", self.switch_type.id, self.role_rogue.id)
        a7 = self.nb.dcim.devices.get(name="SW-ACC-7")
        self._connect_devices(r8.id, a7.id)
        self._connect_devices(r8.id, a7.id)

        print("[Rogue Injection] Successfully injected 8 rogue devices and their connections.")


def main():
    print("==================================================")
    print("   INITIALIZING CAMPUS ROGUE TOPOLOGY INJECTION   ")
    print("==================================================")
    
    generator = RogueTopologyGenerator(k=6)
    generator.clear_old_topology()
    print("")
    
    generator.generate_compliance_topology()
    generator.inject_rogues()
    
    print("\n==================================================")
    print("   DATA INJECTION PIPELINE COMPLETED SUCCESSFULLY ")
    print("==================================================")

if __name__ == "__main__":
    main()
