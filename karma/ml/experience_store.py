"""
Agent Runtime Kernel — Experience Store

The immutable source of truth for all runtime events.
Every execution, its context, its prompt, its outcome, and its resulting reward
are recorded here permanently. This enables re-evaluating past experiences
when the reward logic or pattern learner evolves.

"Die Vergangenheit darf nicht mit umgeschrieben werden."
"""

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from karma.core.persistence import PersistenceLayer

@dataclass
class Experience:
    id: str = field(default_factory=lambda: f"exp_{uuid.uuid4().hex[:12]}")
    request_id: str = ""
    execution_id: str = ""
    llm_call_id: str = ""
    tool_call_id: Optional[str] = None
    project: str = ""
    task: str = ""
    request_payload: str = ""
    
    # Traceability IDs
    context_snapshot_id: str = ""
    prompt_variant_id: str = ""
    
    # Execution Metrics
    model_name: str = "unknown"
    duration_seconds: float = 0.0
    
    # Falsification
    gate_passed: bool = False
    failure_type: Optional[str] = None  # syntax, hallucination, timeout, policy, validation

    # Algorithm Versions
    reward_model_version: str = "1.0"
    gate_version: str = "1.0"
    pattern_learner_version: str = "1.0"
    context_selector_version: str = "1.0"
    prompt_engine_version: str = "1.0"
    
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


class ExperienceStore:
    def __init__(self, persistence: PersistenceLayer):
        self.persistence = persistence
        self.persistence.ensure_schema("experience_store", self._create_schema)

    def _create_schema(self) -> None:
        """DDL only — called at most once per PersistenceLayer instance."""
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS experiences (
                id TEXT PRIMARY KEY,
                request_id TEXT NOT NULL,
                execution_id TEXT NOT NULL,
                llm_call_id TEXT NOT NULL,
                tool_call_id TEXT,
                project TEXT NOT NULL,
                task TEXT NOT NULL,
                request_payload TEXT NOT NULL,
                context_snapshot_id TEXT NOT NULL,
                prompt_variant_id TEXT NOT NULL,
                model_name TEXT NOT NULL,
                duration_seconds REAL NOT NULL,
                gate_passed INTEGER NOT NULL,
                failure_type TEXT,
                reward_model_version TEXT NOT NULL,
                gate_version TEXT NOT NULL,
                pattern_learner_version TEXT NOT NULL,
                context_selector_version TEXT NOT NULL,
                prompt_engine_version TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.persistence.execute("CREATE INDEX IF NOT EXISTS idx_experiences_execution ON experiences(execution_id)")
        self.persistence.execute("CREATE INDEX IF NOT EXISTS idx_experiences_project ON experiences(project)")
        self.persistence.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_experiences_unique_request "
            "ON experiences(project, request_id)"
        )

    def record(self, exp: Experience) -> None:
        """Insert a new immutable experience."""
        with self.persistence.transaction() as conn:
            conn.execute("""
                INSERT INTO experiences (
                    id, request_id, execution_id, llm_call_id, tool_call_id, 
                    project, task, request_payload,
                    context_snapshot_id, prompt_variant_id, 
                    model_name, duration_seconds, gate_passed, failure_type,
                    reward_model_version, gate_version, pattern_learner_version,
                    context_selector_version, prompt_engine_version, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                exp.id, exp.request_id, exp.execution_id, exp.llm_call_id, exp.tool_call_id,
                exp.project, exp.task, exp.request_payload,
                exp.context_snapshot_id, exp.prompt_variant_id, 
                exp.model_name, exp.duration_seconds, 1 if exp.gate_passed else 0,
                exp.failure_type, exp.reward_model_version, exp.gate_version,
                exp.pattern_learner_version, exp.context_selector_version, 
                exp.prompt_engine_version, exp.created_at
            ))
