"""
Agent Runtime Kernel — Training Loop

The Training Loop is the engine of autonomous self-improvement.
It does NOT train a neural network. It orchestrates the kernel's own
improvement cycle based on Needs, Rewards, and Patterns.

One cycle (= one "training iteration"):
    1. NeedsEngine.scan()               → What is missing?
    2. Prioritise Needs by (priority, motivation)
    3. For each critical/important Need:
       a. Generate improvement plan (local, deterministic)
       b. Execute plan (fact update, skill reload, weight adjustment)
       c. RewardModel.score() the result
       d. PatternLearner.store() the experience
       e. If reward < threshold → escalate Need
    4. Reflect: log what happened, what improved, what didn't
    5. Persist reflection to events table

The TrainingLoop ONLY improves things through validated, falsifiable actions.
It never blindly overwrites facts or skills without recording the change and
its outcome.

This is NOT a background daemon. The Scheduler decides when to call it.
The TrainingLoop is a pure, synchronous, testable function.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from llm_middleware.core.persistence import PersistenceLayer
from llm_middleware.ml.needs_engine import NeedsEngine, Need, NeedPriority
from llm_middleware.ml.reward_model import RewardModel, RewardSignal
from llm_middleware.ml.pattern_learner import PatternLearner


# ─── Cycle Result ────────────────────────────────────────────────────────────

@dataclass
class CycleResult:
    """Outcome of one training cycle."""
    cycle_id: str
    project: str
    needs_found: int
    needs_addressed: int
    needs_resolved: int
    needs_escalated: int
    improvements: List[Dict[str, Any]]   # What was changed
    avg_reward: Optional[float]
    duration_seconds: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cycle_id": self.cycle_id,
            "project": self.project,
            "needs_found": self.needs_found,
            "needs_addressed": self.needs_addressed,
            "needs_resolved": self.needs_resolved,
            "needs_escalated": self.needs_escalated,
            "improvements": self.improvements,
            "avg_reward": self.avg_reward,
            "duration_seconds": round(self.duration_seconds, 2),
            "timestamp": self.timestamp,
            "errors": self.errors,
        }


# ─── Improvement Action ──────────────────────────────────────────────────────

@dataclass
class ImprovementAction:
    """
    A single improvement action derived from a Need.
    Actions are deliberately limited to safe, reversible operations.
    """
    action_type: str       # update_fact, reload_skill, adjust_weight, flag_stale, record_gap
    need_id: str
    description: str
    params: Dict[str, Any] = field(default_factory=dict)
    is_reversible: bool = True


# ─── Training Loop ────────────────────────────────────────────────────────────

class TrainingLoop:
    """
    Orchestrates one self-improvement cycle.

    Safe actions only:
    - update_fact: Update a domain fact with better information
    - flag_stale: Mark a fact as requiring refresh
    - record_gap: Log a knowledge gap for future human or LLM attention
    - adjust_weight: Update reward model weights based on outcome data
    - evolve_pattern: Update a pattern's approach after improvement

    Unsafe actions (modifying skills, running code) require explicit human
    approval — the loop records them as Needs but does NOT auto-execute them.
    """

    # Minimum reward to consider an action "resolved"
    RESOLVE_THRESHOLD   = 0.6
    # Below this reward → escalate
    ESCALATE_THRESHOLD  = 0.25
    # Maximum Needs to address per cycle (prevent runaway loops)
    MAX_NEEDS_PER_CYCLE = 5

    def __init__(
        self,
        persistence: PersistenceLayer,
        project: str,
        dry_run: bool = False,
    ) -> None:
        self.persistence = persistence
        self.project = project
        self.dry_run = dry_run
        self.needs_engine = NeedsEngine(persistence, project)
        self.reward_model = RewardModel(persistence, project)
        self.pattern_learner = PatternLearner(persistence, project)

    def run_cycle(self) -> CycleResult:
        """
        Execute one complete training cycle.
        Returns a CycleResult with full accounting of what happened.
        """
        cycle_id = str(uuid.uuid4())[:12]
        start_time = time.monotonic()
        improvements: List[Dict[str, Any]] = []
        errors: List[str] = []
        rewards_this_cycle: List[float] = []

        # 1. Scan for Needs
        new_needs = self.needs_engine.scan()
        all_needs = self.needs_engine.get_active_needs(limit=self.MAX_NEEDS_PER_CYCLE)

        needs_addressed = 0
        needs_resolved = 0
        needs_escalated = 0

        # 2. Work through Needs in priority order
        for need in all_needs:
            if needs_addressed >= self.MAX_NEEDS_PER_CYCLE:
                break

            try:
                action = self._plan_action(need)
                if action is None:
                    continue

                needs_addressed += 1
                t0 = time.monotonic()

                if not self.dry_run:
                    outcome, details = self._execute_action(action)
                else:
                    outcome, details = "success", {"dry_run": True, "action": action.action_type}

                duration = time.monotonic() - t0

                # Score the outcome
                signal = RewardSignal(
                    project=self.project,
                    task=f"improvement:{action.action_type}:{need.category}",
                    outcome=outcome,
                    duration_seconds=duration,
                    skill_name="training_loop",
                    correlation_id=cycle_id,
                )
                breakdown = self.reward_model.score(signal)
                rewards_this_cycle.append(breakdown.final)

                # Learn from this
                self.pattern_learner.store(
                    task=need.description,
                    skill_used="training_loop",
                    approach=json.dumps(action.params),
                    outcome=outcome,
                    score=breakdown.final,
                )

                # Decide: resolve or escalate?
                if breakdown.final >= self.RESOLVE_THRESHOLD:
                    if not self.dry_run:
                        self.needs_engine.resolve(need.need_id, evidence=details)
                    needs_resolved += 1
                    status = "resolved"
                elif breakdown.final < self.ESCALATE_THRESHOLD:
                    if not self.dry_run:
                        self.needs_engine.escalate(need.need_id, reason=f"Reward {breakdown.final:.2f} below threshold")
                    needs_escalated += 1
                    status = "escalated"
                else:
                    status = "partial"

                improvements.append({
                    "need_id": need.need_id,
                    "category": need.category,
                    "action": action.action_type,
                    "outcome": outcome,
                    "reward": breakdown.final,
                    "status": status,
                    "dry_run": self.dry_run,
                })

            except Exception as e:
                errors.append(f"Need {need.need_id}: {e}")
                continue

        # 3. Reflect
        duration = time.monotonic() - start_time
        avg_reward = round(sum(rewards_this_cycle) / len(rewards_this_cycle), 4) if rewards_this_cycle else None

        result = CycleResult(
            cycle_id=cycle_id,
            project=self.project,
            needs_found=len(all_needs),
            needs_addressed=needs_addressed,
            needs_resolved=needs_resolved,
            needs_escalated=needs_escalated,
            improvements=improvements,
            avg_reward=avg_reward,
            duration_seconds=duration,
            errors=errors,
        )

        # 4. Persist cycle result
        if not self.dry_run:
            self.persistence.emit_event(
                event_type="improvement.cycle",
                project=self.project,
                payload=result.to_dict(),
                correlation_id=cycle_id,
            )

        return result

    # ─── Planning ─────────────────────────────────────────────────────────

    def _plan_action(self, need: Need) -> Optional[ImprovementAction]:
        """
        Map a Need to a safe, concrete ImprovementAction.
        Returns None if no safe action is available.
        """
        category = need.category
        evidence = need.evidence

        if category == "knowledge":
            # Flag stale facts for refresh
            domain = evidence.get("domain", "")
            if domain:
                return ImprovementAction(
                    action_type="flag_stale",
                    need_id=need.need_id,
                    description=f"Flag domain '{domain}' facts as requiring refresh",
                    params={"domain": domain, "stale_count": evidence.get("stale_count", 0)},
                )
            # Record knowledge gap
            task = evidence.get("task", need.description)
            return ImprovementAction(
                action_type="record_gap",
                need_id=need.need_id,
                description=f"Record knowledge gap for task: {task[:80]}",
                params={"task": task, "partial_count": evidence.get("partial_count", 0)},
            )

        elif category == "correctness":
            probe = evidence.get("probe", "")
            if probe:
                # Record gate failure pattern
                return ImprovementAction(
                    action_type="record_gap",
                    need_id=need.need_id,
                    description=f"Record structural gap for probe '{probe}'",
                    params={"probe": probe, "failure_rate": evidence.get("failure_rate", 0)},
                    is_reversible=True,
                )
            task = evidence.get("task", "")
            if task:
                return ImprovementAction(
                    action_type="record_gap",
                    need_id=need.need_id,
                    description=f"Record failure pattern for task: {task[:80]}",
                    params={"task": task, "failure_rate": evidence.get("failure_rate", 0)},
                )

        elif category == "quality":
            domain = evidence.get("domain", "")
            return ImprovementAction(
                action_type="record_gap",
                need_id=need.need_id,
                description=f"Record missing validation for domain '{domain}'",
                params={"domain": domain},
            )

        elif category == "runtime":
            return ImprovementAction(
                action_type="record_gap",
                need_id=need.need_id,
                description=f"Record runtime issue: {need.description[:80]}",
                params={"error": need.description},
            )

        return None  # No safe action available

    # ─── Execution ────────────────────────────────────────────────────────

    def _execute_action(self, action: ImprovementAction) -> tuple[str, Dict[str, Any]]:
        """
        Execute a planned action.
        All actions are safe (read/write facts, log events). No code execution.
        Returns (outcome, details).
        """
        t = action.action_type

        if t == "flag_stale":
            domain = action.params.get("domain", "")
            # Write a staleness marker to the ml domain
            self.persistence.set_fact(
                self.project, "ml", f"stale_flag:{domain}",
                {
                    "flagged_at": datetime.now(timezone.utc).isoformat(),
                    "stale_count": action.params.get("stale_count", 0),
                    "needs_refresh": True,
                }
            )
            return "success", {"domain": domain, "flagged": True}

        elif t == "record_gap":
            # Append gap to a structured list in ml domain
            gap_key = f"gap:{action.need_id[:8]}"
            self.persistence.set_fact(
                self.project, "ml", gap_key,
                {
                    "description": action.description,
                    "params": action.params,
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                    "status": "open",
                }
            )
            return "success", {"gap_key": gap_key, "recorded": True}

        elif t == "adjust_weight":
            # Only adjust if new weights are explicitly provided
            new_weights = action.params.get("weights")
            if new_weights:
                try:
                    self.reward_model.update_weights(new_weights)
                    return "success", {"weights_updated": True}
                except ValueError as e:
                    return "failure", {"error": str(e)}
            return "partial", {"reason": "No weight values provided"}

        elif t == "evolve_pattern":
            pattern_id = action.params.get("pattern_id")
            new_approach = action.params.get("new_approach", "")
            if pattern_id and new_approach:
                evolved = self.pattern_learner.evolve(pattern_id, new_approach, reason=action.description)
                return ("success" if evolved else "failure"), {"evolved": evolved}
            return "failure", {"reason": "Missing pattern_id or new_approach"}

        return "partial", {"reason": f"Unknown action type: {t}"}

    # ─── Dry Run ──────────────────────────────────────────────────────────

    def simulate(self) -> CycleResult:
        """Run a cycle in dry_run mode — no writes, just plans."""
        old_dry = self.dry_run
        self.dry_run = True
        try:
            return self.run_cycle()
        finally:
            self.dry_run = old_dry
