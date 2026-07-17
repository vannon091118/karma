"""
Context Snapshot Store

Saves the exact context string that was presented to the LLM during an execution.
This prevents historical drift where a file changes and suddenly old experiences
are inexplicable. "Festplatten kosten heute weniger als Entwicklerzeit."
"""

import hashlib
import uuid
import zlib
from datetime import datetime, timezone
from typing import Optional
from karma.core.persistence import PersistenceLayer

class ContextSnapshotStore:
    def __init__(self, persistence: PersistenceLayer):
        self.persistence = persistence
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS context_snapshots (
                id TEXT PRIMARY KEY,
                content_hash TEXT NOT NULL,
                compressed_blob BLOB NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.persistence.manager.get_connection().commit()

    def save_snapshot(self, context_text: str) -> str:
        """Saves a compressed snapshot of the context and returns its ID."""
        content_hash = hashlib.sha256(context_text.encode('utf-8')).hexdigest()
        
        # Check if we already have this exact context saved
        existing = self.persistence.fetchone(
            "SELECT id FROM context_snapshots WHERE content_hash = ?", (content_hash,)
        )
        if existing:
            return existing["id"]

        snapshot_id = f"ctx_{uuid.uuid4().hex[:12]}"
        compressed = zlib.compress(context_text.encode('utf-8'))
        
        with self.persistence.transaction() as conn:
            conn.execute("""
                INSERT INTO context_snapshots (id, content_hash, compressed_blob, created_at)
                VALUES (?, ?, ?, ?)
            """, (snapshot_id, content_hash, compressed, datetime.now(timezone.utc).isoformat()))
            
        return snapshot_id

    def load_snapshot(self, snapshot_id: str) -> Optional[str]:
        """Loads and decompresses a historical context snapshot."""
        row = self.persistence.fetchone(
            "SELECT compressed_blob FROM context_snapshots WHERE id = ?", (snapshot_id,)
        )
        if not row:
            return None
            
        return zlib.decompress(row["compressed_blob"]).decode('utf-8')
