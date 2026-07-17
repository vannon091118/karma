"""
LLM Middleware Runtime - Compatibility Layer
Re-exports all runtime modules for backward compatibility.
"""

from .memory_core import (
    load_memory,
    save_memory,
    get_fact,
    set_fact,
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

from .context_optimizer import (
    assemble_context,
    assemble_cascade_context,
    estimate_tokens,
    score_fact_relevance,
    compress_fact,
)

from .prompt_engine import (
    load_formats,
    get_platform_config,
    list_platforms,
    generate_prompt,
    generate_full_prompt,
)

from .orchestrator import (
    TEMPLATES,
    init_cascade,
    get_next_steps,
    generate_step_prompt,
    complete_step,
    fail_step,
    reset_cascade,
)

from .falsification_gate import (
    run_falsification_gate,
    FalsificationResult,
    FalsificationGate,
)

from .platform_adapter import load_formats as load_platform_formats

__all__ = [
    # memory_core
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
    # context_optimizer
    "assemble_context",
    "assemble_cascade_context",
    "estimate_tokens",
    "score_fact_relevance",
    "compress_fact",
    # prompt_engine
    "load_formats",
    "get_platform_config",
    "list_platforms",
    "generate_prompt",
    "generate_full_prompt",
    # orchestrator
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
    # platform_adapter
    "load_platform_formats",
]