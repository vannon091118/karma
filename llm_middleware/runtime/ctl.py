#!/usr/bin/env python3
"""
LLM Middleware Runtime — Controller (ctl.py)

Single entry point for ALL agent interactions with the framework.
Replaces team_spawn.py as the unified orchestrator.

The framework directory is the PRIMARY data source.
.claude, .hermes, .config are FALLBACKS only.

Usage:
    ctl.py status [--project <name>]         Show framework status
    ctl.py projects                           List all projects
    ctl.py switch <project>                   Switch active project

    ctl.py dispatch "<request>" [--project <name>] [--platform <name>]
                                              Auto-select skills, build context, generate prompt

    ctl.py skills [discover|list|load|unload|group|ungroup]
                                              Skill registry commands

    ctl.py cascade [templates|start|status|next|prompt|complete|fail|reset]
                                              Skill cascade engine

    ctl.py memory [get|set|list|cross|log]    Memory bus commands

    ctl.py prompt <skill> [--platform <name>] [--project <name>]
                                              Generate prompt for a skill

    ctl.py export <platform>                  Export skills to platform format
    ctl.py import <platform>                  Import skills from platform format

    ctl.py verify [--project <name>]          Run staleness checks
    ctl.py stats                              Show cache/stats
"""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# ─── Paths ──────────────────────────────────────────────────────────────────

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
RUNTIME_DIR = FRAMEWORK_ROOT / "runtime"
SCRIPTS_DIR = RUNTIME_DIR
MANIFEST_PATH = FRAMEWORK_ROOT / "domains" / "MANIFEST.json"

# Scripts (legacy, still used for some operations)
MEMORY_BUS = SCRIPTS_DIR / "memory_bus.py"
SKILL_REGISTRY = SCRIPTS_DIR / "skill_registry.py"
STALENESS_CHECK = SCRIPTS_DIR / "staleness_check.py"

# Runtime modules imported directly via the installed package
from llm_middleware.runtime import memory_core, orchestrator, context_optimizer, prompt_engine, platform_adapter


# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_manifest() -> Dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"domains": {}, "skill_groups": {}}
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"domains": {}, "skill_groups": {}}


def _get_project(argv: List[str]) -> str:
    """Extract --project flag or use default."""
    for i, arg in enumerate(argv):
        if arg == "--project" and i + 1 < len(argv):
            return argv[i + 1]
    return "default"


def _get_platform(argv: List[str]) -> str:
    """Extract --platform flag or default to hermes."""
    for i, arg in enumerate(argv):
        if arg == "--platform" and i + 1 < len(argv):
            return argv[i + 1]
    return "hermes"


def _run_legacy_script(script: Path, args: List[str]) -> tuple:
    """Run a legacy script and return (code, output)."""
    cmd = [sys.executable, str(script)] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        return result.returncode, result.stdout
    except subprocess.TimeoutExpired:
        return -1, "TIMEOUT"
    except Exception as e:
        return -1, str(e)


def _match_domains(user_request: str) -> Set[str]:
    """Match user request text against domain keywords."""
    manifest = _load_manifest()
    request_lower = user_request.lower()
    matched = set()
    for domain_name, domain_info in manifest.get("domains", {}).items():
        keywords = [kw.lower() for kw in domain_info.get("keywords", [])]
        if any(kw in request_lower for kw in keywords):
            matched.add(domain_name)
    if not matched:
        matched = {"engine", "runtime"}
    return matched


