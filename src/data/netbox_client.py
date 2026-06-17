import pynetbox
from typing import Any, Dict, List, Optional

from config.settings import netbox_config


def _vlan_record(vlan_obj: Any) -> Optional[Dict[str, Any]]:
    if not vlan_obj:
        return None
    return {"vid": vlan_obj.vid, "name": vlan_obj.name}


class NetBoxClient:
    def __init__(self):
        self.nb = pynetbox.api(
            netbox_config.NETBOX_URL,
            token=netbox_config.NETBOX_API_TOKEN,
        )

    def fetch_all_devices(self) -> List[Dict[str, Any]]:
        try:
            devices = self.nb.dcim.devices.all()
            cleaned_devices = []

            for device in devices:
                role_obj = getattr(device, "role", None)
                role_name = role_obj.name if role_obj else None

                type_obj = getattr(device, "device_type", None)
                manufacturer_obj = getattr(type_obj, "manufacturer", None) if type_obj else None
                vendor_name = manufacturer_obj.name if manufacturer_obj else None
                model_name = type_obj.model if type_obj else None

                site_obj = getattr(device, "site", None)
                site_name = site_obj.name if site_obj else None

                rack_obj = getattr(device, "rack", None)
                rack_name = rack_obj.name if rack_obj else None

                ip_obj = getattr(device, "primary_ip", None)
                primary_ip = ip_obj.address if ip_obj else None

                cleaned_devices.append(
                    {
                        "id": device.id,
                        "name": device.name,
                        "model": model_name,
                        "vendor": vendor_name,
                        "role": role_name,
                        "site": site_name,
                        "rack": rack_name,
                        "manufacturer": vendor_name,
                        "primary_ip": primary_ip,
                        "status": device.status.value if device.status else None,
                    }
                )
            return cleaned_devices

        except Exception as exc:
            print(f"[Error] Get error when getting device list:: {exc}")
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
                    a_interface_id = a_term.object.id

                    b_device = b_term.object.device.name
                    b_interface = b_term.object.name
                    b_interface_id = b_term.object.id

                    cleaned_cables.append(
                        {
                            "cable_id": cable.id,
                            "source_device": a_device,
                            "source_interface": a_interface,
                            "source_interface_id": a_interface_id,
                            "target_device": b_device,
                            "target_interface": b_interface,
                            "target_interface_id": b_interface_id,
                            "status": cable.status.value if cable.status else None,
                        }
                    )

                except StopIteration:
                    continue
                except AttributeError:
                    continue

            return cleaned_cables

        except Exception as exc:
            print(f"[Error] Get error when getting cable list: {exc}")
            return []

    def fetch_all_interfaces_vlan(self) -> List[Dict[str, Any]]:
        try:
            interfaces = self.nb.dcim.interfaces.all()
            cleaned_interfaces = []

            for interface in interfaces:
                mode_value = interface.mode.value if interface.mode else None
                untagged_vlan = _vlan_record(getattr(interface, "untagged_vlan", None))
                tagged_vlans = [
                    record
                    for vlan in getattr(interface, "tagged_vlans", []) or []
                    if (record := _vlan_record(vlan))
                ]

                vlan_id = None
                if untagged_vlan:
                    vlan_id = untagged_vlan["vid"]
                elif tagged_vlans:
                    vlan_id = tagged_vlans[0]["vid"]

                cleaned_interfaces.append(
                    {
                        "id": interface.id,
                        "name": interface.name,
                        "mac_address": interface.mac_address or None,
                        "mode": mode_value,
                        "device_id": interface.device.id if interface.device else None,
                        "device_name": interface.device.name if interface.device else None,
                        "interface_name": interface.name,
                        "untagged_vlan": untagged_vlan,
                        "tagged_vlans": tagged_vlans,
                        "vlan_id": vlan_id,
                    }
                )
            return cleaned_interfaces

        except Exception as exc:
            print(f"[Error] Get error when getting interface list: {exc}")
            return []


if __name__ == "__main__":
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
