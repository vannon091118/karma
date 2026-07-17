#!/usr/bin/env python3
"""
LLM Middleware Runtime — Context Optimizer

Token-budgeted context assembly with relevance scoring.
Reads domain memory, filters by task keywords, compresses facts to fit
within a configurable token budget. Optimized for LLM prompt injection.

Key principle: Every token in the context must earn its place through relevance.
"""

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent

from llm_middleware.runtime import memory_core

# ─── Token Estimation ────────────────────────────────────────────────────────

from llm_middleware.core.index import estimate_tokens, estimate_tokens_json


# ─── Relevance Scoring ───────────────────────────────────────────────────────

def score_fact_relevance(fact_key: str, fact_value: Any, task_keywords: List[str],
                         domain_priority: int = 5) -> float:
    """
    Score a fact's relevance to a task. Higher = more relevant.
    
    Scoring factors:
    - Exact keyword match in key: +1.0
    - Partial keyword match in key: +0.5
    - Keyword found in value: +0.3
    - Domain priority bonus: priority 1 = +0.2, priority 5+ = +0.0
    """
    score = 0.0
    key_lower = fact_key.lower()
    value_str = json.dumps(fact_value, ensure_ascii=False).lower() if not isinstance(fact_value, str) else fact_value.lower()

    # Exact keyword match in key
    for kw in task_keywords:
        if kw.lower() in key_lower:
            score += 1.0
            break

    # Partial keyword match in key (split on underscores)
    if score < 0.5:
        for kw in task_keywords:
            for part in kw.lower().replace("-", "_").split("_"):
                if len(part) > 3 and part in key_lower:
                    score += 0.5
                    break
            if score >= 0.5:
                break

    # Keyword in value
    for kw in task_keywords:
        if kw.lower() in value_str:
            score += 0.3
            break

    # Domain priority bonus (P1 = +0.2, P5+ = +0.0)
    priority_bonus = max(0.0, 0.2 - (domain_priority - 1) * 0.05)
    score += priority_bonus

    return min(score, 2.0)


# ─── Compression Strategies ──────────────────────────────────────────────────

def compress_fact(key: str, value: Any, budget_remaining: int) -> Tuple[str, Any, int]:
    """
    Compress a fact to fit within the remaining token budget.
    Returns (key, compressed_value, tokens_used).
    
    Strategies (in order of preference):
    1. Full value if it fits
    2. Truncated string with [TRUNCATED] marker
    3. Summary dict with key fields only
    4. Skip if too small to be useful
    """
    full_tokens = estimate_tokens_json(value)

    if full_tokens <= budget_remaining:
        return key, value, full_tokens

    # Strategy 2: Truncate strings
    if isinstance(value, str):
        target_chars = budget_remaining * 3
        truncated = value[:target_chars] + " [TRUNCATED]"
        return key, truncated, estimate_tokens(truncated)

    # Strategy 3: Summary for dicts
    if isinstance(value, dict):
        summary = {}
        used = 0
        for k, v in value.items():
            item_tokens = estimate_tokens_json({k: v})
            if used + item_tokens > budget_remaining:
                summary["[TRUNCATED]"] = f"...{len(value) - len(summary)} more keys"
                break
            summary[k] = v
            used += item_tokens
        return key, summary, used

    # Strategy 4: Skip
    return key, "[SKIPPED — insufficient budget]", 5


# ─── Context Assembly ────────────────────────────────────────────────────────

def assemble_context(project: str, domains: List[str], task_keywords: List[str],
                     token_budget: int = 4000,
                     domain_priorities: Optional[Dict[str, int]] = None,
                     include_metadata: bool = True) -> Dict[str, Any]:
    """
    Build a token-budgeted context package from project memory.
    
    Returns a dict with:
    - facts: {domain: {key: value}} — only relevant facts within budget
    - metadata: token usage stats, compression applied
    - warnings: staleness or missing domain alerts
    """
    if domain_priorities is None:
        domain_priorities = {}

    memory = memory_core.load_memory(project)
    idx = memory_core._load_index(project)

    # Collect all candidate facts with relevance scores
    candidates: List[Tuple[float, str, str, Any, int]] = []  # (score, domain, key, value, est_tokens)

    for domain in domains:
        dom_data = memory.get("domains", {}).get(domain, {})
        priority = domain_priorities.get(domain, 5)

        for key, value in dom_data.items():
            if key.startswith("_"):
                continue  # Skip metadata keys
            entry_key = f"{domain}.{key}"
            est_tokens = idx.get(entry_key, {}).get("tokens", estimate_tokens_json(value))
            score = score_fact_relevance(key, value, task_keywords, priority)
            candidates.append((score, domain, key, value, est_tokens))

    # Sort by relevance descending
    candidates.sort(key=lambda x: x[0], reverse=True)

    # Fill token budget
    result_facts: Dict[str, Dict[str, Any]] = {}
    used_tokens = 0
    skipped = 0
    compressed = 0

    for score, domain, key, value, est_tokens in candidates:
        if score < 0.1:
            skipped += 1
            continue

        remaining = token_budget - used_tokens
        if remaining < 10:
            skipped += 1
            continue

        if est_tokens <= remaining:
            # Fits fully
            result_facts.setdefault(domain, {})[key] = value
            used_tokens += est_tokens
        else:
            # Try compression
            comp_key, comp_value, comp_tokens = compress_fact(key, value, remaining)
            if comp_tokens <= remaining:
                result_facts.setdefault(domain, {})[comp_key] = comp_value
                used_tokens += comp_tokens
                compressed += 1
            else:
                skipped += 1

    # Metadata
    context: Dict[str, Any] = {
        "facts": result_facts,
    }

    if include_metadata:
        context["metadata"] = {
            "project": project,
            "domains_queried": domains,
            "task_keywords": task_keywords,
            "token_budget": token_budget,
            "tokens_used": used_tokens,
            "tokens_remaining": token_budget - used_tokens,
            "facts_included": sum(len(v) for v in result_facts.values()),
            "facts_compressed": compressed,
            "facts_skipped": skipped,
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }

    # Warnings
    warnings: List[str] = []
    for domain in domains:
        if domain not in memory.get("domains", {}):
            warnings.append(f"Domain '{domain}' has no data in project '{project}'")
    if warnings:
        context["warnings"] = warnings

    return context


