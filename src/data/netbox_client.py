import pynetbox
from typing import List, Dict, Any
from config.settings import netbox_config


class NetBoxClient:
    def __init__(self):
        self.nb = pynetbox.api(
            netbox_config.NETBOX_URL,
            token=netbox_config.NETBOX_API_TOKEN
        )
    
    def fetch_all_devices(self) -> List[Dict[str, Any]]:
        try:
            devices = self.nb.dcim.devices.all()
            cleaned_devices = []
            
            for device in devices:
                role_obj = getattr(device, "role", None)
                role_name = role_obj.name if role_obj else "Unknown"
                
                type_obj = getattr(device, "device_type", None)
                manufacturer_obj = getattr(type_obj, "manufacturer", None) if type_obj else None
                manufacturer_name = manufacturer_obj.name if manufacturer_obj else "Unknown"
                
                ip_obj = getattr(device, "primary_ip", None)
                primary_ip = ip_obj.address if ip_obj else "None"

                cleaned_devices.append({
                    "id": device.id,
                    "name": device.name,
                    "role": role_name,
                    "manufacturer": manufacturer_name,
                    "primary_ip": primary_ip,
                    "status": device.status.value if device.status else "Unknown"
                })
            return cleaned_devices
            
        except Exception as e:
            print(f"[Error] Get error when getting device list:: {str(e)}")
            return []

    def fetch_all_cables(self) -> List[Dict[str, Any]]:
        try:
            cables = self.nb.dcim.cables.all()
            cleaned_cables = []

            for cable in cables:
                try:
                    a_term = next(iter(cable.a_terminations))
                    b_term = next(iter(cable.b_terminations))

                    a_device = a_term.object.device.name
                    a_interface = a_term.object.name

                    b_device = b_term.object.device.name
                    b_interface = b_term.object.name

                    cleaned_cables.append({
                        "cable_id": cable.id,
                        "source_device": a_device,
                        "source_interface": a_interface,
                        "target_device": b_device,
                        "target_interface": b_interface,
                        "status": cable.status.value if cable.status else "Unknown"
                    })

                except StopIteration:
                    continue
                except AttributeError:
                    continue

            return cleaned_cables

        except Exception as e:
            print(f"[Error] Get error when getting cable list: {str(e)}")
            return []
    
    def fetch_all_interfaces_vlan(self) -> List[Dict[str, Any]]:
        try:
            interfaces = self.nb.dcim.interfaces.all()
            cleaned_interfaces = []

            for interface in interfaces:
                vlan_id = None
                if interface.untagged_vlan:
                    vlan_id = interface.untagged_vlan.vid
                elif interface.tagged_vlans:
                    first_vlan = next(iter(interface.tagged_vlans), None)
                    vlan_id = first_vlan.vid if first_vlan else None

                cleaned_interfaces.append({
                    "device_name": interface.device.name if interface.device else "Unknown",
                    "interface_name": interface.name,
                    "mode": interface.mode.value if interface.mode else "None",
                    "vlan_id": vlan_id
                })
            return cleaned_interfaces

        except Exception as e:
            print(f"[Error] Get error when getting interface list: {str(e)}")
            return []
        
if __name__ == '__main__':
    client = NetBoxClient()

    print("\n[1] Extracting Devices list...")
    devices_data = client.fetch_all_devices()
    print(f"Found {len(devices_data)} devices.")
    if devices_data:
        print("First device sample:", devices_data[0])

    print("\n[2] Extracting Cables list...")
    cables_data = client.fetch_all_cables()
    print(f"Found {len(cables_data)} cables.")
    if cables_data:
        print("First cable sample:", cables_data[0])

    print("\n[3] Extracting Interface/VLAN list...")
    interfaces_data = client.fetch_all_interfaces_vlan()
    print(f"Found {len(interfaces_data)} interfaces.")
    if interfaces_data:
        print("First interface sample:", interfaces_data[0])