#!/usr/bin/env python3
"""LLM Middleware Runtime — CLI Entry Point."""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import click
from rich.console import Console
from rich.table import Table

from . import (
    get_fact,
    set_fact,
    get_relevant_facts,
    load_log,
    add_log_entry,
    load_cascade,
    save_cascade,
    list_projects,
    cache_stats,
    project_dir,
    memory_path,
    log_path,
    index_path,
    assemble_context,
    estimate_tokens,
    load_formats,
    get_platform_config,
    list_platforms,
    generate_prompt,
    generate_full_prompt,
    TEMPLATES,
    init_cascade,
    get_next_steps,
    generate_step_prompt,
    complete_step,
    fail_step,
    reset_cascade,
)
from . import __version__
from .core.persistence import PersistenceLayer, create_project_persistence


def _load_manifest() -> Dict[str, Any]:
    """Load the domain manifest via the shared registry loader."""
    from llm_middleware.skills.registry import _load_manifest as _registry_load_manifest
    return _registry_load_manifest()


def _create_persistence(project: str = "default") -> PersistenceLayer:
    """Create a project-scoped persistence layer."""
    return create_project_persistence(project)

console = Console()


# ─── Helpers ────────────────────────────────────────────────────────────────

def _resolve_project(project: Optional[str]) -> str:
    if project:
        return project
    from llm_middleware.core.persistence import create_persistence
    try:
        persistence = create_persistence()
        return persistence.get_active_project()
    except Exception:
        return "default"


def list_projects() -> List[Dict[str, Any]]:
    """List projects using the SQLite persistence layer."""
    persistence = _create_persistence()
    return persistence.list_projects()


def _format_json(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False)


# ─── Commands ───────────────────────────────────────────────────────────────

@click.group()
@click.version_option(version=__version__)
def cli():
    """LLM Middleware Runtime — Agent-agnostic context injection & memory sync."""
    pass


@cli.group()
def project():
    """Project management."""
    pass


@project.command("list")
def project_list():
    """List all projects with stats."""
    projects = list_projects()
    if not projects:
        console.print("(no projects)")
        return
    
    table = Table(title="Projects")
    table.add_column("NAME", style="cyan")
    table.add_column("DOMAINS", justify="right")
    table.add_column("FACTS", justify="right")
    table.add_column("LOGS", justify="right")
    table.add_column("INDEXED", justify="right")
    
    for p in projects:
        table.add_row(
            p["name"],
            str(p["domains"]),
            str(p["facts"]),
            str(p["logs"]),
            str(p["indexed"]),
        )
        from llm_middleware import __version__
    console.print(table)

@project.command("switch")
@click.argument("name")
def project_switch(name: str):
    """Set active project."""
    persistence = _create_persistence(name)
    persistence.switch_project(name)
    # Ensure project directory exists in old location for backward compat
    project_dir(name)
    console.print(f"[green]Switched to project:[/green] {name}")


@project.command("active")
def project_active():
    """Show active project."""
    from llm_middleware.core.persistence import create_persistence
    persistence = create_persistence()
    console.print(persistence.get_active_project())


@cli.group()
def memory():
    """Memory bus operations."""
    pass


@memory.command("get")
@click.argument("domain", required=False)
@click.argument("key", required=False)
@click.option("--project", "-p", help="Project name")
def memory_get(domain: Optional[str], key: Optional[str], project: Optional[str]):
    """Get memory (full, domain, or single key)."""
    proj = _resolve_project(project)
    p = _create_persistence(proj)
    data = p.get_all_memory(proj)
    if domain is None:
        console.print(_format_json(data))
    elif key is None:
        console.print(_format_json(data.get("domains", {}).get(domain, {})))
    else:
        val = data.get("domains", {}).get(domain, {}).get(key)
        if val is not None:
            console.print(_format_json(val))
        else:
            console.print("[yellow]NOT FOUND[/yellow]")


@memory.command("set")
@click.argument("domain")
@click.argument("value_json")
@click.argument("key", required=False)
@click.option("--project", "-p", help="Project name")
def memory_set(domain: str, value_json: str, key: Optional[str], project: Optional[str]):
    """Set a fact (domain + key + JSON value)."""
    proj = _resolve_project(project)
    import json
    try:
        value = json.loads(value_json)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON:[/red] {e}")
        sys.exit(1)

    p = _create_persistence(proj)
    p.create_project(proj)
    if key is None:
        if not isinstance(value, dict):
            console.print("[red]Without --key, value must be a JSON object[/red]")
            sys.exit(1)
        for k, v in value.items():
            p.set_fact(proj, domain, k, v)
    else:
        p.set_fact(proj, domain, key, value)
    console.print(f"[green]OK[/green] [{proj}] {domain}" + (f".{key}" if key else ""))


@memory.command("list")
@click.option("--project", "-p", help="Project name")
def memory_list(project: Optional[str]):
    """List domains with key counts."""
    proj = _resolve_project(project)
    p = _create_persistence(proj)
    data = p.get_all_memory(proj)
    domains = data.get("domains", {})

    table = Table(title=f"Memory: {proj}")
    table.add_column("DOMAIN", style="cyan")
    table.add_column("KEYS", justify="right")
    table.add_column("LAST UPDATED")

    for domain in sorted(domains.keys()):
        keys = domains.get(domain, {})
        count = len([k for k in keys.keys() if not k.startswith("_")])
        updated = keys.get("_last_updated", "—")[:19]
        table.add_row(domain, str(count), updated)
    console.print(table)


