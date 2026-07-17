"""Tests for migration idempotency (Bug 2: migration runs on every DB access)."""

import json
import tempfile
from pathlib import Path

import pytest

from llm_middleware.core.persistence import (
    PersistenceConfig,
    PersistenceLayer,
    migrate_from_json,
)


def _make_json_project(root: Path, name: str, facts: dict) -> None:
    """Create a JSON-format project dir with a memory.json."""
    pdir = root / name
    pdir.mkdir(parents=True, exist_ok=True)
    domains = {}
    for domain, kv in facts.items():
        domains[domain] = dict(kv)
    (pdir / "memory.json").write_text(json.dumps({"domains": domains}))


def _fact_count(persistence: PersistenceLayer, project: str) -> int:
    for p in persistence.list_projects():
        if p["name"] == project:
            return p["facts"]
    return 0


def test_migration_is_idempotent_on_repeated_runs():
    """Running migrate_from_json twice must NOT double the fact count."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        json_dir = tmp / "json_projects"
        _make_json_project(json_dir, "proj", {"bio": {"a": 1, "b": 2, "c": 3}})

        config = PersistenceConfig(framework_dir=tmp / "db", db_filename="mw.db")
        p = PersistenceLayer(config)

        migrate_from_json(p, json_dir)
        first = _fact_count(p, "proj")
        assert first == 3, f"expected 3 facts after first migration, got {first}"

        # Second run must be a no-op, not re-import
        migrate_from_json(p, json_dir)
        second = _fact_count(p, "proj")
        assert second == 3, f"migration not idempotent: {first} -> {second}"


def test_migration_writes_sentinel():
    """After migration a sentinel must exist so future runs skip re-import."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        json_dir = tmp / "json_projects"
        _make_json_project(json_dir, "proj", {"bio": {"a": 1}})

        config = PersistenceConfig(framework_dir=tmp / "db", db_filename="mw.db")
        p = PersistenceLayer(config)

        migrate_from_json(p, json_dir)
        sentinel = json_dir / ".migrated.lock"
        assert sentinel.exists(), "expected .migrated.lock sentinel after migration"
