#!/usr/bin/env python3
"""
LLM Middleware Runtime — Platform Adapter

Translates framework skills and context between different agent platform formats.
Each platform has its own conventions for skill files, context injection, and memory.

This adapter ensures the same skill content works seamlessly whether the agent
is Hermes, Claude Code, OpenCode, Cursor, Windsurf, or GitHub Copilot.

Bidirectional: exports framework skills to platform format AND imports
platform-format skills back into the framework.
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

FORMATS_PATH = FRAMEWORK_ROOT / "middleware" / "AGENT_FORMATS.json"


# ─── Format Registry ─────────────────────────────────────────────────────────

def load_formats() -> Dict[str, Any]:
    if not FORMATS_PATH.exists():
        return {"agents": {}}
    try:
        with FORMATS_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"agents": {}}


def get_platform(platform: str) -> Dict[str, Any]:
    return load_formats().get("agents", {}).get(platform, {})


# ─── Skill Discovery (Framework Format) ─────────────────────────────────────

def _discover_framework_skills() -> List[Dict[str, Any]]:
    """Find all SKILL.md files in the framework."""
    skills = []
    for skill_md in sorted(FRAMEWORK_ROOT.rglob("SKILL.md")):
        rel = str(skill_md.relative_to(FRAMEWORK_ROOT))
        if rel.startswith("domains/"):
            continue
        try:
            content = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue

        info = {
            "name": skill_md.parent.name,
            "path": rel,
            "abs_path": str(skill_md),
            "content": content,
        }

        # Parse frontmatter
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        if match:
            for line in match.group(1).split("\n"):
                line = line.strip()
                if line.startswith("description:"):
                    info["description"] = line.split(":", 1)[1].strip().strip('"\'')
                elif line.startswith("version:"):
                    info["version"] = line.split(":", 1)[1].strip().strip('"\'')
                elif line.startswith("name:"):
                    info["name"] = line.split(":", 1)[1].strip().strip('"\'')

        skills.append(info)
    return skills


# ─── Export: Framework → Platform ────────────────────────────────────────────

def _export_to_hermes(skills: List[Dict[str, Any]], output_dir: Path) -> int:
    """Export skills to Hermes format (SKILL.md with YAML frontmatter)."""
    count = 0
    for skill in skills:
        dest = output_dir / skill["name"] / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(skill["content"], encoding="utf-8")
        count += 1
    return count


def _export_to_claude(skills: List[Dict[str, Any]], output_dir: Path,
                      project_context: str = "", force: bool = False) -> int:
    """Export skills to Claude Code format (.claude/skills/<name>/SKILL.md + CLAUDE.md)."""
    skills_dir = output_dir / "skills"
    count = 0

    for skill in skills:
        dest = skills_dir / skill["name"] / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(skill["content"], encoding="utf-8")
        count += 1

    # Generate CLAUDE.md entry point
    claude_md = output_dir / "CLAUDE.md"
    if claude_md.exists() and not force:
        # Check if already has framework skills section
        existing = claude_md.read_text(encoding="utf-8")
        if "## Framework Skills" in existing:
            return count  # Already has our section
        # Append skill listing
        skill_lines = [f"- `{s['name']}`: {s.get('description', '')}" for s in skills]
        new_section = f"\n\n## Framework Skills (auto-exported)\n\n{chr(10).join(skill_lines)}\n"
        claude_md.write_text(existing + new_section, encoding="utf-8")
    else:
        # Generate fresh CLAUDE.md
        skill_lines = [f"- `{s['name']}`: {s.get('description', '')}" for s in skills]
        content = f"""# Claude Code — Project Skills

## Core Principles
- Read before you write
- Test before you commit
- Evidence over assumption

## Framework Skills (auto-exported)

{chr(10).join(skill_lines)}

