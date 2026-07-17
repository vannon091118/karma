"""
Agent Runtime Kernel — Reward Model

"What gets measured gets improved."

The Reward Model assigns a deterministic score [0.0–1.0] to any kernel
outcome — without calling any external LLM or API.

Scoring inputs (all local):
    - Falsification Gate result (6 probes)
    - Task outcome (success / partial / failure)
    - Execution duration (efficiency signal)
    - Cache hit rate (knowledge reuse signal)
    - Staleness of facts used (knowledge freshness signal)
    - User feedback if explicitly provided (optional)

Score interpretation:
    0.0–0.3   Poor — pattern should be avoided
    0.3–0.6   Mediocre — usable but improvable
    0.6–0.8   Good — worth repeating
    0.8–1.0   Excellent — store as high-weight pattern

The model writes every scored outcome to the `rewards` SQLite table.
The PatternLearner reads this table to decide what to remember.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from karma.core.persistence import PersistenceLayer


# ─── Reward Signal ───────────────────────────────────────────────────────────

@dataclass
class RewardSignal:
    """
    Input to the reward model — raw runtime observations.
    All fields are optional: model scores with what is available.
    """
    project: str
    task: str
    outcome: str                      # success, partial, failure
    gate_passed: Optional[bool] = None
    gate_probe_results: List[Dict[str, Any]] = field(default_factory=list)
    duration_seconds: Optional[float] = None
    cache_hits: int = 0
    cache_misses: int = 0
    facts_used: int = 0
    stale_facts: int = 0              # How many used facts were stale
    user_feedback: Optional[float] = None   # 0.0–1.0 if provided
    skill_name: Optional[str] = None
    correlation_id: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


# ─── Score Components ─────────────────────────────────────────────────────────

@dataclass
class ScoreBreakdown:
    """Transparency: shows contribution of each factor."""
    outcome_score: float        # 0.0–1.0
    gate_score: float           # 0.0–1.0
    efficiency_score: float     # 0.0–1.0
    knowledge_score: float      # 0.0–1.0
    feedback_score: float       # 0.0–1.0 (1.0 if no feedback given)
    final: float                # Weighted composite
    weights: Dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "outcome": self.outcome_score,
            "gate": self.gate_score,
            "efficiency": self.efficiency_score,
            "knowledge": self.knowledge_score,
            "feedback": self.feedback_score,
            "final": self.final,
            "weights": self.weights,
        }


# ─── Reward Model ────────────────────────────────────────────────────────────

class RewardModel:
    """
    Deterministic reward scorer.
    Same inputs → same score. No randomness. No external calls.

    Weights are configurable and stored per-project in facts (domain='ml', key='reward_weights').
    This allows the system to eventually learn better weights through meta-learning.
    """

    DEFAULT_WEIGHTS = {
        "outcome":    0.40,   # Most important: did the task succeed?
        "gate":       0.25,   # Second: did it pass verification?
        "efficiency": 0.10,   # How fast was it?
        "knowledge":  0.15,   # Was fresh knowledge used?
        "feedback":   0.10,   # User signal (if available)
    }

    # Outcome base scores
    OUTCOME_SCORES = {
        "success": 1.0,
        "partial": 0.45,
        "failure": 0.0,
    }

    # Duration thresholds (seconds) for efficiency scoring
    FAST_THRESHOLD  = 5.0
    SLOW_THRESHOLD  = 120.0

    def __init__(self, persistence: PersistenceLayer, project: str) -> None:
        self.persistence = persistence
        self.project = project
        self._ensure_schema()
        self._weights = self._load_weights()

    def _ensure_schema(self) -> None:
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS rewards (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                project     TEXT NOT NULL,
                task        TEXT NOT NULL,
                skill       TEXT,
                outcome     TEXT NOT NULL,
                score       REAL NOT NULL,
                breakdown   TEXT NOT NULL,
                signal      TEXT NOT NULL,
                correlation_id TEXT,
                scored_at   TEXT NOT NULL
            )
        """)
        self.persistence.execute(
            "CREATE INDEX IF NOT EXISTS idx_rewards_project_task ON rewards(project, task)"
        )
        self.persistence.execute(
            "CREATE INDEX IF NOT EXISTS idx_rewards_score ON rewards(project, score DESC)"
        )
        self.persistence.manager.get_connection().commit()

    def _load_weights(self) -> Dict[str, float]:
        """Load weights from project facts, fall back to defaults."""
        try:
            stored = self.persistence.get_fact(self.project, "ml", "reward_weights")
            if isinstance(stored, dict):
                # Merge with defaults so new keys are always present
                return {**self.DEFAULT_WEIGHTS, **stored}
        except Exception:
            pass
        return dict(self.DEFAULT_WEIGHTS)

    # ─── Scoring ──────────────────────────────────────────────────────────

    def score(self, signal: RewardSignal) -> ScoreBreakdown:
        """
        Score an outcome. Persist it. Return the breakdown.
        """
        breakdown = self._compute(signal)

        # Persist to rewards table
        now = datetime.now(timezone.utc).isoformat()
        with self.persistence.transaction() as conn:
            conn.execute("""
                INSERT INTO rewards (project, task, skill, outcome, score, breakdown, signal, correlation_id, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                signal.project, signal.task, signal.skill_name,
                signal.outcome, breakdown.final,
                json.dumps(breakdown.to_dict()),
                json.dumps(self._signal_to_dict(signal)),
                signal.correlation_id, now
            ))

        # Emit event
        self.persistence.emit_event(
            event_type="learning.reward_scored",
            project=signal.project,
            payload={
                "task": signal.task,
                "score": breakdown.final,
                "outcome": signal.outcome,
                "breakdown": breakdown.to_dict(),
            },
            correlation_id=signal.correlation_id,
        )

        return breakdown

    def _compute(self, signal: RewardSignal) -> ScoreBreakdown:
        """Pure computation — no I/O."""
        w = self._weights

        # 1. Outcome score
        outcome_score = self.OUTCOME_SCORES.get(signal.outcome, 0.0)

        # 2. Gate score — weighted by probe count
        gate_score = 1.0  # default: no gate info = neutral
        if signal.gate_passed is not None:
            if signal.gate_passed:
                gate_score = 1.0
            else:
                passed = sum(1 for p in signal.gate_probe_results if p.get("passed"))
                total = len(signal.gate_probe_results) or 1
                gate_score = passed / total * 0.5  # Partial credit for partial pass

        # 3. Efficiency score
        efficiency_score = 0.5  # neutral if no duration
        if signal.duration_seconds is not None:
            d = signal.duration_seconds
            if d <= self.FAST_THRESHOLD:
                efficiency_score = 1.0
            elif d >= self.SLOW_THRESHOLD:
                efficiency_score = 0.0
            else:
                efficiency_score = 1.0 - (d - self.FAST_THRESHOLD) / (self.SLOW_THRESHOLD - self.FAST_THRESHOLD)

        # 4. Knowledge score — penalise stale facts
        knowledge_score = 0.5  # neutral if no fact info
        total_facts = signal.facts_used + signal.cache_hits + signal.cache_misses
        if total_facts > 0:
            # Freshness: penalise stale facts
            stale_rate = signal.stale_facts / max(signal.facts_used, 1)
            freshness = 1.0 - min(1.0, stale_rate)
            # Reuse: reward cache hits
            cache_total = signal.cache_hits + signal.cache_misses
            reuse = signal.cache_hits / cache_total if cache_total > 0 else 0.5
            knowledge_score = freshness * 0.6 + reuse * 0.4

        # 5. Feedback score
        feedback_score = 0.5  # neutral if no feedback
        if signal.user_feedback is not None:
            feedback_score = max(0.0, min(1.0, signal.user_feedback))

        # Weighted composite
        final = (
            outcome_score    * w["outcome"] +
            gate_score       * w["gate"] +
            efficiency_score * w["efficiency"] +
            knowledge_score  * w["knowledge"] +
            feedback_score   * w["feedback"]
        )
        final = max(0.0, min(1.0, final))

        return ScoreBreakdown(
            outcome_score=outcome_score,
            gate_score=gate_score,
            efficiency_score=efficiency_score,
            knowledge_score=knowledge_score,
            feedback_score=feedback_score,
            final=round(final, 4),
            weights=dict(w),
        )

    # ─── Analytics ────────────────────────────────────────────────────────

    def average_score(self, task: Optional[str] = None, last_n: int = 20) -> Optional[float]:
        """Average reward score for recent outcomes."""
        query = "SELECT AVG(score) as avg FROM (SELECT score FROM rewards WHERE project = ?"
        params: list = [self.project]
        if task:
            query += " AND task = ?"
            params.append(task)
        query += f" ORDER BY scored_at DESC LIMIT {last_n})"
        row = self.persistence.fetchone(query, tuple(params))
        return round(row["avg"], 4) if row and row["avg"] is not None else None

    def trend(self, task: str, last_n: int = 10) -> List[float]:
        """Score trend for a task (oldest first)."""
        rows = self.persistence.fetchall(
            "SELECT score FROM (SELECT score, scored_at FROM rewards WHERE project = ? AND task = ? ORDER BY scored_at DESC LIMIT ?) ORDER BY scored_at ASC",
            (self.project, task, last_n)
        )
        return [r["score"] for r in rows]

    def top_tasks(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Tasks with highest average reward."""
        rows = self.persistence.fetchall(
            """
            SELECT task, AVG(score) as avg_score, COUNT(*) as runs, MAX(scored_at) as last_run
            FROM rewards WHERE project = ?
            GROUP BY task
            ORDER BY avg_score DESC
            LIMIT ?
            """,
            (self.project, limit)
        )
        return [dict(r) for r in rows]

    def update_weights(self, new_weights: Dict[str, float]) -> None:
        """
        Update scoring weights and persist them.
        Only the Improvement controller should call this — after validation.
        """
        # Validate: weights must sum to ~1.0
        total = sum(new_weights.values())
        if abs(total - 1.0) > 0.05:
            raise ValueError(f"Weights must sum to 1.0, got {total:.3f}")
        self._weights = {**self.DEFAULT_WEIGHTS, **new_weights}
        self.persistence.set_fact(self.project, "ml", "reward_weights", self._weights)

    @staticmethod
    def _signal_to_dict(signal: RewardSignal) -> Dict[str, Any]:
        return {
            "project": signal.project,
            "task": signal.task,
            "outcome": signal.outcome,
            "gate_passed": signal.gate_passed,
            "duration_seconds": signal.duration_seconds,
            "cache_hits": signal.cache_hits,
            "cache_misses": signal.cache_misses,
            "facts_used": signal.facts_used,
            "stale_facts": signal.stale_facts,
            "user_feedback": signal.user_feedback,
        }