@memory.command("relevant")
@click.argument("keywords", nargs=-1, required=True)
@click.option("--domains", "-d", multiple=True, help="Domains to search")
@click.option("--budget", "-b", default=4000, help="Token budget")
@click.option("--project", "-p", help="Project name")
def memory_relevant(keywords: tuple, domains: tuple, budget: int, project: Optional[str]):
    """Get facts relevant to keywords within token budget."""
    proj = _resolve_project(project)
    dom_list = list(domains) if domains else ["engine", "runtime", "save", "reflection", "assets"]
    facts = get_relevant_facts(proj, dom_list, list(keywords), budget)
    console.print(_format_json(facts))


@cli.group()
def log():
    """Execution log."""
    pass


@log.command("show")
@click.option("--limit", "-l", default=20)
@click.option("--agent", "-a", help="Filter by agent")
@click.option("--project", "-p", help="Project name")
def log_show(limit: int, agent: Optional[str], project: Optional[str]):
    """Show recent log entries."""
    proj = _resolve_project(project)
    entries = load_log(proj, limit=limit, agent=agent)

    table = Table(title=f"Execution Log: {proj}")
    table.add_column("TIME", style="dim")
    table.add_column("AGENT", style="cyan")
    table.add_column("DOMAIN")
    table.add_column("TASK")
    table.add_column("OUTCOME")

    for e in entries:
        ts = e.get("timestamp", "?")[:19]
        outcome = e.get("outcome", "?")
        icon = "✅" if outcome == "success" else "❌" if outcome == "failure" else "⚠️"
        table.add_row(ts, e.get("agent", "?"), e.get("domain", "?"), e.get("task", "?"), f"{icon} {outcome}")
    console.print(table)


@log.command("add")
@click.argument("entry_json")
@click.option("--project", "-p", help="Project name")
def log_add(entry_json: str, project: Optional[str]):
    """Add a log entry."""
    proj = _resolve_project(project)
    import json
    try:
        entry = json.loads(entry_json)
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON:[/red] {e}")
        sys.exit(1)
    add_log_entry(proj, entry)
    console.print(f"[green]OK[/green] [{proj}] logged: {entry.get('task', '?')}")


@cli.group()
def cascade():
    """Cascade pipeline operations."""
    pass


@cascade.command("templates")
def cascade_templates():
    """List cascade templates."""
    table = Table(title="Cascade Templates")
    table.add_column("NAME", style="cyan")
    table.add_column("STEPS", justify="right")
    table.add_column("DESCRIPTION")
    for name, tmpl in sorted(TEMPLATES.items()):
        steps = len(tmpl["steps"])
        desc = tmpl.get("description", "")
        table.add_row(name, str(steps), desc)
    console.print(table)


@cascade.command("start")
@click.argument("template")
@click.option("--project", "-p", help="Project name")
def cascade_start(template: str, project: Optional[str]):
    """Initialize a new cascade from template."""
    proj = _resolve_project(project)
    if template not in TEMPLATES:
        console.print(f"[red]Unknown template:[/red] {template}")
        console.print(f"Available: {', '.join(sorted(TEMPLATES.keys()))}")
        sys.exit(1)
    init_cascade(proj, template)


@cascade.command("status")
@click.option("--project", "-p", help="Project name")
def cascade_status(project: Optional[str]):
    """Show cascade progress."""
    proj = _resolve_project(project)
    from .orchestrator import cmd_status
    cmd_status(proj)


@cascade.command("next")
@click.option("--project", "-p", help="Project name")
def cascade_next(project: Optional[str]):
    """Show next ready steps."""
    proj = _resolve_project(project)
    from .orchestrator import cmd_next
    cmd_next(proj)


@cascade.command("prompt")
@click.argument("step")
@click.option("--project", "-p", help="Project name")
def cascade_prompt(step: str, project: Optional[str]):
    """Generate prompt for a cascade step."""
    proj = _resolve_project(project)
    from .orchestrator import cmd_prompt
    cmd_prompt(proj, step)


@cascade.command("complete")
@click.argument("step")
@click.argument("output_file")
@click.option("--project", "-p", help="Project name")
def cascade_complete(step: str, output_file: str, project: Optional[str]):
    """Mark step as complete with output file."""
    proj = _resolve_project(project)
    from .orchestrator import cmd_complete
    cmd_complete(proj, step, output_file)


@cascade.command("fail")
@click.argument("step")
@click.argument("error")
@click.option("--project", "-p", help="Project name")
def cascade_fail(step: str, error: str, project: Optional[str]):
    """Mark step as failed."""
    proj = _resolve_project(project)
    from .orchestrator import cmd_fail
    cmd_fail(proj, step, error)


@cascade.command("reset")
@click.option("--project", "-p", help="Project name")
def cascade_reset(project: Optional[str]):
    """Reset cascade state."""
    proj = _resolve_project(project)
    from .orchestrator import cmd_reset
    cmd_reset(proj)


@cli.group()
def prompt():
    """Prompt generation for agent platforms."""
    pass


@prompt.command("platforms")
def prompt_platforms():
    """List supported agent platforms."""
    platforms = list_platforms()
    table = Table(title="Supported Platforms")
    table.add_column("PLATFORM", style="cyan")
    table.add_column("NAME")
    table.add_column("FORMAT")
    table.add_column("SKILL LOCATION")
    formats = load_formats()
    for key in sorted(platforms):
        info = formats.get("agents", {}).get(key, {})
        table.add_row(key, info.get("name", "?"), info.get("skill_format", "?"), info.get("skill_location", "?"))
    console.print(table)


