#!/usr/bin/env python3
"""
LLM Middleware Runtime — Prompt Engine

Generates platform-specific prompts from assembled context.
Reads AGENT_FORMATS.json to know each platform's expectations,
then wraps skill content, domain facts, and cascade outputs
into the exact format the calling agent needs.

Key insight: The same context becomes a different prompt depending
on whether it's consumed by Claude Code, OpenCode, Cursor, or Hermes.
"""

import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

from llm_middleware.core import memory_core, context_optimizer

FORMATS_PATH = FRAMEWORK_ROOT / "middleware" / "AGENT_FORMATS.json"


# ─── Format Registry ─────────────────────────────────────────────────────────

def load_formats() -> Dict[str, Any]:
    """Load the agent format registry."""
    if not FORMATS_PATH.exists():
        return {"agents": {}}
    try:
        with FORMATS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"agents": {}}


def get_platform_config(platform: str) -> Dict[str, Any]:
    """Get configuration for a specific agent platform."""
    formats = load_formats()
    return formats.get("agents", {}).get(platform, {})


def list_platforms() -> List[str]:
    """List all registered platforms."""
    formats = load_formats()
    return list(formats.get("agents", {}).keys())


# ─── Prompt Templates ────────────────────────────────────────────────────────

def _render_hermes_prompt(context: Dict[str, Any], skill_content: str,
                          metadata: Dict[str, Any]) -> str:
    """Render prompt for Hermes/Freebuff agent."""
    lines = []
    lines.append("# Agent Task")
    lines.append("")
    lines.append(f"**Project:** {metadata.get('project', 'unknown')}")
    lines.append(f"**Step:** {metadata.get('step', 'standalone')}")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")

    # Skill definition
    lines.append("---")
    lines.append("## Skill Definition")
    lines.append("")
    lines.append(skill_content)
    lines.append("")

    # Domain facts
    facts = context.get("domain_facts", context.get("facts", {}))
    if facts:
        lines.append("---")
        lines.append("## Domain Context")
        lines.append("")
        for domain, domain_facts in sorted(facts.items()):
            lines.append(f"### {domain}")
            for key, value in domain_facts.items():
                if isinstance(value, (dict, list)):
                    lines.append(f"- **{key}:** `{json.dumps(value, ensure_ascii=False)[:200]}`")
                else:
                    lines.append(f"- **{key}:** {value}")
            lines.append("")

    # Previous outputs
    prev = context.get("previous_outputs", {})
    if prev:
        lines.append("---")
        lines.append("## Previous Step Outputs")
        lines.append("")
        for step_name, output in prev.items():
            lines.append(f"### From: {step_name}")
            lines.append("```")
            lines.append(output[:2000])
            lines.append("```")
            lines.append("")

    # Warnings
    warnings = context.get("warnings", [])
    if warnings:
        lines.append("---")
        lines.append("## ⚠️ Warnings")
        for w in warnings:
            lines.append(f"- {w}")
        lines.append("")

    return "\n".join(lines)


def _render_claude_prompt(context: Dict[str, Any], skill_content: str,
                          metadata: Dict[str, Any]) -> str:
    """Render prompt for Claude Code — structured, concise, action-oriented."""
    lines = []
    lines.append(f"<task project=\"{metadata.get('project', 'unknown')}\" step=\"{metadata.get('step', 'standalone')}\">")
    lines.append("")

    # Skill as instructions
    lines.append("<instructions>")
    lines.append(skill_content)
    lines.append("</instructions>")
    lines.append("")

    # Domain facts as context
    facts = context.get("domain_facts", context.get("facts", {}))
    if facts:
        lines.append("<context>")
        for domain, domain_facts in sorted(facts.items()):
            for key, value in domain_facts.items():
                val_str = json.dumps(value, ensure_ascii=False)[:150] if isinstance(value, (dict, list)) else str(value)
                lines.append(f"  {domain}.{key} = {val_str}")
        lines.append("</context>")
        lines.append("")

    # Previous outputs
    prev = context.get("previous_outputs", {})
    if prev:
        lines.append("<previous_results>")
        for step_name, output in prev.items():
            lines.append(f"  <!-- from: {step_name} -->")
            lines.append(f"  {output[:1000]}")
        lines.append("</previous_results>")
        lines.append("")

    lines.append("</task>")
    return "\n".join(lines)


