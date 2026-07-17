"""
Agent Runtime Kernel — Needs Engine

"A system without needs has no initiative."

The Needs Engine is the kernel's initiative layer. It continuously inspects
the runtime state and generates structured Needs — prioritised goals that the
Scheduler and Planner can act on without waiting for a human request.

Need sources (what triggers a Need):
    1. Execution log analysis — recurring failures, low success rates
    2. Staleness detection — facts older than threshold → "refresh needed"
    3. Falsification failures — probes that keep failing → "structural gap"
    4. Pattern gaps — tasks attempted without matching learned pattern
    5. Reflection output — explicit gaps found during reflection
    6. Cache miss spikes — knowledge not available, needs acquisition

Need lifecycle:
    DETECTED → ACTIVE → SCHEDULED → IN_PROGRESS → RESOLVED | ESCALATED

All Needs are stored in SQLite (needs table). The engine never modifies
project facts directly — it only generates Needs. Separation of concerns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from llm_middleware.core.persistence import PersistenceLayer


# ─── Priority ────────────────────────────────────────────────────────────────

class NeedPriority(str, Enum):
    """
    Scheduler reads priority to decide what to work on next.
    Critical beats everything. Optional only runs when nothing else queued.
    """
    CRITICAL  = "critical"   # Data loss, broken project, security
    IMPORTANT = "important"  # Quality, correctness, missing tests
    OPTIONAL  = "optional"   # Performance, cleanup, documentation


PRIORITY_ORDER = {
    NeedPriority.CRITICAL:  0,
    NeedPriority.IMPORTANT: 1,
    NeedPriority.OPTIONAL:  2,
}


# ─── Need ────────────────────────────────────────────────────────────────────

@dataclass
class Need:
    """
    A structured, actionable requirement identified by the engine.

    motivation: float in [0.0, 1.0] — how strongly the engine wants to act.
    A motivation < 0.3 means "don't touch it". The scheduler respects this.
    """
    need_id: str
    project: str
    category: str             # quality, correctness, knowledge, performance, ...
    description: str
    priority: NeedPriority
    source: str               # Which detector created this Need
    evidence: Dict[str, Any]  # Raw data that led to this Need
    motivation: float = 0.5   # 0.0–1.0
    status: str = "detected"  # detected, active, scheduled, in_progress, resolved, escalated
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    resolved_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "need_id": self.need_id,
            "project": self.project,
            "category": self.category,
            "description": self.description,
            "priority": self.priority.value,
            "source": self.source,
            "evidence": self.evidence,
            "motivation": self.motivation,
            "status": self.status,
            "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "Need":
        d = dict(d)
        d["priority"] = NeedPriority(d.get("priority", "optional"))
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})  # type: ignore[attr-defined]


# ─── Needs Engine ────────────────────────────────────────────────────────────

class NeedsEngine:
    """
    Inspects runtime state and surfaces Needs autonomously.

    Each detector method returns a list of Needs. Detectors are independent —
    a failure in one does not block others.

    The engine does NOT execute anything. It only surfaces what is missing.
    Execution is the Scheduler's and TrainingLoop's responsibility.
    """

    # How many recent log entries to analyse
    LOG_WINDOW = 50
    # Failure rate threshold above which a Need is created
    FAILURE_RATE_THRESHOLD = 0.3
    # Facts older than this (days) are considered stale
    STALENESS_DAYS = 7
    # Cache miss rate threshold
    CACHE_MISS_THRESHOLD = 0.6

    def __init__(self, persistence: PersistenceLayer, project: str) -> None:
        self.persistence = persistence
        self.project = project
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        """Create needs table if it doesn't exist (schema extension v3)."""
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS needs (
                need_id   TEXT PRIMARY KEY,
                project   TEXT NOT NULL,
                category  TEXT NOT NULL,
                description TEXT NOT NULL,
                priority  TEXT NOT NULL,
                source    TEXT NOT NULL,
                evidence  TEXT NOT NULL,
                motivation REAL NOT NULL DEFAULT 0.5,
                status    TEXT NOT NULL DEFAULT 'detected',
                created_at TEXT NOT NULL,
                resolved_at TEXT
            )
        """)
        self.persistence.execute(
            "CREATE INDEX IF NOT EXISTS idx_needs_project_status ON needs(project, status)"
        )
        self.persistence.execute(
            "CREATE INDEX IF NOT EXISTS idx_needs_priority ON needs(priority, status)"
        )
        self.persistence.manager.get_connection().commit()

    # ─── Public API ───────────────────────────────────────────────────────

    def scan(self) -> List[Need]:
        """
        Run all detectors and persist new Needs.
        Returns only newly created Needs (duplicates are deduplicated by source+category).
        """
        detectors = [
            self._detect_failure_patterns,
            self._detect_stale_facts,
            self._detect_gate_failures,
            self._detect_missing_tests,
            self._detect_knowledge_gaps,
        ]

        new_needs: List[Need] = []
        for detector in detectors:
            try:
                found = detector()
                for need in found:
                    if self._is_new(need):
                        self._persist(need)
                        new_needs.append(need)
            except Exception as e:
                # Detector failure is a Warning, not a crash
                self._persist(Need(
                    need_id=self._make_id("detector_error", detector.__name__),
                    project=self.project,
                    category="runtime",
                    description=f"Detector '{detector.__name__}' crashed: {e}",
                    priority=NeedPriority.IMPORTANT,
                    source="needs_engine.meta",
                    evidence={"error": str(e)},
                    motivation=0.4,
                ))

        return new_needs

    def get_active_needs(
        self,
        priority: Optional[NeedPriority] = None,
        limit: int = 20,
    ) -> List[Need]:
        """Return open Needs sorted by priority, then motivation desc."""
        query = """
            SELECT * FROM needs
            WHERE project = ? AND status IN ('detected', 'active', 'scheduled')
        """
        params: list = [self.project]
        if priority:
            query += " AND priority = ?"
            params.append(priority.value)
        query += " ORDER BY CASE priority WHEN 'critical' THEN 0 WHEN 'important' THEN 1 ELSE 2 END, motivation DESC LIMIT ?"
        params.append(limit)

        rows = self.persistence.fetchall(query, tuple(params))
        return [self._row_to_need(r) for r in rows]

    def resolve(self, need_id: str, evidence: Optional[Dict[str, Any]] = None) -> None:
        """Mark a Need as resolved."""
        now = datetime.now(timezone.utc).isoformat()
        with self.persistence.transaction() as conn:
            conn.execute(
                "UPDATE needs SET status = 'resolved', resolved_at = ? WHERE need_id = ?",
                (now, need_id)
            )
        if evidence:
            self.persistence.emit_event(
                event_type="need.resolved",
                project=self.project,
                payload={"need_id": need_id, "evidence": evidence},
            )

    def escalate(self, need_id: str, reason: str) -> None:
        """Escalate a Need to CRITICAL."""
        with self.persistence.transaction() as conn:
            conn.execute(
                "UPDATE needs SET priority = 'critical', status = 'escalated' WHERE need_id = ?",
                (need_id,)
            )
        self.persistence.emit_event(
            event_type="need.escalated",
            project=self.project,
            payload={"need_id": need_id, "reason": reason},
        )

    def stats(self) -> Dict[str, Any]:
        """Return Need statistics for the project."""
        rows = self.persistence.fetchall(
            "SELECT status, priority, COUNT(*) as cnt FROM needs WHERE project = ? GROUP BY status, priority",
            (self.project,)
        )
        result: Dict[str, Any] = {"by_status": {}, "by_priority": {}, "total": 0}
        for row in rows:
            s, p, cnt = row["status"], row["priority"], row["cnt"]
            result["by_status"][s] = result["by_status"].get(s, 0) + cnt
            result["by_priority"][p] = result["by_priority"].get(p, 0) + cnt
            result["total"] += cnt
        return result

    # ─── Detectors ────────────────────────────────────────────────────────

    def _detect_failure_patterns(self) -> List[Need]:
        """Detect: repeated task failures → knowledge or skill gap."""
        rows = self.persistence.fetchall(
            """
            SELECT task, outcome, COUNT(*) as cnt
            FROM execution_log
            WHERE project = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (self.project, self.LOG_WINDOW)
        )

        total = len(rows)
        if total == 0:
            return []

        failures_by_task: Dict[str, int] = {}
        counts_by_task: Dict[str, int] = {}
        for row in rows:
            task = row["task"]
            counts_by_task[task] = counts_by_task.get(task, 0) + 1
            if row["outcome"] in ("failure", "partial"):
                failures_by_task[task] = failures_by_task.get(task, 0) + 1

        needs = []
        for task, fail_count in failures_by_task.items():
            total_task = counts_by_task[task]
            rate = fail_count / total_task if total_task > 0 else 0.0
            if rate >= self.FAILURE_RATE_THRESHOLD:
                motivation = min(1.0, rate * 1.5)
                priority = NeedPriority.CRITICAL if rate > 0.7 else NeedPriority.IMPORTANT
                needs.append(Need(
                    need_id=self._make_id("failure_pattern", task),
                    project=self.project,
                    category="correctness",
                    description=f"Task '{task}' fails {rate:.0%} of the time ({fail_count}/{total_task}). Skill or knowledge gap suspected.",
                    priority=priority,
                    source="needs_engine.failure_detector",
                    evidence={"task": task, "failure_rate": rate, "failures": fail_count, "total": total_task},
                    motivation=motivation,
                ))
        return needs

    def _detect_stale_facts(self) -> List[Need]:
        """Detect: domain facts not updated in STALENESS_DAYS → refresh needed."""
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self.STALENESS_DAYS)).isoformat()

        rows = self.persistence.fetchall(
            """
            SELECT domain, COUNT(*) as cnt, MIN(updated_at) as oldest
            FROM facts
            WHERE project = ? AND updated_at < ?
            GROUP BY domain
            ORDER BY cnt DESC
            """,
            (self.project, cutoff)
        )

        needs = []
        for row in rows:
            domain = row["domain"]
            cnt = row["cnt"]
            needs.append(Need(
                need_id=self._make_id("stale_facts", domain),
                project=self.project,
                category="knowledge",
                description=f"Domain '{domain}' has {cnt} facts not updated in {self.STALENESS_DAYS}+ days. May be stale.",
                priority=NeedPriority.OPTIONAL,
                source="needs_engine.staleness_detector",
                evidence={"domain": domain, "stale_count": cnt, "oldest": row["oldest"], "cutoff": cutoff},
                motivation=0.35,
            ))
        return needs

    def _detect_gate_failures(self) -> List[Need]:
        """Detect: recurring falsification gate failures → structural issue."""
        rows = self.persistence.fetchall(
            """
            SELECT payload FROM events
            WHERE project = ? AND event_type = 'falsification.probe'
            ORDER BY timestamp DESC
            LIMIT 100
            """,
            (self.project,)
        )

        probe_failures: Dict[str, int] = {}
        probe_total: Dict[str, int] = {}
        for row in rows:
            try:
                data = json.loads(row["payload"])
                payload = data.get("payload", data)
                probe = payload.get("probe", "unknown")
                probe_total[probe] = probe_total.get(probe, 0) + 1
                if not payload.get("passed", True):
                    probe_failures[probe] = probe_failures.get(probe, 0) + 1
            except (json.JSONDecodeError, KeyError):
                continue

        needs = []
        for probe, fail_count in probe_failures.items():
            total = probe_total.get(probe, 1)
            rate = fail_count / total
            if rate >= 0.5:
                needs.append(Need(
                    need_id=self._make_id("gate_failure", probe),
                    project=self.project,
                    category="correctness",
                    description=f"Falsification probe '{probe}' fails {rate:.0%} of the time. Structural gap in process or knowledge.",
                    priority=NeedPriority.IMPORTANT,
                    source="needs_engine.gate_detector",
                    evidence={"probe": probe, "failure_rate": rate, "failures": fail_count, "total": total},
                    motivation=min(1.0, rate * 1.3),
                ))
        return needs

    def _detect_missing_tests(self) -> List[Need]:
        """Detect: domains with facts but no test evidence in logs."""
        domain_rows = self.persistence.fetchall(
            "SELECT DISTINCT domain FROM facts WHERE project = ?",
            (self.project,)
        )
        domains_with_facts = {r["domain"] for r in domain_rows}

        log_rows = self.persistence.fetchall(
            "SELECT DISTINCT domain FROM execution_log WHERE project = ? AND domain IS NOT NULL",
            (self.project,)
        )
        domains_with_logs = {r["domain"] for r in log_rows}

        untested = domains_with_facts - domains_with_logs
        needs = []
        for domain in untested:
            needs.append(Need(
                need_id=self._make_id("missing_tests", domain),
                project=self.project,
                category="quality",
                description=f"Domain '{domain}' has facts but no execution log entries. No evidence of validation.",
                priority=NeedPriority.OPTIONAL,
                source="needs_engine.test_detector",
                evidence={"domain": domain},
                motivation=0.3,
            ))
        return needs

    def _detect_knowledge_gaps(self) -> List[Need]:
        """Detect: tasks logged as 'partial' with no subsequent success → knowledge gap."""
        rows = self.persistence.fetchall(
            """
            SELECT task, COUNT(*) as partial_count
            FROM execution_log
            WHERE project = ? AND outcome = 'partial'
            GROUP BY task
            HAVING partial_count >= 2
            """,
            (self.project,)
        )

        needs = []
        for row in rows:
            task = row["task"]
            cnt = row["partial_count"]
            needs.append(Need(
                need_id=self._make_id("knowledge_gap", task),
                project=self.project,
                category="knowledge",
                description=f"Task '{task}' repeatedly produces partial results ({cnt}x). Knowledge gap or skill mismatch.",
                priority=NeedPriority.IMPORTANT,
                source="needs_engine.gap_detector",
                evidence={"task": task, "partial_count": cnt},
                motivation=0.6,
            ))
        return needs

    # ─── Helpers ──────────────────────────────────────────────────────────

    def _make_id(self, source: str, key: str) -> str:
        """Deterministic Need ID. Same source+key = same ID = natural dedup."""
        import hashlib
        raw = f"{self.project}:{source}:{key}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _is_new(self, need: Need) -> bool:
        """Return True if this Need is not already open in the DB."""
        row = self.persistence.fetchone(
            "SELECT status FROM needs WHERE need_id = ?",
            (need.need_id,)
        )
        if row is None:
            return True
        # Re-open only if previously resolved
        return row["status"] == "resolved"

    def _persist(self, need: Need) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.persistence.transaction() as conn:
            conn.execute("""
                INSERT INTO needs (need_id, project, category, description, priority,
                                   source, evidence, motivation, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(need_id) DO UPDATE SET
                    motivation = excluded.motivation,
                    status = CASE WHEN needs.status = 'resolved' THEN 'detected' ELSE needs.status END,
                    created_at = CASE WHEN needs.status = 'resolved' THEN excluded.created_at ELSE needs.created_at END
            """, (
                need.need_id, need.project, need.category, need.description,
                need.priority.value, need.source,
                json.dumps(need.evidence), need.motivation,
                need.status, now
            ))

    @staticmethod
    def _row_to_need(row: Any) -> Need:
        d = dict(row)
        d["evidence"] = json.loads(d.get("evidence", "{}"))
        d["priority"] = NeedPriority(d["priority"])
        return Need(**{k: v for k, v in d.items() if k in Need.__dataclass_fields__})  # type: ignore[attr-defined]