def _select_skills(user_request: str) -> List[str]:
    """Auto-select skills relevant to a user request."""
    manifest = _load_manifest()
    matched_domains = _match_domains(user_request)
    groups = manifest.get("skill_groups", {})

    # Map domains to groups
    relevant_groups: Set[str] = {"pipeline"}  # Always include pipeline
    domain_to_group = {
        "engine": "syxcraft", "runtime": "syxcraft", "save": "syxcraft",
        "reflection": "syxcraft", "assets": "syxcraft", "settlement": "syxcraft",
        "world": "syxcraft", "ui": "syxcraft",
        "performance": "meta", "documentation": "quality", "release": "quality",
        "research": "infrastructure",
    }
    for domain in matched_domains:
        group = domain_to_group.get(domain)
        if group:
            relevant_groups.add(group)
    if "documentation" in matched_domains or "research" in matched_domains:
        relevant_groups.add("quality")

    # Collect skills from groups
    selected: List[str] = []
    for gname in relevant_groups:
        ginfo = groups.get(gname, {})
        for skill in ginfo.get("load_order", ginfo.get("skills", [])):
            if skill not in selected:
                selected.append(skill)

    return selected


# ─── Commands ────────────────────────────────────────────────────────────────

def cmd_status(project: str) -> None:
    """Show comprehensive framework status."""
    manifest = _load_manifest()
    domains = manifest.get("domains", {})
    groups = manifest.get("skill_groups", {})

    # Project info
    projects = memory_core.list_projects()
    proj_info = next((p for p in projects if p["name"] == project), None)

    # Skills
    import skill_registry
    skills = skill_registry.discover_skills()

    print("╔══════════════════════════════════════════════════════════════════╗")
    print("║              LLM MIDDLEWARE RUNTIME — STATUS                   ║")
    print("╠══════════════════════════════════════════════════════════════════╣")
    print(f"║  Project:    {project:<52}║")
    print(f"║  Skills:     {len(skills):<52}║")
    print(f"║  Domains:    {len(domains):<52}║")
    print(f"║  Groups:     {len(groups):<52}║")
    if proj_info:
        print(f"║  Facts:      {proj_info.get('facts', 0):<52}║")
        print(f"║  Logs:       {proj_info.get('logs', 0):<52}║")
        print(f"║  Indexed:    {proj_info.get('indexed', 0):<52}║")
    print("╠══════════════════════════════════════════════════════════════════╣")

    # Domain memory
    print("║  🧠 DOMAIN MEMORY:                                             ║")
    memory = memory_core.load_memory(project)
    for domain_name in sorted(domains.keys()):
        dom_data = memory.get("domains", {}).get(domain_name, {})
        fact_count = len([k for k in dom_data.keys() if not k.startswith("_")])
        icon = "🟢" if fact_count > 0 else "⚪"
        print(f"║    {icon} {domain_name:<15} {fact_count} facts{' ' * max(0, 35 - len(str(fact_count)))}║")

    # Cascade state
    cascade = memory_core.load_cascade(project)
    print("╠══════════════════════════════════════════════════════════════════╣")
    if cascade.get("steps"):
        status = cascade.get("status", "idle")
        tmpl = cascade.get("template", "?")
        completed = sum(1 for s in cascade.get("steps", {}).values() if s.get("status") == "completed")
        total = len(cascade.get("steps", {}))
        print(f"║  🔄 CASCADE: {tmpl} [{status}] {completed}/{total} steps{' ' * max(0, 20 - len(tmpl) - len(status))}║")
    else:
        print("║  📭 No active cascade                                           ║")

    # Groups
    print("╠══════════════════════════════════════════════════════════════════╣")
    print("║  📂 SKILL GROUPS:                                              ║")
    for gname, ginfo in sorted(groups.items()):
        gskills = ginfo.get("skills", [])
        print(f"║    {gname:<20} {len(gskills)} skills{' ' * max(0, 30 - len(str(len(gskills))))}║")

    print("╚══════════════════════════════════════════════════════════════════╝")
    print()
    print("Commands: dispatch | skills | cascade | memory | prompt | export | verify")


def cmd_projects() -> None:
    projects = memory_core.list_projects()
    if not projects:
        print("(no projects)")
        return
    print(f"{'PROJECT':<20} {'DOMAINS':<8} {'FACTS':<8} {'LOGS':<8} {'INDEXED'}")
    print("─" * 60)
    for p in projects:
        print(f"{p['name']:<20} {p['domains']:<8} {p['facts']:<8} {p['logs']:<8} {p['indexed']}")