@prompt.command("generate")
@click.argument("project")
@click.argument("skill")
@click.option("--platform", default="hermes", help="Target platform")
@click.option("--domains", "-d", multiple=True, help="Domains to include")
@click.option("--keywords", "-k", multiple=True, help="Task keywords")
@click.option("--budget", "-b", default=8000, help="Token budget")
def prompt_generate(project: str, skill: str, platform: str, domains: tuple, keywords: tuple, budget: int):
    """Generate a platform-specific prompt for a skill."""
    proj = _resolve_project(project)
    dom_list = list(domains) if domains else ["engine"]
    kw_list = list(keywords) if keywords else [skill]
    prompt_text = generate_full_prompt(proj, skill, dom_list, kw_list, platform, budget)
    console.print(prompt_text)


@prompt.command("quick")
@click.argument("project")
@click.argument("skill")
@click.option("--platform", default="hermes", help="Target platform")
def prompt_quick(project: str, skill: str, platform: str):
    """Quick prompt with auto-detected domains/keywords."""
    proj = _resolve_project(project)
    # Auto-detect via skill registry
    from llm_middleware.skills.registry import discover_skills, _map_skills_to_domains
    skills = discover_skills()
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    skill_domains = [d for d, s_list in domain_map.items() if skill in s_list]
    if not skill_domains:
        skill_domains = ["engine"]
    keywords = skills.get(skill, {}).get("tags", [skill])
    prompt_text = generate_full_prompt(proj, skill, skill_domains, keywords, platform)
    console.print(prompt_text)


@cli.command()
@click.option("--project", "-p", help="Project name (defaults to current directory name)")
@click.option("--force", is_flag=True, help="Overwrite existing .llm-mw/ if present")
def init(project: Optional[str], force: bool):
    """Initialize a project: detect context, sync memory, write onboarding files.

    Creates .llm-mw/ with index.md (domain TOC), inventory.md (skill
    manifest), scopes.md (active domains) and a CLAUDE.md snippet so the
    orchestrator knows this project is middleware-managed.
    """
    proj = project or Path.cwd().name
    proj_dir = Path.cwd()
    proj_dir.mkdir(parents=True, exist_ok=True)
    dot = proj_dir / ".llm-mw"

    if dot.exists() and not force:
        console.print(f"[yellow].llm-mw/ already exists in {proj_dir} — use --force to overwrite[/yellow]")
        return

    dot.mkdir(parents=True, exist_ok=True)
    persistence = _create_persistence(proj)
    persistence.create_project(proj)

    from llm_middleware.skills.registry import (
discover_skills,  _map_skills_to_domains,    )
    skills = discover_skills()
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    domains = manifest.get("domains", {})

    # index.md — domain TOC
    (dot / "index.md").write_text(
        "# LLM Middleware — Domain Index\n\n"
        + "\n".join(f"- **{d}** — {info.get('description', '')}" for d, info in sorted(domains.items()))
        + "\n", encoding="utf-8"
    )
    # inventory.md — skill manifest
    inv = ["# LLM Middleware — Skill Inventory\n", f"Total skills: {len(skills)}\n"]
    for name in sorted(skills):
        ds = ", ".join(domain_map.get(name, []))
        inv.append(f"- `{name}` → domains: {ds or '—'}")
    (dot / "inventory.md").write_text("\n".join(inv) + "\n", encoding="utf-8")
    # scopes.md — active domains for this project
    (dot / "scopes.md").write_text(
        "# LLM Middleware — Project Scopes\n\n"
        f"project: {proj}\nactive_domains: {', '.join(sorted(domains.keys())) or 'none'}\n",
        encoding="utf-8",
    )
    # CLAUDE.md snippet
    snippet = (
        "# Project managed by LLM Middleware Runtime\n\n"
        "This project uses `llm-mw` as a persistent context layer. Available commands:\n"
        f"- `llm-mw status --project {proj}` — show sync state\n"
        "- `llm-mw memory get <domain> [key]` — read project memory\n"
        "- `llm-mw skill list` — list available skills\n"
        f"- `llm-mw dispatch '<request>' --project {proj}` — auto-select skills & build delegate tasks\n"
    )
    claude = proj_dir / "CLAUDE.md"
    existing = claude.read_text(encoding="utf-8") if claude.exists() else ""
    if "llm-mw" not in existing:
        with claude.open("a", encoding="utf-8") as f:
            f.write("\n" + snippet)
    console.print(f"[green]Initialized[/green] project [bold]{proj}[/bold] at {dot}")
    console.print("  📋 index.md · inventory.md · scopes.md · CLAUDE.md")


@cli.command()
@click.option("--project", "-p", help="Project name")
def onboard(project: Optional[str]):
    """Interactive onboarding wizard for humans new to the middleware.

    Explains the core concepts, asks for a project name and relevant domains,
    then runs `init` for you.
    """
    console.print("[bold cyan]═══ LLM Middleware Runtime — Onboarding ═══[/bold cyan]")
    console.print(
        "This tool is a [bold]persistent context layer[/bold] between you and LLM agents.\n"
        "It keeps per-project memory, selects skills automatically, and verifies\n"
        "results through a falsification gate before they are accepted.\n"
    )
    console.print("Core concepts:")
    for line in [
        "• [cyan]Projects[/cyan] are isolated — each has its own memory, never mixed.",
        "• [cyan]Domains[/cyan] are knowledge areas (engine, runtime, ui, ...).",
        "• [cyan]Skills[/cyan] are reusable agent instructions, mapped to domains.",
        "• [cyan]Falsification[/cyan] tests every result before it is trusted.",
    ]:
        console.print("  " + line)

    name = project or click.prompt("Project name", default=Path.cwd().name)
    from llm_middleware.skills.registry import discover_skills
    skills = discover_skills()
    manifest = _load_manifest()
    domains = manifest.get("domains", {})
    console.print(f"\nAvailable domains ({len(domains)}):")
    for d, info in sorted(domains.items()):
        console.print(f"  • {d} — {info.get('description', '')[:60]}")
    chosen = click.prompt(
        "Relevant domains (comma-separated, or 'all')",
        default="all",
    )
    if chosen.strip().lower() != "all":
        picked = [c.strip() for c in chosen.split(",") if c.strip() in domains]
    else:
        picked = sorted(domains.keys())

    # run init for the chosen project
    ctx = click.get_current_context()
    ctx.invoke(init, project=name, force=False)
    console.print(
        f"\n[green]Onboarded[/green] [bold]{name}[/bold] with {len(picked)} domains: {', '.join(picked)}"
    )
    console.print(f"Next steps: `llm-mw status --project {name}` to verify.")


