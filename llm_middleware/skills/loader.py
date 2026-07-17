"""
LLM Middleware — Skill Loader & Platform Adapter
Loads skills and exports them to platform-native formats.
"""

import json
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from .registry import SkillRegistry, discover_skills, _load_skill_content


# ─── Platform Format Registry ───────────────────────────────────────────────

PLATFORM_FORMATS = {
    "hermes": {
        "name": "Hermes (Freebuff)",
        "extension": ".md",
        "frontmatter": True,
        "delimiter": "---",
        "required_fields": ["name", "description", "version"],
        "skill_dir": "~/.hermes/skills/{name}/SKILL.md",
    },
    "claude": {
        "name": "Claude Code",
        "extension": ".md",
        "frontmatter": True,
        "delimiter": "---",
        "required_fields": ["name", "description"],
        "skill_dir": ".claude/skills/{name}/SKILL.md",
    },
    "opencode": {
        "name": "OpenCode",
        "extension": ".md",
        "frontmatter": False,
        "required_fields": ["title"],
        "skill_dir": ".opencode/rules/{name}.md",
        "header_format": "# {name}\n\n{description}\n\n---\n\n{content}",
    },
    "cursor": {
        "name": "Cursor",
        "extension": ".mdc",
        "frontmatter": True,
        "delimiter": "---",
        "required_fields": ["description"],
        "extra_frontmatter": {"globs": "**/*", "alwaysApply": False},
        "skill_dir": ".cursor/rules/{name}.mdc",
    },
    "windsurf": {
        "name": "Windsurf",
        "extension": ".md",
        "frontmatter": True,
        "delimiter": "---",
        "required_fields": ["name", "description"],
        "extra_frontmatter": {"globs": "**/*", "alwaysApply": False},
        "skill_dir": ".windsurf/rules/{name}.md",
    },
    "copilot": {
        "name": "GitHub Copilot",
        "extension": ".md",
        "frontmatter": False,
        "required_fields": [],
        "skill_dir": ".github/copilot-instructions.md",
        "note": "Copilot uses a single instructions file, not per-skill files",
    },
}


# ─── Platform Adapter ───────────────────────────────────────────────────────