def cmd_dispatch(user_request: str, project: str, platform: str) -> None:
    """Auto-select skills, build context, generate prompt."""
    # Select relevant skills
    selected_skills = _select_skills(user_request)
    matched_domains = list(_match_domains(user_request))

    print(f"📋 Dispatch: {len(selected_skills)} skills, {len(matched_domains)} domains")
    print(f"   Domains: {', '.join(sorted(matched_domains))}")
    print(f"   Skills:  {', '.join(selected_skills[:5])}{'...' if len(selected_skills) > 5 else ''}")
    print()

    # For the first/primary skill, generate a full prompt
    primary_skill = selected_skills[0] if selected_skills else "execution"
    # Build task keywords: individual words + bigrams for compound relevance
    words = user_request.lower().split()
    task_keywords = words[:10]
    # Add bigrams for compound matching (e.g., "mana resource", "slave trade")
    for i in range(len(words) - 1):
        bigram = f"{words[i]}_{words[i+1]}"
        if bigram not in task_keywords:
            task_keywords.append(bigram)

    import skill_registry
    skills = skill_registry.discover_skills()
    manifest = _load_manifest()
    domain_map = skill_registry._map_skills_to_domains(skills, manifest)
    skill_domains = [d for d, s_list in domain_map.items() if primary_skill in s_list]

    # Load skill content
    skill_content = ""
    if primary_skill in skills:
        try:
            skill_content = Path(skills[primary_skill]["abs_path"]).read_text(encoding="utf-8")
        except OSError:
            skill_content = f"[UNREADABLE: {primary_skill}]"

    # Assemble context
    context = context_optimizer.assemble_context(
        project=project,
        domains=skill_domains or matched_domains,
        task_keywords=task_keywords,
        token_budget=8000,
    )

    # Generate platform-specific prompt
    prompt = prompt_engine.generate_prompt(
        context=context,
        skill_content=skill_content,
        platform=platform,
        metadata={
            "project": project,
            "step": primary_skill,
            "request": user_request,
        },
    )

    # Log the dispatch
    memory_core.add_log_entry(project, {
        "agent": "ctl",
        "domain": ",".join(matched_domains),
        "task": f"dispatch:{primary_skill}",
        "outcome": "success",
        "evidence": f"{len(selected_skills)} skills selected, {len(prompt)} chars prompt",
    })

    print(prompt)


def cmd_skills(action: str, args: List[str]) -> None:
    """Delegate to skill_registry.py."""
    code, output = _run_legacy_script(SKILL_REGISTRY, [action] + args)
    print(output, end="")
    if code != 0:
        sys.exit(code)


def cmd_cascade(action: str, args: List[str], project: str) -> None:
    """Cascade engine commands."""
    if action == "templates":
        orchestrator.cmd_templates()
    elif action == "start":
        if not args:
            print("Usage: ctl.py cascade start <template>", file=sys.stderr)
            sys.exit(1)
        orchestrator.init_cascade(project, args[0])
    elif action == "status":
        orchestrator.cmd_status(project)
    elif action == "next":
        orchestrator.cmd_next(project)
    elif action == "prompt":
        if not args:
            print("Usage: ctl.py cascade prompt <step>", file=sys.stderr)
            sys.exit(1)
        orchestrator.cmd_prompt(project, args[0])
    elif action == "complete":
        if len(args) < 2:
            print("Usage: ctl.py cascade complete <step> <file>", file=sys.stderr)
            sys.exit(1)
        orchestrator.cmd_complete(project, args[0], args[1])
    elif action == "fail":
        if len(args) < 2:
            print("Usage: ctl.py cascade fail <step> <error>", file=sys.stderr)
            sys.exit(1)
        orchestrator.cmd_fail(project, args[0], args[1])
    elif action == "reset":
        orchestrator.cmd_reset(project)
    else:
        print(f"Unknown cascade command: {action}", file=sys.stderr)
        print("Available: templates, start, status, next, prompt, complete, fail, reset", file=sys.stderr)
        sys.exit(1)


