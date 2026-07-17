"""
Agent Runtime Kernel — Replay Engine

"Unser System kann erklären, warum es gelernt hat."

The Replay Engine iterates over the immutable Experience Store and re-evaluates
historical data using the *latest* RewardModel and PatternLearner rules.
This allows the system to recalculate its Knowledge Graph and Pattern weights
entirely from scratch when grading policies change.
"""

from typing import Any, Dict
from datetime import datetime, timezone
import json

from karma.core.persistence import PersistenceLayer
from karma.ml.experience_store import Experience, ExperienceStore
from karma.ml.reward_model import RewardModel, RewardSignal
from karma.ml.pattern_learner import PatternLearner
from karma.ml.knowledge_graph import KnowledgeGraph


class ReplayEngine:
    def __init__(self, persistence: PersistenceLayer, project: str):
        self.persistence = persistence
        self.project = project

    def replay_all(self) -> Dict[str, Any]:
        """
        Re-evaluate all historical experiences for the current project.
        Re-builds pattern weights from scratch using current reward weights.
        """
        # 1. Fetch all experiences (ordered by creation to simulate time forward)
        rows = self.persistence.fetchall(
            "SELECT * FROM experiences WHERE project = ? ORDER BY created_at ASC",
            (self.project,)
        )
        
        # 2. Reset the PatternLearner and KnowledgeGraph for this project (truncate derived views)
        with self.persistence.transaction() as conn:
            conn.execute("DELETE FROM patterns WHERE project = ?", (self.project,))
            conn.execute("DELETE FROM kg_edges WHERE project = ?", (self.project,))
            
        rm = RewardModel(self.persistence, self.project)
        pl = PatternLearner(self.persistence, self.project)
        kg = KnowledgeGraph(self.persistence, self.project)
        es = ExperienceStore(self.persistence)

        stats = {
            "experiences_replayed": 0,
            "patterns_generated": 0,
            "successes": 0,
            "failures": 0
        }

        for row in rows:
            # We don't use Experience.from_row here to avoid schema mismatch issues if we changed it.
            # But dict unpacking is close enough:
            d = dict(row)
            
            # Reconstruct the RewardSignal as if it just happened
            signal = RewardSignal(
                project=self.project,
                task=d["task"],
                skill_name=d["prompt_variant_id"].split("-")[0] if "-" in d["prompt_variant_id"] else "unknown",
                outcome="success" if d["gate_passed"] else "failure",
                gate_passed=bool(d["gate_passed"]),
                duration_seconds=d["duration_seconds"],
                extra={
                    "experience_id": d["id"],
                    "variant_id": d["prompt_variant_id"],
                    "failure_type": d["failure_type"],
                    "is_replay": True
                }
            )
            
            # Calculate NEW reward
            breakdown = rm.score(signal)
            
            # Learn NEW pattern
            pattern_record = pl.store(
                task=d["task"],
                skill_used=signal.skill_name,
                approach=f"Prompt variant {d['prompt_variant_id']}",
                outcome=signal.outcome,
                score=breakdown.final,
                metadata={"variant_id": d["prompt_variant_id"], "experience_id": d["id"]},
            )
            
            # Rebuild Knowledge Graph
            kg.update_from_experience(d["id"], breakdown.final)
            
            stats["experiences_replayed"] += 1
            if d["gate_passed"]:
                stats["successes"] += 1
            else:
                stats["failures"] += 1

        stats["patterns_generated"] = len(pl.top_patterns(limit=1000))
        return stats
