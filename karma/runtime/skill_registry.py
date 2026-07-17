#!/usr/bin/env python3
"""
SyxCraft V71 Framework — Skill Registry

Dynamic skill discovery and state management.
Discovers all SKILL.md files under the framework root,
tracks loaded/unloaded state in the memory bus,
and provides query interfaces for /team orchestration.

Usage:
    skill_registry.py discover          # Scan all skills, return JSON
    skill_registry.py list              # Show all skills with status
    skill_registry.py load <name>       # Mark skill as loaded
    skill_registry.py unload <name>     # Mark skill as unloaded
    skill_registry.py status <name>     # Show skill details
    skill_registry.py context <name>    # Generate prompt context for a loaded skill
    skill_registry.py group <group>     # Load all skills in a group
    skill_registry.py ungroup <group>   # Unload all skills in a group
"""

import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# Framework root
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = FRAMEWORK_ROOT / "domains" / "MANIFEST.json"
MEMORY_BUS = FRAMEWORK_ROOT / "runtime" / "memory_bus.py"

# State file for tracking loaded skills (persists across sessions)
STATE_PATH = Path(os.environ.get(
    "SYXCRAFT_SKILL_STATE",
    str(Path.home() / ".karma" / "skill_state.json")
))

# ─── State persistence ──────────────────────────────────────────────────────

def _ensure_state_dir() -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)

def _load_state() -> Dict[str, Any]:
    _ensure_state_dir()
    if not STATE_PATH.exists():
        return {"loaded": {}, "history": [], "last_scan": None}
    try:
        with STATE_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"loaded": {}, "history": [], "last_scan": None}

def _save_state(state: Dict[str, Any]) -> None:
    _ensure_state_dir()
    temp = STATE_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    temp.replace(STATE_PATH)

# ─── Manifest loading ───────────────────────────────────────────────────────

def _load_manifest() -> Dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"domains": {}, "skill_groups": {}}
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"domains": {}, "skill_groups": {}}

# ─── Skill discovery ────────────────────────────────────────────────────────

def _parse_skill_frontmatter(skill_md: Path) -> Dict[str, Any]:
    """Parse YAML frontmatter from a SKILL.md file."""
    info: Dict[str, Any] = {
        "name": skill_md.parent.name,
        "path": str(skill_md.relative_to(FRAMEWORK_ROOT.parent)),
        "abs_path": str(skill_md),
        "description": "",
        "version": "unknown",
        "tags": [],
        "related_skills": [],
    }
    try:
        content = skill_md.read_text(encoding="utf-8")
    except OSError:
        return info

    # Extract YAML frontmatter
    match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
    if not match:
        return info

    frontmatter = match.group(1)
    for line in frontmatter.split("\n"):
        line = line.strip()
        if line.startswith("name:"):
            info["name"] = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("description:"):
            info["description"] = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("version:"):
            info["version"] = line.split(":", 1)[1].strip().strip('"\'')

    # Extract tags and related_skills from metadata block
    meta_match = re.search(r'metadata:\s*\n(.*?)(?=\n\S|\Z)', content, re.DOTALL)
    if meta_match:
        meta_block = meta_match.group(1)
        tags_match = re.search(r'tags:\s*\[(.*?)\]', meta_block)
        if tags_match:
            info["tags"] = [t.strip().strip('"\'') for t in tags_match.group(1).split(",")]
        related_match = re.search(r'related_skills:\s*\[(.*?)\]', meta_block)
        if related_match:
            info["related_skills"] = [s.strip().strip('"\'') for s in related_match.group(1).split(",")]

    return info

def discover_skills() -> Dict[str, Dict[str, Any]]:
    """Scan framework root for all SKILL.md files and parse them."""
    skills = {}
    for skill_md in sorted(FRAMEWORK_ROOT.rglob("SKILL.md")):
        # Skip domains/ subdirectory knowledge files
        rel = skill_md.relative_to(FRAMEWORK_ROOT)
        if str(rel).startswith("domains/"):
            continue
        info = _parse_skill_frontmatter(skill_md)
        skills[info["name"]] = info
    return skills

