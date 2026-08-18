from abc import ABC, abstractmethod
import hashlib
from typing import Dict, Any, Optional
from src.models import CheckResult, TargetConfig


class BaseDetector(ABC):
    def __init__(self, target: TargetConfig):
        self.target = target

    @abstractmethod
    async def analyze(
        self,
        html: str,
        final_url: str,
        status_code: int,
        previous_state: Optional[Dict[str, Any]] = None
    ) -> CheckResult:
        pass

    @staticmethod
    def calculate_hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
