"""
Base interface for website and form detectors.
"""
from abc import ABC, abstractmethod
import hashlib
from typing import Dict, Any, Optional, Tuple
from src.models import CheckResult, TargetConfig


class BaseDetector(ABC):
    """Abstract base class for all target-specific detectors."""

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
        """
        Analyzes the fetched HTML content and URL state.
        Returns a CheckResult indicating if an alert should be dispatched.
        """
        pass

    @staticmethod
    def calculate_hash(content: str) -> str:
        """Calculates a SHA-256 hash of the cleaned text."""
        return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()