def _map_skills_to_domains(skills: Dict[str, Dict[str, Any]], manifest: Dict[str, Any]) -> Dict[str, List[str]]:
    """Map each skill to its primary domain(s) based on keywords and tags."""
    domain_map: Dict[str, List[str]] = {d: [] for d in manifest.get("domains", {})}
    domains = manifest.get("domains", {})

    for skill_name, info in skills.items():
        skill_text = f"{skill_name} {' '.join(info.get('tags', []))} {info.get('description', '')}".lower()
        matched_domains: List[str] = []

        for domain_name, domain_info in domains.items():
            domain_keywords = [kw.lower() for kw in domain_info.get("keywords", [])]
            if any(kw in skill_text for kw in domain_keywords):
                matched_domains.append(domain_name)

        if not matched_domains:
            matched_domains = ["documentation"]  # fallback

        for d in matched_domains:
            if d in domain_map:
                domain_map[d].append(skill_name)

    return domain_map

# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_discover() -> None:
    """Scan and return all skills as JSON."""
    skills = discover_skills()
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    state = _load_state()

    output = {
        "framework_root": str(FRAMEWORK_ROOT),
        "total_skills": len(skills),
        "total_domains": len(manifest.get("domains", {})),
        "loaded_count": len(state.get("loaded", {})),
        "skills": skills,
        "domain_map": domain_map,
        "skill_groups": manifest.get("skill_groups", {}),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

def cmd_list() -> None:
    """Show all skills with loaded/unloaded status."""
    skills = discover_skills()
    state = _load_state()
    loaded = state.get("loaded", {})
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)

    # Build reverse map: skill_name -> [domains]
    skill_to_domains: Dict[str, List[str]] = {}
    for domain_name, skill_names in domain_map.items():
        for sname in skill_names:
            skill_to_domains.setdefault(sname, []).append(domain_name)

    print(f"{'SKILL':<40} {'STATUS':<10} {'VERSION':<8} {'DOMAIN'}")
    print("─" * 80)
    for name, info in sorted(skills.items()):
        status = "🟢 LOADED" if name in loaded else "⚪ IDLE"
        domains = ", ".join(skill_to_domains.get(name, []))
        print(f"{name:<40} {status:<10} {info.get('version', '?'):<8} {domains}")

    print(f"\nTotal: {len(skills)} skills, {len(loaded)} loaded")

