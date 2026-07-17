"""
LLM Middleware Runtime — Memory Core Wrapper
Forwards all calls to the consolidated, SQLite-backed llm_middleware.core.memory_core.
"""

from llm_middleware.core.memory_core import (
    load_memory,
    save_memory,
    get_fact,
    set_fact,
    score_relevance,
    get_relevant_facts,
    load_log,
    add_log_entry,
    load_cascade,
    save_cascade,
    list_projects,
    cache_stats,
    cache_clear,
    project_dir,
    memory_path,
    log_path,
    cascade_path,
    index_path,
)

__all__ = [
    "load_memory",
    "save_memory",
    "get_fact",
    "set_fact",
    "score_relevance",
    "get_relevant_facts",
    "load_log",
    "add_log_entry",
    "load_cascade",
    "save_cascade",
    "list_projects",
    "cache_stats",
    "cache_clear",
    "project_dir",
    "memory_path",
    "log_path",
    "cascade_path",
    "index_path",
]
