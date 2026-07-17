"""
LLM Middleware — Memory Bus & Project Memory
Persistent read/write store backed entirely by SQLite (ACID/isolation).
No direct JSON file writes.
"""

import json
import os
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_middleware.core.persistence import create_persistence, create_project_persistence

REQUIRED_FACT_KEYS = {"fact", "source", "confidence", "verified_by"}
CONFIDENCE_LEVELS = {"high", "medium", "low"}


def _validate_fact(value: Any) -> None:
    if not isinstance(value, dict):
        raise ValueError("Facts must be JSON objects.")
    if "fact" not in value:
        return  # Allow raw config objects
    missing = REQUIRED_FACT_KEYS - value.keys()
    if missing:
        raise ValueError(f"Fact missing required keys: {missing}")
    if value["confidence"] not in CONFIDENCE_LEVELS:
        raise ValueError(f"Invalid confidence '{value['confidence']}'. Valid: {CONFIDENCE_LEVELS}")


# ─── Public API: MemoryBus Class ────────────────────────────────────────────

class MemoryBus:
    """Main interface for memory operations. Entirely backed by SQLite."""
    
    def __init__(self, project: str = "default"):
        self.project = project
        self.persistence = create_project_persistence(project)
        self.persistence.create_project(project)
    
    def get(self, domain: Optional[str] = None, key: Optional[str] = None) -> Any:
        if domain is None:
            data = self.persistence.get_all_memory(self.project)
            data["project"] = self.project
            return data
        if key is None:
            return self.persistence.get_domain(self.project, domain)
        return self.persistence.get_fact(self.project, domain, key)
    
    def set(self, domain: str, value: Any, key: Optional[str] = None) -> None:
        _validate_fact(value)
        if key is None:
            if not isinstance(value, dict):
                raise ValueError("Value must be a dict when key is None")
            # Overwrite entire domain
            self.persistence.delete_fact(self.project, domain)
            for k, v in value.items():
                if k.startswith("_"):
                    continue
                self.persistence.set_fact(self.project, domain, k, v)
        else:
            self.persistence.set_fact(self.project, domain, key, value)
    
    def update(self, domain: str, key: str, value: Any) -> None:
        _validate_fact(value)
        existing = self.persistence.get_fact(self.project, domain, key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged = dict(existing)
            merged.update(value)
            self.persistence.set_fact(self.project, domain, key, merged)
        else:
            self.persistence.set_fact(self.project, domain, key, value)
    
    def delete(self, domain: str, key: Optional[str] = None) -> None:
        self.persistence.delete_fact(self.project, domain, key)
    
    def list_domains(self) -> Dict[str, Dict[str, Any]]:
        domains = self.persistence.list_domains(self.project)
        return {
            d["domain"]: {
                "keys": d["keys"],
                "last_updated": d["last_updated"][:19] if d["last_updated"] else "—"
            }
            for d in domains
        }
    
    def cross_project(self, domain: str, key: str) -> Dict[str, Any]:
        global_persistence = create_persistence()
        return global_persistence.cross_project_query(domain, key)
    
    def log(self, limit: int = 20, agent: Optional[str] = None) -> List[Dict[str, Any]]:
        return self.persistence.load_log(self.project, limit, agent)
    
    def log_add(self, entry: Dict[str, Any]) -> None:
        self.persistence.add_log_entry(self.project, entry)
    
    @staticmethod
    def list_projects() -> List[Dict[str, Any]]:
        projects_dir = Path(
            os.environ.get(
                "LLM_MIDDLEWARE_ROOT",
                str(Path.home() / ".llm-middleware"),
            )
        ) / "projects"
        if not projects_dir.exists():
            return []
        projects = []
        for f in sorted(projects_dir.glob("*.db")):
            name = f.stem
            proj_p = create_project_persistence(name)
            stats = proj_p.fetchone("""
                SELECT 
                    (SELECT COUNT(DISTINCT domain) FROM facts) as domains,
                    (SELECT COUNT(*) FROM facts) as facts,
                    (SELECT COUNT(*) FROM execution_log) as logs
            """)
            projects.append({
                "name": name,
                "domains": stats["domains"] if stats and stats["domains"] is not None else 0,
                "facts": stats["facts"] if stats and stats["facts"] is not None else 0,
                "logs": stats["logs"] if stats and stats["logs"] is not None else 0,
                "indexed": stats["facts"] if stats and stats["facts"] is not None else 0,
            })
        return projects
    
    @staticmethod
    def switch(project: str) -> None:
        global_p = create_persistence()
        global_p.switch_project(project)
        proj_p = create_project_persistence(project)
        proj_p.create_project(project)
    
    @staticmethod
    def active() -> str:
        global_p = create_persistence()
        return global_p.get_active_project()


# ─── Module-level functions for backward compatibility ──────────────────────

def load_memory(project: str) -> Dict[str, Any]:
    persistence = create_project_persistence(project)
    data = persistence.get_all_memory(project)
    data["project"] = project
    return data


def save_memory(project: str, data: Dict[str, Any]) -> None:
    persistence = create_project_persistence(project)
    domains = data.get("domains", {})
    for domain, keys in domains.items():
        existing_keys = set(persistence.get_domain(project, domain).keys())
        new_keys = set(k for k in keys.keys() if not k.startswith("_"))
        for key, value in keys.items():
            if key.startswith("_"):
                continue
            persistence.set_fact(project, domain, key, value)
        for key in existing_keys - new_keys:
            persistence.delete_fact(project, domain, key)
    all_stored_domains = [d["domain"] for d in persistence.list_domains(project)]
    for domain in all_stored_domains:
        if domain not in domains:
            persistence.delete_fact(project, domain)


def get_fact(project: str, domain: str, key: str) -> Optional[Any]:
    persistence = create_project_persistence(project)
    return persistence.get_fact(project, domain, key)


def set_fact(project: str, domain: str, key: str, value: Any) -> None:
    persistence = create_project_persistence(project)
    persistence.set_fact(project, domain, key, value)


def load_log(project: str, limit: int = 50, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    persistence = create_project_persistence(project)
    return persistence.load_log(project, limit, agent)


def add_log_entry(project: str, entry: Dict[str, Any]) -> None:
    persistence = create_project_persistence(project)
    persistence.add_log_entry(project, entry)


def load_cascade(project: str) -> Dict[str, Any]:
    persistence = create_project_persistence(project)
    return persistence.load_cascade(project)


def save_cascade(project: str, state: Dict[str, Any]) -> None:
    persistence = create_project_persistence(project)
    persistence.save_cascade(project, state)


def list_projects() -> List[Dict[str, Any]]:
    return MemoryBus.list_projects()


# Re-export
__all__ = [
    "MemoryBus",
    "load_memory",
    "save_memory", 
    "get_fact",
    "set_fact",
    "load_log",
    "add_log_entry",
    "load_cascade",
    "save_cascade",
    "list_projects",
]