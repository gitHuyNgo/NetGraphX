from dataclasses import dataclass
from typing import Any, Dict, List, TYPE_CHECKING

if TYPE_CHECKING:
    from src.data.netbox_client import NetBoxClient


@dataclass
class TopologyData:
    """Normalized topology snapshot collected once from NetBox."""

    devices: List[Dict[str, Any]]
    cables: List[Dict[str, Any]]
    interfaces: List[Dict[str, Any]]

    @classmethod
    def from_netbox(cls, client: "NetBoxClient") -> "TopologyData":
        return cls(
            devices=client.fetch_all_devices(),
            cables=client.fetch_all_cables(),
            interfaces=client.fetch_all_interfaces_vlan(),
        )

    @property
    def is_valid(self) -> bool:
        return bool(self.devices and self.cables)
