"""
LLM Middleware — Skill Creator
Generates new SKILL.md files from templates with auto-format detection.
"""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


# ─── Configuration ──────────────────────────────────────────────────────────

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = FRAMEWORK_ROOT / "domains" / "MANIFEST.json"
AGENT_FORMATS_PATH = FRAMEWORK_ROOT / "middleware" / "AGENT_FORMATS.json"

SKILL_TEMPLATE = """---
name: {name}
description: "{description}"
version: 0.1.0
author: Auto-generated
license: MIT
metadata:
  hermes:
    tags: {tags}
    related_skills: {related_skills}
---

# /{name} — {description}

## Overview

{description}

---

## Usage

Describe how to invoke this skill.

---

## Commands

| Command | Description |
|---------|-------------|
| `/{name}` | Main entry point |
| `/{name} --help` | Show help |

---

## Guardrails

| ⛔ Forbidden | ✅ Allowed |
|-------------|------------|
| Hardcoding values | Dynamic discovery via registry |
| External API calls without fallback | Local-first operations |

---

## Verification Checklist

- [ ] Skill loads without errors
- [ ] Context generation works
- [ ] Related skills identified correctly
"""


class SkillTemplate:
    """Template for generating new skills."""
    
    def __init__(self, name: str, description: str, tags: List[str] = None, 
                 related_skills: List[str] = None, domain: str = None):
        self.name = name
        self.description = description
        self.tags = tags or []
        self.related_skills = related_skills or []
        self.domain = domain
    
    def render(self) -> str:
        """Render the skill template."""
        return SKILL_TEMPLATE.format(
            name=self.name,
            description=self.description,
            tags=json.dumps(self.tags),
            related_skills=json.dumps(self.related_skills),
        )