## Usage
Load a skill by reading `.claude/skills/<name>/SKILL.md`.
"""
        claude_md.write_text(content, encoding="utf-8")

    return count


def _export_to_opencode(skills: List[Dict[str, Any]], output_dir: Path) -> int:
    """Export skills to OpenCode format (.opencode/rules/<name>.md)."""
    rules_dir = output_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for skill in skills:
        dest = rules_dir / f"{skill['name']}.md"
        # OpenCode: no frontmatter, just content with title header
        desc = skill.get("description", skill["name"])
        content = f"# {skill['name']}\n\n{desc}\n\n---\n\n"
        # Strip YAML frontmatter from original content
        raw = skill["content"]
        fm_match = re.match(r'^---\s*\n.*?\n---\s*\n?', raw, re.DOTALL)
        if fm_match:
            raw = raw[fm_match.end():]
        content += raw
        dest.write_text(content, encoding="utf-8")
        count += 1

    return count


def _export_to_cursor(skills: List[Dict[str, Any]], output_dir: Path) -> int:
    """Export skills to Cursor format (.cursor/rules/<name>.mdc)."""
    rules_dir = output_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for skill in skills:
        dest = rules_dir / f"{skill['name']}.mdc"
        desc = skill.get("description", skill["name"])
        # Cursor uses custom frontmatter with globs
        frontmatter = f"""---
description: {desc}
globs: "**/*"
alwaysApply: false
---
"""
        # Strip original frontmatter
        raw = skill["content"]
        fm_match = re.match(r'^---\s*\n.*?\n---\s*\n?', raw, re.DOTALL)
        if fm_match:
            raw = raw[fm_match.end():]
        dest.write_text(frontmatter + raw, encoding="utf-8")
        count += 1

    return count


def _export_to_windsurf(skills: List[Dict[str, Any]], output_dir: Path) -> int:
    """Export skills to Windsurf format (.windsurf/rules/<name>.md)."""
    rules_dir = output_dir / "rules"
    rules_dir.mkdir(parents=True, exist_ok=True)
    count = 0

    for skill in skills:
        dest = rules_dir / f"{skill['name']}.md"
        desc = skill.get("description", skill["name"])
        frontmatter = f"""---
name: {skill['name']}
description: {desc}
---
"""
        raw = skill["content"]
        fm_match = re.match(r'^---\s*\n.*?\n---\s*\n?', raw, re.DOTALL)
        if fm_match:
            raw = raw[fm_match.end():]
        dest.write_text(frontmatter + raw, encoding="utf-8")
        count += 1

    return count


def _export_to_copilot(skills: List[Dict[str, Any]], output_dir: Path) -> int:
    """Export all skills merged into a single copilot-instructions.md."""
    dest = output_dir / "copilot-instructions.md"
    dest.parent.mkdir(parents=True, exist_ok=True)

    if dest.exists():
        existing = dest.read_text(encoding="utf-8")
        if "## Framework Skills" in existing:
            return 0  # Already has our section

    sections = []
    for skill in skills:
        desc = skill.get("description", skill["name"])
        raw = skill["content"]
        fm_match = re.match(r'^---\s*\n.*?\n---\s*\n?', raw, re.DOTALL)
        if fm_match:
            raw = raw[fm_match.end():]
        sections.append(f"### {skill['name']}\n\n{desc}\n\n{raw}")

    content = "# Copilot Instructions — Framework Skills\n\n" + "\n\n---\n\n".join(sections)
    dest.write_text(content, encoding="utf-8")
    return len(skills)


# Export dispatch table
EXPORTERS = {
    "hermes": lambda s, o, **kw: _export_to_hermes(s, o),
    "claude": lambda s, o, **kw: _export_to_claude(s, o, force=kw.get("force", False)),
    "opencode": lambda s, o, **kw: _export_to_opencode(s, o),
    "cursor": lambda s, o, **kw: _export_to_cursor(s, o),
    "windsurf": lambda s, o, **kw: _export_to_windsurf(s, o),
    "copilot": lambda s, o, **kw: _export_to_copilot(s, o),
}

# Platform output directory (relative to project root)
OUTPUT_DIRS = {
    "hermes": Path.home() / ".hermes" / "skills",
    "claude": Path(".claude"),
    "opencode": Path(".opencode"),
    "cursor": Path(".cursor"),
    "windsurf": Path(".windsurf"),
    "copilot": Path(".github"),
}


# ─── Import: Platform → Framework ────────────────────────────────────────────

def _import_from_claude(skills_dir: Path) -> List[Dict[str, Any]]:
    """Import Claude Code skills back to framework format."""
    imported = []
    if not skills_dir.exists():
        return imported

    for skill_dir in sorted(skills_dir.iterdir()):
        skill_md = skill_dir / "SKILL.md"
        if skill_md.exists():
            content = skill_md.read_text(encoding="utf-8")
            imported.append({
                "name": skill_dir.name,
                "content": content,
                "source": "claude",
            })
    return imported


def _import_from_opencode(rules_dir: Path) -> List[Dict[str, Any]]:
    """Import OpenCode rules back to framework format."""
    imported = []
    if not rules_dir.exists():
        return imported

    for rule_file in sorted(rules_dir.glob("*.md")):
        content = rule_file.read_text(encoding="utf-8")
        # Convert to SKILL.md format with frontmatter
        name = rule_file.stem
        desc_match = re.search(r'^#\s+.*\n\n(.*?)(?:\n---|\n#|\Z)', content, re.DOTALL)
        desc = desc_match.group(1).strip() if desc_match else name

        skill_content = f"""---