# ─── Cascade-Aware Context ───────────────────────────────────────────────────

def assemble_cascade_context(project: str, step_name: str,
                             skill_domains: List[str],
                             task_keywords: List[str],
                             previous_outputs: Dict[str, str],
                             token_budget: int = 8000) -> Dict[str, Any]:
    """
    Build context for a cascade step, including previous step outputs.
    
    Budget allocation:
    - 60% for domain facts
    - 30% for previous step outputs
    - 10% for metadata/warnings
    """
    fact_budget = int(token_budget * 0.6)
    output_budget = int(token_budget * 0.3)

    # Domain facts
    fact_context = assemble_context(
        project=project,
        domains=skill_domains,
        task_keywords=task_keywords,
        token_budget=fact_budget,
        include_metadata=False,
    )

    # Previous outputs (truncate to budget)
    trimmed_outputs: Dict[str, str] = {}
    output_tokens_used = 0
    for name, content in previous_outputs.items():
        content_tokens = estimate_tokens(content)
        remaining = output_budget - output_tokens_used
        if content_tokens <= remaining:
            trimmed_outputs[name] = content
            output_tokens_used += content_tokens
        elif remaining > 100:
            # Partial truncation
            target_chars = remaining * 3
            trimmed_outputs[name] = content[:target_chars] + "\n[TRUNCATED]"
            output_tokens_used += remaining
        else:
            trimmed_outputs[name] = f"[SKIPPED — {content_tokens} tokens exceeds budget]"

    return {
        "step": step_name,
        "facts": fact_context.get("facts", {}),
        "previous_outputs": trimmed_outputs,
        "metadata": {
            "fact_tokens": fact_context.get("metadata", {}).get("tokens_used", 0) if "metadata" in fact_context else 0,
            "output_tokens": output_tokens_used,
            "total_tokens": fact_context.get("metadata", {}).get("tokens_used", 0) + output_tokens_used if "metadata" in fact_context else output_tokens_used,
            "budget": token_budget,
        },
        "warnings": fact_context.get("warnings", []),
    }


# ─── CLI ────────────────────────────────────────────────────────────────────

USAGE = """LLM Middleware — Context Optimizer

Usage:
    context_optimizer.py facts <project> <domain> [<domain>...] --keywords <kw1> [<kw2>...] [--budget N]
    context_optimizer.py cascade <project> <step> --domains <d1> [<d2>...] --keywords <kw1> [<kw2>...] [--budget N]
    context_optimizer.py stats <project>
"""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(USAGE)
        return 1

    command = argv[1]

    # Parse common flags
    budget = 4000
    keywords: List[str] = []
    for i, arg in enumerate(argv):
        if arg == "--budget" and i + 1 < len(argv):
            try:
                budget = int(argv[i + 1])
            except ValueError:
                pass
        if arg == "--keywords" and i + 1 < len(argv):
            keywords = [a for a in argv[i + 1:] if not a.startswith("--")]

    if command == "facts":
        # Find domains (between command and --keywords)
        args = [a for a in argv[2:] if not a.startswith("--")]
        # Filter out keyword values that leaked into args
        kw_start = next((i for i, a in enumerate(argv) if a == "--keywords"), len(argv))
        domain_args = [a for a in argv[2:kw_start] if not a.startswith("--")]
        if not domain_args:
            print("Usage: context_optimizer.py facts <project> <domain>... --keywords <kw>...", file=sys.stderr)
            return 1
        project = domain_args[0]
        domains = domain_args[1:] if len(domain_args) > 1 else ["engine"]

        context = assemble_context(project, domains, keywords, budget)
        print(json.dumps(context, indent=2, ensure_ascii=False))

    elif command == "cascade":
        # Not directly invoked — used internally by orchestrator
        print("Use 'orchestrator.py prompt' for cascade context generation.", file=sys.stderr)
        return 1

    elif command == "stats":
        if len(argv) < 3:
            print("Usage: context_optimizer.py stats <project>", file=sys.stderr)
            return 1
        project = argv[2]
        projects = memory_core.list_projects()
        proj = next((p for p in projects if p["name"] == project), None)
        if proj:
            print(json.dumps(proj, indent=2))
        else:
            print(f"Project '{project}' not found.", file=sys.stderr)
            return 1

    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