@cli.command()
@click.option("--project", "-p", help="Project name")
def status(project: Optional[str]):
    """Show framework status."""
    proj = _resolve_project(project)

    from llm_middleware.skills.registry import discover_skills
    skills = discover_skills()
    manifest = _load_manifest()
    domains = manifest.get("domains", {})
    groups = manifest.get("skill_groups", {})

    # Load skill state from new persistence layer
    persistence = _create_persistence(proj)
    skill_state = persistence.load_skill_state(proj)
    loaded = skill_state.get("loaded", {})

    console.print("╔══════════════════════════════════════════════════════════════╗")
    console.print("║              LLM MIDDLEWARE RUNTIME — STATUS                 ║")
    console.print("╠══════════════════════════════════════════════════════════════╣")
    console.print(f"║  Project:    {proj:<52}║")
    console.print(f"║  Skills:     {len(loaded)}/{len(skills):<52}║")
    console.print(f"║  Domains:    {len(domains):<52}║")
    console.print(f"║  Groups:     {len(groups):<52}║")
    console.print("╠══════════════════════════════════════════════════════════════╣")

    console.print("║  📦 LOADED SKILLS:                                         ║")
    if loaded:
        for name in sorted(loaded.keys()):
            version = loaded[name].get("version", "?")
            console.print(f"║    🟢 {name:<35} v{version:<8}          ║")
    else:
        console.print("║    (none loaded — use 'llm-mw skill load <skill|group>')     ║")

    console.print("╠══════════════════════════════════════════════════════════════╣")
    console.print("║  📂 SKILL GROUPS:                                          ║")
    for gname, ginfo in sorted(groups.items()):
        gskills = ginfo.get("skills", [])
        gloaded = sum(1 for s in gskills if s in loaded)
        console.print(f"║    {gname:<20} {gloaded}/{len(gskills)} loaded{' ' * max(0, 22 - len(str(gloaded)) - len(str(len(gskills))))}║")

    console.print("╚══════════════════════════════════════════════════════════════╝")
    console.print()
    console.print("Commands: project | memory | log | cascade | prompt | skill | status")


@cli.group()
def skill():
    """Skill management."""
    pass


@skill.command("list")
def skill_list():
    """List all skills with status."""
    from llm_middleware.skills.registry import discover_skills, _map_skills_to_domains
    skills = discover_skills()
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)

    # Load skill state from new persistence layer
    proj = _resolve_project(None)
    persistence = _create_persistence(proj)
    skill_state = persistence.load_skill_state(proj)
    loaded = skill_state.get("loaded", {})

    skill_to_domains = {}
    for domain, skill_list in domain_map.items():
        for s in skill_list:
            skill_to_domains.setdefault(s, []).append(domain)

    table = Table(title="All Skills")
    table.add_column("SKILL", style="cyan")
    table.add_column("STATUS", justify="center")
    table.add_column("VERSION")
    table.add_column("DOMAINS")

    for name, info in sorted(skills.items()):
        status = "🟢 LOADED" if name in loaded else "⚪ IDLE"
        domains = ", ".join(skill_to_domains.get(name, []))
        table.add_row(name, status, info.get("version", "?"), domains)

    console.print(table)
    console.print(f"\nTotal: {len(skills)} skills, {len(loaded)} loaded")


@skill.command("load")
@click.argument("target")
@click.option("--project", "-p", help="Project name")
def skill_load(target: str, project: Optional[str]):
    """Load a skill or group."""
    from llm_middleware.skills.registry import discover_skills
    skills = discover_skills()
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})

    proj = _resolve_project(project)
    persistence = _create_persistence(proj)

    if target in groups:
        group = groups[target]
        load_order = group.get("load_order", group.get("skills", []))
        
        # Load existing state first
        existing_state = persistence.load_skill_state(proj)
        loaded = existing_state.get("loaded", {})
        
        for skill_name in load_order:
            if skill_name in skills:
                skill_info = skills[skill_name]
                loaded[skill_name] = {
                    "loaded_at": datetime.now(timezone.utc).isoformat(),
                    "version": skill_info.get("version", "unknown"),
                }
                console.print(f"[green]Loaded: {skill_name}[/green]")
            else:
                console.print(f"  [yellow]Warning: Skill '{skill_name}' in group '{target}' not found, skipping.[/yellow]")
        
        # Save merged state
        persistence.save_skill_state(proj, {"loaded": loaded, "history": []})
        
    elif target in skills:
        skill_info = skills[target]
        
        # Load existing state and add new skill
        existing_state = persistence.load_skill_state(proj)
        loaded = existing_state.get("loaded", {})
        loaded[target] = {
            "loaded_at": datetime.now(timezone.utc).isoformat(),
            "version": skill_info.get("version", "unknown"),
        }
        
        persistence.save_skill_state(proj, {"loaded": loaded, "history": []})
        console.print(f"[green]Loaded: {target}[/green]")
    else:
        console.print(f"[red]Unknown skill or group:[/red] {target}")
        console.print(f"Skills: {', '.join(sorted(skills.keys()))}")
        console.print(f"Groups: {', '.join(sorted(groups.keys()))}")
        sys.exit(1)


