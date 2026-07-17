"""
LLM Middleware — Skill Registry
Dynamic skill discovery, loading, and context generation.
"""

import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

# Framework root
FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
# Project root = parent of framework root (where domains/ lives)
PROJECT_ROOT = FRAMEWORK_ROOT.parent
SKILLS_ROOT = Path(os.environ.get(
    "HERMES_SKILLS_DIR",
    str(Path.home() / ".claude" / "skills")
))
MANIFEST_PATH = PROJECT_ROOT / "domains" / "MANIFEST.json"
MEMORY_BUS = FRAMEWORK_ROOT / "runtime" / "memory_bus.py"
# State file for tracking loaded skills
STATE_PATH = Path(os.environ.get(
    "LLM_MIDDLEWARE_SKILL_STATE",
    str(Path.home() / ".llm-middleware" / "skill_state.json")
))


# ─── State Persistence ──────────────────────────────────────────────────────

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


# ─── Manifest Loading ───────────────────────────────────────────────────────

def _load_manifest() -> Dict[str, Any]:
    if not MANIFEST_PATH.exists():
        return {"domains": {}, "skill_groups": {}}
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"domains": {}, "skill_groups": {}}


# ─── Skill Discovery & Parsing ──────────────────────────────────────────────

@dataclass
class SkillInfo:
    """Parsed skill metadata from SKILL.md frontmatter."""
    name: str
    path: str
    abs_path: str
    description: str = ""
    version: str = "unknown"
    tags: List[str] = field(default_factory=list)
    related_skills: List[str] = field(default_factory=list)
    domains: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    loaded: bool = False
    loaded_at: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "version": self.version,
            "tags": self.tags,
            "related_skills": self.related_skills,
            "domains": self.domains,
            "metadata": self.metadata,
            "loaded": self.loaded,
            "loaded_at": self.loaded_at,
        }


