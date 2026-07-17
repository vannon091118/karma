#!/usr/bin/env python3
"""
Framework Skill Migration Tool

Exports framework skills into platform-native formats for any known agent.
Enables seamless switching between Hermes, Claude Code, OpenCode, Cursor,
Windsurf, and GitHub Copilot while preserving skill content and context.

Usage:
    migrate_skills.py export <platform>              # Export all skills to platform format
    migrate_skills.py export <platform> --skill <n>  # Export one skill
    migrate_skills.py export <platform> --group <g>  # Export skill group
    migrate_skills.py list-platforms                  # Show all supported platforms
    migrate_skills.py diff <platform>                 # Show what would change (dry-run)
    migrate_skills.py import <platform>              # Import platform skills into framework

Example:
    migrate_skills.py export claude                  # Export to .claude/skills/
    migrate_skills.py export opencode                # Export to .opencode/rules/
    migrate_skills.py export cursor                  # Export to .cursor/rules/
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Paths ──────────────────────────────────────────────────────────────────

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
MIDDLEWARE_DIR = FRAMEWORK_ROOT / "middleware"
FORMATS_PATH = MIDDLEWARE_DIR / "AGENT_FORMATS.json"
SKILL_REGISTRY = FRAMEWORK_ROOT / "runtime" / "skill_registry.py"

# ─── Helpers ────────────────────────────────────────────────────────────────

def _load_formats() -> Dict[str, Any]:
    if not FORMATS_PATH.exists():
        print(f"ERROR: {FORMATS_PATH} not found", file=sys.stderr)
        sys.exit(1)
    with FORMATS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def _parse_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
    """Parse YAML-like frontmatter from markdown. Returns (meta, body)."""
    match = re.match(r'^---\s*\n(.*?)\n---\s*\n?(.*)', content, re.DOTALL)
    if not match:
        return {}, content

    meta = {}
    for line in match.group(1).split("\n"):
        line = line.strip()
        if ":" in line:
            key, val = line.split(":", 1)
            meta[key.strip()] = val.strip().strip('"\'')
    return meta, match.group(2)


def _discover_skills() -> List[Dict[str, Any]]:
    """Discover all SKILL.md files in the framework."""
    skills = []
    for skill_md in sorted(FRAMEWORK_ROOT.rglob("SKILL.md")):
        rel = skill_md.relative_to(FRAMEWORK_ROOT)
        if str(rel).startswith("domains/"):
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = _parse_frontmatter(content)
        skills.append({
            "name": meta.get("name", skill_md.parent.name),
            "description": meta.get("description", ""),
            "version": meta.get("version", "unknown"),
            "path": str(rel),
            "abs_path": str(skill_md),
            "content": content,
            "meta": meta,
            "body": body,
            "dir_name": skill_md.parent.name,
        })
    return skills


# ─── Platform Exporters ─────────────────────────────────────────────────────

def _export_hermes(skills: List[Dict[str, Any]], output_dir: Path, skill_filter: Optional[str] = None) -> int:
    """Export to Hermes format: ~/.hermes/skills/<name>/SKILL.md"""
    count = 0
    for skill in skills:
        if skill_filter and skill["dir_name"] != skill_filter:
            continue
        target = output_dir / skill["dir_name"] / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(skill["content"], encoding="utf-8")
        count += 1
        print(f"  ✅ {skill['dir_name']}/SKILL.md")
    return count


def _export_claude(skills: List[Dict[str, Any]], output_dir: Path, skill_filter: Optional[str] = None) -> int:
    """Export to Claude Code format: .claude/skills/<name>/SKILL.md + CLAUDE.md"""
    count = 0
    skill_names = []
    for skill in skills:
        if skill_filter and skill["dir_name"] != skill_filter:
            continue
        target = output_dir / skill["dir_name"] / "SKILL.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(skill["content"], encoding="utf-8")
        skill_names.append(skill["dir_name"])
        count += 1
        print(f"  ✅ {skill['dir_name']}/SKILL.md")

    # Generate CLAUDE.md at project root — Claude Code's primary entry point
    claude_md = output_dir.parent / "CLAUDE.md"
    if claude_md.exists():
        # Append skill listing to existing CLAUDE.md instead of overwriting
        existing = claude_md.read_text(encoding="utf-8")
        if "## Framework Skills" in existing:
            print(f"  ⚠️  CLAUDE.md already has Framework Skills section — skipping")
            return count
        lines = [existing, "\n\n## Framework Skills (auto-exported)\n\n"]
    else:
        lines = []
    lines.append("# Project Instructions — Auto-exported from Framework")
    lines.append("")
    lines.append(f"*Generated: {datetime.now(timezone.utc).isoformat()[:19]}*")
    lines.append(f"*Skills: {count}*")
    lines.append("")
    lines.append("## Available Skills")
    lines.append("")
    lines.append("Load skills on demand using `/skill <name>` or by reading `.claude/skills/<name>/SKILL.md`.")
    lines.append("")
    for name in skill_names:
        lines.append(f"- `{name}`")
    lines.append("")
    lines.append("## Core Principles")
    lines.append("")
    lines.append("- Verify every fact against source code before acting")
    lines.append("- No silent fallbacks — DEGRADED state after 3 failures")
    lines.append("- Self-citation is not proof")
    lines.append("- Staleness check: verify domain baselines before loading as context")
    lines.append("")
    claude_md.parent.mkdir(parents=True, exist_ok=True)
    claude_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✅ CLAUDE.md (project entry point)")
    return count


def _export_opencode(skills: List[Dict[str, Any]], output_dir: Path, skill_filter: Optional[str] = None) -> int:
    """Export to OpenCode format: .opencode/rules/<name>.md (no frontmatter)"""
    count = 0
    for skill in skills:
        if skill_filter and skill["dir_name"] != skill_filter:
            continue
        target = output_dir / f"{skill['dir_name']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)

        # OpenCode: no YAML frontmatter, just markdown with title header
        lines = []
        lines.append(f"# {skill['name']}")
        lines.append("")
        if skill["description"]:
            lines.append(f"> {skill['description']}")
            lines.append("")
        lines.append(f"*Version: {skill['version']} | Source: {skill['dir_name']}*")
        lines.append("")
        lines.append("---")
        lines.append("")
        # Strip frontmatter from body
        _, body = _parse_frontmatter(skill["content"])
        lines.append(body)

        target.write_text("\n".join(lines), encoding="utf-8")
        count += 1
        print(f"  ✅ {skill['dir_name']}.md")
    return count


def _export_cursor(skills: List[Dict[str, Any]], output_dir: Path, skill_filter: Optional[str] = None) -> int:
    """Export to Cursor format: .cursor/rules/<name>.mdc with custom frontmatter"""
    count = 0
    for skill in skills:
        if skill_filter and skill["dir_name"] != skill_filter:
            continue
        target = output_dir / f"{skill['dir_name']}.mdc"
        target.parent.mkdir(parents=True, exist_ok=True)

        # Cursor: YAML frontmatter with globs + alwaysApply
        lines = ["---"]
        lines.append(f"description: \"{skill['description'][:100]}\"")
        lines.append("globs: \"**/*\"")
        lines.append("alwaysApply: false")
        lines.append("---")
        lines.append("")
        # Strip frontmatter from body
        _, body = _parse_frontmatter(skill["content"])
        lines.append(body)

        target.write_text("\n".join(lines), encoding="utf-8")
        count += 1
        print(f"  ✅ {skill['dir_name']}.mdc")
    return count


def _export_windsurf(skills: List[Dict[str, Any]], output_dir: Path, skill_filter: Optional[str] = None) -> int:
    """Export to Windsurf format: .windsurf/rules/<name>.md"""
    count = 0
    for skill in skills:
        if skill_filter and skill["dir_name"] != skill_filter:
            continue
        target = output_dir / f"{skill['dir_name']}.md"
        target.parent.mkdir(parents=True, exist_ok=True)

        # Windsurf: similar to Cursor but .md extension
        lines = ["---"]
        lines.append(f"name: \"{skill['name']}\"")
        lines.append(f"description: \"{skill['description'][:100]}\"")
        lines.append("globs: \"**/*\"")
        lines.append("alwaysApply: false")
        lines.append("---")
        lines.append("")
        _, body = _parse_frontmatter(skill["content"])
        lines.append(body)

        target.write_text("\n".join(lines), encoding="utf-8")
        count += 1
        print(f"  ✅ {skill['dir_name']}.md")
    return count


def _export_copilot(skills: List[Dict[str, Any]], output_dir: Path, skill_filter: Optional[str] = None) -> int:
    """Export to Copilot format: single .github/copilot-instructions.md"""
    target = output_dir / "copilot-instructions.md"
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        existing = target.read_text(encoding="utf-8")
        if "## Framework Skills" in existing:
            print(f"  ⚠️  copilot-instructions.md already has Framework Skills — skipping")
            return 0
        print(f"  ⚠️  copilot-instructions.md exists — appending skill section")
        lines = [existing, "\n\n## Framework Skills (auto-exported)\n\n"]
    else:
        lines = []
    lines.append("# Copilot Instructions — Auto-exported from Framework")
    lines.append("")
    lines.append(f"*Generated: {datetime.now(timezone.utc).isoformat()[:19]}*")
    lines.append(f"*Skills: {len(skills)}*")
    lines.append("")
    lines.append("---")
    lines.append("")

    count = 0
    for skill in skills:
        if skill_filter and skill["dir_name"] != skill_filter:
            continue
        lines.append(f"## {skill['name']}")
        lines.append("")
        if skill["description"]:
            lines.append(f"> {skill['description']}")
            lines.append("")
        _, body = _parse_frontmatter(skill["content"])
        # Truncate long skills for Copilot (single-file format)
        if len(body) > 3000:
            body = body[:3000] + "\n\n*[Truncated — see full skill in framework]*\n"
        lines.append(body)
        lines.append("")
        lines.append("---")
        lines.append("")
        count += 1

    target.write_text("\n".join(lines), encoding="utf-8")
    print(f"  ✅ copilot-instructions.md ({count} skills merged)")
    return count


# ─── Platform → Output Dir Mapping ──────────────────────────────────────────

PLATFORM_EXPORTERS = {
    "hermes": ("~/.hermes/skills", _export_hermes),
    "claude": (".claude/skills", _export_claude),
    "opencode": (".opencode/rules", _export_opencode),
    "cursor": (".cursor/rules", _export_cursor),
    "windsurf": (".windsurf/rules", _export_windsurf),
    "copilot": (".github", _export_copilot),
}


# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_list_platforms() -> None:
    """Show all supported platforms."""
    formats = _load_formats()
    agents = formats.get("agents", {})

    print(f"{'PLATFORM':<12} {'NAME':<25} {'SKILL FORMAT':<15} {'LOCATION'}")
    print("─" * 80)
    for key, info in agents.items():
        print(f"{key:<12} {info['name']:<25} {info['skill_format']:<15} {info['skill_location']}")

    print(f"\nUse: migrate_skills.py export <platform>")


def cmd_export(platform: str, skill_filter: Optional[str] = None, group_filter: Optional[str] = None) -> None:
    """Export framework skills to a platform's native format."""
    if platform not in PLATFORM_EXPORTERS:
        print(f"ERROR: Unknown platform '{platform}'", file=sys.stderr)
        print(f"Available: {', '.join(PLATFORM_EXPORTERS.keys())}", file=sys.stderr)
        sys.exit(1)

    skills = _discover_skills()
    if not skills:
        print("No skills found in framework.")
        return

    # Apply group filter
    if group_filter:
        manifest_path = FRAMEWORK_ROOT / "domains" / "MANIFEST.json"
        if manifest_path.exists():
            with manifest_path.open("r") as f:
                manifest = json.load(f)
            group = manifest.get("skill_groups", {}).get(group_filter, {})
            group_skills = set(group.get("skills", []))
            skills = [s for s in skills if s["dir_name"] in group_skills]
            if not skills:
                print(f"No skills found in group '{group_filter}'")
                return

    output_dir_str, exporter = PLATFORM_EXPORTERS[platform]
    # Resolve ~ for hermes, use project root for others
    if output_dir_str.startswith("~"):
        output_dir = Path(output_dir_str).expanduser()
    else:
        output_dir = FRAMEWORK_ROOT.parent / output_dir_str

    print(f"Exporting {len(skills)} skills to {platform} format...")
    print(f"Output: {output_dir}")
    print()

    count = exporter(skills, output_dir, skill_filter)

    print(f"\n✅ {count} skill(s) exported to {platform} format at {output_dir}")


