"""
LLM Middleware — SQLite Persistence Layer
WAL mode, transactional, schema versioned, idempotency keys.
Replaces JSON file I/O with ACID guarantees.
"""

import json
import os
import sqlite3
import sys
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Dict, List, Optional

# ─── Schema Version ────────────────────────────────────────────────────────

CURRENT_SCHEMA_VERSION = 4
SCHEMA_VERSION_PRAGMA = "user_version"

# ─── Connection Manager ────────────────────────────────────────────────────

class SQLiteConnectionManager:
    """Thread-safe SQLite connection pool with WAL mode."""
    
    def __init__(self, db_path: Path, max_connections: int = 5):
        self.db_path = db_path
        self.max_connections = max_connections
        self._local = {}
        self._lock = Lock()
        self._initialized = False
    
    def _create_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(
            str(self.db_path),
            timeout=30.0,
            check_same_thread=False,
            isolation_level=None,   # autocommit — we manage all transactions explicitly
        )
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn
    
    def get_connection(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()  # unique per OS thread
        with self._lock:
            if thread_id not in self._local:
                self._local[thread_id] = self._create_connection()
                if not self._initialized:
                    self._initialize_schema(self._local[thread_id])
                    self._initialized = True
            return self._local[thread_id]
    
    def _initialize_schema(self, conn: sqlite3.Connection) -> None:
        """Create tables and run migrations."""
        current_version = conn.execute(f"PRAGMA {SCHEMA_VERSION_PRAGMA}").fetchone()[0]

        if current_version == 0:
            self._create_schema_v1(conn)
            current_version = 1

        if current_version < CURRENT_SCHEMA_VERSION:
            self._run_migrations(conn, current_version)

        # PRAGMA user_version is not transactional but needs explicit commit
        # when isolation_level=None (autocommit mode).
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(f"PRAGMA {SCHEMA_VERSION_PRAGMA} = {CURRENT_SCHEMA_VERSION}")
        conn.execute("COMMIT")
    
    def _create_schema_v1(self, conn: sqlite3.Connection) -> None:
        """Initial schema creation."""
        conn.executescript("""
            -- Projects table
            CREATE TABLE projects (
                name TEXT PRIMARY KEY,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            
            -- Facts table: project + domain + key = unique fact
            CREATE TABLE facts (
                project TEXT NOT NULL,
                domain TEXT NOT NULL,
                key TEXT NOT NULL,
                value TEXT NOT NULL,           -- JSON serialized
                tokens INTEGER NOT NULL DEFAULT 0,
                hash TEXT NOT NULL,            -- MD5 of value for change detection
                updated_at TEXT NOT NULL,
                PRIMARY KEY (project, domain, key)
            );
            
            -- Index for token budget queries
            CREATE INDEX idx_facts_project_domain ON facts(project, domain);
            CREATE INDEX idx_facts_updated ON facts(updated_at);
            
            -- Execution log
            CREATE TABLE execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                agent TEXT NOT NULL,
                domain TEXT,
                task TEXT NOT NULL,
                outcome TEXT NOT NULL,         -- success, failure, partial
                evidence TEXT,
                timestamp TEXT NOT NULL,
                metadata TEXT DEFAULT '{}'
            );
            CREATE INDEX idx_log_project_time ON execution_log(project, timestamp);
            CREATE INDEX idx_log_agent ON execution_log(agent);
            
            -- Cascade state
            CREATE TABLE cascade_state (
                project TEXT PRIMARY KEY,
                template TEXT NOT NULL,
                description TEXT,
                status TEXT NOT NULL,          -- idle, in_progress, completed, blocked
                started_at TEXT,
                completed_at TEXT,
                steps TEXT NOT NULL,           -- JSON serialized steps
                metadata TEXT DEFAULT '{}'
            );
            
            -- Skill state per project
            CREATE TABLE skill_state (
                project TEXT NOT NULL,
                skill_name TEXT NOT NULL,
                loaded_at TEXT NOT NULL,
                version TEXT,
                metadata TEXT DEFAULT '{}',
                PRIMARY KEY (project, skill_name)
            );
            
            -- Cross-project references
            CREATE TABLE cross_references (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source_project TEXT NOT NULL,
                source_domain TEXT NOT NULL,
                source_key TEXT NOT NULL,
                target_project TEXT NOT NULL,
                target_domain TEXT NOT NULL,
                target_key TEXT NOT NULL,
                relation_type TEXT NOT NULL,   -- references, derives_from, conflicts_with
                created_at TEXT NOT NULL
            );
            CREATE INDEX idx_xref_source ON cross_references(source_project, source_domain, source_key);
            CREATE INDEX idx_xref_target ON cross_references(target_project, target_domain, target_key);
            
            -- Idempotency keys
            CREATE TABLE idempotency_keys (
                key TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                operation TEXT NOT NULL,       -- complete_step, fail_step, etc.
                created_at TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                result TEXT                    -- JSON serialized result
            );
            CREATE INDEX idx_idempotency_expires ON idempotency_keys(expires_at);
            
            -- Events (for audit/replay)
            CREATE TABLE events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                project TEXT,
                payload TEXT NOT NULL,         -- JSON serialized
                timestamp TEXT NOT NULL,
                correlation_id TEXT
            );
            CREATE INDEX idx_events_project_time ON events(project, timestamp);
            CREATE INDEX idx_events_type ON events(event_type);
            CREATE INDEX idx_events_correlation ON events(correlation_id);
            
            -- Schema metadata
            CREATE TABLE schema_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)
    
    def _run_migrations(self, conn: sqlite3.Connection, from_version: int) -> None:
        """Run schema migrations."""
        migrations = {
            1: self._migrate_v1_to_v2,
            2: self._migrate_v2_to_v3,
            3: self._migrate_v3_to_v4,
        }
        
        for version in range(from_version, CURRENT_SCHEMA_VERSION):
            if version in migrations:
                migrations[version](conn)
    
    def _migrate_v1_to_v2(self, conn: sqlite3.Connection) -> None:
        """Add cascade_state.metadata if missing, add events table."""
        cols = conn.execute("PRAGMA table_info(cascade_state)").fetchall()
        col_names = [c[1] for c in cols]
        if "metadata" not in col_names:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("ALTER TABLE cascade_state ADD COLUMN metadata TEXT DEFAULT '{}'")
            conn.execute("COMMIT")

    def _migrate_v2_to_v3(self, conn: sqlite3.Connection) -> None:
        """Create relations table for knowledge graph."""
        # executescript() always issues COMMIT first, safe in autocommit mode
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS relations (
                project TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id TEXT NOT NULL,
                metadata TEXT DEFAULT '{}',
                updated_at TEXT NOT NULL,
                PRIMARY KEY (project, source_type, source_id, relation_type, target_type, target_id)
            );
            CREATE INDEX IF NOT EXISTS idx_relations_source ON relations(project, source_type, source_id);
            CREATE INDEX IF NOT EXISTS idx_relations_target ON relations(project, target_type, target_id);
        """)

    def _migrate_v3_to_v4(self, conn: sqlite3.Connection) -> None:
        """Add UNIQUE constraint on experiences(project, request_id).

        No-op on fresh DBs — ExperienceStore._ensure_schema() creates the
        index when the table is first instantiated.
        """
        try:
            conn.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_experiences_unique_request
                ON experiences(project, request_id)
            """)
        except Exception:
            pass  # table not yet created — ExperienceStore will add the index
    
    def close_all(self) -> None:
        with self._lock:
            for conn in self._local.values():
                conn.close()
            self._local.clear()


# ─── High-Level API ────────────────────────────────────────────────────────

@dataclass
class PersistenceConfig:
    framework_dir: Path
    db_filename: str = "middleware.db"
    
    @property
    def db_path(self) -> Path:
        return self.framework_dir / self.db_filename


class PersistenceLayer:
    """
    Main persistence interface. All read/write operations go through here.
    Provides transactional boundaries and idempotency.

    Schema lifecycle
    ----------------
    Modules MUST NOT run DDL in their ``__init__``.  Instead they call::

        self.persistence.ensure_schema("my_module", self._create_schema)

    The registry guarantees the callable runs exactly once per
    ``PersistenceLayer`` instance — a set lookup on every subsequent call.
    Call ``persistence.ensure_all_schemas()`` once at startup to pre-warm
    every known schema before the first ``handle_turn()``.
    """

    def __init__(self, config: PersistenceConfig):
        self.config = config
        self.config.framework_dir.mkdir(parents=True, exist_ok=True)
        self.manager = SQLiteConnectionManager(config.db_path)
        # Registry: schema keys that have already been initialised.
        # Checked before every ensure_schema() call; a set lookup is O(1).
        self._schemas_initialized: set[str] = set()
    
    @contextmanager
    def transaction(self):
        """Context manager for explicit IMMEDIATE transactions (supports nesting).

        With isolation_level=None (autocommit), conn.commit() is a no-op.
        We use explicit SQL BEGIN IMMEDIATE / COMMIT / ROLLBACK so the
        locking semantics are unambiguous regardless of Python version.
        """
        conn = self.manager.get_connection()
        in_tx = conn.in_transaction
        if not in_tx:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if not in_tx:
                conn.execute("COMMIT")
        except Exception:
            if not in_tx:
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
            raise
    
    # ─── Schema Registry ─────────────────────────────────────────────────

    def ensure_schema(self, schema_key: str, create_fn) -> None:
        """Run ``create_fn`` exactly once per ``schema_key`` per instance.

        Safe to call from ``__init__`` of any service class — subsequent
        calls cost one ``in`` check on a Python ``set`` and return
        immediately without touching SQLite.

        ``create_fn`` must be a zero-argument callable that issues only
        DDL (``CREATE TABLE / INDEX IF NOT EXISTS``).  It MUST NOT call
        ``conn.commit()`` — the registry runs DDL directly on the
        connection in autocommit mode, so every statement commits itself.
        """
        if schema_key in self._schemas_initialized:
            return
        create_fn()
        self._schemas_initialized.add(schema_key)

    def ensure_all_schemas(self) -> None:
        """Pre-warm all known module schemas.

        Call this once during application startup (CLI init, MCP server
        startup, test fixtures) so that the first ``handle_turn()`` never
        pays the DDL cost.  Idempotent — safe to call multiple times.
        """
        # Import here to avoid circular imports at module load time.
        from karma.ml.experience_store import ExperienceStore
        from karma.ml.knowledge_graph import KnowledgeGraph
        from karma.ml.reward_model import RewardModel
        from karma.ml.pattern_learner import PatternLearner
        from karma.ml.needs_engine import NeedsEngine
        from karma.core.context_snapshot import ContextSnapshotStore

        ExperienceStore(self)      # registers "experience_store"
        KnowledgeGraph(self, "")   # registers "knowledge_graph"
        RewardModel(self, "")      # registers "reward_model"
        PatternLearner(self, "")   # registers "pattern_learner"
        NeedsEngine(self)          # registers "needs_engine"
        ContextSnapshotStore(self) # registers "context_snapshot"

    # ─── Query Execution ─────────────────────────────────────────────────

    def execute(self, query: str, params: tuple = ()) -> sqlite3.Cursor:
        """Execute a query within an implicit transaction."""
        conn = self.manager.get_connection()
        return conn.execute(query, params)
    
    def executemany(self, query: str, params_list: List[tuple]) -> sqlite3.Cursor:
        conn = self.manager.get_connection()
        return conn.executemany(query, params_list)
    
    def fetchone(self, query: str, params: tuple = ()) -> Optional[sqlite3.Row]:
        conn = self.manager.get_connection()
        return conn.execute(query, params).fetchone()
    
    def fetchall(self, query: str, params: tuple = ()) -> List[sqlite3.Row]:
        conn = self.manager.get_connection()
        return conn.execute(query, params).fetchall()
    
    # ─── Project Management ───────────────────────────────────────────────
    
    def create_project(self, name: str, metadata: Optional[Dict] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO projects (name, created_at, updated_at, metadata) VALUES (?, ?, ?, ?)",
                (name, now, now, json.dumps(metadata or {}))
            )
            conn.execute(
                "UPDATE projects SET updated_at = ?, metadata = ? WHERE name = ?",
                (now, json.dumps(metadata or {}), name)
            )
    
    def list_projects(self) -> List[Dict[str, Any]]:
        rows = self.fetchall("""
            SELECT p.name, p.created_at, p.updated_at, p.metadata,
                   (SELECT COUNT(DISTINCT domain) FROM facts WHERE project = p.name) as domains,
                   (SELECT COUNT(*) FROM facts WHERE project = p.name) as facts,
                   (SELECT COUNT(*) FROM execution_log WHERE project = p.name) as logs,
                   (SELECT COUNT(DISTINCT domain || key) FROM facts WHERE project = p.name) as indexed
            FROM projects p
            ORDER BY p.updated_at DESC
        """)
        return [dict(r) for r in rows]
    
    def switch_project(self, name: str) -> None:
        self.create_project(name)
        # Active project stored in a simple config key
        with self.transaction() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO schema_meta (key, value) VALUES ('active_project', ?)",
                (name,)
            )
    
    def get_active_project(self) -> str:
        row = self.fetchone("SELECT value FROM schema_meta WHERE key = 'active_project'")
        return row[0] if row else "default"
    
    # ─── Fact Operations (Memory) ────────────────────────────────────────
    
    def get_fact(self, project: str, domain: str, key: str) -> Optional[Any]:
        row = self.fetchone(
            "SELECT value FROM facts WHERE project = ? AND domain = ? AND key = ?",
            (project, domain, key)
        )
        if row:
            return json.loads(row["value"])
        return None
    
    def set_fact(self, project: str, domain: str, key: str, value: Any) -> None:
        now = datetime.now(timezone.utc).isoformat()
        value_json = json.dumps(value, ensure_ascii=False)
        tokens = max(1, len(value_json) // 3)
        value_hash = self._hash_value(value_json)
        
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO facts (project, domain, key, value, tokens, hash, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, domain, key) DO UPDATE SET
                    value = excluded.value,
                    tokens = excluded.tokens,
                    hash = excluded.hash,
                    updated_at = excluded.updated_at
            """, (project, domain, key, value_json, tokens, value_hash, now))
            
            # Update project timestamp
            conn.execute(
                "UPDATE projects SET updated_at = ? WHERE name = ?",
                (now, project)
            )
    
    def get_domain(self, project: str, domain: str) -> Dict[str, Any]:
        rows = self.fetchall(
            "SELECT key, value FROM facts WHERE project = ? AND domain = ?",
            (project, domain)
        )
        return {r["key"]: json.loads(r["value"]) for r in rows}
    
    def delete_fact(self, project: str, domain: str, key: Optional[str] = None) -> bool:
        with self.transaction() as conn:
            if key is None:
                cursor = conn.execute(
                    "DELETE FROM facts WHERE project = ? AND domain = ?",
                    (project, domain)
                )
            else:
                cursor = conn.execute(
                    "DELETE FROM facts WHERE project = ? AND domain = ? AND key = ?",
                    (project, domain, key)
                )
            return cursor.rowcount > 0
    
    def list_domains(self, project: str) -> List[Dict[str, Any]]:
        rows = self.fetchall(""" 
            SELECT domain, COUNT(*) as keys, MAX(updated_at) as last_updated
            FROM facts WHERE project = ? GROUP BY domain
        """, (project,))
        return [dict(r) for r in rows]

    def get_all_memory(self, project: str) -> Dict[str, Any]:
        """Get all memory for a project as a dict with domains."""
        domains = self.list_domains(project)
        result = {"domains": {}}
        for d in domains:
            domain_name = d["domain"]
            result["domains"][domain_name] = self.get_domain(project, domain_name)
        return result

    def get_index(self, project: str) -> Dict[str, Any]:
        """Get index for a project."""
        rows = self.fetchall(
            "SELECT domain, key, tokens, hash, updated_at FROM facts WHERE project = ?",
            (project,)
        )
        return {f"{r['domain']}.{r['key']}": {"tokens": r["tokens"], "hash": r["hash"], "updated": r["updated_at"]} for r in rows}

    # ─── Relevance Queries (Token-Budgeted) ──────────────────────────────
    
    def get_relevant_facts(
        self,
        project: str,
        domains: List[str],
        task_keywords: List[str],
        token_budget: int = 4000
    ) -> Dict[str, Any]:
        """Get facts relevant to task, within token budget."""
        if not domains:
            return {}
        
        placeholders = ",".join("?" * len(domains))
        rows = self.fetchall(
            f"""
            SELECT domain, key, value, tokens
            FROM facts
            WHERE project = ? AND domain IN ({placeholders})
            ORDER BY updated_at DESC
            """,
            (project, *domains)
        )
        
        # Score relevance
        scored = []
        for row in rows:
            relevance = self._score_relevance(f"{row['domain']}.{row['key']}", task_keywords)
            scored.append((relevance, row))
        
        scored.sort(key=lambda x: x[0], reverse=True)
        
        # Fill budget
        result = {}
        used = 0
        for relevance, row in scored:
            if relevance < 0.1:
                continue
            tokens = row["tokens"]
            if used + tokens > token_budget and relevance < 0.5:
                break
            result.setdefault(row["domain"], {})[row["key"]] = json.loads(row["value"])
            used += tokens
        
        return result
    
    def _score_relevance(self, fact_key: str, keywords: List[str]) -> float:
        """Simple keyword-based relevance scoring."""
        score = 0.0
        fact_lower = fact_key.lower()
        for kw in keywords:
            kw_lower = kw.lower()
            if kw_lower in fact_lower:
                score += 1.0
                break
        if score < 0.5:
            for kw in keywords:
                for part in kw.lower().replace("-", "_").split("_"):
                    if len(part) > 3 and part in fact_lower:
                        score += 0.5
                        break
        return min(score, 2.0)
    
    def _hash_value(self, value: str) -> str:
        import hashlib
        return hashlib.md5(value.encode()).hexdigest()[:8]
    
    # ─── Execution Log ───────────────────────────────────────────────────
    
    def add_log_entry(self, project: str, entry: Dict[str, Any]) -> None:
        entry.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        entry.setdefault("project", project)
        
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO execution_log (project, agent, domain, task, outcome, evidence, timestamp, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project,
                entry.get("agent", "unknown"),
                entry.get("domain"),
                entry.get("task", "unknown"),
                entry.get("outcome", "unknown"),
                entry.get("evidence"),
                entry["timestamp"],
                json.dumps({k: v for k, v in entry.items() 
                           if k not in ("project", "agent", "domain", "task", "outcome", "evidence", "timestamp")})
            ))
    
    def load_log(self, project: str, limit: int = 50, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        if agent:
            rows = self.fetchall("""
                SELECT * FROM execution_log 
                WHERE project = ? AND agent = ? 
                ORDER BY timestamp DESC LIMIT ?
            """, (project, agent, limit))
        else:
            rows = self.fetchall("""
                SELECT * FROM execution_log 
                WHERE project = ? 
                ORDER BY timestamp DESC LIMIT ?
            """, (project, limit))
        return [dict(r) for r in rows]
    
    # ─── Cascade State ───────────────────────────────────────────────────
    
    def load_cascade(self, project: str) -> Dict[str, Any]:
        row = self.fetchone(
            "SELECT * FROM cascade_state WHERE project = ?",
            (project,)
        )
        if row:
            data = dict(row)
            data["steps"] = json.loads(data["steps"])
            data["metadata"] = json.loads(data["metadata"])
            return data
        return {"steps": {}, "current": 0, "status": "idle"}
    
    def save_cascade(self, project: str, state: Dict[str, Any]) -> None:
        steps_json = json.dumps(state.get("steps", {}))
        metadata_json = json.dumps(state.get("metadata", {}))
        
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO cascade_state (project, template, description, status, started_at, completed_at, steps, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project) DO UPDATE SET
                    template = excluded.template,
                    description = excluded.description,
                    status = excluded.status,
                    started_at = excluded.started_at,
                    completed_at = excluded.completed_at,
                    steps = excluded.steps,
                    metadata = excluded.metadata
            """, (
                project,
                state.get("template", ""),
                state.get("description", ""),
                state.get("status", "idle"),
                state.get("started_at"),
                state.get("completed_at"),
                steps_json,
                metadata_json
            ))
    
    # ─── Skill State ─────────────────────────────────────────────────────
    
    def load_skill_state(self, project: str) -> Dict[str, Any]:
        rows = self.fetchall(
            "SELECT skill_name, loaded_at, version, metadata FROM skill_state WHERE project = ?",
            (project,)
        )
        return {
            "loaded": {r["skill_name"]: {"loaded_at": r["loaded_at"], "version": r["version"]} for r in rows},
            "history": []
        }
    
    def save_skill_state(self, project: str, state: Dict[str, Any]) -> None:
        loaded = state.get("loaded", {})
        with self.transaction() as conn:
            # Clear and rebuild
            conn.execute("DELETE FROM skill_state WHERE project = ?", (project,))
            for skill_name, info in loaded.items():
                conn.execute("""
                    INSERT INTO skill_state (project, skill_name, loaded_at, version, metadata)
                    VALUES (?, ?, ?, ?, ?)
                """, (project, skill_name, info.get("loaded_at", ""), info.get("version"), "{}"))
    
    # ─── Cross-Project Queries ───────────────────────────────────────────
    
    def cross_project_query(self, domain: str, key: str) -> Dict[str, Any]:
        rows = self.fetchall("""
            SELECT p.name as project, f.value
            FROM facts f
            JOIN projects p ON f.project = p.name
            WHERE f.domain = ? AND f.key = ?
        """, (domain, key))
        return {r["project"]: json.loads(r["value"]) for r in rows}
    
    # ─── Knowledge Graph / Relations ─────────────────────────────────────
    
    def add_relation(
        self,
        project: str,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str,
        metadata: Optional[Dict] = None
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO relations (project, source_type, source_id, relation_type, target_type, target_id, metadata, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project, source_type, source_id, relation_type, target_type, target_id) DO UPDATE SET
                    metadata = excluded.metadata,
                    updated_at = excluded.updated_at
            """, (
                project, source_type, source_id, relation_type, target_type, target_id,
                json.dumps(metadata or {}), now
            ))
            
    def delete_relation(
        self,
        project: str,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str
    ) -> bool:
        with self.transaction() as conn:
            cursor = conn.execute("""
                DELETE FROM relations
                WHERE project = ? AND source_type = ? AND source_id = ?
                  AND relation_type = ? AND target_type = ? AND target_id = ?
            """, (project, source_type, source_id, relation_type, target_type, target_id))
            return cursor.rowcount > 0

    def get_relations(
        self,
        project: str,
        source_id: Optional[str] = None,
        source_type: Optional[str] = None,
        relation_type: Optional[str] = None,
        target_id: Optional[str] = None,
        target_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM relations WHERE project = ?"
        params = [project]
        if source_id:
            query += " AND source_id = ?"
            params.append(source_id)
        if source_type:
            query += " AND source_type = ?"
            params.append(source_type)
        if relation_type:
            query += " AND relation_type = ?"
            params.append(relation_type)
        if target_id:
            query += " AND target_id = ?"
            params.append(target_id)
        if target_type:
            query += " AND target_type = ?"
            params.append(target_type)
            
        rows = self.fetchall(query, tuple(params))
        result = []
        for r in rows:
            d = dict(r)
            d["metadata"] = json.loads(d.get("metadata", "{}"))
            result.append(d)
        return result
    
    # ─── Idempotency ─────────────────────────────────────────────────────
    
    def check_idempotency(self, key: str) -> Optional[Any]:
        row = self.fetchone(
            "SELECT result FROM idempotency_keys WHERE key = ? AND expires_at > ?",
            (key, datetime.now(timezone.utc).isoformat())
        )
        if row and row["result"]:
            return json.loads(row["result"])
        return None
    
    def store_idempotency(
        self,
        key: str,
        project: str,
        operation: str,
        result: Any,
        ttl_hours: int = 24
    ) -> None:
        now = datetime.now(timezone.utc)
        expires = now + timedelta(hours=ttl_hours)
        
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO idempotency_keys (key, project, operation, created_at, expires_at, result)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    result = excluded.result,
                    expires_at = excluded.expires_at
            """, (key, project, operation, now.isoformat(), expires.isoformat(), json.dumps(result)))
    
    # ─── Events / Telemetry ──────────────────────────────────────────────
    
    def emit_event(self, event_type: str, project: Optional[str], payload: Dict, correlation_id: Optional[str] = None) -> None:
        with self.transaction() as conn:
            conn.execute("""
                INSERT INTO events (event_type, project, payload, timestamp, correlation_id)
                VALUES (?, ?, ?, ?, ?)
            """, (event_type, project, json.dumps(payload), datetime.now(timezone.utc).isoformat(), correlation_id))
    
    def get_events(
        self,
        project: Optional[str] = None,
        event_type: Optional[str] = None,
        limit: int = 100
    ) -> List[Dict]:
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        if project:
            query += " AND project = ?"
            params.append(project)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        rows = self.fetchall(query, tuple(params))
        return [dict(r) for r in rows]
    
    # ─── Maintenance ─────────────────────────────────────────────────────
    
    def vacuum(self) -> None:
        conn = self.manager.get_connection()
        conn.execute("VACUUM")
    
    def close(self) -> None:
        self.manager.close_all()


# ─── Migration Helper (JSON → SQLite) ────────────────────────────────────

def migrate_from_json(persistence: PersistenceLayer, json_projects_dir: Path) -> None:
    """One-time migration from JSON files to SQLite.

    Idempotent: writes a ``.migrated.lock`` sentinel after the first successful
    run and skips re-import on subsequent calls (fixes Bug 2 — migration was
    re-running on every DB access and duplicating facts).
    """
    if not json_projects_dir.exists():
        return

    sentinel = json_projects_dir / ".migrated.lock"
    if sentinel.exists():
        return

    for project_dir in json_projects_dir.iterdir():
        if not project_dir.is_dir():
            continue
        
        project = project_dir.name
        persistence.create_project(project)
        
        # memory.json → facts
        mem_path = project_dir / "memory.json"
        if mem_path.exists():
            try:
                data = json.loads(mem_path.read_text())
                for domain, dom_data in data.get("domains", {}).items():
                    for key, value in dom_data.items():
                        if key.startswith("_"):
                            continue
                        persistence.set_fact(project, domain, key, value)
            except (json.JSONDecodeError, OSError):
                pass
        
        # execution_log.json → log
        log_path = project_dir / "execution_log.json"
        if log_path.exists():
            try:
                entries = json.loads(log_path.read_text())
                if isinstance(entries, dict):
                    entries = entries.get("entries", [])
                for entry in entries:
                    persistence.add_log_entry(project, entry)
            except (json.JSONDecodeError, OSError):
                pass
        
        # cascade_state.json → cascade
        cascade_path = project_dir / "cascade_state.json"
        if cascade_path.exists():
            try:
                state = json.loads(cascade_path.read_text())
                persistence.save_cascade(project, state)
            except (json.JSONDecodeError, OSError):
                pass
        
        # skill_state.json → skill_state
        skill_path = project_dir / "skill_state.json"
        if skill_path.exists():
            try:
                state = json.loads(skill_path.read_text())
                persistence.save_skill_state(project, state)
            except (json.JSONDecodeError, OSError):
                pass
        
        # Also check legacy locations
        _migrate_legacy_skill_states(persistence, project)

    # Write sentinel so migration never re-runs (Bug 2 fix)
    try:
        sentinel.write_text(datetime.now(timezone.utc).isoformat())
    except OSError:
        pass


def _migrate_legacy_skill_states(persistence: PersistenceLayer, project: str) -> None:
    """Migrate skill state from legacy locations."""
    legacy_paths = [
        Path.home() / ".hermes" / "syxcraft" / "skill_state.json",
        Path.home() / ".hermes" / "framework" / "projects" / project / "skill_state.json",
    ]
    
    for legacy_path in legacy_paths:
        if legacy_path.exists():
            try:
                state = json.loads(legacy_path.read_text())
                persistence.save_skill_state(project, state)
                break  # Use first found
            except (json.JSONDecodeError, OSError):
                continue


# ─── Factory ──────────────────────────────────────────────────────────────

_persistence_cache: Dict[str, PersistenceLayer] = {}
_persistence_lock = threading.Lock()

def create_persistence(framework_dir: Optional[Path | str] = None) -> PersistenceLayer:
    """Create persistence layer with default config."""
    global _persistence_cache
    if framework_dir is None:
        framework_dir = os.environ.get(
            "LLM_MIDDLEWARE_ROOT",
            str(Path.home() / ".karma")
        )
    fw_path = Path(framework_dir).resolve()
    db_path = fw_path / "middleware.db"
    cache_key = str(db_path)
    
    with _persistence_lock:
        if cache_key not in _persistence_cache:
            config = PersistenceConfig(framework_dir=fw_path)
            persistence = PersistenceLayer(config)
            persistence.ensure_all_schemas()
            _persistence_cache[cache_key] = persistence
        return _persistence_cache[cache_key]


_project_persistence_cache: Dict[str, PersistenceLayer] = {}
_project_persistence_lock = threading.Lock()

def create_project_persistence(project: str = "default") -> PersistenceLayer:
    """Create a project-scoped persistence layer at projects/<project>.db.

    Single source of truth for per-project DB isolation — used by both the CLI
    and the orchestrator so the path convention never drifts.
    """
    global _project_persistence_cache
    projects_dir = Path(
        os.environ.get(
            "LLM_MIDDLEWARE_ROOT",
            str(Path.home() / ".karma"),
        )
    ) / "projects"
    projects_dir.mkdir(parents=True, exist_ok=True)
    db_path = projects_dir / f"{project}.db"
    cache_key = str(db_path.resolve())
    
    with _project_persistence_lock:
        if cache_key not in _project_persistence_cache:
            config = PersistenceConfig(framework_dir=projects_dir, db_filename=f"{project}.db")
            persistence = PersistenceLayer(config)
            persistence.ensure_all_schemas()
            _project_persistence_cache[cache_key] = persistence
        return _project_persistence_cache[cache_key]