class PlatformAdapter:
    """Adapts skills to platform-native formats."""
    
    def __init__(self, project_root: Optional[Path] = None):
        self.project_root = project_root or Path.cwd()
        self.registry = SkillRegistry()
    
    def list_platforms(self) -> Dict[str, Dict[str, Any]]:
        """List all supported platforms with format details."""
        return {k: v for k, v in PLATFORM_FORMATS.items()}
    
    def _render_hermes(self, skill_name: str, content: str) -> str:
        """Render for Hermes - keep as-is with frontmatter."""
        return content
    
    def _render_claude(self, skill_name: str, content: str) -> str:
        """Render for Claude Code - keep as-is with frontmatter."""
        return content
    
    def _render_opencode(self, skill_name: str, content: str) -> str:
        """Render for OpenCode - markdown without frontmatter."""
        # Extract frontmatter fields
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        frontmatter = {}
        body = content
        
        if match:
            fm_text = match.group(1)
            for line in fm_text.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip().strip('"\'')
            body = content[match.end():].strip()
        
        title = frontmatter.get("name", skill_name)
        description = frontmatter.get("description", "")
        
        fmt = PLATFORM_FORMATS["opencode"].get("header_format", "")
        return fmt.format(name=title, description=description, content=body)
    
    def _render_cursor(self, skill_name: str, content: str) -> str:
        """Render for Cursor - .mdc with frontmatter and globs."""
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        frontmatter = {}
        body = content
        
        if match:
            fm_text = match.group(1)
            for line in fm_text.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip().strip('"\'')
            body = content[match.end():].strip()
        
        # Add Cursor-specific frontmatter
        extra = PLATFORM_FORMATS["cursor"].get("extra_frontmatter", {})
        frontmatter.update(extra)
        
        # Build frontmatter
        fm_lines = ["---"]
        for k, v in frontmatter.items():
            if isinstance(v, bool):
                fm_lines.append(f"{k}: {str(v).lower()}")
            elif isinstance(v, str):
                fm_lines.append(f'{k}: "{v}"')
            else:
                fm_lines.append(f"{k}: {v}")
        fm_lines.append("---")
        
        return "\n".join(fm_lines) + "\n\n" + body
    
    def _render_windsurf(self, skill_name: str, content: str) -> str:
        """Render for Windsurf - similar to Cursor."""
        return self._render_cursor(skill_name, content)
    
    def _render_copilot(self, skill_name: str, content: str) -> str:
        """Render for Copilot - append to single instructions file."""
        # Extract key info
        match = re.match(r'^---\s*\n(.*?)\n---', content, re.DOTALL)
        frontmatter = {}
        body = content
        
        if match:
            fm_text = match.group(1)
            for line in fm_text.split("\n"):
                if ":" in line:
                    k, v = line.split(":", 1)
                    frontmatter[k.strip()] = v.strip().strip('"\'')
            body = content[match.end():].strip()
        
        title = frontmatter.get("name", skill_name)
        description = frontmatter.get("description", "")
        
        return f"## {title}\n\n{description}\n\n{body}\n"
    
    def render_skill(self, skill_name: str, platform: str) -> str:
        """Render a skill for a specific platform."""
        content = _load_skill_content(skill_name)
        if content.startswith("[SKILL"):
            return content
        
        renderer = getattr(self, f"_render_{platform}", None)
        if renderer:
            return renderer(skill_name, content)
        
        # Default: return as-is
        return content
    
    def export_skill(self, skill_name: str, platform: str, 
                     target_dir: Optional[Path] = None, 
                     force: bool = False) -> Dict[str, Any]:
        """Export a single skill to platform format."""
        if platform not in PLATFORM_FORMATS:
            return {"error": f"Unknown platform: {platform}"}
        
        fmt = PLATFORM_FORMATS[platform]
        content = self.render_skill(skill_name, platform)
        
        if content.startswith("[SKILL"):
            return {"error": content}
        
        # Determine target path
        if target_dir is None:
            target_dir = self.project_root
        
        skill_path_template = fmt["skill_dir"]
        if "{name}" in skill_path_template:
            skill_filename = skill_path_template.format(name=skill_name)
        else:
            skill_filename = skill_path_template
        
        target_path = target_dir / skill_filename
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Check if exists
        if target_path.exists() and not force:
            return {"error": f"File exists: {target_path} (use --force to overwrite)"}
        
        # Write
        target_path.write_text(content, encoding="utf-8")
        
        return {
            "status": "exported",
            "skill": skill_name,
            "platform": platform,
            "path": str(target_path),
        }
    
    def export_group(self, group_name: str, platform: str,
                     target_dir: Optional[Path] = None,
                     force: bool = False) -> Dict[str, Any]:
        """Export all skills in a group to platform format."""
        manifest = self.registry.get_groups()
        if group_name not in manifest:
            return {"error": f"Group '{group_name}' not found"}
        
        group = manifest[group_name]
        skills = group.get("load_order", group.get("skills", []))
        
        results = []
        for skill_name in skills:
            result = self.export_skill(skill_name, platform, target_dir, force)
            results.append(result)
        
        return {
            "group": group_name,
            "platform": platform,
            "results": results,
        }
    
    def export_all(self, platform: str, target_dir: Optional[Path] = None,
                   force: bool = False) -> Dict[str, Any]:
        """Export all skills to platform format."""
        skills = self.registry.discover()
        
        results = []
        for skill_name in skills:
            result = self.export_skill(skill_name, platform, target_dir, force)
            results.append(result)
        
        return {
            "platform": platform,
            "total": len(skills),
            "results": results,
        }


# ─── Skill Loader ───────────────────────────────────────────────────────────

class SkillLoader:
    """Loads skills and makes them available for agents."""
    
    def __init__(self, project: str = "default"):
        self.project = project
        self.registry = SkillRegistry()
        self.loaded: Dict[str, str] = {}  # skill_name -> content
    
    def load(self, skill_name: str) -> str:
        """Load a skill by name, caching the content."""
        if skill_name in self.loaded:
            return self.loaded[skill_name]
        
        content = _load_skill_content(skill_name)
        if content.startswith("[SKILL"):
            raise ValueError(content)
        
        self.loaded[skill_name] = content
        return content
    
    def load_group(self, group_name: str) -> Dict[str, str]:
        """Load all skills in a group."""
        manifest = self.registry.get_groups()
        if group_name not in manifest:
            raise ValueError(f"Group '{group_name}' not found")
        
        group = manifest[group_name]
        skills = group.get("load_order", group.get("skills", []))
        
        result = {}
        for skill_name in skills:
            try:
                result[skill_name] = self.load(skill_name)
            except ValueError:
                pass
        
        return result
    
    def load_all(self) -> Dict[str, str]:
        """Load all discovered skills."""
        skills = self.registry.discover()
        result = {}
        for skill_name in skills:
            try:
                result[skill_name] = self.load(skill_name)
            except ValueError:
                pass
        return result
    
    def get_loaded(self) -> Dict[str, str]:
        """Get currently loaded skills."""
        return self.loaded.copy()
    
    def unload(self, skill_name: str) -> bool:
        """Unload a skill from cache."""
        if skill_name in self.loaded:
            del self.loaded[skill_name]
            return True
        return False


# ─── Import re for rendering ────────────────────────────────────────────────

import re


__all__ = [
    "PlatformAdapter",
    "SkillLoader",
    "PLATFORM_FORMATS",
]