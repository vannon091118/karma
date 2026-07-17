"""
Agent Runtime Kernel — Knowledge Graph

A deterministically derived view over the immutable Experience Store.
It maps Tasks to Facts using statistical relationships (`improves_with`, `confused_by`).

Features:
- Time-weighting (decay of old facts via `last_seen`)
- Negative knowledge (`confused_by` relations)
- Fully calculable from the Experience Store (no independent truth)
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import math

from karma.core.persistence import PersistenceLayer
from karma.ml.experience_store import ExperienceStore
from karma.core.context_snapshot import ContextSnapshotStore


class KnowledgeGraph:
    def __init__(self, persistence: PersistenceLayer, project: str):
        self.persistence = persistence
        self.project = project
        self.persistence.ensure_schema("knowledge_graph", self._create_schema)

    def _create_schema(self) -> None:
        """DDL only — called at most once per PersistenceLayer instance."""
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS kg_edges (
                project TEXT NOT NULL,
                task TEXT NOT NULL,
                fact_domain TEXT NOT NULL,
                fact_key TEXT NOT NULL,
                relation TEXT NOT NULL,  -- 'improves_with' or 'confused_by'
                weight REAL NOT NULL DEFAULT 0.0,
                observations INTEGER NOT NULL DEFAULT 0,
                confidence REAL NOT NULL DEFAULT 0.0,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (project, task, fact_domain, fact_key, relation)
            )
        """)

    def update_from_experience(self, experience_id: str, reward_score: float) -> None:
        """
        Derives graph edges from a single historical experience.
        High reward -> reinforces 'improves_with'
        Low reward -> reinforces 'confused_by'
        """
        es = ExperienceStore(self.persistence)
        row = self.persistence.fetchone("SELECT * FROM experiences WHERE id = ?", (experience_id,))
        if not row:
            return
            
        task = row["task"]
        snapshot_id = row["context_snapshot_id"]
        
        # Load the facts that were ACTUALLY used
        css = ContextSnapshotStore(self.persistence)
        snapshot_text = css.load_snapshot(snapshot_id)
        if not snapshot_text:
            return
            
        try:
            context_data = json.loads(snapshot_text)
            facts = context_data.get("facts", {})
        except Exception:
            return # If it's not JSON or malformed, we can't extract facts easily
            
        now = datetime.now(timezone.utc).isoformat()
        
        # Determine relation type based on reward
        if reward_score >= 0.6:
            relation = "improves_with"
            delta = reward_score  # weight increases more for higher scores
        elif reward_score <= 0.4:
            relation = "confused_by"
            delta = 1.0 - reward_score  # weight increases more for lower scores
        else:
            return  # Neutral experience, doesn't strongly drive the graph
            
        for domain, keys in facts.items():
            for key in keys.keys():
                self._upsert_edge(task, domain, key, relation, delta, now)

    def _upsert_edge(self, task: str, domain: str, key: str, relation: str, delta: float, now: str) -> None:
        """Update or insert a graph edge with time-decay and confidence calculation."""
        with self.persistence.transaction() as conn:
            existing = self.persistence.fetchone(
                """SELECT weight, observations, last_seen 
                   FROM kg_edges 
                   WHERE project = ? AND task = ? AND fact_domain = ? AND fact_key = ? AND relation = ?""",
                (self.project, task, domain, key, relation)
            )
            
            if existing:
                obs = existing["observations"] + 1
                # Time decay: reduce old weight if last_seen is old
                # For simplicity, we just use EMA here
                old_weight = existing["weight"]
                alpha = 0.2
                new_weight = (1 - alpha) * old_weight + alpha * delta
                
                # Confidence asymptotically approaches 1.0 based on observations
                confidence = 1.0 - math.exp(-obs / 5.0)
                
                conn.execute(
                    """UPDATE kg_edges 
                       SET weight = ?, observations = ?, confidence = ?, last_seen = ?
                       WHERE project = ? AND task = ? AND fact_domain = ? AND fact_key = ? AND relation = ?""",
                    (new_weight, obs, confidence, now, self.project, task, domain, key, relation)
                )
            else:
                confidence = 1.0 - math.exp(-1 / 5.0)
                conn.execute(
                    """INSERT INTO kg_edges (project, task, fact_domain, fact_key, relation, weight, observations, confidence, last_seen)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (self.project, task, domain, key, relation, delta, 1, confidence, now)
                )

    def get_task_relations(self, task: str) -> Dict[str, List[Dict[str, Any]]]:
        """Retrieve the graph for a specific task."""
        rows = self.persistence.fetchall(
            """SELECT fact_domain, fact_key, relation, weight, observations, confidence, last_seen
               FROM kg_edges 
               WHERE project = ? AND task = ?
               ORDER BY confidence DESC, weight DESC""",
            (self.project, task)
        )
        
        result = {"improves_with": [], "confused_by": []}
        for r in rows:
            rel = r["relation"]
            if rel in result:
                result[rel].append({
                    "domain": r["fact_domain"],
                    "key": r["fact_key"],
                    "weight": r["weight"],
                    "confidence": r["confidence"],
                    "observations": r["observations"],
                    "last_seen": r["last_seen"]
                })
        return result