name: {name}
description: {desc}
version: "1.0.0"
---

{content}
"""
        imported.append({
            "name": name,
            "content": skill_content,
            "source": "opencode",
        })
    return imported


def _import_from_cursor(rules_dir: Path) -> List[Dict[str, Any]]:
    """Import Cursor rules back to framework format."""
    imported = []
    if not rules_dir.exists():
        return imported

    for rule_file in sorted(rules_dir.glob("*.mdc")):
        content = rule_file.read_text(encoding="utf-8")
        name = rule_file.stem
        desc_match = re.search(r'description:\s*(.+)', content)
        desc = desc_match.group(1).strip() if desc_match else name

        # Strip Cursor frontmatter and add framework frontmatter
        fm_match = re.match(r'^---\s*\n.*?\n---\s*\n?', content, re.DOTALL)
        raw = content[fm_match.end():] if fm_match else content

        skill_content = f"""---
name: {name}
description: {desc}
version: "1.0.0"
---

{raw}
"""
        imported.append({
            "name": name,
            "content": skill_content,
            "source": "cursor",
        })
    return imported


IMPORTERS = {
    "claude": lambda p: _import_from_claude(p / "skills"),
    "opencode": lambda p: _import_from_opencode(p / "rules"),
    "cursor": lambda p: _import_from_cursor(p / "rules"),
}


# ─── Diff ────────────────────────────────────────────────────────────────────

def diff_export(platform: str, project_root: Optional[Path] = None) -> Dict[str, Any]:
    """Show what would be exported without writing. For dry-run previews."""
    skills = _discover_framework_skills()
    platform_config = get_platform(platform)

    if not platform_config:
        return {"error": f"Unknown platform: {platform}"}

    output_dir = OUTPUT_DIRS.get(platform, Path(f".{platform}"))
    if not output_dir.is_absolute():
        base = project_root or FRAMEWORK_ROOT.parent
        output_dir = base / output_dir

    # Count existing files
    existing_files = []
    if output_dir.exists():
        existing_files = [str(f.relative_to(output_dir)) for f in output_dir.rglob("*") if f.is_file()]

    return {
        "platform": platform,
        "platform_name": platform_config.get("name", platform),
        "skill_count": len(skills),
        "output_dir": str(output_dir),
        "existing_files": len(existing_files),
        "skills": [{"name": s["name"], "description": s.get("description", "")} for s in skills],
    }


# ─── CLI ────────────────────────────────────────────────────────────────────

USAGE = """LLM Middleware — Platform Adapter