def cmd_diff(platform: str) -> None:
    """Show what would change without writing (dry-run)."""
    if platform not in PLATFORM_EXPORTERS:
        print(f"ERROR: Unknown platform '{platform}'", file=sys.stderr)
        sys.exit(1)

    skills = _discover_skills()
    output_dir_str, _ = PLATFORM_EXPORTERS[platform]
    if output_dir_str.startswith("~"):
        output_dir = Path(output_dir_str).expanduser()
    else:
        output_dir = FRAMEWORK_ROOT.parent / output_dir_str

    print(f"Diff: Framework → {platform} ({output_dir})")
    print()

    new_count = 0
    update_count = 0
    for skill in skills:
        ext = {"hermes": "SKILL.md", "claude": "SKILL.md", "opencode": ".md",
               "cursor": ".mdc", "windsurf": ".md", "copilot": ".md"}.get(platform, ".md")

        if platform in ("hermes", "claude"):
            target = output_dir / skill["dir_name"] / "SKILL.md"
        elif platform == "copilot":
            target = output_dir / "copilot-instructions.md"
        else:
            target = output_dir / f"{skill['dir_name']}{ext}"

        if target.exists():
            update_count += 1
            print(f"  📝 {skill['dir_name']} (would update)")
        else:
            new_count += 1
            print(f"  ➕ {skill['dir_name']} (would create)")

    print(f"\nSummary: {new_count} new, {update_count} updates")


def cmd_import(platform: str) -> None:
    """Import platform skills into framework (placeholder)."""
    print(f"Import from {platform}: not yet implemented.")
    print("This would read skills from the platform's native format")
    print("and convert them back to framework SKILL.md format.")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1

    command = argv[1]

    if command == "export":
        if len(argv) < 3:
            print("Usage: migrate_skills.py export <platform> [--skill <name>] [--group <name>]", file=sys.stderr)
            return 1
        platform = argv[2]
        skill_filter = None
        group_filter = None
        for i, arg in enumerate(argv):
            if arg == "--skill" and i + 1 < len(argv):
                skill_filter = argv[i + 1]
            if arg == "--group" and i + 1 < len(argv):
                group_filter = argv[i + 1]
        cmd_export(platform, skill_filter, group_filter)

    elif command == "list-platforms":
        cmd_list_platforms()

    elif command == "diff":
        if len(argv) < 3:
            print("Usage: migrate_skills.py diff <platform>", file=sys.stderr)
            return 1
        cmd_diff(argv[2])

    elif command == "import":
        if len(argv) < 3:
            print("Usage: migrate_skills.py import <platform>", file=sys.stderr)
            return 1
        cmd_import(argv[2])

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
