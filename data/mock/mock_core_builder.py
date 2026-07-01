import pynetbox
import logging
import requests
from config.settings import netbox_config

logger = logging.getLogger(__name__)

class BaseTopologyGenerator:
    def __init__(self, k: int = 2, num_sites: int = 4):
        self.k = k
        self.num_sites = num_sites
        self.nb = pynetbox.api(
            netbox_config.NETBOX_URL, 
            token=netbox_config.NETBOX_API_TOKEN
        )
        
        # 1. Sites
        self.sites = []
        for i in range(1, self.num_sites + 1):
            site_slug = f"viettel-lab-site-{i}"
            site = self.nb.dcim.sites.get(slug=site_slug)
            if not site:
                site = self.nb.dcim.sites.create(name=f"Viettel Lab Site {i}", slug=site_slug)
            self.sites.append(site)

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
        self.role_unknown = self._get_or_create_role("Unknown", "unknown", "9e9e9e")

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
        logger.info("[Purge Engine] Initiating database cleanup for mock devices...")
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
                if getattr(interface, "cable", None) and interface.cable.id not in cable_ids_purged:
                    try:
                        cable_record = self.nb.dcim.cables.get(interface.cable.id)
                        if cable_record:
                            cable_record.delete()
                            cable_ids_purged.add(interface.cable.id)
                    except (pynetbox.core.query.RequestError, requests.exceptions.RequestException):
                        pass
                
                if getattr(interface, "untagged_vlan", None):
                    try:
                        interface.untagged_vlan = None
                        interface.mode = None
                        interface.save()
                    except (pynetbox.core.query.RequestError, requests.exceptions.RequestException):
                        pass

        if cable_ids_purged:
            logger.info(f"[Purge Engine] Successfully cleared {len(cable_ids_purged)} cable records.")

        device_delete_count = 0
        for device in target_mock_devices:
            try:
                device.delete()
                device_delete_count += 1
            except (pynetbox.core.query.RequestError, requests.exceptions.RequestException) as e:
                logger.error(f"[Purge Engine] Failed to delete target record {device.name}: {str(e)}")
                
        logger.info(f"[Purge Engine] Successfully cleared {device_delete_count} device records.")

    def _get_or_create_device(self, name, device_type_id, role_id, site_id):
        dev = self.nb.dcim.devices.get(name=name)
        if not dev:
            dev = self.nb.dcim.devices.create(
                name=name, 
                device_type=device_type_id,
                role=role_id, 
                site=site_id, 
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

    def generate_compliance_topology(self):
        logger.info(f"[Campus Star] Generating hierarchy with fanout k={self.k} across {self.num_sites} sites...")
        
        endpoint_nodes = []
        access_nodes = []
        dist_nodes = []
        core_nodes = []
        dist_count, acc_count, host_count = 0, 0, 0
        
        for s_idx, site in enumerate(self.sites):
            core = self._get_or_create_device(f"SW-CORE-SITE{s_idx+1}", self.switch_type.id, self.role_core.id, site.id)
            core_nodes.append(core)
            
            for d in range(1, self.k + 1):
                dist_count += 1
                dist_name = f"SW-DIST-{dist_count}"
                dist = self._get_or_create_device(dist_name, self.switch_type.id, self.role_dist.id, site.id)
                dist_nodes.append(dist)
                self._connect_devices(core.id, dist.id)
                
                for a in range(1, self.k + 1):
                    acc_count += 1
                    acc_name = f"SW-ACC-{acc_count}"
                    acc = self._get_or_create_device(acc_name, self.switch_type.id, self.role_access.id, site.id)
                    access_nodes.append(acc)
                    self._connect_devices(dist.id, acc.id)
                    
                    for h in range(1, self.k + 1):
                        host_count += 1
                        host_name = f"HOST-{host_count}"
                        host = self._get_or_create_device(host_name, self.host_type.id, self.role_endpoint.id, site.id)
                        endpoint_nodes.append(host)
                        self._connect_devices(acc.id, host.id)

        logger.info(f"[Campus Star] Fabric deployed: {self.num_sites} Cores, {dist_count} Dist, {acc_count} Access, {host_count} Endpoints.")
        return {"core": core_nodes, "dist": dist_nodes, "access": access_nodes, "endpoint": endpoint_nodes}