Usage:
    platform_adapter.py list                                     List supported platforms
    platform_adapter.py export <platform> [--force] [--dry-run]  Export skills to platform format
    platform_adapter.py import <platform>                        Import skills from platform format
    platform_adapter.py diff <platform>                          Show export preview (dry-run)
"""


def cmd_list() -> None:
    formats = load_formats()
    agents = formats.get("agents", {})
    print(f"{'PLATFORM':<12} {'NAME':<25} {'FORMAT':<12} {'EXPORT':<6} {'IMPORT'}")
    print("─" * 70)
    for key, info in sorted(agents.items()):
        has_export = "✅" if key in EXPORTERS else "❌"
        has_import = "✅" if key in IMPORTERS else "❌"
        print(f"{key:<12} {info.get('name', '?'):<25} {info.get('skill_format', '?'):<12} {has_export:<6} {has_import}")


def cmd_export(platform: str, force: bool = False, dry_run: bool = False) -> None:
    if platform not in EXPORTERS:
        print(f"ERROR: Unknown platform '{platform}'. Available: {', '.join(EXPORTERS.keys())}", file=sys.stderr)
        sys.exit(1)

    skills = _discover_framework_skills()

    output_dir = OUTPUT_DIRS.get(platform, Path(f".{platform}"))
    if not output_dir.is_absolute():
        output_dir = FRAMEWORK_ROOT.parent / output_dir

    if dry_run:
        diff = diff_export(platform)
        print(json.dumps(diff, indent=2, ensure_ascii=False))
        return

    count = EXPORTERS[platform](skills, output_dir, force=force)
    print(f"✅ Exported {count} skills to {platform} format at {output_dir}")


def cmd_import(platform: str) -> None:
    if platform not in IMPORTERS:
        print(f"ERROR: Import not supported for '{platform}'. Available: {', '.join(IMPORTERS.keys())}", file=sys.stderr)
        sys.exit(1)

    input_dir = OUTPUT_DIRS.get(platform, Path(f".{platform}"))
    if not input_dir.is_absolute():
        input_dir = FRAMEWORK_ROOT.parent / input_dir

    imported = IMPORTERS[platform](input_dir)
    if not imported:
        print(f"No skills found to import from {platform} at {input_dir}")
        return

    # Write imported skills to framework
    for skill in imported:
        dest = FRAMEWORK_ROOT / "skills" / skill["name"] / "SKILL.md"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(skill["content"], encoding="utf-8")
        print(f"  ← {skill['name']} (from {skill['source']})")

    print(f"\n✅ Imported {len(imported)} skills from {platform}")


def cmd_diff(platform: str) -> None:
    diff = diff_export(platform)
    if "error" in diff:
        print(f"ERROR: {diff['error']}", file=sys.stderr)
        sys.exit(1)
    print(json.dumps(diff, indent=2, ensure_ascii=False))


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(USAGE)
        return 1

    command = argv[1]

    if command == "list":
        cmd_list()
    elif command == "export":
        if len(argv) < 3:
            print("Usage: platform_adapter.py export <platform> [--force] [--dry-run]", file=sys.stderr)
            return 1
        force = "--force" in argv
        dry_run = "--dry-run" in argv
        cmd_export(argv[2], force=force, dry_run=dry_run)
    elif command == "import":
        if len(argv) < 3:
            print("Usage: platform_adapter.py import <platform>", file=sys.stderr)
            return 1
        cmd_import(argv[2])
    elif command == "diff":
        if len(argv) < 3:
            print("Usage: platform_adapter.py diff <platform>", file=sys.stderr)
            return 1
        cmd_diff(argv[2])
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
