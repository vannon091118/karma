#!/usr/bin/env python3
"""
SyxCraft V71 Framework — /team Unified Orchestrator

Single entry point for the /team command. Dynamically discovers skills,
loads/unloads them, queries domain memory, and dispatches work to the
appropriate skill pipeline.

Usage:
    team.py status                          # Show loaded skills, domains, memory index
    team.py load <skill|group>              # Load a skill or group
    team.py unload <skill|group>            # Unload a skill or group
    team.py load-all                        # Load everything
    team.py unload-all                      # Unload everything
    team.py dispatch "<user_request>"       # Auto-select and dispatch skills for a request
    team.py context <skill>                 # Get prompt context for a loaded skill
    team.py domains                         # Show domain manifest with memory index
    team.py memory [<domain>] [<key>]       # Query memory bus
    team.py pipeline                        # Show pipeline status
    team.py groups                          # Show all skill groups

Example:
    team.py dispatch "implement Undead conversion with MANA resource"
    team.py load pipeline                   # Load all pipeline skills
    team.py status
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

# ─── Paths ──────────────────────────────────────────────────────────────────

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = FRAMEWORK_ROOT / "runtime"
MANIFEST_PATH = FRAMEWORK_ROOT / "domains" / "MANIFEST.json"
MEMORY_BUS = SCRIPTS_DIR / "memory_bus.py"
SKILL_REGISTRY = SCRIPTS_DIR / "skill_registry.py"
STALENESS_CHECK = SCRIPTS_DIR / "staleness_check.py"

STATE_PATH = Path(os.environ.get(
    "SYXCRAFT_SKILL_STATE",
    str(Path.home() / ".llm-middleware" / "skill_state.json")
))

# ─── Helpers ────────────────────────────────────────────────────────────────

def _run_script(script: Path, args: List[str], capture: bool = True) -> Tuple[int, str]:
    """Run a Python script and return (exit_code, output)."""
    cmd = [sys.executable, str(script)] + args
    try:
        result = subprocess.run(cmd, capture_output=capture, text=True, timeout=30)
        return result.returncode, result.stdout if capture else ""
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)

def _load_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}

def _save_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(path)

def _load_manifest() -> Dict[str, Any]:
    return _load_json(MANIFEST_PATH)

def _load_state() -> Dict[str, Any]:
    if not STATE_PATH.exists():
        return {"loaded": {}, "history": [], "last_scan": None}
    return _load_json(STATE_PATH)

# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_status() -> None:
    """Show complete /team status: loaded skills, domains, memory index."""
    state = _load_state()
    loaded = state.get("loaded", {})
    manifest = _load_manifest()
    domains = manifest.get("domains", {})
    groups = manifest.get("skill_groups", {})

    # Discover all skills
    code, output = _run_script(SKILL_REGISTRY, ["discover"])
    total_skills = 0
    if code == 0:
        try:
            discovery = json.loads(output)
            total_skills = discovery.get("total_skills", 0)
        except json.JSONDecodeError:
            pass

    # Memory bus status
    code, mem_output = _run_script(MEMORY_BUS, ["list"])
    memory_domains = []
    if code == 0:
        for line in mem_output.strip().split("\n")[1:]:  # skip header
            parts = line.split("\t")
            if len(parts) >= 2:
                memory_domains.append({"domain": parts[0].strip(), "keys": parts[1].strip()})

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              /team — UNIFIED ORCHESTRATOR                  ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║  Skills: {len(loaded)}/{total_skills} loaded{' ' * max(0, 38 - len(str(len(loaded))) - len(str(total_skills)))}║")
    print(f"║  Domains: {len(domains)} registered{' ' * max(0, 37 - len(str(len(domains))))}║")
    print(f"║  Memory:  {len(memory_domains)} domains with data{' ' * max(0, 33 - len(str(len(memory_domains))))}║")
    print(f"║  Groups:  {len(groups)} available{' ' * max(0, 37 - len(str(len(groups))))}║")
    print("╠══════════════════════════════════════════════════════════════╣")

    # Loaded skills
    print("║  📦 LOADED SKILLS:                                         ║")
    if loaded:
        for name in sorted(loaded.keys()):
            version = loaded[name].get("version", "?")
            print(f"║    🟢 {name:<35} v{version:<8}          ║")
    else:
        print("║    (none loaded — use /team load <skill|group>)            ║")

    # Domain memory index
    print("╠══════════════════════════════════════════════════════════════╣")
    print("║  🧠 DOMAIN MEMORY INDEX:                                   ║")
    if memory_domains:
        for md in memory_domains:
            print(f"║    {md['domain']:<15} {md['keys']} keys{' ' * max(0, 30 - len(md['keys']) - len(md['domain']))}║")
    else:
        print("║    (no data — domains load on first /team dispatch)        ║")

    # Groups
    print("╠══════════════════════════════════════════════════════════════╣")
    print("║  📂 SKILL GROUPS:                                          ║")
    for gname, ginfo in sorted(groups.items()):
        gskills = ginfo.get("skills", [])
        gloaded = sum(1 for s in gskills if s in loaded)
        print(f"║    {gname:<20} {gloaded}/{len(gskills)} loaded{' ' * max(0, 22 - len(str(gloaded)) - len(str(len(gskills))))}║")

    print("╚══════════════════════════════════════════════════════════════╝")
    print()
    print("Commands: load <skill|group> | unload <skill|group> | dispatch \"<request>\"")
    print("          domains | memory [<domain>] | pipeline | groups | context <skill>")


def cmd_load(target: str) -> None:
    """Load a skill by name, or all skills in a group."""
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})

    if target in groups:
        # Load group
        _run_script(SKILL_REGISTRY, ["group", target], capture=False)
    else:
        # Load single skill
        _run_script(SKILL_REGISTRY, ["load", target], capture=False)


def cmd_unload(target: str) -> None:
    """Unload a skill by name, or all skills in a group."""
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})

    if target in groups:
        _run_script(SKILL_REGISTRY, ["ungroup", target], capture=False)
    else:
        _run_script(SKILL_REGISTRY, ["unload", target], capture=False)


def cmd_load_all() -> None:
    """Load every discovered skill."""
    _run_script(SKILL_REGISTRY, ["load-all"], capture=False)


def cmd_unload_all() -> None:
    """Unload every loaded skill."""
    _run_script(SKILL_REGISTRY, ["unload-all"], capture=False)


def cmd_domains() -> None:
    """Show the full domain manifest with memory keys."""
    manifest = _load_manifest()
    domains = manifest.get("domains", {})

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              DOMAIN MANIFEST — Single Source of Truth       ║")
    print("╠══════════════════════════════════════════════════════════════╣")

    for name, info in sorted(domains.items(), key=lambda x: x[1].get("priority", 99)):
        print(f"║                                                              ║")
        print(f"║  🔷 {name.upper()} (P{info.get('priority', '?')})")
        print(f"║     {info.get('description', '')}")
        print(f"║     Memory keys: {', '.join(info.get('memory_keys', []))}")
        print(f"║     Knowledge: {info.get('knowledge', '—')}")
        deps = info.get("depends_on", [])
        refs = info.get("cross_refs", [])
        if deps:
            print(f"║     Depends on: {', '.join(deps)}")
        if refs:
            print(f"║     Cross-refs: {', '.join(refs)}")

    print("╚══════════════════════════════════════════════════════════════╝")


def cmd_memory(domain: Optional[str] = None, key: Optional[str] = None) -> None:
    """Query the memory bus."""
    args = ["get"]
    if domain:
        args.append(domain)
    if key:
        args.append(key)
    code, output = _run_script(MEMORY_BUS, args)
    if code == 0:
        print(output)
    else:
        print(f"ERROR: Memory bus returned code {code}", file=sys.stderr)


def cmd_pipeline() -> None:
    """Show pipeline status (loads workflow skill context)."""
    workflow_memory = FRAMEWORK_ROOT / "workflow" / "memory" / "pipeline-state.json"
    if workflow_memory.exists():
        state = _load_json(workflow_memory)
        print("╔══════════════════════════════════════════════════════════════╗")
        print("║              PIPELINE STATUS                                ║")
        print("╠══════════════════════════════════════════════════════════════╣")
        current = state.get("current_phase", "none")
        print(f"║  Current Phase: {current:<44}║")
        history = state.get("phase_history", [])
        for entry in history[-5:]:
            print(f"║    {entry.get('phase', '?'):<20} {entry.get('status', '?'):<15} {entry.get('timestamp', '?')[:19]}  ║")
        print("╚══════════════════════════════════════════════════════════════╝")
    else:
        print("Pipeline: no state found. Start with /workflow or /konzept.")


def cmd_groups() -> None:
    """Show all skill groups with members and load status."""
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})
    state = _load_state()
    loaded = state.get("loaded", {})

    print("╔══════════════════════════════════════════════════════════════╗")
    print("║              SKILL GROUPS                                   ║")
    print("╠══════════════════════════════════════════════════════════════╣")

    for gname, ginfo in sorted(groups.items()):
        gskills = ginfo.get("skills", [])
        gloaded = sum(1 for s in gskills if s in loaded)
        print(f"║                                                              ║")
        print(f"║  📂 {gname} ({gloaded}/{len(gskills)} loaded)")
        print(f"║     {ginfo.get('description', '')}")
        for s in ginfo.get("load_order", gskills):
            status = "🟢" if s in loaded else "⚪"
            print(f"║     {status} {s}")

    print("╚══════════════════════════════════════════════════════════════╝")


def cmd_context(skill_name: str) -> None:
    """Get the full prompt context for a loaded skill."""
    code, output = _run_script(SKILL_REGISTRY, ["context", skill_name])
    if code == 0:
        print(output)
    else:
        print(f"ERROR: Could not get context for '{skill_name}'", file=sys.stderr)


def _match_domains(user_request: str, manifest: Dict[str, Any]) -> Set[str]:
    """Match user request against domain keywords. Shared helper."""
    request_lower = user_request.lower()
    domains = manifest.get("domains", {})
    matched: Set[str] = set()
    for domain_name, domain_info in domains.items():
        keywords = [kw.lower() for kw in domain_info.get("keywords", [])]
        if any(kw in request_lower for kw in keywords):
            matched.add(domain_name)
    if not matched:
        matched = {"engine", "runtime", "settlement"}
    return matched


def _select_relevant_skills(user_request: str, manifest: Dict[str, Any]) -> List[str]:
    """Select skills relevant to a user request based on domain keywords."""
    groups = manifest.get("skill_groups", {})
    matched_domains = _match_domains(user_request, manifest)

    # Map domains to skill groups
    relevant_groups: Set[str] = set()
    if any(d in matched_domains for d in ["engine", "runtime", "save", "reflection", "assets"]):
        relevant_groups.add("syxcraft")
    if any(d in matched_domains for d in ["settlement", "world", "ui"]):
        relevant_groups.add("syxcraft")
        relevant_groups.add("pipeline")
    if "documentation" in matched_domains or "research" in matched_domains:
        relevant_groups.add("quality")
        relevant_groups.add("meta")

    # Always include pipeline for dispatch
    relevant_groups.add("pipeline")

    # Collect skills from groups
    selected_skills: List[str] = []
    for gname in relevant_groups:
        ginfo = groups.get(gname, {})
        for skill in ginfo.get("load_order", ginfo.get("skills", [])):
            if skill not in selected_skills:
                selected_skills.append(skill)

    return selected_skills


def cmd_dispatch(user_request: str) -> None:
    """Auto-select relevant skills, load them, build delegate tasks."""
    manifest = _load_manifest()
    state = _load_state()
    loaded = state.get("loaded", {})

    # Select relevant skills (uses shared domain matching)
    selected_skills = _select_relevant_skills(user_request, manifest)

    # Load selected skills that aren't already loaded
    newly_loaded = []
    load_errors = []
    for skill in selected_skills:
        if skill not in loaded:
            code, output = _run_script(SKILL_REGISTRY, ["load", skill])
            if code == 0:
                newly_loaded.append(skill)
            else:
                load_errors.append(f"{skill}: {output.strip()}")

    if load_errors:
        print(f"WARN: {len(load_errors)} skill(s) failed to load:", file=sys.stderr)
        for err in load_errors:
            print(f"  - {err}", file=sys.stderr)

    # Load domain memory for matched domains (uses shared domain matching)
    matched_domains = _match_domains(user_request, manifest)
    domain_states: Dict[str, Any] = {}
    for d in sorted(matched_domains):
        code, output = _run_script(MEMORY_BUS, ["get", d])
        if code == 0 and output.strip():
            try:
                domain_states[d] = json.loads(output)
            except json.JSONDecodeError:
                domain_states[d] = {}

    # Staleness check: verify high-risk domain baselines against Stufe-1 sources
    staleness_warnings = []
    code, staleness_output = _run_script(STALENESS_CHECK, ["scan", "--json"])
    if code != 0 and staleness_output.strip():
        try:
            staleness_data = json.loads(staleness_output)
            for sf in staleness_data.get("stale_files", []):
                staleness_warnings.append(f"{sf['file']}: {sf['summary']}")
        except json.JSONDecodeError:
            pass
        if staleness_warnings:
            print(f"⚠️  STALENESS WARNING: {len(staleness_warnings)} domain baseline(s) may be outdated:", file=sys.stderr)
            for w in staleness_warnings:
                print(f"  - {w}", file=sys.stderr)
            print("  → Run 'python3 scripts/staleness_check.py scan' for details", file=sys.stderr)

    # Build output
    output = {
        "trigger": "/team",
        "user_request": user_request,
        "selected_skills": selected_skills,
        "newly_loaded": newly_loaded,
        "load_errors": load_errors,
        "staleness_warnings": staleness_warnings,
        "matched_domains": sorted(matched_domains),
        "domain_memory": domain_states,
        "pipeline_hint": _detect_pipeline_phase(user_request),
        "delegate_tasks": _build_delegate_tasks(user_request, sorted(matched_domains), domain_states, selected_skills),
    }

    print(json.dumps(output, indent=2, ensure_ascii=False))


def _detect_pipeline_phase(user_request: str) -> str:
    """Hint which pipeline phase the request maps to."""
    req = user_request.lower()
    if any(w in req for w in ["analyze", "dump", "extract", "distill"]):
        return "dump-analyse"
    elif any(w in req for w in ["concept", "plan", "design", "decide", "research"]):
        return "konzept"
    elif any(w in req for w in ["implement", "build", "code", "create", "write", "add"]):
        return "execution"
    elif any(w in req for w in ["test", "verify", "validate", "falsify", "check"]):
        return "tests"
    return "konzept"  # default


def _build_delegate_tasks(
    user_request: str,
    domains: List[str],
    domain_states: Dict[str, Any],
    skills: List[str]
) -> List[Dict[str, Any]]:
    """Build delegate_task payloads for each matched domain."""
    tasks = []
    manifest = _load_manifest()
    domain_info = manifest.get("domains", {})

    for domain in domains:
        state = domain_states.get(domain, {})
        d_info = domain_info.get(domain, {})
        tasks.append({
            "role": "leaf",
            "description": f"{domain.upper()} Specialist — {user_request}",
            "context": {
                "domain": domain,
                "description": d_info.get("description", ""),
                "user_request": user_request,
                "architecture_state": state,
                "memory_keys": d_info.get("memory_keys", []),
                "knowledge_path": d_info.get("knowledge", ""),
                "available_skills": skills,
                "acceptance_criteria": [
                    "Verify every fact against source code or SSOT before acting",
                    "Persist new facts via memory_bus.py update with evidence",
                    "Report evidence, confidence level, and any blocking issues",
                ],
                "constraints": [
                    "Engine: Snake2D V71",
                    "No silent fallbacks",
                    "All reflection validated at runtime",
                    "Data-driven before code-driven",
                ],
            },
            "toolsets": ["terminal", "file", "research", "skills"],
            "max_turns": 50,
        })
    return tasks


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        cmd_status()
        return 0

    command = argv[1]

    if command == "status":
        cmd_status()
    elif command == "load":
        if len(argv) < 3:
            print("Usage: team.py load <skill|group>", file=sys.stderr)
            return 1
        cmd_load(argv[2])
    elif command == "unload":
        if len(argv) < 3:
            print("Usage: team.py unload <skill|group>", file=sys.stderr)
            return 1
        cmd_unload(argv[2])
    elif command == "load-all":
        cmd_load_all()
    elif command == "unload-all":
        cmd_unload_all()
    elif command == "domains":
        cmd_domains()
    elif command == "memory":
        domain = argv[2] if len(argv) > 2 else None
        key = argv[3] if len(argv) > 3 else None
        cmd_memory(domain, key)
    elif command == "pipeline":
        cmd_pipeline()
    elif command == "groups":
        cmd_groups()
    elif command == "context":
        if len(argv) < 3:
            print("Usage: team.py context <skill>", file=sys.stderr)
            return 1
        cmd_context(argv[2])
    elif command == "dispatch":
        if len(argv) < 3:
            print("Usage: team.py dispatch \"<user_request>\"", file=sys.stderr)
            return 1
        cmd_dispatch(argv[2])
    else:
        # Treat unknown command as a dispatch request
        cmd_dispatch(" ".join(argv[1:]))

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
