from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from typing import Dict, List, Optional


class TargetType(str, Enum):
    GOOGLE_FORM = "GOOGLE_FORM"
    BEST_OPP_WEB = "BEST_OPP_WEB"
    HOPS_INSTRUCTIONS = "HOPS_INSTRUCTIONS"
    CONCORDIA_WEB = "CONCORDIA_WEB"


class FormStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    UNKNOWN = "UNKNOWN"


@dataclass
class CheckResult:
    target_id: str
    target_name: str
    url: str
    is_open: bool
    status_changed: bool
    previous_state: Optional[str]
    current_state: str
    summary: str
    details: str
    detected_links: List[str] = field(default_factory=list)
    html_hash: str = ""
    screenshot_path: Optional[str] = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    error: Optional[str] = None


@dataclass
class TargetConfig:
    id: str
    name: str
    url: str
    target_type: TargetType
    enabled: bool = True
    custom_headers: Dict[str, str] = field(default_factory=dict)
