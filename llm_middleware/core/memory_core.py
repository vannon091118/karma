"""
LLM Middleware Runtime — Memory Core
Primary data source for all agent interactions, backed entirely by SQLite.
No direct JSON file writes.
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from llm_middleware.core.persistence import create_persistence, create_project_persistence

_cache: Dict[str, Any] = {}
_cache_hits = 0
_cache_misses = 0


def _cache_key(project: str, domain: Optional[str] = None, key: Optional[str] = None) -> str:
    parts = [project]
    if domain:
        parts.append(domain)
    if key:
        parts.append(key)
    return ":".join(parts)


def _cache_get(project: str, domain: Optional[str] = None, key: Optional[str] = None) -> Optional[Any]:
    global _cache_hits, _cache_misses
    ck = _cache_key(project, domain, key)
    if ck in _cache:
        _cache_hits += 1
        return _cache[ck]
    _cache_misses += 1
    return None


def _cache_set(value: Any, project: str, domain: Optional[str] = None, key: Optional[str] = None) -> None:
    ck = _cache_key(project, domain, key)
    _cache[ck] = value


def cache_stats() -> Dict[str, int]:
    return {"hits": _cache_hits, "misses": _cache_misses, "size": len(_cache)}


def cache_clear() -> None:
    global _cache, _cache_hits, _cache_misses
    _cache = {}
    _cache_hits = 0
    _cache_misses = 0


PROJECTS_DIR = Path.home() / ".llm-middleware" / "projects"


def project_dir(project: str) -> Path:
    d = PROJECTS_DIR / project
    d.mkdir(parents=True, exist_ok=True)
    return d


def memory_path(project: str) -> Path:
    return project_dir(project) / "memory.json"


def log_path(project: str) -> Path:
    return project_dir(project) / "execution_log.json"


def cascade_path(project: str) -> Path:
    return project_dir(project) / "cascade_state.json"


def index_path(project: str) -> Path:
    return project_dir(project) / "index.json"


# ─── Memory I/O ─────────────────────────────────────────────────────────────

def load_memory(project: str) -> Dict[str, Any]:
    """Load project memory from SQLite."""
    cached = _cache_get(project)
    if cached is not None:
        return cached
        
    persistence = create_project_persistence(project)
    data = persistence.get_all_memory(project)
    data["project"] = project
    _cache_set(data, project)
    return data


def save_memory(project: str, data: Dict[str, Any]) -> None:
    """Save project memory to SQLite and invalidate cache."""
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
            
    # delete removed domains
    all_stored_domains = [d["domain"] for d in persistence.list_domains(project)]
    for domain in all_stored_domains:
        if domain not in domains:
            persistence.delete_fact(project, domain)
            
    _cache.pop(_cache_key(project), None)


# ─── Granular Fact Access ───────────────────────────────────────────────────

def get_fact(project: str, domain: str, key: str) -> Optional[Any]:
    """Get a single fact from SQLite."""
    cached = _cache_get(project, domain, key)
    if cached is not None:
        return cached

    persistence = create_project_persistence(project)
    value = persistence.get_fact(project, domain, key)
    if value is not None:
        _cache_set(value, project, domain, key)
    return value


def set_fact(project: str, domain: str, key: str, value: Any) -> None:
    """Set a single fact in SQLite."""
    persistence = create_project_persistence(project)
    persistence.set_fact(project, domain, key, value)
    _cache_set(value, project, domain, key)


# ─── Relevance Scoring ──────────────────────────────────────────────────────

def score_relevance(fact_key: str, task_keywords: List[str]) -> float:
    """Score how relevant a fact is to a task. 0.0 = irrelevant, 1.0 = critical."""
    fact_lower = fact_key.lower()
    for kw in task_keywords:
        if kw.lower() in fact_lower:
            return 1.0
    for kw in task_keywords:
        for word in kw.lower().split("_"):
            if len(word) > 3 and word in fact_lower:
                return 0.5
    return 0.0


def get_relevant_facts(project: str, domains: List[str], task_keywords: List[str],
                       token_budget: int = 4000) -> Dict[str, Any]:
    """Get facts relevant to a task from SQLite, sorted by relevance, within token budget."""
    if not domains:
        return {}
        
    persistence = create_project_persistence(project)
    placeholders = ",".join("?" for _ in domains)
    rows = persistence.fetchall(
        f"SELECT domain, key, value, tokens FROM facts WHERE project = ? AND domain IN ({placeholders})",
        (project, *domains)
    )
    
    candidates: List[Tuple[float, str, str, Any, int]] = []
    for r in rows:
        domain = r["domain"]
        key = r["key"]
        value = json.loads(r["value"])
        tokens = r["tokens"]
        
        entry_key = f"{domain}.{key}"
        relevance = score_relevance(entry_key, task_keywords)
        candidates.append((relevance, domain, key, value, tokens))
        
    candidates.sort(key=lambda x: x[0], reverse=True)
    
    result: Dict[str, Any] = {}
    used_tokens = 0
    for relevance, domain, key, value, tokens in candidates:
        if used_tokens + tokens > token_budget and relevance < 0.5:
            break
        result.setdefault(domain, {})[key] = value
        used_tokens += tokens
        
    return result


# ─── Execution Log ──────────────────────────────────────────────────────────

def load_log(project: str, limit: int = 50, agent: Optional[str] = None) -> List[Dict[str, Any]]:
    persistence = create_project_persistence(project)
    return persistence.load_log(project, limit, agent)


def add_log_entry(project: str, entry: Dict[str, Any]) -> None:
    persistence = create_project_persistence(project)
    persistence.add_log_entry(project, entry)


# ─── Cascade State ──────────────────────────────────────────────────────────

def load_cascade(project: str) -> Dict[str, Any]:
    persistence = create_project_persistence(project)
    return persistence.load_cascade(project)


def save_cascade(project: str, state: Dict[str, Any]) -> None:
    persistence = create_project_persistence(project)
    persistence.save_cascade(project, state)


# ─── Project Listing ────────────────────────────────────────────────────────

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
