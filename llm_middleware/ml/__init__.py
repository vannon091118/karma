"""
Agent Runtime Kernel — ML Layer

Modules:
- needs_engine:      Detects what the system needs (without user input)
- reward_model:      Scores outcomes deterministically (0.0–1.0)
- pattern_learner:   Stores and retrieves experience patterns (SQLite)
- training_loop:     Orchestrates self-improvement cycles
- self_improvement:  Top-level controller — the "brain" of autonomy
"""

from .needs_engine import NeedsEngine, Need, NeedPriority
from .reward_model import RewardModel, RewardSignal
from .pattern_learner import PatternLearner, ExperienceRecord
from .training_loop import TrainingLoop
from .self_improvement import SelfImprovementController

__all__ = [
    "NeedsEngine", "Need", "NeedPriority",
    "RewardModel", "RewardSignal",
    "PatternLearner", "ExperienceRecord",
    "TrainingLoop",
    "SelfImprovementController",
]
