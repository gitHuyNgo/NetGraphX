import logging
from typing import Any, Dict, List, Optional
import requests

from config.settings import netbox_config

logger = logging.getLogger(__name__)

class NetBoxClient:
    def __init__(self):
        self.graphql_url = f"{netbox_config.NETBOX_URL.rstrip('/')}/graphql/"
        self.headers = {
            "Authorization": f"Token {netbox_config.NETBOX_API_TOKEN}",
            "Content-Type": "application/json"
        }

    def _execute_graphql(self, query: str, list_name: str) -> List[Dict[str, Any]]:
        """
        Executes a GraphQL query with pagination for a specific list (e.g. device_list).
        Returns all accumulated items.
        """
        limit = 1000
        offset = 0
        all_results = []
        
        while True:
            # We inject the pagination arguments directly into the query string for simplicity
            # assuming the caller formats the query with {limit} and {offset}
            paginated_query = query.replace("{limit}", str(limit)).replace("{offset}", str(offset))
            
            try:
                response = requests.post(
                    self.graphql_url,
                    headers=self.headers,
                    json={"query": paginated_query},
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                
                if "errors" in data:
                    logger.error(f"[GraphQL Error] {data['errors']}")
                    break
                    
                items = data.get("data", {}).get(list_name, [])
                if not items:
                    break
                    
                all_results.extend(items)
                
                if len(items) < limit:
                    break # Reached the last page
                    
                offset += limit
                
            except requests.exceptions.RequestException as exc:
                logger.error(f"[Error] GraphQL request failed: {exc}")
                break
                
        return all_results

    def fetch_all_devices(self) -> List[Dict[str, Any]]:
        query = """
        query {
          device_list(pagination: {limit: {limit}, offset: {offset}}) {
            id
            name
            status
            primary_ip4 { address }
            role { name }
            site { name }
            rack { name }
            device_type { 
              model 
              manufacturer { name } 
            }
          }
        }
        """
        raw_devices = self._execute_graphql(query, "device_list")
        cleaned_devices = []
        
        for dev in raw_devices:
            role_name = dev.get("role", {}).get("name") if dev.get("role") else None
            site_name = dev.get("site", {}).get("name") if dev.get("site") else None
            rack_name = dev.get("rack", {}).get("name") if dev.get("rack") else None
            primary_ip = dev.get("primary_ip4", {}).get("address") if dev.get("primary_ip4") else None
            
            device_type = dev.get("device_type") or {}
            model_name = device_type.get("model")
            vendor_name = device_type.get("manufacturer", {}).get("name") if device_type.get("manufacturer") else None
            
            cleaned_devices.append({
                "id": dev["id"],
                "name": dev["name"],
                "model": model_name,
                "vendor": vendor_name,
                "role": role_name,
                "site": site_name,
                "rack": rack_name,
                "manufacturer": vendor_name,
                "primary_ip": primary_ip,
                "status": dev["status"]
            })
            
        return cleaned_devices

    def fetch_all_cables(self) -> List[Dict[str, Any]]:
        query = """
        query {
          cable_list(pagination: {limit: {limit}, offset: {offset}}) {
            id
            status
            a_terminations { 
              ... on InterfaceType { id name device { name } } 
            }
            b_terminations { 
              ... on InterfaceType { id name device { name } } 
            }
          }
        }
        """
        raw_cables = self._execute_graphql(query, "cable_list")
        cleaned_cables = []
        
        for cable in raw_cables:
            a_terms = cable.get("a_terminations") or []
            b_terms = cable.get("b_terminations") or []
            
            if not a_terms or not b_terms:
                continue
                
            a_term = a_terms[0]
            b_term = b_terms[0]
            
            # Skip if termination is not an Interface (e.g. empty dict or missing device)
            if not a_term or "device" not in a_term or not b_term or "device" not in b_term:
                continue
                
            a_device = a_term["device"]["name"] if a_term["device"] else None
            a_interface = a_term["name"]
            a_interface_id = a_term["id"]
            
            b_device = b_term["device"]["name"] if b_term["device"] else None
            b_interface = b_term["name"]
            b_interface_id = b_term["id"]
            
            if not a_device or not b_device:
                continue
            
            cleaned_cables.append({
                "cable_id": cable["id"],
                "source_device": a_device,
                "source_interface": a_interface,
                "source_interface_id": a_interface_id,
                "target_device": b_device,
                "target_interface": b_interface,
                "target_interface_id": b_interface_id,
                "status": cable["status"]
            })
            
        return cleaned_cables

    def fetch_all_interfaces_vlan(self) -> List[Dict[str, Any]]:
        query = """
        query {
          interface_list(pagination: {limit: {limit}, offset: {offset}}) {
            id
            name
            mac_addresses { mac_address }
            mode
            device { id name }
            untagged_vlan { vid name }
            tagged_vlans { vid name }
          }
        }
        """
        raw_interfaces = self._execute_graphql(query, "interface_list")
        cleaned_interfaces = []
        
        def _vlan_record(vlan_dict):
            if not vlan_dict:
                return None
            return {"vid": vlan_dict.get("vid"), "name": vlan_dict.get("name")}
        
        for interface in raw_interfaces:
            mode_value = interface.get("mode")
            untagged_vlan = _vlan_record(interface.get("untagged_vlan"))
            
            tagged_vlans = []
            if interface.get("tagged_vlans"):
                for vlan in interface["tagged_vlans"]:
                    record = _vlan_record(vlan)
                    if record:
                        tagged_vlans.append(record)
            
            vlan_id = None
            if untagged_vlan:
                vlan_id = untagged_vlan["vid"]
            elif tagged_vlans:
                vlan_id = tagged_vlans[0]["vid"]
                
            device = interface.get("device") or {}
            
            macs = interface.get("mac_addresses") or []
            mac_addr = macs[0].get("mac_address") if macs else None
            
            cleaned_interfaces.append({
                "id": interface["id"],
                "name": interface["name"],
                "mac_address": mac_addr,
                "mode": mode_value,
                "device_id": device.get("id"),
                "device_name": device.get("name"),
                "interface_name": interface["name"],
                "untagged_vlan": untagged_vlan,
                "tagged_vlans": tagged_vlans,
                "vlan_id": vlan_id
            })
            
        return cleaned_interfaces


if __name__ == "__main__":
    client = NetBoxClient()

    logger.setLevel(logging.INFO)
    logging.basicConfig(level=logging.INFO)

    logger.info("\n[1] Extracting Devices list...")
    devices_data = client.fetch_all_devices()
    logger.info(f"Found {len(devices_data)} devices.")
    if devices_data:
        logger.info(f"First device sample: {devices_data[0]}")

    logger.info("\n[2] Extracting Cables list...")
    cables_data = client.fetch_all_cables()
    logger.info(f"Found {len(cables_data)} cables.")
    if cables_data:
        logger.info(f"First cable sample: {cables_data[0]}")

    logger.info("\n[3] Extracting Interface/VLAN list...")
    interfaces_data = client.fetch_all_interfaces_vlan()
    logger.info(f"Found {len(interfaces_data)} interfaces.")
    if interfaces_data:
        logger.info(f"First interface sample: {interfaces_data[0]}")
