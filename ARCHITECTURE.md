# Agent Runtime Kernel — Architecture

> Früher: LLM Middleware  
> Jetzt: Autonome Laufzeitumgebung mit Speicher, Planung, Lernen und Falsifizierung

---

## Stabiler Kern — Status

| Prinzip | Status | Nachweis |
|---|---|---|
| **Projektisolation** | ✅ Fertig | `~/.karma/projects/<name>.db` — jedes Projekt eigene SQLite-Datei |
| **Ein Persistenzpfad** | ✅ Fertig | `create_project_persistence()` — einziger Factory, kein Legacy-JSON |
| **Falsification Gate** | ✅ Fertig | 6 Proben, Negativtest nachgewiesen |
| **Needs Engine** | ✅ Fertig | 5 Detektoren, Lifecycle detected → resolved \| escalated |
| **Learning Engine** | ✅ Fertig | PatternLearner + RewardModel + TrainingLoop |
| **Self-Improvement** | ✅ Fertig | Nur durch validierten Reward-Score, Safety-Stop bei degrading trend |
| **Knowledge Graph** | ✅ Fertig | Schema v3, Relations-API, CLI, Graph-Traversal |

**Teststand:** 27 Tests, 0 Fehler, 0 Warnungen.

---

## Persistenzpfad (Single Source of Truth)

```
~/.karma/
├── middleware.db           # globale DB (active_project, cross-project)
├── skill_state.json        # Skill-Registry-State
└── projects/
    ├── <projekt-a>.db      # Fakten, Logs, Events, Needs, Patterns, Relations
    └── ...
```

Früher zwei konkurrierende Pfade (`.hermes/framework/` JSON + SQLite). Jetzt: `LLM_MIDDLEWARE_ROOT` ist der einzige Root. Alle `.hermes`-Referenzen entfernt.

---

## Schema-Versionen

| Version | Änderung |
|---|---|
| v1 | facts, execution_log, cascade_state, skill_state, cross_references, idempotency_keys, events |
| v2 | cascade_state.metadata |
| v3 | **relations** — Knowledge Graph Kanten |

Migration ist idempotent (Sentinel `.migrated.lock`).

---

## Architektur

```
              Runtime Kernel (cli.py)
                      │
     ┌────────────────┼────────────────┐
     │                │                │
 Needs Engine     Planner         Scheduler
     │                │                │
     └────────────┬───┴───────────────┘
                  │
          Cascade Runtime
                  │
     ┌────────────┼─────────────┐
     │            │             │
 Memory      Skill Engine   Event Bus
     │            │             │
     └───────┬────┴───────┬─────┘
             │            │
      Reflection    Learning Engine
             └─────┬──────┘
                   │
          Knowledge Graph (v3)
                   │
          Prompt Generation
                   │
        Claude / Hermes / Cursor /
        Copilot / lokale Modelle
```

---

## Knowledge Graph: Weltmodell

Knoten-Typen: `repository`, `module`, `file`, `class`, `dependency`, `history`, `owner`, `problem`, `risk`

Relationen: `contains`, `depends_on`, `authored_by`, `affects`, `has_history`, `reveals`, `mitigates`

```bash
karma graph add repository my_repo contains module core -p proj
karma graph list my_repo --direction both -p proj
karma graph traverse my_repo --depth 4 -p proj
```

---

## Needs Engine

5 Detektoren:
- `failure_detector` — Failure-Rate ≥ 30%
- `staleness_detector` — Facts älter als 7 Tage
- `gate_detector` — Falsification-Probe ≥ 50% Fehler
- `test_detector` — Domains ohne Execution-Log
- `gap_detector` — Tasks mit wiederholtem `partial`-Outcome

Motivation < 0.3 → „Nicht anfassen".

---

## Learning Engine

```
TrainingLoop.run_cycle():
  1. NeedsEngine.scan()
  2. Priorisierung (priority × motivation)
  3. Pro Need: plan → execute (safe only) → score → store
  4. Resolve ≥ 0.6 | Escalate < 0.25
  5. Reflection → events
```

Safety-Stop: Reward 3× < 0.20 → CRITICAL Need, Loop stoppt.

---

## Falsification Gate: 6 Proben

1. **Assumptions** — Dokumentiert mit Quellenangabe?
2. **Test Coverage** — Tests vorhanden und grün?
3. **Contradictions** — Verletzt MANIFEST.json-Invarianten?
4. **Regressions** — Tests entfernt? Debug-Output?
5. **Idempotency** — SHA-256 des Artefakts
6. **Determinism** — Kein `random`/`uuid`/`time` im Hot Path

---

## Offene Baustellen

| # | Baustein | Nächster Schritt |
|---|---|---|
| 1 | **Scheduler** | Cron-Dispatcher für `run_cycle()` |
| 2 | **Planner** | Needs → konkrete LLM-Tasks |
| 3 | **Graph-Populierung** | Auto-Scan von Repo-Struktur |
| 4 | **Human-Review Queue** | Tabelle + CLI für Skill-Änderungen |
| 5 | **Cross-Projekt-Lernen** | Pattern-Transfer zwischen Projekten |

> Erweiterungen erst nach nachgewiesener Stabilität des Kerns.

---

*Stand: 2026-07-17 — 27 Tests grün*