def _parse_skill_frontmatter(skill_md: Path) -> Dict[str, Any]:
    """Parse YAML frontmatter from a SKILL.md file."""
    info: Dict[str, Any] = {
        "name": skill_md.parent.name,
        "path": str(skill_md.relative_to(skill_md.parents[2]) if len(skill_md.parents) >= 3 else skill_md),
        "abs_path": str(skill_md),
        "description": "",
        "version": "unknown",
        "tags": [],
        "related_skills": [],
        "metadata": {},
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
    """Scan framework root and skills directories for all SKILL.md files and parse them."""
    skills = {}
    
    # Scan framework root (for syxcraft skills)
    for skill_md in sorted(FRAMEWORK_ROOT.rglob("SKILL.md")):
        # Skip domains/ subdirectory knowledge files
        rel = skill_md.relative_to(FRAMEWORK_ROOT)
        if str(rel).startswith("domains/"):
            continue
        info = _parse_skill_frontmatter(skill_md)
        skills[info["name"]] = info
    
    # Scan HERMES_SKILLS_DIR (~/.claude/skills)
    if SKILLS_ROOT.exists():
        for skill_md in sorted(SKILLS_ROOT.rglob("SKILL.md")):
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


def _load_skill_content(skill_name: str) -> str:
    """Read the SKILL.md content for a named skill."""
    skills = discover_skills()
    if skill_name not in skills:
        return f"[SKILL NOT FOUND: {skill_name}]"
    skill_path = Path(skills[skill_name]["abs_path"])
    try:
        return skill_path.read_text(encoding="utf-8")
    except OSError:
        return f"[SKILL UNREADABLE: {skill_path}]"


# ─── Skill Loading/Unloading Commands ───────────────────────────────────────

def cmd_load(skill_name: str) -> Dict[str, Any]:
    """Mark a skill as loaded."""
    skills = discover_skills()
    if skill_name not in skills:
        return {"error": f"Skill '{skill_name}' not found. Available: {', '.join(sorted(skills.keys()))}"}

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
    return {"loaded": skill_name, "version": skills[skill_name].get("version", "?")}


def cmd_unload(skill_name: str) -> Dict[str, Any]:
    """Mark a skill as unloaded."""
    state = _load_state()
    loaded = state.get("loaded", {})
    if skill_name not in loaded:
        return {"warning": f"'{skill_name}' was not loaded."}

    del loaded[skill_name]
    state["loaded"] = loaded
    state.setdefault("history", []).append({
        "action": "unload",
        "skill": skill_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_state(state)
    return {"unloaded": skill_name}


def cmd_load_all() -> Dict[str, Any]:
    """Load every discovered skill."""
    skills = discover_skills()
    loaded_count = 0
    for name in sorted(skills.keys()):
        cmd_load(name)
        loaded_count += 1
    return {"loaded": loaded_count, "total": len(skills)}


def cmd_unload_all() -> Dict[str, Any]:
    """Unload every loaded skill."""
    state = _load_state()
    count = len(state.get("loaded", {}))
    state["loaded"] = {}
    state.setdefault("history", []).append({
        "action": "unload_all",
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    _save_state(state)
    return {"unloaded": count}


def cmd_group(group_name: str) -> Dict[str, Any]:
    """Load all skills in a named group."""
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})
    if group_name not in groups:
        return {"error": f"Group '{group_name}' not found. Available: {', '.join(sorted(groups.keys()))}"}

    group = groups[group_name]
    skills = discover_skills()
    load_order = group.get("load_order", group.get("skills", []))
    loaded = []
    for skill_name in load_order:
        if skill_name in skills:
            cmd_load(skill_name)
            loaded.append(skill_name)
        else:
            print(f"  WARN: Skill '{skill_name}' in group '{group_name}' not found, skipping.", file=sys.stderr)

    return {"group": group_name, "loaded": loaded, "total": len(load_order)}


def cmd_ungroup(group_name: str) -> Dict[str, Any]:
    """Unload all skills in a named group."""
    manifest = _load_manifest()
    groups = manifest.get("skill_groups", {})
    if group_name not in groups:
        return {"error": f"Group '{group_name}' not found."}

    group = groups[group_name]
    for skill_name in group.get("skills", []):
        cmd_unload(skill_name)

    return {"group": group_name, "unloaded": True}


# ─── Skill Context Generation ───────────────────────────────────────────────

def cmd_context(skill_name: str) -> Dict[str, Any]:
    """Generate the full prompt context for a loaded skill."""
    skills = discover_skills()
    if skill_name not in skills:
        return {"error": f"Skill '{skill_name}' not found."}

    info = skills[skill_name]
    skill_path = Path(info["abs_path"])

    try:
        content = skill_path.read_text(encoding="utf-8")
    except OSError:
        return {"error": f"Cannot read {skill_path}"}

    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    skill_domains = [d for d, s_list in domain_map.items() if skill_name in s_list]

    # Load domain knowledge for matched domains (truncated)
    MAX_KNOWLEDGE_CHARS = 2000
    domain_context = {}
    for domain_name in skill_domains:
        domain_info = manifest.get("domains", {}).get(domain_name, {})
        knowledge_path = FRAMEWORK_ROOT / domain_info.get("knowledge", "")
        if knowledge_path.exists():
            try:
                domain_context[domain_name] = knowledge_path.read_text(encoding="utf-8")[:MAX_KNOWLEDGE_CHARS]
            except OSError:
                pass

    return {
        "skill_name": skill_name,
        "skill_content": content,
        "domains": skill_domains,
        "domain_context": domain_context,
        "related_skills": info.get("related_skills", []),
    }


def cmd_status(skill_name: str) -> Dict[str, Any]:
    """Show detailed info about a skill."""
    skills = discover_skills()
    if skill_name not in skills:
        return {"error": f"Skill '{skill_name}' not found."}

    info = skills[skill_name]
    state = _load_state()
    loaded_info = state.get("loaded", {}).get(skill_name)
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    skill_domains = [d for d, s_list in domain_map.items() if skill_name in s_list]

    return {
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


def cmd_list() -> List[Dict[str, Any]]:
    """Show all skills with loaded/unloaded status."""
    skills = discover_skills()
    state = _load_state()
    loaded = state.get("loaded", {})
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)

    # Build reverse map: skill_name -> [domains]
    skill_to_domains: Dict[str, List[str]] = {}
    for domain, skill_names in domain_map.items():
        for s in skill_names:
            skill_to_domains.setdefault(s, []).append(domain)

    result = []
    for name, info in sorted(skills.items()):
        result.append({
            "name": name,
            "status": "loaded" if name in loaded else "idle",
            "version": info.get("version", "?"),
            "domains": ", ".join(skill_to_domains.get(name, [])),
        })
    return result


def cmd_discover() -> Dict[str, Any]:
    """Scan and return all skills as JSON."""
    skills = discover_skills()
    manifest = _load_manifest()
    domain_map = _map_skills_to_domains(skills, manifest)
    state = _load_state()

    return {
        "framework_root": str(FRAMEWORK_ROOT),
        "total_skills": len(skills),
        "total_domains": len(manifest.get("domains", {})),
        "loaded_count": len(state.get("loaded", {})),
        "skills": skills,
        "domain_map": domain_map,
        "skill_groups": manifest.get("skill_groups", {}),
    }


# ─── SkillRegistry Class (High-level API) ───────────────────────────────────

class SkillRegistry:
    """High-level skill registry with caching and domain awareness."""
    
    def __init__(self):
        self._skills: Dict[str, SkillInfo] = {}
        self._manifest: Dict[str, Any] = {}
        self._domain_map: Dict[str, List[str]] = {}
        self._refresh()
    
    def _refresh(self) -> None:
        raw_skills = discover_skills()
        self._skills = {name: SkillInfo(info) for name, info in raw_skills.items()}
        self._manifest = _load_manifest()
        self._domain_map = _map_skills_to_domains(
            {name: info.to_dict() for name, info in self._skills.items()},
            self._manifest
        )
        # Assign domains to skill info
        for skill_name, domains in self._get_skill_domains().items():
            if skill_name in self._skills:
                self._skills[skill_name].domains = domains
    
    def _get_skill_domains(self) -> Dict[str, List[str]]:
        """Reverse map: skill_name -> [domains]"""
        result = {}
        for domain, skill_list in self._domain_map.items():
            for skill in skill_list:
                result.setdefault(skill, []).append(domain)
        return result
    
    def discover(self) -> Dict[str, SkillInfo]:
        """Discover and return all skills."""
        return self._skills
    
    def list(self, show_loaded: bool = True) -> List[Dict[str, Any]]:
        """List all skills with status."""
        state = _load_state()
        loaded = state.get("loaded", {})
        
        result = []
        for name, info in sorted(self._skills.items()):
            item = info.to_dict()
            item["status"] = "loaded" if name in loaded else "idle"
            if show_loaded and name in loaded:
                item["loaded_at"] = loaded[name].get("loaded_at")
            result.append(item)
        return result
    
    def load(self, name: str) -> Dict[str, Any]:
        """Load a skill."""
        if name not in self._skills:
            return {"error": f"Skill '{name}' not found"}
        return cmd_load(name)
    
    def unload(self, name: str) -> Dict[str, Any]:
        """Unload a skill."""
        return cmd_unload(name)
    
    def load_group(self, group: str) -> Dict[str, Any]:
        """Load a skill group."""
        return cmd_group(group)
    
    def unload_group(self, group: str) -> Dict[str, Any]:
        """Unload a skill group."""
        return cmd_ungroup(group)
    
    def load_all(self) -> Dict[str, Any]:
        """Load all skills."""
        return cmd_load_all()
    
    def unload_all(self) -> Dict[str, Any]:
        """Unload all skills."""
        return cmd_unload_all()
    
    def get_context(self, name: str) -> Dict[str, Any]:
        """Get prompt context for a skill."""
        return cmd_context(name)
    
    def get_content(self, name: str) -> str:
        """Get raw SKILL.md content."""
        return _load_skill_content(name)
    
    def get_groups(self) -> Dict[str, Dict[str, Any]]:
        """Get all skill groups."""
        return self._manifest.get("skill_groups", {})


__all__ = [
    "discover_skills",
    "cmd_load",
    "cmd_unload",
    "cmd_load_all",
    "cmd_unload_all",
    "cmd_group",
    "cmd_ungroup",
    "cmd_context",
    "cmd_status",
    "cmd_list",
    "cmd_discover",
    "SkillInfo",
    "SkillRegistry",
]