def cmd_load(skill_name: str) -> None:
    """Mark a skill as loaded."""
    skills = discover_skills()
    if skill_name not in skills:
        print(f"ERROR: Skill '{skill_name}' not found. Available: {', '.join(sorted(skills.keys()))}", file=sys.stderr)
        sys.exit(1)

    state = _load_state()
    loaded = state.get("loaded", {})
    loaded[skill_name] = {
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "version": skills[skill_name].get("version", "unknown"),
    }
    state["loaded"] = loaded
    state.setdefault("history", []).append({
        "action": "load",
        "skill": skill_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_state(state)
    print(f"✅ Loaded: {skill_name} v{skills[skill_name].get('version', '?')}")

def cmd_unload(skill_name: str) -> None:
    """Mark a skill as unloaded."""
    state = _load_state()
    loaded = state.get("loaded", {})
    if skill_name not in loaded:
        print(f"WARN: '{skill_name}' was not loaded.", file=sys.stderr)
        return

    del loaded[skill_name]
    state["loaded"] = loaded
    state.setdefault("history", []).append({
        "action": "unload",
        "skill": skill_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_state(state)
    print(f"⚪ Unloaded: {skill_name}")

def cmd_status(skill_name: str) -> None:
    """Show detailed info about a skill."""
    skills = discover_skills()
    if skill_name not in skills:
        print(f"ERROR: Skill '{skill_name}' not found.", file=sys.stderr)
        sys.exit(1)

    info = skills[skill_name]
    state = _load_state()
    loaded_info = state.get("loaded", {}).get(skill_name)
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)

    # Find which domains this skill belongs to
    skill_domains = [d for d, s_list in domain_map.items() if skill_name in s_list]

    output = {
        "name": info["name"],
        "version": info.get("version", "unknown"),
        "description": info.get("description", ""),
        "path": info["path"],
        "tags": info.get("tags", []),
        "related_skills": info.get("related_skills", []),
        "domains": skill_domains,
        "loaded": loaded_info is not None,
        "loaded_at": loaded_info.get("loaded_at") if loaded_info else None,
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

def cmd_context(skill_name: str) -> None:
    """Generate the prompt context block for a loaded skill."""
    skills = discover_skills()
    if skill_name not in skills:
        print(f"ERROR: Skill '{skill_name}' not found.", file=sys.stderr)
        sys.exit(1)

    info = skills[skill_name]
    skill_path = Path(info["abs_path"])

    # Read the SKILL.md content
    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError:
        print(f"ERROR: Cannot read {skill_path}", file=sys.stderr)
        sys.exit(1)

    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    skill_domains = [d for d, s_list in domain_map.items() if skill_name in s_list]

    # Load domain knowledge for matched domains (truncated to fit prompt budget)
    MAX_KNOWLEDGE_CHARS = 2000  # Keep domain context compact for prompt injection
    domain_context = {}
    for domain_name in skill_domains:
        domain_info = manifest.get("domains", {}).get(domain_name, {})
        knowledge_path = FRAMEWORK_ROOT / domain_info.get("knowledge", "")
        if knowledge_path.exists():
            try:
                domain_context[domain_name] = knowledge_path.read_text(encoding="utf-8")[:MAX_KNOWLEDGE_CHARS]
            except OSError:
                pass

    output = {
        "skill_name": skill_name,
        "skill_content": content,
        "domains": skill_domains,
        "domain_context": domain_context,
        "related_skills": info.get("related_skills", []),
    }
    print(json.dumps(output, indent=2, ensure_ascii=False))

def cmd_group(group_name: str) -> None:
    """Load all skills in a named group."""
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})
    if group_name not in groups:
        print(f"ERROR: Group '{group_name}' not found. Available: {', '.join(sorted(groups.keys()))}", file=sys.stderr)
        sys.exit(1)

    group = groups[group_name]
    skills = discover_skills()
    load_order = group.get("load_order", group.get("skills", []))

    loaded_count = 0
    for skill_name in load_order:
        if skill_name in skills:
            cmd_load(skill_name)
            loaded_count += 1
        else:
            print(f"  WARN: Skill '{skill_name}' in group '{group_name}' not found, skipping.", file=sys.stderr)

    print(f"\n📦 Group '{group_name}': {loaded_count}/{len(load_order)} skills loaded")

def cmd_ungroup(group_name: str) -> None:
    """Unload all skills in a named group."""
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})
    if group_name not in groups:
        print(f"ERROR: Group '{group_name}' not found.", file=sys.stderr)
        sys.exit(1)

    group = groups[group_name]
    for skill_name in group.get("skills", []):
        cmd_unload(skill_name)

    print(f"\n📦 Group '{group_name}': all skills unloaded")

def cmd_load_all() -> None:
    """Load every discovered skill."""
    skills = discover_skills()
    for name in sorted(skills.keys()):
        cmd_load(name)
    print(f"\n🚀 All {len(skills)} skills loaded")

def cmd_unload_all() -> None:
    """Unload every loaded skill."""
    state = _load_state()
    count = len(state.get("loaded", {}))
    state["loaded"] = {}
    state.setdefault("history", []).append({
        "action": "unload_all",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_state(state)
    print(f"⚪ All {count} skills unloaded")

# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1

    command = argv[1]

    if command == "discover":
        cmd_discover()
    elif command == "list":
        cmd_list()
    elif command == "load":
        if len(argv) < 3:
            print("Usage: skill_registry.py load <name>", file=sys.stderr)
            return 1
        cmd_load(argv[2])
    elif command == "unload":
        if len(argv) < 3:
            print("Usage: skill_registry.py unload <name>", file=sys.stderr)
            return 1
        cmd_unload(argv[2])
    elif command == "status":
        if len(argv) < 3:
            print("Usage: skill_registry.py status <name>", file=sys.stderr)
            return 1
        cmd_status(argv[2])
    elif command == "context":
        if len(argv) < 3:
            print("Usage: skill_registry.py context <name>", file=sys.stderr)
            return 1
        cmd_context(argv[2])
    elif command == "group":
        if len(argv) < 3:
            print("Usage: skill_registry.py group <group_name>", file=sys.stderr)
            return 1
        cmd_group(argv[2])
    elif command == "ungroup":
        if len(argv) < 3:
            print("Usage: skill_registry.py ungroup <group_name>", file=sys.stderr)
            return 1
        cmd_ungroup(argv[2])
    elif command == "load-all":
        cmd_load_all()
    elif command == "unload-all":
        cmd_unload_all()
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