def _render_opencode_prompt(context: Dict[str, Any], skill_content: str,
                            metadata: Dict[str, Any]) -> str:
    """Render prompt for OpenCode — plain markdown, no XML."""
    lines = []
    lines.append(f"# {metadata.get('step', 'Task')}")
    lines.append(f"Project: {metadata.get('project', 'unknown')}")
    lines.append("")

    lines.append("## Instructions")
    lines.append("")
    lines.append(skill_content)
    lines.append("")

    facts = context.get("domain_facts", context.get("facts", {}))
    if facts:
        lines.append("## Context")
        lines.append("")
        for domain, domain_facts in sorted(facts.items()):
            lines.append(f"### {domain}")
            for key, value in domain_facts.items():
                val = json.dumps(value, ensure_ascii=False)[:150] if isinstance(value, (dict, list)) else str(value)
                lines.append(f"- {key}: {val}")
            lines.append("")

    prev = context.get("previous_outputs", {})
    if prev:
        lines.append("## Previous Results")
        for step_name, output in prev.items():
            lines.append(f"\n### {step_name}")
            lines.append(f"```\n{output[:1000]}\n```")

    return "\n".join(lines)


def _render_cursor_prompt(context: Dict[str, Any], skill_content: str,
                          metadata: Dict[str, Any]) -> str:
    """Render prompt for Cursor — structured with code blocks."""
    lines = []
    lines.append(f"<!-- Task: {metadata.get('step', 'unknown')} | Project: {metadata.get('project', 'unknown')} -->")
    lines.append("")
    lines.append(skill_content)
    lines.append("")

    facts = context.get("domain_facts", context.get("facts", {}))
    if facts:
        lines.append("## Reference Context")
        lines.append("")
        for domain, domain_facts in sorted(facts.items()):
            lines.append(f"**{domain}:**")
            for key, value in domain_facts.items():
                val = json.dumps(value, ensure_ascii=False)[:100] if isinstance(value, (dict, list)) else str(value)
                lines.append(f"  - {key}: {val}")
            lines.append("")

    return "\n".join(lines)


def _render_generic_prompt(context: Dict[str, Any], skill_content: str,
                           metadata: Dict[str, Any]) -> str:
    """Fallback renderer — plain text with sections."""
    lines = []
    lines.append(f"Task: {metadata.get('step', 'unknown')}")
    lines.append(f"Project: {metadata.get('project', 'unknown')}")
    lines.append("")
    lines.append("=== INSTRUCTIONS ===")
    lines.append(skill_content)
    lines.append("")

    facts = context.get("domain_facts", context.get("facts", {}))
    if facts:
        lines.append("=== CONTEXT ===")
        for domain, domain_facts in sorted(facts.items()):
            for key, value in domain_facts.items():
                val = json.dumps(value, ensure_ascii=False)[:100] if isinstance(value, (dict, list)) else str(value)
                lines.append(f"  {domain}.{key} = {val}")

    return "\n".join(lines)


# ─── Platform Dispatch ───────────────────────────────────────────────────────

RENDERERS = {
    "hermes": _render_hermes_prompt,
    "claude": _render_claude_prompt,
    "opencode": _render_opencode_prompt,
    "cursor": _render_cursor_prompt,
    "windsurf": _render_opencode_prompt,  # Windsurf uses similar format to OpenCode
    "copilot": _render_cursor_prompt,     # Copilot uses similar format to Cursor
}


def generate_prompt(context: Dict[str, Any], skill_content: str,
                    platform: str = "hermes",
                    metadata: Optional[Dict[str, Any]] = None) -> str:
    """
    Generate a platform-specific prompt from assembled context.
    
    Args:
        context: Assembled context from context_optimizer
        skill_content: Raw SKILL.md content
        platform: Target agent platform (hermes, claude, opencode, cursor, windsurf, copilot)
        metadata: Optional metadata dict with project, step, etc.
    
    Returns:
        Formatted prompt string ready for the target platform
    """
    if metadata is None:
        metadata = {}

    renderer = RENDERERS.get(platform, _render_generic_prompt)
    return renderer(context, skill_content, metadata)