@skill.command("unload")
@click.argument("target")
def skill_unload(target: str):
    """Unload a skill or group."""
    from llm_middleware.skills.registry import discover_skills, cmd_unload, cmd_ungroup
    skills = discover_skills()
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})

    if target in groups:
        cmd_ungroup(target)
    elif target in skills:
        cmd_unload(target)
    else:
        console.print(f"[red]Unknown skill or group:[/red] {target}")
        sys.exit(1)


@skill.command("load-all")
def skill_load_all():
    """Load all skills."""
    from llm_middleware.skills.registry import cmd_load_all
    cmd_load_all()


@skill.command("unload-all")
def skill_unload_all():
    """Unload all skills."""
    from llm_middleware.skills.registry import cmd_unload_all
    cmd_unload_all()


@skill.command("context")
@click.argument("skill_name")
def skill_context(skill_name: str):
    """Get prompt context for a loaded skill."""
    from llm_middleware.skills.registry import cmd_context
    cmd_context(skill_name)


@cli.command()
@click.argument("request")
@click.option("--project", "-p", help="Project name")
@click.option("--platform", default="hermes", help="Target platform")
def dispatch(request: str, project: Optional[str], platform: str):
    """Auto-select skills and build delegate tasks for a request."""
    proj = _resolve_project(project)
    
    from llm_middleware.skills.registry import discover_skills, _map_skills_to_domains
    from llm_middleware.core.context_optimizer import assemble_context
    from llm_middleware.prompt_engine import generate_prompt
    
    persistence = _create_persistence(proj)
    
    # Select relevant skills
    selected_skills = _select_skills(request)
    matched_domains = list(_match_domains(request))
    
    console.print(f"📋 Dispatch: {len(selected_skills)} skills, {len(matched_domains)} domains")
    console.print(f"   Domains: {', '.join(sorted(matched_domains))}")
    console.print(f"   Skills:  {', '.join(selected_skills[:5])}{'...' if len(selected_skills) > 5 else ''}")
    console.print()
    
    # For the primary skill, generate a full prompt
    primary_skill = selected_skills[0] if selected_skills else "execution"
    
    # Build task keywords: individual words + bigrams
    words = request.lower().split()
    task_keywords = words[:10]
    for i in range(len(words) - 1):
        bigram = f"{words[i]}_{words[i+1]}"
        if bigram not in task_keywords:
            task_keywords.append(bigram)
    
    skills = discover_skills()
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    skill_domains = [d for d, s_list in domain_map.items() if primary_skill in s_list]
    
    # Load skill content
    skill_content = ""
    if primary_skill in skills:
        try:
            skill_content = Path(skills[primary_skill]["abs_path"]).read_text(encoding="utf-8")
        except OSError:
            skill_content = f"[UNREADABLE: {primary_skill}]"
    
    # Assemble context
    context = assemble_context(
        project=proj,
        domains=skill_domains or matched_domains,
        task_keywords=task_keywords,
        token_budget=8000,
    )
    
    # Generate platform-specific prompt
    prompt = generate_prompt(
        context=context,
        skill_content=skill_content,
        platform=platform,
        metadata={
            "project": proj,
            "step": primary_skill,
            "request": request,
        },
    )
    
    # Log the dispatch
    persistence.add_log_entry(proj, {
        "agent": "ctl",
        "domain": ",".join(matched_domains),
        "task": f"dispatch:{primary_skill}",
        "outcome": "success",
        "evidence": f"{len(selected_skills)} skills selected, {len(prompt)} chars prompt",
    })
    
    console.print(prompt)




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

    selected: List[str] = []
    for gname in relevant_groups:
        ginfo = groups.get(gname, {})
        for skill in ginfo.get("load_order", ginfo.get("skills", [])):
            if skill not in selected:
                selected.append(skill)

    return selected


@cli.group()
def sync():
    """Sync memory & skills to active agent platform."""
    pass


@sync.command("status")
@click.option("--project", "-p", help="Project name")
def sync_status(project: Optional[str]):
    """Show sync status (cache, index, memory)."""
    proj = _resolve_project(project)
    stats = cache_stats()
    idx_path = index_path(proj)
    mem_path = memory_path(proj)
    log_p = log_path(proj)

    table = Table(title=f"Sync Status: {proj}")
    table.add_column("ITEM", style="cyan")
    table.add_column("VALUE")

    table.add_row("Cache Hits", str(stats["hits"]))
    table.add_row("Cache Misses", str(stats["misses"]))
    table.add_row("Cache Size", str(stats["size"]))
    table.add_row("Memory File", str(mem_path) + (" ✅" if mem_path.exists() else " ❌"))
    table.add_row("Index File", str(idx_path) + (" ✅" if idx_path.exists() else " ❌"))
    table.add_row("Log File", str(log_p) + (" ✅" if log_p.exists() else " ❌"))

    # Index stats
    if idx_path.exists():
        import json
        with idx_path.open() as f:
            idx = json.load(f)
        table.add_row("Indexed Facts", str(len(idx)))
        total_tokens = sum(v.get("tokens", 0) for v in idx.values())
        table.add_row("Total Tokens (est.)", str(total_tokens))

    console.print(table)


@cli.command()
@click.argument("platform")
@click.option("--group", "-g", help="Skill group to export")
@click.option("--force", is_flag=True, help="Overwrite existing")
@click.option("--dry-run", is_flag=True, help="Show what would be exported")
def export(platform: str, group: Optional[str], force: bool, dry_run: bool):
    """Export skills to platform-native format."""
    from llm_middleware.runtime.migrate_skills import main as migrate_main
    args = ["export", platform]
    if group:
        args.extend(["--group", group])
    if force:
        args.append("--force")
    if dry_run:
        args.append("--dry-run")
    sys.exit(migrate_main(args))


