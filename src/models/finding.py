from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class AffectedLink:
    source: str
    target: str
    cable_id: Optional[int] = None
    source_interface: Optional[str] = None
    target_interface: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Finding:
    type: str
    severity: str
    affected_nodes: List[str]
    description: str
    affected_links: List[AffectedLink] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "type": self.type,
            "severity": self.severity,
            "affected_nodes": self.affected_nodes,
            "affected_links": [link.to_dict() for link in self.affected_links],
            "description": self.description,
        }
