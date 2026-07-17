"""
test_concurrency.py — Parallel-Agent-Simulation

Testet dass bei N gleichzeitigen Agenten, die denselben request_id nutzen,
genau 1 Experience pro request_id entsteht (Idempotenz unter Concurrent Load).

Läuft gegen eine echte SQLite-DB (kein Mock), da der Bug nur dort auftritt.
"""
import threading
import uuid
from pathlib import Path

import pytest

from karma.core.persistence import PersistenceConfig, PersistenceLayer
from karma.turn_kernel import handle_turn, TurnRequest, TurnResult


CONTENT = "def add(a, b): return a + b\n"


@pytest.fixture()
def persistence(tmp_path):
    config = PersistenceConfig(framework_dir=tmp_path)
    return PersistenceLayer(config)


def _do_turn(persistence, project, request_id, results, idx):
    req = TurnRequest(
        project=project,
        request_id=request_id,
        task="concurrent_task",
        content=CONTENT,
        skill_name="test_skill",
    )
    try:
        result = handle_turn(persistence, req)
        results[idx] = result
    except Exception as e:
        results[idx] = e


def test_idempotency_under_concurrent_load(persistence):
    """10 Threads feuern denselben request_id gleichzeitig.
    
    Erwartet:
    - Genau 1 Experience-Row in der DB
    - Genau 1 Idempotency-Key
    - Alle Threads erhalten ein TurnResult (kein Crash)
    - Mindestens 9 von 10 sind idempotent_replay=True
    """
    project = "concurrent_test_proj"
    persistence.execute("INSERT OR IGNORE INTO projects (name, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))", (project,))

    shared_request_id = f"shared_{uuid.uuid4().hex[:8]}"
    n_threads = 10
    results = [None] * n_threads

    threads = [
        threading.Thread(
            target=_do_turn,
            args=(persistence, project, shared_request_id, results, i),
        )
        for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # No exceptions
    exceptions = [r for r in results if isinstance(r, Exception)]
    assert not exceptions, f"Threads raised exceptions: {exceptions}"

    # All returned TurnResults
    assert all(isinstance(r, TurnResult) for r in results), "Not all results are TurnResult"

    # Exactly 1 experience row for this request_id
    row = persistence.fetchone(
        "SELECT COUNT(*) as cnt FROM experiences WHERE project = ? AND request_id = ?",
        (project, shared_request_id),
    )
    assert row["cnt"] == 1, (
        f"Expected exactly 1 experience, got {row['cnt']}. "
        "Race condition in idempotency check!"
    )

    # Exactly 1 idempotency key
    idem_row = persistence.fetchone(
        "SELECT COUNT(*) as cnt FROM idempotency_keys WHERE key = ?",
        (f"turn:{project}:{shared_request_id}",),
    )
    assert idem_row["cnt"] == 1, f"Expected 1 idempotency key, got {idem_row['cnt']}"

    # At least 9 replays (first writer wins, rest are replays)
    replays = sum(1 for r in results if isinstance(r, TurnResult) and r.idempotent_replay)
    assert replays >= n_threads - 1, (
        f"Expected >= {n_threads - 1} idempotent replays, got {replays}. "
        "Something processed the turn more than once."
    )


def test_distinct_request_ids_no_collision(persistence):
    """10 Threads mit verschiedenen request_ids → 10 Experiences, 0 Duplikate."""
    project = "distinct_test_proj"
    persistence.execute("INSERT OR IGNORE INTO projects (name, created_at, updated_at) VALUES (?, datetime('now'), datetime('now'))", (project,))

    n_threads = 10
    results = [None] * n_threads

    threads = [
        threading.Thread(
            target=_do_turn,
            args=(persistence, project, f"req_{i}_{uuid.uuid4().hex[:6]}", results, i),
        )
        for i in range(n_threads)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    exceptions = [r for r in results if isinstance(r, Exception)]
    assert not exceptions, f"Threads raised exceptions: {exceptions}"

    row = persistence.fetchone(
        "SELECT COUNT(*) as cnt FROM experiences WHERE project = ?",
        (project,),
    )
    assert row["cnt"] == n_threads, (
        f"Expected {n_threads} experiences, got {row['cnt']}"
    )
