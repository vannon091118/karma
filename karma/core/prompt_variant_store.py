from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional
from karma.core.persistence import PersistenceLayer

@dataclass
class PromptVariant:
    id: str
    skill_name: str
    version: int
    content: str          # der eigentliche Prompt-Text
    hash: str
    wins: int = 0
    losses: int = 0
    gate_failures: int = 0
    average_reward: float = 0.0
    average_runtime: float = 0.0
    confidence: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    last_used: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    parent_id: Optional[str] = None   # woher diese Variante abstammt

    @property
    def win_rate(self) -> float:
        total = self.wins + self.losses
        return self.wins / total if total > 0 else 0.5

    @property
    def n_runs(self) -> int:
        return self.wins + self.losses

class PromptVariantStore:
    """
    Verwaltet versionierte Prompt-Varianten pro Skill.
    Persistenz: SQLite via facts-Tabelle mit Namespace 'prompt_variants'.
    """

    def __init__(self, persistence: PersistenceLayer, project: str):
        self.p = persistence
        self.project = project

    def get_best_variant(self, skill_name: str, exploration_rate: float = 0.0) -> Optional[PromptVariant]:
        """
        Policy-driven exploration. Rate determined by caller (e.g. 0.0 in Prod, 0.2 in Testing).
        """
        import random
        variants = self._load_variants(skill_name)
        if not variants:
            return None
        
        now = datetime.now(timezone.utc).isoformat()
        if random.random() < exploration_rate:
            chosen = random.choice(variants)
        else:
            chosen = max(variants, key=lambda v: v.win_rate)
            
        chosen.last_used = now
        self._save_variants(skill_name, variants)
        return chosen

    def record_outcome(self, variant_id: str, skill_name: str, success: bool, reward: float = 0.0, runtime: float = 0.0, gate_passed: bool = True):
        variants = self._load_variants(skill_name)
        for v in variants:
            if v.id == variant_id:
                if success:
                    v.wins += 1
                else:
                    v.losses += 1
                
                if not gate_passed:
                    v.gate_failures += 1
                    
                total = v.wins + v.losses
                
                # EMA for reward and runtime
                alpha = 0.2
                v.average_reward = (1 - alpha) * v.average_reward + alpha * reward
                v.average_runtime = (1 - alpha) * v.average_runtime + alpha * runtime
                
                # Confidence grows with number of runs, capping at 1.0
                v.confidence = min(1.0, total / 20.0)
                break
        self._save_variants(skill_name, variants)

    def propose_variant(self, base: PromptVariant, mutated_content: str) -> PromptVariant:
        """Erzeugt neue Variante aus Mutation. Muss durch FalsificationGate."""
        import hashlib
        h = hashlib.sha256(mutated_content.encode()).hexdigest()[:16]
        return PromptVariant(
            id=f"{base.skill_name}-v{base.version + 1}-{h}",
            skill_name=base.skill_name,
            version=base.version + 1,
            content=mutated_content,
            hash=h,
            parent_id=base.id,
        )

    def _load_variants(self, skill_name: str):
        raw = self.p.get_fact(self.project, "prompt_variants", skill_name)
        if not raw:
            return []
        return [PromptVariant(**v) for v in json.loads(raw)]

    def _save_variants(self, skill_name: str, variants: list):
        self.p.set_fact(
            self.project, "prompt_variants", skill_name,
            json.dumps([v.__dict__ for v in variants])
        )
