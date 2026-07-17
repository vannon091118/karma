#!/usr/bin/env python3
"""
Framework Memory Bus — Standalone Middleware Layer CLI
Backed entirely by SQLite (no direct JSON file writes).
"""

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from llm_middleware.core.persistence import create_persistence, create_project_persistence
from llm_middleware.core.memory import MemoryBus


def _get_active_project(argv: List[str]) -> str:
    """Get project from --project flag or active project in config."""
    for i, arg in enumerate(argv):
        if arg == "--project" and i + 1 < len(argv):
            return argv[i + 1]
    global_p = create_persistence()
    return global_p.get_active_project()


# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_get(argv: List[str]) -> None:
    project = _get_active_project(argv)
    args = [a for a in argv[2:] if not a.startswith("--")]
    
    bus = MemoryBus(project)
    
    domain = args[0] if len(args) > 0 else None
    key = args[1] if len(args) > 1 else None
    
    val = bus.get(domain, key)
    if val is not None:
        print(json.dumps(val, indent=2, ensure_ascii=False))
    else:
        print("null")


def cmd_set(argv: List[str]) -> None:
    project = _get_active_project(argv)
    args = [a for a in argv[2:] if not a.startswith("--")]
    if len(args) < 2:
        print("Usage: memory_bus.py set <domain> [<key>] '<json>'", file=sys.stderr)
        sys.exit(1)
        
    if len(args) == 2:
        domain, val_str = args[0], args[1]
        key = None
    else:
        domain, key, val_str = args[0], args[1], args[2]

    try:
        val = json.loads(val_str)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
        
    bus = MemoryBus(project)
    try:
        bus.set(domain, val, key)
        if key:
            print(f"OK [{project}] set {domain}.{key}")
        else:
            print(f"OK [{project}] set {domain}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_update(argv: List[str]) -> None:
    project = _get_active_project(argv)
    args = [a for a in argv[2:] if not a.startswith("--")]
    if len(args) < 3:
        print("Usage: memory_bus.py update <domain> <key> '<json>'", file=sys.stderr)
        sys.exit(1)
        
    domain, key, val_str = args[0], args[1], args[2]
    try:
        val = json.loads(val_str)
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
        
    bus = MemoryBus(project)
    try:
        bus.update(domain, key, val)
        print(f"OK [{project}] updated {domain}.{key}")
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)


def cmd_delete(argv: List[str]) -> None:
    project = _get_active_project(argv)
    args = [a for a in argv[2:] if not a.startswith("--")]
    if len(args) < 1:
        print("Usage: memory_bus.py delete <domain> [<key>]", file=sys.stderr)
        sys.exit(1)
        
    domain = args[0]
    key = args[1] if len(args) > 1 else None
    
    bus = MemoryBus(project)
    bus.delete(domain, key)
    if key:
        print(f"OK [{project}] deleted {domain}.{key}")
    else:
        print(f"OK [{project}] deleted domain {domain}")


def cmd_list(argv: List[str]) -> None:
    project = _get_active_project(argv)
    bus = MemoryBus(project)
    doms = bus.list_domains()
    print(f"PROJECT: {project}  ({len(doms)} domains)")
    print(f"{'DOMAIN':<15} {'KEYS':<6} {'LAST UPDATED'}")
    print("─" * 50)
    for domain, info in doms.items():
        print(f"{domain:<15} {info['keys']:<6} {info['last_updated']}")


def cmd_projects() -> None:
    projects = MemoryBus.list_projects()
    print(f"PROJECTS ({len(projects)}):")
    print(f"{'NAME':<20} {'DOMAINS':<8} {'FACTS':<8} {'LOGS':<8}")
    print("─" * 50)
    for p in projects:
        print(f"{p['name']:<20} {p['domains']:<8} {p['facts']:<8} {p['logs']:<8}")


def cmd_switch(argv: List[str]) -> None:
    args = [a for a in argv[2:] if not a.startswith("--")]
    if len(args) < 1:
        print("Usage: memory_bus.py switch <project>", file=sys.stderr)
        sys.exit(1)
    project = args[0]
    MemoryBus.switch(project)
    print(f"OK: Active project switched to '{project}'")


def cmd_active() -> None:
    print(MemoryBus.active())


