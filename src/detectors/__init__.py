"""
Detectors package initialization.
"""
from src.detectors.base import BaseDetector
from src.detectors.google_forms import GoogleFormsDetector
from src.detectors.hops_detector import HopsDetector
from src.detectors.best_opp_web import BestOpportunityWebDetector
from src.detectors.concordia import ConcordiaDetector

__all__ = [
    "BaseDetector",
    "GoogleFormsDetector",
    "HopsDetector",
    "BestOpportunityWebDetector",
    "ConcordiaDetector",
]