def generate_full_prompt(project: str, skill_name: str,
                         domains: List[str], task_keywords: List[str],
                         platform: str = "hermes",
                         token_budget: int = 8000) -> str:
    """
    One-shot: assemble context + generate prompt for a skill.
    
    Convenience function that combines context_optimizer.assemble_context()
    with generate_prompt().
    """
    # Assemble context
    context = context_optimizer.assemble_context(
        project=project,
        domains=domains,
        task_keywords=task_keywords,
        token_budget=int(token_budget * 0.85),  # Reserve 15% for prompt overhead
    )

    # Load skill content
    from llm_middleware.skills.registry import discover_skills
    skills = discover_skills()
    skill_content = ""
    if skill_name in skills:
        try:
            skill_content = Path(skills[skill_name]["abs_path"]).read_text(encoding="utf-8")
        except OSError:
            skill_content = f"[SKILL UNREADABLE: {skill_name}]"
    else:
        skill_content = f"[SKILL NOT FOUND: {skill_name}]"

    metadata = {
        "project": project,
        "skill": skill_name,
        "step": skill_name,
        "platform": platform,
    }

    return generate_prompt(context, skill_content, platform, metadata)


# ─── CLI ────────────────────────────────────────────────────────────────────

USAGE = """LLM Middleware — Prompt Engine

Usage:
    prompt_engine.py platforms                          List supported platforms
    prompt_engine.py generate <project> <skill> --platform <name> --domains <d1> [<d2>...] --keywords <kw1> [<kw2>...] [--budget N]
    prompt_engine.py quick <project> <skill> [<platform>]  Quick prompt with auto-detected domains
"""


def cmd_platforms() -> None:
    """List all supported platforms with their format details."""
    formats = load_formats()
    agents = formats.get("agents", {})
    print(f"{'PLATFORM':<12} {'NAME':<25} {'FORMAT':<12} {'SKILL_PATH'}")
    print("─" * 80)
    for key, info in sorted(agents.items()):
        print(f"{key:<12} {info.get('name', '?'):<25} {info.get('skill_format', '?'):<12} {info.get('skill_location', '?')}")
    print(f"\nDefault: hermes")


def cmd_generate(argv: List[str]) -> None:
    """Generate a full prompt for a skill on a specific platform."""
    args = [a for a in argv[2:] if not a.startswith("--")]

    # Parse flags
    platform = "hermes"
    domains: List[str] = []
    keywords: List[str] = []
    budget = 8000

    for i, arg in enumerate(argv):
        if arg == "--platform" and i + 1 < len(argv):
            platform = argv[i + 1]
        elif arg == "--domains" and i + 1 < len(argv):
            domains = [a for a in argv[i + 1:] if not a.startswith("--")]
        elif arg == "--keywords" and i + 1 < len(argv):
            keywords = [a for a in argv[i + 1:] if not a.startswith("--")]
        elif arg == "--budget" and i + 1 < len(argv):
            try:
                budget = int(argv[i + 1])
            except ValueError:
                pass

    if len(args) < 2:
        print("Usage: prompt_engine.py generate <project> <skill> --platform <name> --domains <d> --keywords <kw>", file=sys.stderr)
        sys.exit(1)

    project, skill_name = args[0], args[1]

    # Auto-detect domains if not specified
    if not domains:
        from llm_middleware.skills.registry import discover_skills, _load_manifest, _map_skills_to_domains
        skills = discover_skills()
        manifest = _load_manifest()
        domain_map = _map_skills_to_domains(skills, manifest)
        domains = [d for d, s_list in domain_map.items() if skill_name in s_list]
        if not domains:
            domains = ["engine"]

    # Auto-detect keywords if not specified
    if not keywords:
        from llm_middleware.skills.registry import discover_skills
        skills = discover_skills()
        keywords = skills.get(skill_name, {}).get("tags", [])

    prompt = generate_full_prompt(project, skill_name, domains, keywords, platform, budget)
    print(prompt)


def cmd_quick(argv: List[str]) -> None:
    """Quick prompt generation with minimal args."""
    if len(argv) < 4:
        print("Usage: prompt_engine.py quick <project> <skill> [<platform>]", file=sys.stderr)
        sys.exit(1)

    project = argv[2]
    skill_name = argv[3]
    platform = argv[4] if len(argv) > 4 else "hermes"

    # Auto everything
    from llm_middleware.skills.registry import discover_skills, _load_manifest, _map_skills_to_domains
    skills = discover_skills()
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)

    domains = [d for d, s_list in domain_map.items() if skill_name in s_list]
    if not domains:
        domains = ["engine"]
    keywords = skills.get(skill_name, {}).get("tags", [])

    prompt = generate_full_prompt(project, skill_name, domains, keywords, platform)
    print(prompt)


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(USAGE)
        return 1

    command = argv[1]

    if command == "platforms":
        cmd_platforms()
    elif command == "generate":
        cmd_generate(argv)
    elif command == "quick":
        cmd_quick(argv)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
