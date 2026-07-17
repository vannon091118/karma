"""
KARMA Evidence Core — Epistemische Kontrolle

Trennt reine Behauptungen (Claims) von messbarer Realität (Evidence).
Die EvidenceStore Klasse kümmert sich um die Persistenz in der SQLite Datenbank.
"""

from enum import Enum
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field, asdict
import datetime
import json
import uuid

from karma.core.persistence import PersistenceLayer


class EvidenceType(Enum):
    SOURCE = "source"           # Dokumentation, ADR, Design Doc
    RUNTIME = "runtime"         # Laufzeit-Log, Execution, Gate-Pass
    TEST = "test"               # Testlauf
    REPLAY = "replay"           # Erfolgreicher Retro-Test
    HUMAN = "human"             # User-Feedback / Approved


@dataclass
class Evidence:
    evidence_id: str
    claim_id: str
    evidence_type: EvidenceType
    source: str
    confidence: float
    timestamp: str
    metadata: dict

    @classmethod
    def create(cls, claim_id: str, evidence_type: EvidenceType, source: str, confidence: float, metadata: Optional[dict] = None) -> "Evidence":
        return cls(
            evidence_id=str(uuid.uuid4()),
            claim_id=claim_id,
            evidence_type=evidence_type,
            source=source,
            confidence=confidence,
            timestamp=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            metadata=metadata or {}
        )


@dataclass
class Claim:
    claim_id: str
    project: str
    statement: str
    domain: str
    evidences: List[Evidence] = field(default_factory=list)

    @classmethod
    def create(cls, project: str, statement: str, domain: str) -> "Claim":
        return cls(
            claim_id=str(uuid.uuid4()),
            project=project,
            statement=statement,
            domain=domain
        )


class ClaimStatus(Enum):
    UNVERIFIED = "unverified"
    SUPPORTED = "supported"
    CONFIRMED = "confirmed"
    CONFLICTED = "conflicted"
    DEPRECATED = "deprecated"


class ConfidenceResolver:
    """Berechnet mehrdimensionale Confidence basierend auf Evidenz-Limits und weist einen Status zu."""
    
    LIMITS = {
        EvidenceType.SOURCE: 0.4,
        EvidenceType.TEST: 0.7,
        EvidenceType.RUNTIME: 0.9,
        EvidenceType.REPLAY: 0.95,
        EvidenceType.HUMAN: 1.0
    }

    @staticmethod
    def resolve(claim: Claim) -> Dict[str, Any]:
        scores = {t.value: 0.0 for t in EvidenceType}
        counts = {t: 0 for t in EvidenceType}
        sums = {t: 0.0 for t in EvidenceType}

        has_positive_runtime = False
        has_negative_runtime = False
        has_positive_source = False
        has_negative_source = False

        for ev in claim.evidences:
            counts[ev.evidence_type] += 1
            sums[ev.evidence_type] += ev.confidence
            
            # Simple heuristic for conflict detection:
            # For this prototype, we assume evidence confidence near 0.0 for a claim means it was refuted.
            if ev.evidence_type in (EvidenceType.RUNTIME, EvidenceType.TEST, EvidenceType.REPLAY):
                if ev.confidence > 0.5:
                    has_positive_runtime = True
                else:
                    has_negative_runtime = True
            elif ev.evidence_type == EvidenceType.SOURCE:
                if ev.confidence > 0.0:
                    has_positive_source = True
                else:
                    has_negative_source = True

        overall = 0.0

        for etype in EvidenceType:
            if counts[etype] > 0:
                avg = sums[etype] / counts[etype]
                capped = min(avg, ConfidenceResolver.LIMITS[etype])
                scores[etype.value] = capped
                if capped > overall:
                    overall = capped  # Highest valid evidence defines overall confidence

        scores["overall"] = round(overall, 4)
        
        # Determine Status
        status = ClaimStatus.UNVERIFIED
        
        # Conflict: Intent vs Reality or contradictory runtime results
        if (has_positive_source and has_negative_runtime) or (has_positive_runtime and has_negative_runtime):
            status = ClaimStatus.CONFLICTED
        elif has_positive_runtime and overall >= 0.7:
            status = ClaimStatus.CONFIRMED
        elif has_positive_source and overall > 0.0:
            status = ClaimStatus.SUPPORTED
            
        scores["status"] = status.value
        return scores


class EvidenceStore:
    """Persistence for Claims and Evidence."""
    
    def __init__(self, persistence: PersistenceLayer):
        self.persistence = persistence
        self.persistence.ensure_schema("evidence_store", self._create_schema)

    def _create_schema(self) -> None:
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS claims (
                claim_id TEXT PRIMARY KEY,
                project TEXT NOT NULL,
                statement TEXT NOT NULL,
                domain TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        self.persistence.execute("""
            CREATE TABLE IF NOT EXISTS evidences (
                evidence_id TEXT PRIMARY KEY,
                claim_id TEXT NOT NULL,
                evidence_type TEXT NOT NULL,
                source TEXT NOT NULL,
                confidence REAL NOT NULL,
                timestamp TEXT NOT NULL,
                metadata TEXT NOT NULL,
                FOREIGN KEY(claim_id) REFERENCES claims(claim_id) ON DELETE CASCADE
            )
        """)
        self.persistence.execute("CREATE INDEX IF NOT EXISTS idx_claims_project ON claims(project)")
        self.persistence.execute("CREATE INDEX IF NOT EXISTS idx_evidences_claim ON evidences(claim_id)")

    def save_claim(self, claim: Claim) -> None:
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self.persistence.transaction() as conn:
            conn.execute("""
                INSERT OR IGNORE INTO claims (claim_id, project, statement, domain, created_at)
                VALUES (?, ?, ?, ?, ?)
            """, (claim.claim_id, claim.project, claim.statement, claim.domain, now))
            
            for ev in claim.evidences:
                conn.execute("""
                    INSERT OR IGNORE INTO evidences (evidence_id, claim_id, evidence_type, source, confidence, timestamp, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    ev.evidence_id, 
                    ev.claim_id, 
                    ev.evidence_type.value, 
                    ev.source, 
                    ev.confidence, 
                    ev.timestamp, 
                    json.dumps(ev.metadata)
                ))

    def get_claim(self, claim_id: str) -> Optional[Claim]:
        claim_row = self.persistence.fetchone("SELECT * FROM claims WHERE claim_id = ?", (claim_id,))
        if not claim_row:
            return None
            
        evidence_rows = self.persistence.fetchall("SELECT * FROM evidences WHERE claim_id = ?", (claim_id,))
        evidences = []
        for r in evidence_rows:
            evidences.append(Evidence(
                evidence_id=r["evidence_id"],
                claim_id=r["claim_id"],
                evidence_type=EvidenceType(r["evidence_type"]),
                source=r["source"],
                confidence=r["confidence"],
                timestamp=r["timestamp"],
                metadata=json.loads(r["metadata"])
            ))
            
        return Claim(
            claim_id=claim_row["claim_id"],
            project=claim_row["project"],
            statement=claim_row["statement"],
            domain=claim_row["domain"],
            evidences=evidences
        )

    def get_claims_by_project(self, project: str) -> List[Claim]:
        rows = self.persistence.fetchall("SELECT claim_id FROM claims WHERE project = ?", (project,))
        claims = []
        for r in rows:
            claim = self.get_claim(r["claim_id"])
            if claim:
                claims.append(claim)
        return claims

