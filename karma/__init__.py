"""
LLM Middleware Runtime - Agent-agnostic context orchestration for any project.
"""

from .core.index import FactIndex, TokenEstimator
from .core.cache import CacheManager, CacheEntry, get_cache, clear_cache
from .core.context_optimizer import assemble_context, assemble_cascade_context, estimate_tokens, score_fact_relevance, compress_fact
from .core.falsification_gate import run_falsification_gate, FalsificationResult, FalsificationGate
from .core.memory import MemoryBus, load_memory, save_memory, get_fact, set_fact, load_log, add_log_entry, load_cascade, save_cascade
from .core.memory_core import list_projects, cache_stats, cache_clear, project_dir, memory_path, log_path, cascade_path, index_path, get_relevant_facts
from .core.persistence import PersistenceLayer, PersistenceConfig, create_persistence, migrate_from_json
from .orchestrator import (
    TEMPLATES,
    init_cascade,
    get_next_steps,
    generate_step_prompt,
    complete_step,
    fail_step,
    reset_cascade,
)
from .prompt_engine import load_formats, get_platform_config, list_platforms, generate_prompt, generate_full_prompt
from .skills.registry import SkillRegistry, SkillInfo, discover_skills, cmd_load, cmd_unload, cmd_load_all, cmd_unload_all, cmd_group, cmd_ungroup, cmd_context, cmd_status, cmd_list, cmd_discover
from .skills.creator import SkillCreator, SkillTemplate, cmd_create, cmd_update, cmd_delete, cmd_export, cmd_suggest
from .skills.loader import SkillLoader, PlatformAdapter

__version__ = "0.3.0"

__all__ = [
    "MemoryBus",
    "load_memory",
    "save_memory",
    "get_fact",
    "set_fact",
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
    "FactIndex",
    "TokenEstimator",
    "assemble_context",
    "assemble_cascade_context",
    "estimate_tokens",
    "score_fact_relevance",
    "compress_fact",
    "CacheManager",
    "CacheEntry",
    "get_cache",
    "clear_cache",
    "PersistenceLayer",
    "PersistenceConfig",
    "create_persistence",
    "migrate_from_json",
    "load_formats",
    "get_platform_config",
    "list_platforms",
    "generate_prompt",
    "generate_full_prompt",
    "TEMPLATES",
    "init_cascade",
    "get_next_steps",
    "generate_step_prompt",
    "complete_step",
    "fail_step",
    "reset_cascade",
    # falsification_gate
    "run_falsification_gate",
    "FalsificationResult",
    "FalsificationGate",
    "SkillRegistry",
    "SkillInfo",
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
    "SkillCreator",
    "SkillTemplate",
    "cmd_create",
    "cmd_update",
    "cmd_delete",
    "cmd_export",
    "cmd_suggest",
    "SkillLoader",
    "PlatformAdapter",
]

from .turn_kernel import handle_turn, TurnRequest, TurnResult