def cmd_memory(action: str, args: List[str], project: str) -> None:
    """Memory bus commands."""
    if action == "get":
        if not args:
            # Dump all
            data = memory_core.load_memory(project)
            print(json.dumps(data, indent=2, ensure_ascii=False))
        elif len(args) == 1:
            # Domain dump
            data = memory_core.load_memory(project)
            dom = data.get("domains", {}).get(args[0], {})
            print(json.dumps(dom, indent=2, ensure_ascii=False))
        else:
            # Single fact
            value = memory_core.get_fact(project, args[0], args[1])
            print(json.dumps(value, indent=2, ensure_ascii=False) if value is not None else "")
    elif action == "set":
        if len(args) < 3:
            print("Usage: ctl.py memory set <domain> <key> '<json>'", file=sys.stderr)
            sys.exit(1)
        try:
            value = json.loads(args[2])
        except json.JSONDecodeError as exc:
            print(f"ERROR: Invalid JSON: {exc}", file=sys.stderr)
            sys.exit(1)
        memory_core.set_fact(project, args[0], args[1], value)
        print(f"OK [{project}]")
    elif action == "list":
        data = memory_core.load_memory(project)
        domains = data.get("domains", {})
        print(f"PROJECT: {project}")
        print(f"{'DOMAIN':<15} {'KEYS':<6} {'LAST_UPDATED'}")
        print("─" * 50)
        for domain in sorted(domains.keys()):
            keys = domains.get(domain, {})
            count = len([k for k in keys.keys() if not k.startswith("_")])
            updated = keys.get("_last_updated", "—")[:19]
            print(f"{domain:<15} {count:<6} {updated}")
    elif action == "cross":
        if len(args) < 2:
            print("Usage: ctl.py memory cross <domain> <key>", file=sys.stderr)
            sys.exit(1)
        # Query across all projects
        results = {}
        for proj in memory_core.list_projects():
            value = memory_core.get_fact(proj["name"], args[0], args[1])
            if value is not None:
                results[proj["name"]] = value
        if results:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print(f"No project has {args[0]}.{args[1]}")
    elif action == "log":
        limit = 20
        agent_filter = None
        for i, a in enumerate(args):
            if a == "--limit" and i + 1 < len(args):
                try:
                    limit = int(args[i + 1])
                except ValueError:
                    pass
            if a == "--agent" and i + 1 < len(args):
                agent_filter = args[i + 1]
        entries = memory_core.load_log(project, limit=limit, agent=agent_filter)
        print(f"PROJECT: {project}  ({len(entries)} entries)")
        for e in entries:
            ts = e.get("timestamp", "?")[:19]
            agent = e.get("agent", "?")[:14]
            task = e.get("task", "?")[:25]
            outcome = e.get("outcome", "?")
            icon = "✅" if outcome == "success" else "❌" if outcome == "failure" else "⚠️"
            print(f"  {ts} {agent:<15} {task:<25} {icon} {outcome}")
    else:
        print(f"Unknown memory command: {action}", file=sys.stderr)
        print("Available: get, set, list, cross, log", file=sys.stderr)
        sys.exit(1)


