"""
AlertIQ Triage Engine — Milestone 2.

Scores AML alerts by SAR probability using a histogram gradient-boosted
classifier (sklearn HistGradientBoostingClassifier — same algorithm as
LightGBM's histogram-based GBDT) trained on the 24 observable features
produced by the Milestone 1 simulation engine.

Public API:
    from alertiq.triage import TriageConfig, AlertDataset, BaselineScorer, TriageScorer, Evaluator
"""

from .config import TriageConfig
from .dataset import AlertDataset
from .baseline import BaselineScorer
from .scorer import TriageScorer
from .evaluator import Evaluator

__all__ = [
    "TriageConfig",
    "AlertDataset",
    "BaselineScorer",
    "TriageScorer",
    "Evaluator",
]
