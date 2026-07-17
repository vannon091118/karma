"""
KARMA — Turn Kernel

Ein kompletter Agenten-Turn (Gate-Check -> unveränderliche Erfahrung ->
Reward -> Knowledge-Graph-Update -> Event) an EINER Stelle, aufrufbar
sowohl von der CLI als auch von einem lang laufenden Prozess wie einem
MCP-Server. Das ist die Transaktionsgrenze, die in den bisherigen
MCP-Skelett-Versuchen im Wrapper selbst lag und dort nicht hingehört.

Platzierung — bewusste Entscheidung, nicht Zufall:
    NICHT unter `experimental_runtime/`.
    Neuen kritischen Code dort abzulegen würde die offene Fragmentierung
    vertiefen statt sie aufzulösen. Dieses Modul liegt deshalb top-level.

    NICHT unter `ml/`. Der Turn orchestriert mehr als Machine Learning
    (Gate, EventBus, Idempotenz-Layer der Persistence).
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from karma.core.persistence import PersistenceLayer
from karma.core.falsification_gate import FalsificationGate
from karma.ml.experience_store import ExperienceStore, Experience
from karma.ml.reward_model import RewardModel, RewardSignal
from karma.ml.knowledge_graph import KnowledgeGraph
from karma.bus.event_bus import Event, EventType, get_global_bus


@dataclass
class Policy:
    reward_model_version: str = "1.0"
    gate_version: str = "2026-07"


class PolicyResolver:
    def __init__(self, persistence: PersistenceLayer, project: str):
        self.persistence = persistence
        self.project = project

    def resolve(self) -> Policy:
        stored = self.persistence.get_fact(self.project, "governance", "active_policy")
        if isinstance(stored, dict):
            return Policy(
                reward_model_version=stored.get("reward_model_version", "1.0"),
                gate_version=stored.get("gate_version", "2026-07"),
            )
        return Policy()


@dataclass
class TurnRequest:
    project: str
    request_id: str          
    task: str
    content: str              
    skill_name: str = "external_agent"
    outcome: str = "success"  
    user_feedback: Optional[float] = None
    context_snapshot_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.outcome not in ("success", "partial", "failure"):
            raise ValueError(
                f"outcome muss 'success'/'partial'/'failure' sein, nicht {self.outcome!r}"
            )


@dataclass
class TurnResult:
    gate_passed: bool
    probes: List[Dict[str, Any]]
    experience_id: Optional[str] = None
    reward: Optional[float] = None
    idempotent_replay: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "gate_passed": self.gate_passed,
            "probes": self.probes,
            "experience_id": self.experience_id,
            "reward": self.reward,
            "idempotent_replay": self.idempotent_replay,
        }


class GateFailure(Exception):
    pass


def handle_turn(persistence: PersistenceLayer, req: TurnRequest) -> TurnResult:
    """Ein kompletter Agenten-Turn.

    Idempotenz-Strategie:
        Der Check und alle nachfolgenden Writes laufen innerhalb DERSELBEN
        BEGIN IMMEDIATE-Transaktion. Das verhindert den TOCTOU-Fensterspalt,
        bei dem zwei Threads gleichzeitig check_idempotency() == None sehen
        und dann beide schreiben.

        Ablauf:
            1. BEGIN IMMEDIATE  ← schließt alle anderen Writer aus
            2. check_idempotency (innerhalb Tx)
            3. wenn Cache-Hit: ROLLBACK (kein Schreiben), Return cached
            4. sonst: Gate, Experience, Reward, KG, store_idempotency, COMMIT
    """
    bus = get_global_bus()
    idem_key = f"turn:{req.project}:{req.request_id}"

    policy = PolicyResolver(persistence, req.project).resolve()

    # ─── Gate (außerhalb Tx – ist CPU/IO-bound, kein DB-Write) ──────────
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(req.content)
            tmp_path = f.name
        gate = FalsificationGate(persistence, req.project)
        gate_passed, probe_results = gate.run(
            step_name=req.task,
            skill_name=req.skill_name,
            output_file=tmp_path,
            cascade_state={"steps": {}, "current_step": req.task},
        )
    except OSError as e:
        raise GateFailure(f"Gate konnte nicht ausgeführt werden: {e}") from e
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    from karma.core.evidence import EvidenceStore, Claim, Evidence
    evidence_store = EvidenceStore(persistence)
    turn_claim = Claim.create(req.project, f"Turn execution for task: {req.task} completed successfully", domain="turn_execution")
    for r in probe_results:
        ev = Evidence.create(
            claim_id=turn_claim.claim_id,
            evidence_type=r.evidence_type,
            source=f"GateProbe::{r.probe_name}",
            confidence=r.evidence_strength,
            metadata={"evidence_str": r.evidence_str, "details": r.details}
        )
        turn_claim.evidences.append(ev)
    
    evidence_store.save_claim(turn_claim)

    probes_dict = [r.to_dict() for r in probe_results]

    with persistence.transaction() as _conn:
        # ─── Idempotenz-Check inside the exclusive lock ──────────────────
        cached = persistence.check_idempotency(idem_key)
        if cached is not None:
            result = TurnResult(**cached)
            result.idempotent_replay = True
            return result

        bus.publish_persisted(
            Event(
                type=EventType.GATE_PASSED if gate_passed else EventType.GATE_FAILED,
                project=req.project,
                payload={"task": req.task, "probes": probes_dict},
                source="turn_kernel",
            ),
            persistence,
        )

        # ─── Experience (unveränderlich) ───────────────────────────────────
        # FIX: Auch Gate-Fails als Experience protokollieren!
        exp = Experience(
            project=req.project,
            request_id=req.request_id,
            task=req.task,
            gate_passed=gate_passed,
            failure_type=None if gate_passed else "falsification_failed",
            reward_model_version=policy.reward_model_version,
            gate_version=policy.gate_version,
            context_snapshot_id=req.context_snapshot_id or "",
        )
        ExperienceStore(persistence).record(exp)

        # ─── Reward ─────────────────────────────────────────────────────────
        reward_model = RewardModel(persistence, req.project)
        breakdown = reward_model.score(
            RewardSignal(
                project=req.project,
                task=req.task,
                outcome=req.outcome,
                gate_passed=gate_passed,
                skill_name=req.skill_name,
                correlation_id=req.request_id,
                user_feedback=req.user_feedback,
            )
        )
        
        bus.publish(
            Event(
                type=EventType.REWARD_SCORED,
                project=req.project,
                payload={"experience_id": exp.id, "reward": breakdown.final},
                source="turn_kernel",
            )
        )

        # ─── Knowledge Graph ────────────────────────────────────────────────
        kg = KnowledgeGraph(persistence, project=req.project)
        kg.update_from_experience(exp.id, breakdown.final)
        kg_updated = bool(exp.context_snapshot_id)
        
        bus.publish_persisted(
            Event(
                type=EventType.KNOWLEDGE_DISTILLED,
                project=req.project,
                payload={"experience_id": exp.id, "task": req.task, "kg_updated": kg_updated},
                source="turn_kernel",
            ),
            persistence,
        )

        result = TurnResult(
            gate_passed=gate_passed,
            probes=probes_dict,
            experience_id=exp.id,
            reward=breakdown.final,
        )
        
        persistence.store_idempotency(
            key=idem_key, project=req.project, operation="turn", result=result.to_dict()
        )
    return result
