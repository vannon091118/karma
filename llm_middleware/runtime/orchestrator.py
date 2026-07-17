#!/usr/bin/env python3
"""
LLM Middleware Runtime — Skill Cascade Engine (Orchestrator)

Assembles contextual LLM prompts by chaining skills together in a Directed Acyclic Graph (DAG).
Execution means generating the exact injected context the LLM needs for the given step in the cascade.

Cascade lifecycle:
  start → [prompt → complete]* → done
  
Steps can run in parallel when their dependencies are met.
State persists per-project in cascade_state.json via memory_core.
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_middleware.runtime import memory_core
from llm_middleware.runtime import skill_registry as _skill_registry_module

# Lazy wrapper kept for API compatibility; now backed by the installed package
def _get_skill_registry():
    return _skill_registry_module


# ─── Cascade Templates ──────────────────────────────────────────────────────

TEMPLATES: Dict[str, Dict[str, Any]] = {
    "full-pipeline": {
        "name": "full-pipeline",
        "description": "Standard 4-phase: dump-analyse → konzept → execution → tests",
        "steps": [
            {"name": "analyze", "skill": "dump-analyse", "depends_on": []},
            {"name": "design", "skill": "konzept", "depends_on": ["analyze"]},
            {"name": "execute", "skill": "execution", "depends_on": ["design"]},
            {"name": "verify", "skill": "tests", "depends_on": ["execute"]},
        ],
    },
    "quick-fix": {
        "name": "quick-fix",
        "description": "Bypass design phase — straight to execution and cleanup",
        "steps": [
            {"name": "execute", "skill": "execution", "depends_on": []},
            {"name": "cleanup", "skill": "repo-clean", "depends_on": ["execute"]},
        ],
    },
    "research-only": {
        "name": "research-only",
        "description": "Parallel research tasks, unified summary at the end",
        "steps": [
            {"name": "sdk-research", "skill": "game-modding-research", "depends_on": []},
            {"name": "mod-analysis", "skill": "game-modding-analysis", "depends_on": []},
            {"name": "summary", "skill": "plan", "depends_on": ["sdk-research", "mod-analysis"]},
        ],
    },
    "quality-audit": {
        "name": "quality-audit",
        "description": "Fullscan → SSOT audit → tree validation → cleanup",
        "steps": [
            {"name": "scan", "skill": "fullscan", "depends_on": []},
            {"name": "ssot-audit", "skill": "ssot-audit", "depends_on": ["scan"]},
            {"name": "tree-check", "skill": "tree-valid", "depends_on": ["scan"]},
            {"name": "cleanup", "skill": "repo-clean", "depends_on": ["ssot-audit", "tree-check"]},
        ],
    },
    "falsification": {
        "name": "falsification",
        "description": "Anti-confirm-bias validation: repo-clean-f, ssot-audit-f, tree-valid-f",
        "steps": [
            {"name": "falsify-repo", "skill": "repo-clean-falsifizierung", "depends_on": []},
            {"name": "falsify-ssot", "skill": "ssot-audit-falsifizierung", "depends_on": []},
            {"name": "falsify-tree", "skill": "tree-valid-falsifizierung", "depends_on": []},
        ],
    },
    "syxcraft-mod": {
        "name": "syxcraft-mod",
        "description": "SyxCraft modding pipeline: research → analysis → engine chain → modding → assets",
        "steps": [
            {"name": "research", "skill": "game-modding-research", "depends_on": []},
            {"name": "analysis", "skill": "game-modding-analysis", "depends_on": ["research"]},
            {"name": "engine", "skill": "syxcraft-engine-chain", "depends_on": ["analysis"]},
            {"name": "mod", "skill": "syxcraft-modding", "depends_on": ["engine"]},
            {"name": "assets", "skill": "syxcraft-asset-generator", "depends_on": ["mod"]},
        ],
    },
}


# ─── Cascade Operations ─────────────────────────────────────────────────────

def _ensure_project(project: str) -> None:
    """Verify project exists in the memory core."""
    projects = [p["name"] for p in memory_core.list_projects()]
    if project not in projects:
        # Create it if it doesn't exist (projects are lazy-created)
        memory_core.save_memory(project, {
            "project": project,
            "domains": {},
            "created": datetime.now(timezone.utc).isoformat(),
        })


def _get_stale_domains(project: str, required_domains: List[str], since: str) -> List[str]:
    """Check if domain data has been updated since cascade started."""
    stale = []
    memory = memory_core.load_memory(project)
    for dom in required_domains:
        updated = memory.get("domains", {}).get(dom, {}).get("_last_updated")
        if updated and since and updated > since:
            stale.append(dom)
    return stale


def _resolve_skill_domains(skill_name: str) -> List[str]:
    """Find which domains a skill maps to."""
    sr = _get_skill_registry()
    skills = sr.discover_skills()
    manifest = sr._load_manifest()
    domain_map = sr._map_skills_to_domains(skills, manifest)
    return [d for d, s_list in domain_map.items() if skill_name in s_list]


def _load_skill_content(skill_name: str) -> str:
    """Read the SKILL.md content for a named skill."""
    sr = _get_skill_registry()
    skills = sr.discover_skills()
    if skill_name not in skills:
        return f"[SKILL NOT FOUND: {skill_name}]"
    skill_path = Path(skills[skill_name]["abs_path"])
    try:
        return skill_path.read_text(encoding="utf-8")
    except OSError:
        return f"[SKILL UNREADABLE: {skill_path}]"


def init_cascade(project: str, template_name: str) -> None:
    """Initialize a new cascade from a template."""
    _ensure_project(project)
    if template_name not in TEMPLATES:
        print(f"ERROR: Template '{template_name}' not found. Available: {', '.join(sorted(TEMPLATES.keys()))}", file=sys.stderr)
        sys.exit(1)

    template = TEMPLATES[template_name]
    state = {
        "template": template_name,
        "description": template.get("description", ""),
        "status": "in_progress",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "execution_id": f"exec_{uuid.uuid4().hex[:12]}",
        "steps": {},
    }

    for step in template["steps"]:
        state["steps"][step["name"]] = {
            "status": "ready" if not step["depends_on"] else "pending",
            "skill": step["skill"],
            "depends_on": step["depends_on"],
            "output_path": None,
            "completed_at": None,
        }

    memory_core.save_cascade(project, state)
    ready = get_next_steps(state)
    print(f"✅ Initialized '{template_name}' for project '{project}'")
    print(f"   Steps: {len(template['steps'])}, Ready now: {', '.join(ready) if ready else 'none'}")


def get_next_steps(cascade_state: Dict[str, Any]) -> List[str]:
    """Identify steps that are ready to execute (all dependencies met)."""
    if cascade_state.get("status") == "completed":
        return []

    ready_steps = []
    for name, data in cascade_state.get("steps", {}).items():
        if data["status"] == "pending":
            deps_met = all(
                cascade_state["steps"].get(dep, {}).get("status") == "completed"
                for dep in data.get("depends_on", [])
            )
            if deps_met:
                data["status"] = "ready"

        if data["status"] == "ready":
            ready_steps.append(name)

    return ready_steps


def generate_step_prompt(project: str, step_name: str) -> Dict[str, Any]:
    """
    Build the full prompt context for a cascade step.
    
    Combines:
    1. Skill definition (SKILL.md content)
    2. Relevant domain memory facts (token-budgeted)
    3. Previous step outputs
    4. Cascade metadata
    """
    _ensure_project(project)
    state = memory_core.load_cascade(project)

    if step_name not in state.get("steps", {}):
        print(f"ERROR: Step '{step_name}' not found in cascade.", file=sys.stderr)
        sys.exit(1)

    step_data = state["steps"][step_name]
    if step_data["status"] not in ("ready", "failed"):
        print(f"WARN: Step '{step_name}' is '{step_data['status']}', not ready.", file=sys.stderr)
        sys.exit(1)

    skill_name = step_data["skill"]

    # 1. Skill definition via PromptVariantStore
    from llm_middleware.core.persistence import create_persistence
    from llm_middleware.core.prompt_variant_store import PromptVariantStore
    import hashlib

    p = create_persistence()
    store = PromptVariantStore(p, project)
    
    # Policy-driven exploration rate (0.0 by default in prod, higher in testing)
    exploration_rate = state.get("exploration_rate", 0.0)
    variant = store.get_best_variant(skill_name, exploration_rate)

    variant_id = "default"
    variant_hash = "none"

    if variant:
        skill_content = variant.content
        variant_id = variant.id
        variant_hash = variant.hash
    else:
        skill_content = _load_skill_content(skill_name)
        variant_hash = hashlib.sha256(skill_content.encode("utf-8")).hexdigest()[:16]

    # Save variant info for complete_step
    state["steps"][step_name]["variant_id"] = variant_id
    state["steps"][step_name]["prompt_hash"] = variant_hash
    memory_core.save_cascade(project, state)

    # 2. Previous step outputs
    prev_outputs: Dict[str, str] = {}
    for dep in step_data.get("depends_on", []):
        dep_data = state["steps"].get(dep, {})
        dep_out = dep_data.get("output_path")
        if dep_out and os.path.exists(dep_out):
            try:
                with open(dep_out, "r", encoding="utf-8") as f:
                    prev_outputs[dep] = f.read()[:4000]  # Truncate for token budget
            except OSError:
                prev_outputs[dep] = f"[UNREADABLE: {dep_out}]"

    # 3. Domain memory facts
    skill_domains = _resolve_skill_domains(skill_name)
    sr = _get_skill_registry()
    skills = sr.discover_skills()
    task_keywords = skills.get(skill_name, {}).get("tags", [])

    # 4. Context assembly
    context_dict = context_optimizer.assemble_context(
        project=project,
        domains=skill_domains,
        task_keywords=step_data["skill"].split("-"),
        token_budget=8000
    )

    # Save immutable context snapshot
    import json
    from llm_middleware.core.context_snapshot import ContextSnapshotStore
    snapshot_store = ContextSnapshotStore(p)
    context_text = json.dumps(context_dict, ensure_ascii=False)
    snapshot_id = snapshot_store.save_snapshot(context_text)
    state["steps"][step_name]["context_snapshot_id"] = snapshot_id
    memory_core.save_cascade(project, state)

    # 4. Staleness warnings
    stale_domains = _get_stale_domains(project, skill_domains, state.get("started_at", ""))

    # Assemble
    prompt = {
        "cascade": {
            "template": state.get("template"),
            "step": step_name,
            "total_steps": len(state.get("steps", {})),
            "completed": sum(1 for s in state["steps"].values() if s["status"] == "completed"),
        },
        "instruction": f"Execute skill '{skill_name}' as cascade step '{step_name}'.",
        "skill_definition": skill_content,
        "domain_facts": context_dict,
        "previous_outputs": prev_outputs,
        "warnings": [],
    }

    if stale_domains:
        prompt["warnings"].append(
            f"Domains updated mid-cascade: {stale_domains}. Context reflects latest state."
        )

    return prompt


def complete_step(project: str, step_name: str, output_file: str) -> None:
    """Mark a cascade step as completed and store its output path."""
    _ensure_project(project)
    state = memory_core.load_cascade(project)

    if step_name not in state.get("steps", {}):
        print(f"ERROR: Step '{step_name}' not found.", file=sys.stderr)
        sys.exit(1)

    if not os.path.exists(output_file):
        print(f"ERROR: Output file '{output_file}' not found.", file=sys.stderr)
        sys.exit(1)

    state["steps"][step_name]["status"] = "completed"
    state["steps"][step_name]["output_path"] = os.path.abspath(output_file)
    state["steps"][step_name]["completed_at"] = datetime.now(timezone.utc).isoformat()

    # --- ML FEEDBACK LOOP (Outcome Capture) ---
    from llm_middleware.core.persistence import create_persistence
    from llm_middleware.core.prompt_variant_store import PromptVariantStore
    from llm_middleware.runtime.falsification_gate import FalsificationGate
    from llm_middleware.runtime.outcome_middleware import LLMCallContext, capture_outcome
    import time

    p = create_persistence()
    gate = FalsificationGate(p, project)
    gate_passed, gate_results = gate.run(step_name, state["steps"][step_name]["skill"], output_file, state)

    failure_type = None
    if not gate_passed:
        failed = [res.probe_name for res in gate_results if not res.passed]
        if failed:
            failure_type = failed[0]

    variant_id = state["steps"][step_name].get("variant_id", "default")
    variant_hash = state["steps"][step_name].get("prompt_hash", "none")
    execution_id = state.get("execution_id", "exec_legacy")
    context_snapshot_id = state["steps"][step_name].get("context_snapshot_id", "none")

    # Calculate duration (fallback to 10s if not tracked accurately)
    started_str = state["steps"][step_name].get("started_at")
    duration = 10.0
    if started_str:
        try:
            started = datetime.fromisoformat(started_str)
            duration = (datetime.now(timezone.utc) - started).total_seconds()
        except ValueError:
            pass

    response_content = Path(output_file).read_text(encoding="utf-8")

    import uuid
    ctx = LLMCallContext(
        project=project,
        task=step_name,
        skill_name=state["steps"][step_name]["skill"],
        prompt_variant_id=variant_id,
        prompt_hash=variant_hash,
        execution_id=execution_id,
        context_snapshot_id=context_snapshot_id,
        llm_call_id=f"call_{uuid.uuid4().hex[:12]}"
    )

    try:
        breakdown = capture_outcome(ctx, response_content, gate_passed, duration, p, failure_type=failure_type)
        print(f"✅ ML Outcome captured! Gate passed: {gate_passed}. Reward: {breakdown.final:.2f}")

        if variant_id != "default":
            store = PromptVariantStore(p, project)
            success = gate_passed and breakdown.outcome_score > 0
            store.record_outcome(
                variant_id=variant_id, 
                skill_name=state["steps"][step_name]["skill"], 
                success=success,
                reward=breakdown.final,
                runtime=duration,
                gate_passed=gate_passed
            )
    except Exception as e:
        print(f"⚠️ ML capture failed (non-fatal): {e}", file=sys.stderr)
    # --- END ML FEEDBACK LOOP ---

    # Check if cascade is fully done
    all_done = all(s["status"] == "completed" for s in state["steps"].values())
    if all_done:
        state["status"] = "completed"
        state["completed_at"] = datetime.now(timezone.utc).isoformat()

    memory_core.save_cascade(project, state)

    # Log the step completion
    memory_core.add_log_entry(project, {
        "agent": "orchestrator",
        "domain": "cascade",
        "task": f"step_complete:{step_name}",
        "outcome": "success",
        "evidence": output_file,
    })

    # Report next steps
    ready = get_next_steps(state)
    if all_done:
        print(f"✅ Cascade COMPLETE. All {len(state['steps'])} steps finished.")
    else:
        print(f"✅ Step '{step_name}' completed. Next: {', '.join(ready)}")


def fail_step(project: str, step_name: str, error: str) -> None:
    """Mark a cascade step as failed."""
    _ensure_project(project)
    state = memory_core.load_cascade(project)

    if step_name not in state.get("steps", {}):
        print(f"ERROR: Step '{step_name}' not found.", file=sys.stderr)
        sys.exit(1)

    state["steps"][step_name]["status"] = "failed"
    state["steps"][step_name]["error"] = error
    state["steps"][step_name]["completed_at"] = datetime.now(timezone.utc).isoformat()
    state["status"] = "blocked"

    memory_core.save_cascade(project, state)

    memory_core.add_log_entry(project, {
        "agent": "orchestrator",
        "domain": "cascade",
        "task": f"step_fail:{step_name}",
        "outcome": "failure",
        "evidence": error,
    })

    print(f"❌ Step '{step_name}' FAILED: {error}", file=sys.stderr)
    print(f"   Cascade BLOCKED. Fix the issue and re-run, or reset with 'reset'.", file=sys.stderr)


def reset_cascade(project: str) -> None:
    """Clear cascade state for a project."""
    memory_core.save_cascade(project, {"steps": [], "current": 0, "status": "idle"})
    print(f"🔄 Cascade reset for project '{project}'.")


# ─── CLI Commands ────────────────────────────────────────────────────────────

def cmd_templates() -> None:
    """List all available cascade templates."""
    print(f"{'TEMPLATE':<20} {'STEPS':<6} {'DESCRIPTION'}")
    print("─" * 70)
    for name, tmpl in sorted(TEMPLATES.items()):
        steps = len(tmpl["steps"])
        desc = tmpl.get("description", "")
        print(f"{name:<20} {steps:<6} {desc}")
    print(f"\nUse: orchestrator.py start <project> <template>")


def cmd_status(project: str) -> None:
    """Show cascade progress for a project."""
    _ensure_project(project)
    state = memory_core.load_cascade(project)

    if not state.get("steps"):
        print(f"No active cascade for project '{project}'.")
        return

    status_icon = {"in_progress": "🔄", "completed": "✅", "blocked": "❌"}.get(state.get("status"), "❓")
    print(f"Cascade: {state.get('template', '?')} {status_icon} [{state.get('status', '?').upper()}]")
    print(f"Started: {state.get('started_at', '?')[:19]}")
    print()

    for name, data in state["steps"].items():
        icon = {"completed": "✅", "ready": "🟢", "pending": "⏳", "failed": "❌"}.get(data["status"], "❓")
        deps = f" ← {','.join(data['depends_on'])}" if data.get("depends_on") else ""
        skill = data.get("skill", "?")
        print(f"  {icon} {name:<18} {skill:<25} [{data['status']}]{deps}")

    ready = get_next_steps(state)
    if ready:
        print(f"\n▶ Next: {', '.join(ready)}")
        print(f"  Run: orchestrator.py prompt {project} {ready[0]}")


def cmd_next(project: str) -> None:
    """Show next ready steps."""
    _ensure_project(project)
    state = memory_core.load_cascade(project)
    ready = get_next_steps(state)
    if ready:
        for step in ready:
            skill = state["steps"][step].get("skill", "?")
            print(f"  🟢 {step} ({skill})")
    else:
        status = state.get("status", "unknown")
        if status == "completed":
            print("✅ All steps completed.")
        elif status == "blocked":
            print("❌ Cascade blocked by a failed step.")
        else:
            print("No steps ready.")


def cmd_prompt(project: str, step_name: str) -> None:
    """Generate and print the full prompt context for a step."""
    prompt = generate_step_prompt(project, step_name)
    print(json.dumps(prompt, indent=2, ensure_ascii=False))


def cmd_complete(project: str, step_name: str, output_file: str) -> None:
    """Mark a step as complete with its output file."""
    complete_step(project, step_name, output_file)


def cmd_fail(project: str, step_name: str, error: str) -> None:
    """Mark a step as failed."""
    fail_step(project, step_name, error)


def cmd_reset(project: str) -> None:
    """Reset cascade state."""
    reset_cascade(project)


# ─── Main ────────────────────────────────────────────────────────────────────

USAGE = """LLM Middleware — Skill Cascade Engine (Orchestrator)

