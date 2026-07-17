from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional, Callable, Any
from karma.ml.reward_model import RewardModel, RewardSignal, ScoreBreakdown
from karma.ml.pattern_learner import PatternLearner
from karma.ml.experience_store import ExperienceStore, Experience
from karma.core.persistence import PersistenceLayer
import hashlib, time

@dataclass
class LLMCallContext:
    project: str
    task: str
    skill_name: str
    prompt_variant_id: str
    prompt_hash: str
    
    # Traceability IDs
    request_id: str = ""
    execution_id: str = ""
    context_snapshot_id: str = ""
    llm_call_id: str = ""
    tool_call_id: Optional[str] = None
    request_payload: str = ""
    model_name: str = "unknown"

def capture_outcome(
    ctx: LLMCallContext,
    response: str,
    gate_passed: bool,
    duration_seconds: float,
    persistence: PersistenceLayer,
    failure_type: str = None
) -> ScoreBreakdown:
    """
    Coordinates the feedback loop:
    1. Records the immutable Experience.
    2. Calculates the Reward.
    3. Updates the PatternLearner.
    """
    # 1. Experience Store
    es = ExperienceStore(persistence)
    exp = Experience(
        request_id=ctx.request_id,
        execution_id=ctx.execution_id,
        llm_call_id=ctx.llm_call_id,
        tool_call_id=ctx.tool_call_id,
        project=ctx.project,
        task=ctx.task,
        request_payload=ctx.request_payload,
        context_snapshot_id=ctx.context_snapshot_id,
        prompt_variant_id=ctx.prompt_variant_id,
        model_name=ctx.model_name,
        duration_seconds=duration_seconds,
        gate_passed=gate_passed,
        failure_type=failure_type,
        # Algorithm versions should theoretically be pulled from the actual modules.
        # Hardcoding "1.0" as a placeholder for now.
        reward_model_version="1.0",
        gate_version="1.0",
        pattern_learner_version="1.0",
        context_selector_version="1.0",
        prompt_engine_version="1.0"
    )
    es.record(exp)

    # 2. Reward Model
    rm = RewardModel(persistence, ctx.project)
    signal = RewardSignal(
        project=ctx.project,
        task=ctx.task,
        skill_name=ctx.skill_name,
        outcome="success" if gate_passed else "failure",
        gate_passed=gate_passed,
        duration_seconds=duration_seconds,
        extra={
            "experience_id": exp.id,
            "variant_id": ctx.prompt_variant_id,
            "prompt_hash": ctx.prompt_hash,
            "response_len": len(response),
            "failure_type": failure_type
        }
    )
    breakdown = rm.score(signal)

    # 3. Pattern Learner
    pl = PatternLearner(persistence, ctx.project)
    pl.store(
        task=ctx.task,
        skill_used=ctx.skill_name,
        approach=f"Prompt variant {ctx.prompt_variant_id}",
        outcome=signal.outcome,
        score=breakdown.final,
        metadata={"variant_id": ctx.prompt_variant_id, "experience_id": exp.id},
    )

    # 4. Knowledge Graph
    from karma.ml.knowledge_graph import KnowledgeGraph
    kg = KnowledgeGraph(persistence, ctx.project)
    kg.update_from_experience(exp.id, breakdown.final)

    return breakdown