@cli.command()
@click.option("--project", "-p", help="Project name")
def index(project: Optional[str]):
    """Show project index (TOC, inventory, scopes)."""
    proj = _resolve_project(project)
    p = _create_persistence(proj)
    data = p.get_all_memory(proj)

    console.print(f"╔══════════════════════════════════════════════════════════════╗")
    console.print(f"║  PROJECT INDEX: {proj:<45}║")
    console.print(f"╚══════════════════════════════════════════════════════════════╝")

    # TOC — Domain structure
    console.print("\n📋 TABLE OF CONTENTS (Domains)")
    domains = data.get("domains", {})
    for domain in sorted(domains.keys()):
        keys = [k for k in domains[domain].keys() if not k.startswith("_")]
        console.print(f"  🔷 {domain} ({len(keys)} keys)")

    # Inventory — Reference catalog
    console.print("\n📦 INVENTORY (Reference Catalog)")
    for domain in sorted(domains.keys()):
        keys = [k for k in domains[domain].keys() if not k.startswith("_")]
        if keys:
            console.print(f"  {domain}:")
            for k in sorted(keys):
                val = domains[domain][k]
                if isinstance(val, dict):
                    console.print(f"    • {k}: {len(val)} fields")
                elif isinstance(val, list):
                    console.print(f"    • {k}: [{len(val)} items]")
                else:
                    console.print(f"    • {k}: {str(val)[:60]}")

    # Scopes — Isolation rules
    console.print("\n🔒 SCOPES (Isolation)")
    console.print("  Project: isolated memory bus")
    console.print("  Domains: independent key spaces")
    console.print("  Agents: separate log streams")



# ─── ML / Self-Improvement Commands ────────────────────────────────────────

@cli.group()
def ml():
    """Agent Runtime Kernel — ML & Self-Improvement commands."""
    pass


def _get_ml_controller(project: str, dry_run: bool = False):
    """Create a SelfImprovementController for the given project."""
    from .ml.self_improvement import SelfImprovementController
    persistence = _create_persistence(project)
    return SelfImprovementController(persistence, project, dry_run=dry_run)


@ml.command("status")
@click.option("--project", "-p", default=None, help="Project name")
def ml_status(project: Optional[str]):
    """Show ML system status: needs, patterns, reward trend."""
    project = _resolve_project(project)
    ctrl = _get_ml_controller(project)
    s = ctrl.status()

    console.print(f"\n[bold cyan]🤖 ML Status — Project: {project}[/bold cyan]\n")

    # Needs summary
    needs = s.get("needs", {})
    total_needs = needs.get("total", 0)
    by_priority = needs.get("by_priority", {})
    console.print(f"[bold]Needs[/bold]  total={total_needs}  "
                  f"critical={by_priority.get('critical', 0)}  "
                  f"important={by_priority.get('important', 0)}  "
                  f"optional={by_priority.get('optional', 0)}")

    # Reward trend
    reward = s.get("reward", {})
    avg = reward.get("avg_last_20")
    trend = reward.get("trend", "insufficient_data")
    trend_icon = {"improving": "📈", "stable": "➡️", "degrading": "📉", "insufficient_data": "❓"}.get(trend, "❓")
    avg_str = f"{avg:.3f}" if avg is not None else "n/a"
    console.print(f"[bold]Reward[/bold] avg(last 20)={avg_str}  trend={trend_icon} {trend}")

    # Pattern summary
    patterns = s.get("patterns", {})
    if patterns:
        console.print("[bold]Patterns[/bold]")
        for status_name, info in patterns.items():
            console.print(f"  {status_name}: {info.get('count', 0)} patterns  "
                          f"avg_weight={info.get('avg_weight', 0):.2f}  "
                          f"avg_score={info.get('avg_score', 0):.2f}")

    # Top patterns
    top = s.get("top_patterns", [])
    if top:
        console.print("\n[bold]Top Patterns[/bold]")
        t = Table(show_header=True, header_style="bold magenta")
        t.add_column("Task (signature)", max_width=40)
        t.add_column("Skill", max_width=20)
        t.add_column("Weight", justify="right")
        t.add_column("Score", justify="right")
        t.add_column("Uses", justify="right")
        for p in top:
            t.add_row(
                p.get("task_signature", "")[:40],
                p.get("skill_used", ""),
                f"{p.get('weight', 0):.2f}",
                f"{p.get('score', 0):.2f}",
                str(p.get("usage_count", 0)),
            )
        console.print(t)


@ml.command("needs")
@click.option("--project", "-p", default=None, help="Project name")
@click.option("--priority", type=click.Choice(["critical", "important", "optional"]), default=None)
@click.option("--scan", is_flag=True, help="Run a fresh scan before listing")
@click.option("--limit", default=20, help="Max needs to show")
def ml_needs(project: Optional[str], priority: Optional[str], scan: bool, limit: int):
    """Show detected Needs. Use --scan to trigger a fresh detection pass."""
    project = _resolve_project(project)
    persistence = _create_persistence(project)

    from .ml.needs_engine import NeedsEngine, NeedPriority

    engine = NeedsEngine(persistence, project)

    if scan:
        new_needs = engine.scan()
        console.print(f"[green]Scan complete — {len(new_needs)} new Need(s) detected[/green]\n")

    prio = NeedPriority(priority) if priority else None
    needs = engine.get_active_needs(priority=prio, limit=limit)

    if not needs:
        console.print("[dim]No open Needs.[/dim]")
        return

    console.print(f"\n[bold cyan]📋 Open Needs — {project}[/bold cyan]")
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("ID", max_width=10)
    t.add_column("Priority", max_width=10)
    t.add_column("Category", max_width=12)
    t.add_column("Description", max_width=55)
    t.add_column("Motivation", justify="right", max_width=10)
    t.add_column("Source", max_width=30)

    priority_colors = {
        "critical":  "bold red",
        "important": "yellow",
        "optional":  "dim",
    }

    for need in needs:
        pcolor = priority_colors.get(need.priority.value, "white")
        t.add_row(
            need.need_id[:8],
            f"[{pcolor}]{need.priority.value}[/{pcolor}]",
            need.category,
            need.description[:55],
            f"{need.motivation:.2f}",
            need.source.split(".")[-1],
        )
    console.print(t)
    console.print(f"\n[dim]Showing {len(needs)} need(s). Use --scan to refresh.[/dim]")