Usage:
    orchestrator.py templates                          List cascade templates
    orchestrator.py start <project> <template>         Initialize cascade from template
    orchestrator.py status <project>                   Show cascade progress
    orchestrator.py next <project>                     Show next ready steps
    orchestrator.py prompt <project> <step>            Generate LLM prompt for a step
    orchestrator.py complete <project> <step> <file>   Mark step done with output file
    orchestrator.py fail <project> <step> <error>      Mark step as failed
    orchestrator.py reset <project>                    Clear cascade state
"""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(USAGE)
        return 1

    command = argv[1]

    if command == "templates":
        cmd_templates()
    elif command == "start":
        if len(argv) < 4:
            print("Usage: orchestrator.py start <project> <template>", file=sys.stderr)
            return 1
        init_cascade(argv[2], argv[3])
    elif command == "status":
        if len(argv) < 3:
            print("Usage: orchestrator.py status <project>", file=sys.stderr)
            return 1
        cmd_status(argv[2])
    elif command == "next":
        if len(argv) < 3:
            print("Usage: orchestrator.py next <project>", file=sys.stderr)
            return 1
        cmd_next(argv[2])
    elif command == "prompt":
        if len(argv) < 4:
            print("Usage: orchestrator.py prompt <project> <step>", file=sys.stderr)
            return 1
        cmd_prompt(argv[2], argv[3])
    elif command == "complete":
        if len(argv) < 5:
            print("Usage: orchestrator.py complete <project> <step> <file>", file=sys.stderr)
            return 1
        cmd_complete(argv[2], argv[3], argv[4])
    elif command == "fail":
        if len(argv) < 5:
            print("Usage: orchestrator.py fail <project> <step> <error>", file=sys.stderr)
            return 1
        cmd_fail(argv[2], argv[3], argv[4])
    elif command == "reset":
        if len(argv) < 3:
            print("Usage: orchestrator.py reset <project>", file=sys.stderr)
            return 1
        cmd_reset(argv[2])
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
