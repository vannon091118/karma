"""
Agent Runtime Kernel — Self-Improvement Controller

The top-level controller for autonomous self-improvement.

This is NOT a daemon. It is a deterministic, testable controller.
The Scheduler decides when to call `run()`.
The Controller decides what to do within a run.

Architecture:
    SelfImprovementController
        │
        ├── TrainingLoop           (cycle orchestration)
        ├── NeedsEngine            (initiative)
        ├── RewardModel            (evaluation)
        └── PatternLearner         (memory)

Safety contract:
    1. Every improvement must be logged BEFORE execution.
    2. Every improvement must be scored AFTER execution.
    3. Improvements with score < SAFETY_THRESHOLD are rolled back (where possible).
    4. The controller never modifies skills or code autonomously.
       It only: writes facts, records gaps, flags stale data, adjusts weights.
    5. A human-review queue holds all proposed skill/code changes.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from llm_middleware.core.persistence import PersistenceLayer
from llm_middleware.ml.training_loop import TrainingLoop, CycleResult
from llm_middleware.ml.needs_engine import NeedsEngine, NeedPriority
from llm_middleware.ml.reward_model import RewardModel
from llm_middleware.ml.pattern_learner import PatternLearner


# ─── Run Summary ─────────────────────────────────────────────────────────────

@dataclass
class ImprovementRunSummary:
    """Summary of a full self-improvement run (may span multiple cycles)."""
    run_id: str
    project: str
    cycles_run: int
    total_needs_found: int
    total_needs_resolved: int
    total_needs_escalated: int
    total_improvements: int
    avg_reward: Optional[float]
    trend: str          # "improving", "stable", "degrading", "insufficient_data"
    duration_seconds: float
    cycles: List[Dict[str, Any]] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "project": self.project,
            "cycles_run": self.cycles_run,
            "total_needs_found": self.total_needs_found,
            "total_needs_resolved": self.total_needs_resolved,
            "total_needs_escalated": self.total_needs_escalated,
            "total_improvements": self.total_improvements,
            "avg_reward": self.avg_reward,
            "trend": self.trend,
            "duration_seconds": round(self.duration_seconds, 2),
            "timestamp": self.timestamp,
        }


# ─── Controller ──────────────────────────────────────────────────────────────

class SelfImprovementController:
    """
    Orchestrates self-improvement runs.

    Usage:
        controller = SelfImprovementController(persistence, "my-project")
        summary = controller.run(cycles=3)
        print(summary.trend)

    The controller keeps a short history of cycle rewards to compute a trend.
    If the trend is "degrading" (rewards consistently falling), it stops early
    and surfaces a CRITICAL Need for human review.
    """

    SAFETY_THRESHOLD     = 0.20   # Rewards below this → something is wrong
    TREND_WINDOW         = 5      # Number of cycles for trend analysis
    MAX_CYCLES           = 10     # Hard cap per run

    def __init__(
        self,
        persistence: PersistenceLayer,
        project: str,
        dry_run: bool = False,
    ) -> None:
        self.persistence = persistence
        self.project = project
        self.dry_run = dry_run
        self.training_loop = TrainingLoop(persistence, project, dry_run)
        self.needs_engine = NeedsEngine(persistence, project)
        self.reward_model = RewardModel(persistence, project)
        self.pattern_learner = PatternLearner(persistence, project)

    def run(self, cycles: int = 1) -> ImprovementRunSummary:
        """
        Run N improvement cycles.
        Stops early if:
            - No Needs found (system is clean)
            - Rewards are consistently degrading (safety stop)
            - Hard cap reached
        """
        import uuid
        run_id = str(uuid.uuid4())[:10]
        start = time.monotonic()

        cycles = min(cycles, self.MAX_CYCLES)
        cycle_results: List[CycleResult] = []
        recent_rewards: List[float] = []

        for i in range(cycles):
            result = self.training_loop.run_cycle()
            cycle_results.append(result)

            if result.avg_reward is not None:
                recent_rewards.append(result.avg_reward)

            # Early stop: no Needs
            if result.needs_found == 0 and i > 0:
                break

            # Early stop: safety — degrading or persistently low rewards
            if len(recent_rewards) >= 3:
                trend = self._compute_trend(recent_rewards[-3:])
                window = recent_rewards[-3:]
                below_threshold = all(r < self.SAFETY_THRESHOLD for r in window)
                if trend in ("degrading", "stable") and below_threshold:
                    # Surface a CRITICAL need for human attention
                    from llm_middleware.ml.needs_engine import Need
                    import hashlib
                    need_id = hashlib.sha256(f"safety:{run_id}:{i}".encode()).hexdigest()[:16]
                    avg_window = sum(window) / len(window)
                    emergency = Need(
                        need_id=need_id,
                        project=self.project,
                        category="runtime",
                        description=(
                            f"Self-improvement loop {trend} with persistently low rewards "
                            f"(avg {avg_window:.2f} < {self.SAFETY_THRESHOLD}). "
                            "Human review required."
                        ),
                        priority=NeedPriority.CRITICAL,
                        source="self_improvement.safety_stop",
                        evidence={
                            "run_id": run_id,
                            "cycle": i,
                            "trend": trend,
                            "recent_rewards": recent_rewards[-5:],
                        },
                        motivation=1.0,
                    )
                    self.needs_engine._persist(emergency)
                    break


        # Aggregate
        total = len(cycle_results)
        total_needs_found     = sum(r.needs_found for r in cycle_results)
        total_needs_resolved  = sum(r.needs_resolved for r in cycle_results)
        total_needs_escalated = sum(r.needs_escalated for r in cycle_results)
        total_improvements    = sum(r.needs_addressed for r in cycle_results)
        all_rewards           = [r for r in recent_rewards if r is not None]
        avg_reward            = round(sum(all_rewards) / len(all_rewards), 4) if all_rewards else None
        trend                 = self._compute_trend(all_rewards) if len(all_rewards) >= 2 else "insufficient_data"
        duration              = time.monotonic() - start

        summary = ImprovementRunSummary(
            run_id=run_id,
            project=self.project,
            cycles_run=total,
            total_needs_found=total_needs_found,
            total_needs_resolved=total_needs_resolved,
            total_needs_escalated=total_needs_escalated,
            total_improvements=total_improvements,
            avg_reward=avg_reward,
            trend=trend,
            duration_seconds=duration,
            cycles=[r.to_dict() for r in cycle_results],
        )

        # Persist run summary
        if not self.dry_run:
            self.persistence.emit_event(
                event_type="improvement.applied",
                project=self.project,
                payload=summary.to_dict(),
                correlation_id=run_id,
            )

        return summary

    def status(self) -> Dict[str, Any]:
        """Return a full status snapshot of the ML system."""
        needs_stats    = self.needs_engine.stats()
        pattern_stats  = self.pattern_learner.stats()
        avg_reward     = self.reward_model.average_score(last_n=20)
        trend_data     = [r["score"] for r in self.persistence.fetchall(
            "SELECT score FROM rewards WHERE project = ? ORDER BY scored_at DESC LIMIT 10",
            (self.project,)
        )]

        return {
            "project": self.project,
            "needs": needs_stats,
            "patterns": pattern_stats,
            "reward": {
                "avg_last_20": avg_reward,
                "trend": self._compute_trend(list(reversed(trend_data))) if len(trend_data) >= 2 else "insufficient_data",
            },
            "top_patterns": self.pattern_learner.top_patterns(5),
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def simulate(self, cycles: int = 1) -> ImprovementRunSummary:
        """Dry-run simulation — no writes."""
        old = self.dry_run
        self.dry_run = True
        self.training_loop.dry_run = True
        try:
            return self.run(cycles)
        finally:
            self.dry_run = old
            self.training_loop.dry_run = old

    # ─── Reflection ───────────────────────────────────────────────────────

    def reflect(self) -> Dict[str, Any]:
        """
        Post-run reflection. Answers:
        - What worked? (high-reward patterns)
        - What failed? (deprecated patterns)
        - What was wasted? (high usage, low reward)
        - What Needs are persistent?
        """
        top = self.pattern_learner.top_patterns(10)
        deprecated_rows = self.persistence.fetchall(
            "SELECT * FROM patterns WHERE project = ? AND status = 'deprecated' ORDER BY updated_at DESC LIMIT 10",
            (self.project,)
        )
        persistent_needs = self.needs_engine.get_active_needs(priority=NeedPriority.CRITICAL)

        wasted = [
            p for p in top
            if p["usage_count"] > 3 and p.get("score", 1.0) < 0.4
        ]

        reflection = {
            "what_worked": [
                {"task": p["task_signature"][:60], "skill": p["skill_used"], "weight": p["weight"]}
                for p in top[:5]
            ],
            "what_failed": [
                {"task": dict(r)["task_signature"][:60], "skill": dict(r)["skill_used"]}
                for r in deprecated_rows[:5]
            ],
            "what_was_wasted": [
                {"task": p["task_signature"][:60], "usage": p["usage_count"], "score": p.get("score")}
                for p in wasted
            ],
            "persistent_critical_needs": [
                {"description": n.description[:80], "source": n.source}
                for n in persistent_needs
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

        # Persist reflection
        self.persistence.emit_event(
            event_type="reflection.done",
            project=self.project,
            payload=reflection,
        )

        return reflection

    # ─── Trend Analysis ───────────────────────────────────────────────────

    @staticmethod
    def _compute_trend(rewards: List[float]) -> str:
        """
        Simple linear trend from reward sequence.
        Returns: "improving", "stable", "degrading", "insufficient_data"
        """
        if len(rewards) < 2:
            return "insufficient_data"

        # Simple slope: compare first half vs second half
        mid = len(rewards) // 2
        first_half = sum(rewards[:mid]) / mid
        second_half = sum(rewards[mid:]) / (len(rewards) - mid)
        delta = second_half - first_half

        if delta > 0.05:
            return "improving"
        elif delta < -0.05:
            return "degrading"
        else:
            return "stable"