@ml.command("train")
@click.option("--project", "-p", default=None, help="Project name")
@click.option("--cycles", default=1, show_default=True, help="Number of improvement cycles")
def ml_train(project: Optional[str], cycles: int):
    """Run self-improvement cycles. Addresses open Needs with safe actions."""
    project = _resolve_project(project)
    ctrl = _get_ml_controller(project)

    console.print(f"\n[bold cyan]🔄 Running {cycles} improvement cycle(s) — {project}[/bold cyan]")

    with console.status("[bold green]Training..."):
        summary = ctrl.run(cycles=cycles)

    console.print(f"\n[bold green]✓ Done[/bold green]  run_id={summary.run_id}")
    console.print(f"  Cycles run:     {summary.cycles_run}")
    console.print(f"  Needs found:    {summary.total_needs_found}")
    console.print(f"  Resolved:       {summary.total_needs_resolved}")
    console.print(f"  Escalated:      {summary.total_needs_escalated}")
    avg = f"{summary.avg_reward:.3f}" if summary.avg_reward is not None else "n/a"
    console.print(f"  Avg reward:     {avg}")
    trend_icon = {"improving": "📈", "stable": "➡️", "degrading": "📉"}.get(summary.trend, "❓")
    console.print(f"  Trend:          {trend_icon} {summary.trend}")
    console.print(f"  Duration:       {summary.duration_seconds:.1f}s")

    if summary.cycles_run > 0 and summary.cycles:
        console.print("\n[bold]Cycle Details:[/bold]")
        for c in summary.cycles:
            resolved = c.get("needs_resolved", 0)
            escalated = c.get("needs_escalated", 0)
            reward = c.get("avg_reward")
            reward_str = f"{reward:.3f}" if reward is not None else "n/a"
            console.print(f"  [{c['cycle_id']}]  resolved={resolved}  escalated={escalated}  reward={reward_str}")


@ml.command("simulate")
@click.option("--project", "-p", default=None, help="Project name")
@click.option("--cycles", default=1, show_default=True, help="Number of cycles to simulate")
def ml_simulate(project: Optional[str], cycles: int):
    """Dry-run: show what training would do without writing anything."""
    project = _resolve_project(project)
    ctrl = _get_ml_controller(project, dry_run=True)

    console.print(f"\n[bold yellow]🔍 Simulating {cycles} cycle(s) — {project} (no writes)[/bold yellow]")

    with console.status("[bold yellow]Simulating..."):
        summary = ctrl.simulate(cycles=cycles)

    console.print(f"\n[bold yellow]Simulation complete[/bold yellow]  run_id={summary.run_id}")
    console.print(f"  Would address:  {summary.total_improvements} need(s)")
    console.print(f"  Would resolve:  {summary.total_needs_resolved}")
    console.print(f"  Would escalate: {summary.total_needs_escalated}")
    avg = f"{summary.avg_reward:.3f}" if summary.avg_reward is not None else "n/a"
    console.print(f"  Simulated reward: {avg}")

    if summary.cycles:
        console.print("\n[bold]Planned actions:[/bold]")
        for c in summary.cycles:
            for imp in c.get("improvements", []):
                console.print(
                    f"  [{imp.get('category', '')}] {imp.get('action', '')}  "
                    f"→ reward={imp.get('reward', 0):.2f}  status={imp.get('status', '')}"
                )


@ml.command("patterns")
@click.option("--project", "-p", default=None, help="Project name")
@click.option("--limit", default=15, show_default=True, help="Number of patterns to show")
@click.option("--status", "filter_status",
              type=click.Choice(["new", "confirmed", "deprecated", "evolved", "all"]),
              default="all")
def ml_patterns(project: Optional[str], limit: int, filter_status: str):
    """Show learned experience patterns."""
    project = _resolve_project(project)
    persistence = _create_persistence(project)
    from .ml.pattern_learner import PatternLearner

    learner = PatternLearner(persistence, project)

    query = "SELECT * FROM patterns WHERE project = ?"
    params: list = [project]
    if filter_status != "all":
        query += " AND status = ?"
        params.append(filter_status)
    query += " ORDER BY weight DESC, score DESC LIMIT ?"
    params.append(limit)

    rows = persistence.fetchall(query, tuple(params))

    if not rows:
        console.print("[dim]No patterns found.[/dim]")
        return

    stats = learner.stats()
    console.print(f"\n[bold cyan]🧠 Patterns — {project}[/bold cyan]")
    for s_name, info in stats.items():
        console.print(f"  {s_name}: {info['count']} patterns  weight={info['avg_weight']:.2f}  score={info['avg_score']:.2f}")

    console.print()
    t = Table(show_header=True, header_style="bold magenta")
    t.add_column("Task Signature", max_width=38)
    t.add_column("Skill", max_width=18)
    t.add_column("Status", max_width=10)
    t.add_column("Weight", justify="right")
    t.add_column("Score", justify="right")
    t.add_column("Uses", justify="right")
    t.add_column("✓", justify="right")
    t.add_column("✗", justify="right")

    status_colors = {"confirmed": "green", "new": "cyan", "deprecated": "red", "evolved": "yellow"}
    for row in rows:
        r = dict(row)
        sc = status_colors.get(r.get("status", ""), "white")
        t.add_row(
            r.get("task_signature", "")[:38],
            r.get("skill_used", "")[:18],
            f"[{sc}]{r.get('status', '')}[/{sc}]",
            f"{r.get('weight', 0):.2f}",
            f"{r.get('score', 0):.2f}",
            str(r.get("usage_count", 0)),
            str(r.get("success_count", 0)),
            str(r.get("failure_count", 0)),
        )
    console.print(t)