def cmd_cross(argv: List[str]) -> None:
    args = [a for a in argv[2:] if not a.startswith("--")]
    if len(args) < 2:
        print("Usage: memory_bus.py cross <domain> <key>", file=sys.stderr)
        sys.exit(1)
    domain, key = args[0], args[1]
    global_persistence = create_persistence()
    results = global_persistence.cross_project_query(domain, key)
    if results:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        print(f"No project has {domain}.{key}")


def cmd_log(argv: List[str]) -> None:
    project = _get_active_project(argv)
    agent_filter = None
    limit = 20
    for i, arg in enumerate(argv):
        if arg == "--agent" and i + 1 < len(argv):
            agent_filter = argv[i + 1]
        if arg == "--limit" and i + 1 < len(argv):
            try:
                limit = int(argv[i + 1])
            except ValueError:
                pass
                
    bus = MemoryBus(project)
    entries = bus.log(limit, agent_filter)
    print(f"PROJECT: {project}  ({len(entries)} entries)")
    print(f"{'TIMESTAMP':<20} {'AGENT':<15} {'DOMAIN':<12} {'TASK':<20} {'OUTCOME'}")
    print("─" * 80)
    for e in entries:
        ts = e.get("timestamp", "?")[:19]
        agent = e.get("agent", "?")[:14]
        domain = e.get("domain", "?")[:11] if e.get("domain") else "—"
        task = e.get("task", "?")[:19]
        outcome = e.get("outcome", "?")
        icon = "✅" if outcome == "success" else "❌" if outcome == "failure" else "⚠️"
        print(f"{ts:<20} {agent:<15} {domain:<12} {task:<20} {icon} {outcome}")


def cmd_log_add(argv: List[str]) -> None:
    project = _get_active_project(argv)
    args = [a for a in argv[2:] if not a.startswith("--")]
    if len(args) < 1:
        print("Usage: memory_bus.py log-add '<json>'", file=sys.stderr)
        sys.exit(1)
    try:
        entry = json.loads(args[0])
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
        
    bus = MemoryBus(project)
    bus.log_add(entry)
    print(f"OK [{project}] logged: {entry.get('task', '?')}")


def cmd_skill_state(argv: List[str]) -> None:
    project = _get_active_project(argv)
    p = create_project_persistence(project)
    state = p.load_skill_state(project)
    print(json.dumps(state, indent=2))


def cmd_skill_state_save(argv: List[str]) -> None:
    project = _get_active_project(argv)
    args = [a for a in argv[2:] if not a.startswith("--")]
    if len(args) < 1:
        print("Usage: memory_bus.py skill-state-save '<json>'", file=sys.stderr)
        sys.exit(1)
    try:
        state = json.loads(args[0])
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON: {exc}", file=sys.stderr)
        sys.exit(1)
        
    p = create_project_persistence(project)
    p.save_skill_state(project, state)
    print(f"OK [{project}]")


# ─── CLI ────────────────────────────────────────────────────────────────────

USAGE = """Framework Memory Bus — Standalone Middleware
Usage:
    memory_bus.py get [<domain>] [<key>] [--project <name>]
    memory_bus.py set <domain> [<key>] '<json>' [--project <name>]
    memory_bus.py update <domain> <key> '<json>' [--project <name>]
    memory_bus.py delete <domain> [<key>] [--project <name>]
    memory_bus.py list [--project <name>]
    memory_bus.py projects
    memory_bus.py switch <project>
    memory_bus.py active
    memory_bus.py cross <domain> <key>
    memory_bus.py log [--project <name>] [--agent <name>] [--limit N]
    memory_bus.py log-add '<json>' [--project <name>]
    memory_bus.py skill-state [--project <name>]
    memory_bus.py skill-state-save '<json>' [--project <name>]
"""


def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(USAGE)
        return 1
    command = argv[1]
    if command == "get":
        cmd_get(argv)
    elif command == "set":
        cmd_set(argv)
    elif command == "update":
        cmd_update(argv)
    elif command == "delete":
        cmd_delete(argv)
    elif command == "list":
        cmd_list(argv)
    elif command == "projects":
        cmd_projects()
    elif command == "switch":
        cmd_switch(argv)
    elif command == "active":
        cmd_active()
    elif command == "cross":
        cmd_cross(argv)
    elif command == "log":
        cmd_log(argv)
    elif command == "log-add":
        cmd_log_add(argv)
    elif command == "skill-state":
        cmd_skill_state(argv)
    elif command == "skill-state-save":
        cmd_skill_state_save(argv)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