class SkillCreator:
    """Creates new skills from templates with platform-specific exports."""
    
    def __init__(self, framework_root: Path = None):
        self.framework_root = framework_root or FRAMEWORK_ROOT
        self.manifest = self._load_manifest()
        self.agent_formats = self._load_agent_formats()
    
    def _load_manifest(self) -> Dict[str, Any]:
        if not MANIFEST_PATH.exists():
            return {"domains": {}, "skill_groups": {}}
        try:
            with MANIFEST_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"domains": {}, "skill_groups": {}}
    
    def _load_agent_formats(self) -> Dict[str, Any]:
        if not AGENT_FORMATS_PATH.exists():
            return {"agents": {}}
        try:
            with AGENT_FORMATS_PATH.open("r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {"agents": {}}
    
    def suggest_domain(self, name: str, description: str) -> List[str]:
        """Suggest domain(s) based on skill name and description."""
        text = f"{name} {description}".lower()
        suggestions = []
        
        for domain_name, domain_info in self.manifest.get("domains", {}).items():
            keywords = [kw.lower() for kw in domain_info.get("keywords", [])]
            if any(kw in text for kw in keywords):
                suggestions.append(domain_name)
        
        return suggestions or ["documentation"]
    
    def suggest_tags(self, name: str, description: str) -> List[str]:
        """Suggest tags based on skill content."""
        tags = []
        text = f"{name} {description}".lower()
        
        # Common tag patterns
        tag_patterns = {
            "pipeline": ["pipeline", "workflow", "build", "ci", "cd"],
            "analysis": ["analyze", "research", "scan", "inspect", "audit"],
            "execution": ["execute", "implement", "build", "create", "generate"],
            "validation": ["test", "verify", "validate", "falsify", "check"],
            "quality": ["quality", "clean", "refactor", "lint", "format"],
            "modding": ["mod", "modding", "game", "syxcraft", "engine"],
            "asset": ["asset", "sprite", "texture", "animation", "icon"],
            "documentation": ["doc", "readme", "changelog", "adr", "ssot"],
            "release": ["release", "version", "package", "deploy", "publish"],
            "performance": ["performance", "optimize", "benchmark", "profile"],
            "debug": ["debug", "inspect", "trace", "diagnose"],
        }
        
        for tag, patterns in tag_patterns.items():
            if any(p in text for p in patterns):
                tags.append(tag)
        
        return tags or ["utility"]
    
    def suggest_related_skills(self, name: str, description: str, max_suggestions: int = 3) -> List[str]:
        """Suggest related existing skills."""
        skills = self._discover_existing_skills()
        suggestions = []
        text = f"{name} {description}".lower()
        
        for skill_name, skill_info in skills.items():
            skill_text = f"{skill_name} {skill_info.get('description', '')} {' '.join(skill_info.get('tags', []))}".lower()
            # Simple overlap scoring
            overlap = len(set(text.split()) & set(skill_text.split()))
            if overlap > 2:
                suggestions.append((skill_name, overlap))
        
        suggestions.sort(key=lambda x: x[1], reverse=True)
        return [s[0] for s in suggestions[:max_suggestions]]
    
    def _discover_existing_skills(self) -> Dict[str, Dict[str, Any]]:
        """Discover all existing skills."""
        from .registry import discover_skills
        return discover_skills()
    
    def create_skill(self, name: str, description: str, domain: str = None,
                     tags: List[str] = None, related: List[str] = None,
                     output_dir: Path = None, dry_run: bool = False) -> Dict[str, Any]:
        """
        Create a new skill from template.
        
        Args:
            name: Skill name (lowercase, hyphens)
            description: Human-readable description
            domain: Target domain (auto-suggested if not provided)
            tags: List of tags (auto-suggested if not provided)
            related: Related skills (auto-suggested if not provided)
            output_dir: Custom output directory (default: .claude/skills/)
            dry_run: If True, return content without writing
            
        Returns:
            Dict with status, path, and generated content
        """
        # Validate name
        name = name.lower().replace("_", "-").replace(" ", "-")
        if not re.match(r'^[a-z0-9-]+$', name):
            return {"error": "Invalid name. Use lowercase letters, numbers, hyphens only."}
        
        # Check if skill already exists
        existing = self._discover_existing_skills()
        if name in existing:
            return {"error": f"Skill '{name}' already exists at {existing[name]['abs_path']}"}
        
        # Auto-suggest missing fields
        if domain is None:
            domains = self.suggest_domain(name, description)
            domain = domains[0] if domains else "documentation"
        
        if tags is None:
            tags = self.suggest_tags(name, description)
        
        if related is None:
            related = self.suggest_related_skills(name, description)
        
        # Create template
        template = SkillTemplate(name, description, tags, related, domain)
        content = template.render()
        
        # Determine output directory
        if output_dir is None:
            # Default to .claude/skills/<name>/SKILL.md (Hermes format)
            output_dir = self.framework_root / ".claude" / "skills" / name
        
        output_path = output_dir / "SKILL.md"
        
        if dry_run:
            return {
                "status": "dry_run",
                "name": name,
                "path": str(output_path),
                "content": content,
                "suggested_domain": domain,
                "suggested_tags": tags,
                "suggested_related": related,
            }
        
        # Write skill file
        output_dir.mkdir(parents=True, exist_ok=True)
        output_path.write_text(content, encoding="utf-8")
        
        # Export to all registered platforms
        exports = self.export_to_platforms(name, content, output_dir.parent)
        
        return {
            "status": "created",
            "name": name,
            "path": str(output_path),
            "domain": domain,
            "tags": tags,
            "related_skills": related,
            "exports": exports,
        }
    
    def export_to_platforms(self, name: str, content: str, base_dir: Path) -> Dict[str, Any]:
        """Export skill to all registered agent platforms."""
        agents = self.agent_formats.get("agents", {})
        exports = {}
        
        for platform, config in agents.items():
            try:
                export_path = self._export_to_platform(name, content, platform, config, base_dir)
                exports[platform] = {"status": "success", "path": str(export_path)}
            except Exception as e:
                exports[platform] = {"status": "error", "error": str(e)}
        
        return exports
    
    def _export_to_platform(self, name: str, content: str, platform: str, 
                           config: Dict[str, Any], base_dir: Path) -> Path:
        """Export a single skill to a specific platform format."""
        mapping = self.agent_formats.get("format_mapping", {}).get("skill_to_platform", {}).get(platform, {})
        
        # Determine file pattern
        file_pattern = mapping.get("file_pattern", "SKILL.md").replace("<name>", name)
        target_dir = base_dir / platform
        
        # Platform-specific directory structure
        if platform == "hermes":
            target_dir = base_dir / "hermes" / "skills" / name
        elif platform == "claude":
            target_dir = base_dir / "claude" / "skills" / name
        elif platform == "opencode":
            target_dir = base_dir / "opencode" / "rules"
            file_pattern = file_pattern.replace(".md", f"-{name}.md")
        elif platform == "cursor":
            target_dir = base_dir / "cursor" / "rules"
            file_pattern = file_pattern.replace(".mdc", f"-{name}.mdc")
        elif platform == "windsurf":
            target_dir = base_dir / "windsurf" / "rules"
        elif platform == "copilot":
            target_dir = base_dir / "github" / "copilot"
            file_pattern = "copilot-instructions.md"
        else:
            target_dir = base_dir / platform
        
        target_dir.mkdir(parents=True, exist_ok=True)
        target_path = target_dir / file_pattern
        
        # Transform content for platform
        platform_content = self._transform_for_platform(content, platform, mapping, name)
        target_path.write_text(platform_content, encoding="utf-8")
        
        return target_path
    
    def _transform_for_platform(self, content: str, platform: str, 
                               mapping: Dict[str, Any], name: str) -> str:
        """Transform skill content for platform-specific format."""
        if platform in ["hermes", "claude"]:
            # Keep as-is with YAML frontmatter
            return content
        
        if platform == "opencode":
            # OpenCode: plain markdown, no frontmatter
            # Extract title and description from frontmatter
            match = re.match(r'---\s*\n(.*?)\n---', content, re.DOTALL)
            if match:
                fm = match.group(1)
                title_match = re.search(r'name:\s*(.+)', fm)
                desc_match = re.search(r'description:\s*"(.+)"', fm)
                title = title_match.group(1).strip().strip('"\'') if title_match else name
                desc = desc_match.group(1).strip() if desc_match else ""
                
                body = content[match.end():].strip()
                return f"# {title}\n\n{desc}\n\n---\n\n{body}"
            return content
        
        if platform in ["cursor", "windsurf"]:
            # Cursor/Windsurf: MDC with custom frontmatter
            fm_lines = []
            fm_lines.append("---")
            fm_lines.append(f"description: \"{name} skill\"")
            
            extra_fm = mapping.get("extra_frontmatter", {})
            for k, v in extra_fm.items():
                if isinstance(v, str) and v.startswith("{") and v.endswith("}"):
                    # Template variable
                    var = v[1:-1]
                    if var == "name":
                        fm_lines.append(f"{k}: \"{name}\"")
                    else:
                        fm_lines.append(f"{k}: {v}")
                else:
                    fm_lines.append(f"{k}: {v}")
            fm_lines.append("---")
            fm_lines.append("")
            
            body = content
            # Remove existing frontmatter
            match = re.match(r'---\s*\n.*?\n---', content, re.DOTALL)
            if match:
                body = content[match.end():].strip()
            
            return "\n".join(fm_lines) + "\n" + body
        
        if platform == "copilot":
            # Copilot: single instructions file
            return f"# {name}\n\n{content}"
        
        return content
    
    def update_skill(self, name: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update an existing skill's metadata."""
        skills = self._discover_existing_skills()
        if name not in skills:
            return {"error": f"Skill '{name}' not found"}
        
        skill_path = Path(skills[name]["abs_path"])
        content = skill_path.read_text(encoding="utf-8")
        
        # Update frontmatter
        match = re.match(r'^(---\s*\n.*?\n---)', content, re.DOTALL)
        if not match:
            return {"error": "No valid frontmatter found"}
        
        fm = match.group(1)
        lines = fm.strip().split("\n")
        new_lines = []
        
        for line in lines:
            key = line.split(":")[0].strip() if ":" in line else None
            if key in updates:
                val = updates[key]
                if isinstance(val, list):
                    val = json.dumps(val)
                elif isinstance(val, str) and " " in val:
                    val = f'"{val}"'
                new_lines.append(f"{key}: {val}")
            else:
                new_lines.append(line)
        
        # Add new keys not in original
        existing_keys = {l.split(":")[0].strip() for l in lines if ":" in l}
        for key, val in updates.items():
            if key not in existing_keys:
                if isinstance(val, list):
                    val = json.dumps(val)
                elif isinstance(val, str) and " " in val:
                    val = f'"{val}"'
                new_lines.append(f"{key}: {val}")
        
        new_fm = "\n".join(new_lines)
        new_content = new_fm + content[match.end():]
        skill_path.write_text(new_content, encoding="utf-8")
        
        return {"status": "updated", "path": str(skill_path)}
    
    def delete_skill(self, name: str) -> Dict[str, Any]:
        """Delete a skill and its platform exports."""
        skills = self._discover_existing_skills()
        if name not in skills:
            return {"error": f"Skill '{name}' not found"}
        
        skill_path = Path(skills[name]["abs_path"])
        skill_dir = skill_path.parent
        
        # Remove skill directory
        import shutil
        if skill_dir.exists():
            shutil.rmtree(skill_dir)
        
        # Remove from platform exports
        removed = []
        for platform in self.agent_formats.get("agents", {}):
            platform_dir = self.framework_root / platform / "skills" / name
            if platform_dir.exists():
                shutil.rmtree(platform_dir)
                removed.append(platform)
        
        return {"status": "deleted", "name": name, "removed_from": removed}


# ─── CLI Commands ────────────────────────────────────────────────────────────

def cmd_create(name: str, description: str, **kwargs) -> Dict[str, Any]:
    """Create a new skill."""
    creator = SkillCreator()
    return creator.create_skill(name, description, **kwargs)


def cmd_update(name: str, **updates) -> Dict[str, Any]:
    """Update an existing skill."""
    creator = SkillCreator()
    return creator.update_skill(name, updates)


def cmd_delete(name: str) -> Dict[str, Any]:
    """Delete a skill."""
    creator = SkillCreator()
    return creator.delete_skill(name)


def cmd_export(name: str, platform: str = "all") -> Dict[str, Any]:
    """Export skill to platform format(s)."""
    creator = SkillCreator()
    skills = creator._discover_existing_skills()
    if name not in skills:
        return {"error": f"Skill '{name}' not found"}
    
    content = Path(skills[name]["abs_path"]).read_text(encoding="utf-8")
    
    if platform == "all":
        return creator.export_to_platforms(name, content, creator.framework_root / ".claude" / "skills")
    else:
        agents = creator.agent_formats.get("agents", {})
        if platform not in agents:
            return {"error": f"Unknown platform: {platform}"}
        export_path = creator._export_to_platform(name, content, platform, agents[platform], 
                                                 creator.framework_root / ".claude" / "skills")
        return {"status": "exported", "platform": platform, "path": str(export_path)}


def cmd_suggest(name: str, description: str) -> Dict[str, Any]:
    """Get auto-suggestions for a new skill."""
    creator = SkillCreator()
    return {
        "domain": creator.suggest_domain(name, description),
        "tags": creator.suggest_tags(name, description),
        "related_skills": creator.suggest_related_skills(name, description),
    }


# ─── SkillTemplate Class (re-export) ────────────────────────────────────────

__all__ = [
    "SkillTemplate",
    "SkillCreator",
    "cmd_create",
    "cmd_update",
    "cmd_delete",
    "cmd_export",
    "cmd_suggest",
]