@ml.command("reflect")
@click.option("--project", "-p", default=None, help="Project name")
def ml_reflect(project: Optional[str]):
    """Run a reflection pass. What worked, what failed, what was wasted."""
    project = _resolve_project(project)
    ctrl = _get_ml_controller(project)

    with console.status("[bold blue]Reflecting..."):
        reflection = ctrl.reflect()

    console.print(f"\n[bold cyan]🔍 Reflection — {project}[/bold cyan]\n")

    worked = reflection.get("what_worked", [])
    if worked:
        console.print("[bold green]✓ What Worked[/bold green]")
        for item in worked:
            console.print(f"  [{item.get('skill', '')}] {item.get('task', '')}  weight={item.get('weight', 0):.2f}")

    failed = reflection.get("what_failed", [])
    if failed:
        console.print("\n[bold red]✗ What Failed[/bold red]")
        for item in failed:
            console.print(f"  [{item.get('skill', '')}] {item.get('task', '')}")

    wasted = reflection.get("what_was_wasted", [])
    if wasted:
        console.print("\n[bold yellow]⚠ What Was Wasted (high usage, low reward)[/bold yellow]")
        for item in wasted:
            console.print(f"  {item.get('task', '')}  uses={item.get('usage', 0)}  score={item.get('score', 0):.2f}")

    critical = reflection.get("persistent_critical_needs", [])
    if critical:
        console.print("\n[bold red]🚨 Persistent Critical Needs[/bold red]")
        for item in critical:
            console.print(f"  [{item.get('source', '')}] {item.get('description', '')}")

    if not (worked or failed or wasted or critical):
        console.print("[dim]Insufficient data for reflection. Run more cycles first.[/dim]")




# ─── Knowledge Graph Commands ────────────────────────────────────────────────

@cli.group()
def graph():
    """Knowledge Graph — relations between Repos, Modules, Files, Classes, …"""
    pass


@graph.command("add")
@click.argument("source_type")
@click.argument("source_id")
@click.argument("relation_type")
@click.argument("target_type")
@click.argument("target_id")
@click.option("--project", "-p", help="Project name")
@click.option("--meta", help="JSON metadata")
def graph_add(source_type: str, source_id: str, relation_type: str,
              target_type: str, target_id: str, project: Optional[str], meta: Optional[str]):
    """Add a relation to the Knowledge Graph."""
    from llm_middleware.core.knowledge_graph import KnowledgeGraph
    proj = _resolve_project(project)
    p = _create_persistence(proj)
    metadata = json.loads(meta) if meta else {}
    KnowledgeGraph(p, proj).add_relation(
        source_type=source_type, source_id=source_id, relation_type=relation_type,
        target_type=target_type, target_id=target_id, metadata=metadata
    )
    console.print(f"[green]✓[/green] {source_type}:{source_id} --[{relation_type}]--> {target_type}:{target_id}")


@graph.command("list")
@click.argument("node_id")
@click.option("--project", "-p", help="Project name")
@click.option("--direction", default="out", type=click.Choice(["out", "in", "both"]))
def graph_list(node_id: str, project: Optional[str], direction: str):
    """List relations for a node."""
    from llm_middleware.core.knowledge_graph import KnowledgeGraph
    proj = _resolve_project(project)
    p = _create_persistence(proj)
    kg = KnowledgeGraph(p, proj)

    table = Table(title=f"Relations: {node_id}")
    table.add_column("DIR", style="dim", width=5)
    table.add_column("TYPE", style="cyan")
    table.add_column("OTHER NODE", style="green")
    table.add_column("RELATION", style="yellow")

    if direction in ("out", "both"):
        for r in kg.get_outgoing(node_id):
            table.add_row("→", r["target_type"], r["target_id"], r["relation_type"])
    if direction in ("in", "both"):
        for r in kg.get_incoming(node_id):
            table.add_row("←", r["source_type"], r["source_id"], r["relation_type"])

    console.print(table)


@graph.command("traverse")
@click.argument("start_id")
@click.option("--depth", default=3, show_default=True)
@click.option("--project", "-p", help="Project name")
def graph_traverse(start_id: str, depth: int, project: Optional[str]):
    """Traverse the Knowledge Graph from a node."""
    from llm_middleware.core.knowledge_graph import KnowledgeGraph
    proj = _resolve_project(project)
    p = _create_persistence(proj)
    subgraph = KnowledgeGraph(p, proj).traverse(start_id, max_depth=depth)
    nodes = subgraph.get("nodes", {})
    edges = subgraph.get("edges", [])
    console.print(f"[bold]Nodes:[/bold] {len(nodes)}  [bold]Edges:[/bold] {len(edges)}")
    for e in edges:
        console.print(f"  {e['source']} --[{e['relation']}]--> {e['target']} ({e['target_type']})")


if __name__ == "__main__":
    cli()