def cmd_prompt(skill_name: str, project: str, platform: str) -> None:
    """Generate a prompt for a specific skill."""
    sys.path.insert(0, str(SCRIPTS_DIR))
    import skill_registry

    skills = skill_registry.discover_skills()
    if skill_name not in skills:
        print(f"ERROR: Skill '{skill_name}' not found. Available: {', '.join(sorted(skills.keys()))}", file=sys.stderr)
        sys.exit(1)

    manifest = _load_manifest()
    domain_map = skill_registry._map_skills_to_domains(skills, manifest)
    domains = [d for d, s_list in domain_map.items() if skill_name in s_list]
    keywords = skills[skill_name].get("tags", [])

    prompt = prompt_engine.generate_full_prompt(
        project=project,
        skill_name=skill_name,
        domains=domains,
        task_keywords=keywords,
        platform=platform,
    )
    print(prompt)


def cmd_verify(project: str) -> None:
    """Run staleness checks."""
    code, output = _run_legacy_script(STALENESS_CHECK, ["scan"])
    print(output, end="")
    if code != 0:
        sys.exit(code)


def cmd_stats() -> None:
    """Show runtime cache stats."""
    stats = memory_core.cache_stats()
    projects = memory_core.list_projects()
    print(f"Cache: {stats['hits']} hits, {stats['misses']} misses, {stats['size']} entries")
    print(f"Projects: {len(projects)}")
    formats = platform_adapter.load_formats()
    print(f"Platforms: {len(formats.get('agents', {}))}")
    print(f"Framework root: {FRAMEWORK_ROOT}")


# ─── Main ────────────────────────────────────────────────────────────────────

USAGE = """LLM Middleware Runtime — Single Entry Point

Usage:
    ctl.py status [--project <name>]
    ctl.py projects
    ctl.py switch <project>

    ctl.py dispatch "<request>" [--project <name>] [--platform <name>]

    ctl.py skills [discover|list|load|unload|group|ungroup|load-all|unload-all]
    ctl.py cascade [templates|start|status|next|prompt|complete|fail|reset] [--project <name>]
    ctl.py memory [get|set|list|cross|log] [--project <name>]

    ctl.py prompt <skill> [--platform <name>] [--project <name>]
    ctl.py export <platform> [--force] [--dry-run]
    ctl.py import <platform>

    ctl.py verify [--project <name>]
    ctl.py stats
"""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(USAGE)
        return 1

    command = argv[1]
    project = _get_project(argv)
    platform = _get_platform(argv)

    if command == "status":
        cmd_status(project)
    elif command == "projects":
        cmd_projects()
    elif command == "switch":
        if len(argv) < 3:
            print("Usage: ctl.py switch <project>", file=sys.stderr)
            return 1
        memory_core.save_memory(argv[2], {
            "project": argv[2],
            "domains": {},
            "created": datetime.now(timezone.utc).isoformat(),
        })
        print(f"Switched to: {argv[2]}")
    elif command == "dispatch":
        if len(argv) < 3:
            print('Usage: ctl.py dispatch "<request>"', file=sys.stderr)
            return 1
        cmd_dispatch(argv[2], project, platform)
    elif command == "skills":
        action = argv[2] if len(argv) > 2 else "list"
        cmd_skills(action, argv[3:])
    elif command == "cascade":
        action = argv[2] if len(argv) > 2 else "status"
        cmd_cascade(action, argv[3:], project)
    elif command == "memory":
        action = argv[2] if len(argv) > 2 else "list"
        cmd_memory(action, argv[3:], project)
    elif command == "prompt":
        if len(argv) < 3:
            print("Usage: ctl.py prompt <skill>", file=sys.stderr)
            return 1
        cmd_prompt(argv[2], project, platform)
    elif command == "export":
        if len(argv) < 3:
            print("Usage: ctl.py export <platform>", file=sys.stderr)
            return 1
        force = "--force" in argv
        dry_run = "--dry-run" in argv
        platform_adapter.cmd_export(argv[2], force=force, dry_run=dry_run)
    elif command == "import":
        if len(argv) < 3:
            print("Usage: ctl.py import <platform>", file=sys.stderr)
            return 1
        platform_adapter.cmd_import(argv[2])
    elif command == "verify":
        cmd_verify(project)
    elif command == "stats":
        cmd_stats()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
