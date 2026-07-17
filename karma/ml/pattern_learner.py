"""
Agent Runtime Kernel — Pattern Learner

"Experience is what you get when you didn't get what you wanted."
But experience is also what you get when you DID — and remembered how.

The Pattern Learner stores input→outcome mappings as weighted experience records.
On new tasks, it retrieves the most similar past experience and suggests an approach.

No neural networks. No embeddings API. No cloud.
Similarity is computed with TF-IDF-like token overlap — pure Python.

Schema: `patterns` table in SQLite.

Pattern lifecycle:
    NEW          → stored with weight from reward score
    CONFIRMED    → reward > 0.7 twice → weight += 0.1
    DEPRECATED   → reward < 0.3 three times → weight -= 0.2 (soft delete at weight < 0.05)
    EVOLVED      → skill_evolution updated the approach

The PatternLearner is intentionally read-heavy. Writes happen after every task.
Reads happen before every task (retrieval at inference time).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from karma.core.persistence import PersistenceLayer


# ─── Experience Record ───────────────────────────────────────────────────────

@dataclass
class ExperienceRecord:
    """
    A stored experience: what was tried, how, with what result.
    """
    pattern_id: str
    project: str
    task_signature: str      # Normalised task description (tokenised, sorted)
    skill_used: str
    approach: str            # What the execution plan was
    outcome: str             # success, partial, failure
    score: float             # Reward score at time of storage
    weight: float            # Current confidence weight [0.0, 1.0]
    usage_count: int = 0
    success_count: int = 0
    failure_count: int = 0
    status: str = "new"      # new, confirmed, deprecated, evolved
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}

    @classmethod
    def from_row(cls, row: Any) -> "ExperienceRecord":
        d = dict(row)
        d["metadata"] = json.loads(d.get("metadata", "{}"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


# ─── Pattern Learner ─────────────────────────────────────────────────────────

class PatternLearner:
    """
    Stores and retrieves experience-based patterns.

    store(task, skill, approach, outcome, score):
        Persist a new experience. If a matching pattern exists, update its weight.

    retrieve(task, top_k=3):
        Find the most similar past experiences for a given task.
        Returns ranked list (best match first).

    evolve(pattern_id, new_approach):
        Update a pattern's approach (e.g. after skill improvement).
    """

    # Reward thresholds
    CONFIRM_THRESHOLD    = 0.7
    DEPRECATE_THRESHOLD  = 0.3
    MIN_WEIGHT           = 0.05   # Below this → effectively invisible to retrieval
    MAX_WEIGHT           = 1.0

    # Weight adjustments
    CONFIRM_BOOST        = 0.10
    FAILURE_PENALTY      = 0.15
    NEW_PATTERN_WEIGHT   = 0.5    # Starting weight for a new pattern

    # Retrieval
    MIN_SIMILARITY       = 0.15   # Don't return patterns below this similarity
    MAX_RETRIEVE         = 10

    def __init__(self, persistence: PersistenceLayer, project: str) -> None:
        self.persistence = persistence
        self.project = project
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS patterns (
                pattern_id    TEXT PRIMARY KEY,
                project       TEXT NOT NULL,
                task_signature TEXT NOT NULL,
                skill_used    TEXT NOT NULL,
                approach      TEXT NOT NULL,
                outcome       TEXT NOT NULL,
                score         REAL NOT NULL,
                weight        REAL NOT NULL DEFAULT 0.5,
                usage_count   INTEGER NOT NULL DEFAULT 0,
                success_count INTEGER NOT NULL DEFAULT 0,
                failure_count INTEGER NOT NULL DEFAULT 0,
                status        TEXT NOT NULL DEFAULT 'new',
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL,
                metadata      TEXT NOT NULL DEFAULT '{}'
            )
        """)
        self.persistence.execute(
            "CREATE INDEX IF NOT EXISTS idx_patterns_project ON patterns(project, status, weight DESC)"
        )
        self.persistence.execute(
            "CREATE INDEX IF NOT EXISTS idx_patterns_sig ON patterns(task_signature)"
        )
        self.persistence.manager.get_connection().commit()

    # ─── Store ────────────────────────────────────────────────────────────

    def store(
        self,
        task: str,
        skill_used: str,
        approach: str,
        outcome: str,
        score: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ExperienceRecord:
        """
        Store a new experience or update an existing matching pattern.
        Returns the record (new or updated).
        """
        signature = self._make_signature(task)
        pattern_id = self._make_id(signature, skill_used)
        now = datetime.now(timezone.utc).isoformat()

        existing = self._get_by_id(pattern_id)

        if existing is None:
            # New pattern
            record = ExperienceRecord(
                pattern_id=pattern_id,
                project=self.project,
                task_signature=signature,
                skill_used=skill_used,
                approach=approach,
                outcome=outcome,
                score=score,
                weight=self.NEW_PATTERN_WEIGHT,
                usage_count=1,
                success_count=1 if outcome == "success" else 0,
                failure_count=1 if outcome == "failure" else 0,
                status="new",
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            )
            self._insert(record)
        else:
            # Update existing
            record = existing
            record.usage_count += 1
            record.updated_at = now
            record.score = (record.score * 0.7 + score * 0.3)  # EMA

            if outcome == "success":
                record.success_count += 1
                if score >= self.CONFIRM_THRESHOLD:
                    record.weight = min(self.MAX_WEIGHT, record.weight + self.CONFIRM_BOOST)
                    if record.status == "new" and record.success_count >= 2:
                        record.status = "confirmed"
            elif outcome == "failure":
                record.failure_count += 1
                if score < self.DEPRECATE_THRESHOLD:
                    record.weight = max(0.0, record.weight - self.FAILURE_PENALTY)
                    if record.weight < self.MIN_WEIGHT:
                        record.status = "deprecated"
            # partial: no weight change, just EMA score update

            self._update(record)

        # Emit event
        self.persistence.emit_event(
            event_type="learning.pattern_stored",
            project=self.project,
            payload={
                "pattern_id": pattern_id,
                "task": task[:100],
                "skill": skill_used,
                "outcome": outcome,
                "score": score,
                "weight": record.weight,
                "status": record.status,
            },
        )

        return record

    # ─── Retrieve ─────────────────────────────────────────────────────────

    def retrieve(self, task: str, top_k: int = 3) -> List[Tuple[ExperienceRecord, float]]:
        """
        Find the most similar past experiences for a task.
        Returns list of (record, similarity_score) sorted by relevance.
        """
        query_sig = self._make_signature(task)
        query_tokens = set(query_sig.split())

        # Fetch active patterns (not deprecated)
        rows = self.persistence.fetchall(
            """
            SELECT * FROM patterns
            WHERE project = ? AND status != 'deprecated' AND weight >= ?
            ORDER BY weight DESC
            LIMIT ?
            """,
            (self.project, self.MIN_WEIGHT, self.MAX_RETRIEVE * 3)
        )

        scored: List[Tuple[ExperienceRecord, float]] = []
        for row in rows:
            record = ExperienceRecord.from_row(row)
            sim = self._token_similarity(query_tokens, set(record.task_signature.split()))
            if sim >= self.MIN_SIMILARITY:
                # Combine similarity with pattern weight
                relevance = sim * 0.7 + record.weight * 0.3
                scored.append((record, round(relevance, 4)))

        scored.sort(key=lambda x: x[1], reverse=True)
        result = scored[:top_k]

        # Track usage
        if result:
            best_id = result[0][0].pattern_id
            with self.persistence.transaction() as conn:
                conn.execute(
                    "UPDATE patterns SET usage_count = usage_count + 1 WHERE pattern_id = ?",
                    (best_id,)
                )
            self.persistence.emit_event(
                event_type="learning.pattern_applied",
                project=self.project,
                payload={
                    "task": task[:100],
                    "pattern_id": best_id,
                    "similarity": result[0][1],
                    "top_k": len(result),
                },
            )

        return result

    # ─── Evolve ───────────────────────────────────────────────────────────

    def evolve(self, pattern_id: str, new_approach: str, reason: str = "") -> bool:
        """
        Update a pattern's approach after skill improvement.
        Only valid for confirmed or new patterns.
        """
        now = datetime.now(timezone.utc).isoformat()
        with self.persistence.transaction() as conn:
            cursor = conn.execute(
                """
                UPDATE patterns
                SET approach = ?, status = 'evolved', updated_at = ?
                WHERE pattern_id = ? AND status IN ('new', 'confirmed')
                """,
                (new_approach, now, pattern_id)
            )
        if cursor.rowcount > 0:
            self.persistence.emit_event(
                event_type="skill.evolved",
                project=self.project,
                payload={"pattern_id": pattern_id, "reason": reason},
            )
            return True
        return False

    # ─── Analytics ────────────────────────────────────────────────────────

    def stats(self) -> Dict[str, Any]:
        rows = self.persistence.fetchall(
            """
            SELECT status, COUNT(*) as cnt, AVG(weight) as avg_weight, AVG(score) as avg_score
            FROM patterns WHERE project = ?
            GROUP BY status
            """,
            (self.project,)
        )
        return {r["status"]: {"count": r["cnt"], "avg_weight": round(r["avg_weight"] or 0, 3), "avg_score": round(r["avg_score"] or 0, 3)} for r in rows}

    def top_patterns(self, limit: int = 10) -> List[Dict[str, Any]]:
        rows = self.persistence.fetchall(
            """
            SELECT pattern_id, task_signature, skill_used, outcome, score, weight, usage_count, status
            FROM patterns WHERE project = ? AND status != 'deprecated'
            ORDER BY weight DESC, score DESC
            LIMIT ?
            """,
            (self.project, limit)
        )
        return [dict(r) for r in rows]

    # ─── Internal ─────────────────────────────────────────────────────────

    @staticmethod
    def _make_signature(task: str) -> str:
        """
        Normalise task text to a token set for similarity matching.
        Removes stop words, lowercases, sorts — so order doesn't matter.
        """
        stop_words = {
            "a", "an", "the", "is", "it", "in", "on", "at", "to", "for",
            "of", "and", "or", "with", "that", "this", "are", "was", "be",
            "as", "by", "from", "aber", "und", "der", "die", "das", "ein",
            "eine", "im", "ich", "du", "er", "sie", "es", "wir", "ihr",
        }
        tokens = re.findall(r'\b[a-zA-ZäöüÄÖÜß]{3,}\b', task.lower())
        meaningful = sorted(set(t for t in tokens if t not in stop_words))
        return " ".join(meaningful[:30])  # Cap at 30 tokens to keep signatures compact

    @staticmethod
    def _token_similarity(a: set, b: set) -> float:
        """Jaccard similarity between two token sets."""
        if not a or not b:
            return 0.0
        return len(a & b) / len(a | b)

    @staticmethod
    def _make_id(signature: str, skill: str) -> str:
        raw = f"{signature}::{skill}"
        return hashlib.sha256(raw.encode()).hexdigest()[:20]

    def _get_by_id(self, pattern_id: str) -> Optional[ExperienceRecord]:
        row = self.persistence.fetchone(
            "SELECT * FROM patterns WHERE pattern_id = ?", (pattern_id,)
        )
        return ExperienceRecord.from_row(row) if row else None

    def _insert(self, record: ExperienceRecord) -> None:
        with self.persistence.transaction() as conn:
            conn.execute("""
                INSERT INTO patterns
                (pattern_id, project, task_signature, skill_used, approach, outcome,
                 score, weight, usage_count, success_count, failure_count, status,
                 created_at, updated_at, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                record.pattern_id, record.project, record.task_signature,
                record.skill_used, record.approach, record.outcome,
                record.score, record.weight,
                record.usage_count, record.success_count, record.failure_count,
                record.status, record.created_at, record.updated_at,
                json.dumps(record.metadata),
            ))

    def _update(self, record: ExperienceRecord) -> None:
        with self.persistence.transaction() as conn:
            conn.execute("""
                UPDATE patterns SET
                    outcome = ?, score = ?, weight = ?,
                    usage_count = ?, success_count = ?, failure_count = ?,
                    status = ?, updated_at = ?
                WHERE pattern_id = ?
            """, (
                record.outcome, record.score, record.weight,
                record.usage_count, record.success_count, record.failure_count,
                record.status, record.updated_at, record.pattern_id,
            ))
