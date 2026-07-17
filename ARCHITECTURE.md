# Agent Runtime Kernel — Architecture

> Früher: LLM Middleware  
> Jetzt: Autonome Laufzeitumgebung mit Speicher, Planung, Lernen und Falsifizierung

---

## Stabiler Kern — Status

| Prinzip | Status | Nachweis |
|---|---|---|
| **Projektisolation** | ✅ Fertig | `~/.karma/projects/<name>.db` — jedes Projekt eigene SQLite-Datei |
| **Ein Persistenzpfad** | ✅ Fertig | `create_project_persistence()` — einziger Factory, kein Legacy-JSON |
| **Falsification Gate** | ✅ Stabil | 6 Proben, Negativtest nachgewiesen, Legacy + Modern API |
| **Evidence Layer** | ✅ Stabil | Claim/Evidence/ConfidenceResolver, 5 Evidenztypen, Status-Resolver |
| **Needs Engine** | ✅ Fertig | 5 Detektoren, Lifecycle detected → resolved \| escalated |
| **Learning Engine** | ✅ Fertig | PatternLearner + RewardModel + TrainingLoop |
| **Self-Improvement** | ✅ Fertig | Nur durch validierten Reward-Score, Safety-Stop bei degrading trend |
| **Knowledge Graph** | 🟡 Partiell | Schema v3, Relations-API, CLI, Graph-Traversal — Evidence-Binding fehlt |

**Teststand:** 36 Tests, 0 Fehler, 0 Warnungen.

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

| # | Baustein | Status | Nächster Schritt |
|---|---|---|---|
| 1 | **Claim Resolver** | 🔜 | Claim → Evidence → Status (UNVERIFIED/SUPPORTED/CONFIRMED/CONFLICTED) |
| 2 | **Graph-Populierung** | 🔜 | Evidence-backed Edges: Claim → Claim mit Evidence-IDs + Confidence |
| 3 | **Human-Review Queue** | 🔜 | Tabelle + CLI für konfliktierte Claims |
| 4 | **Scheduler** | 🔜 | Cron-Dispatcher für `run_cycle()` |
| 5 | **Cross-Projekt-Lernen** | 🔜 | Pattern-Transfer nur nach Claim-Resolver + Provenance |

> Reihenfolge: Evidence → Graph → Review → Scheduler → Cross-Project.
> Der Graph darf kein Orakel werden. predecessoren müssen zuerst stehen.

---

## Evidence Layer — Status: STABLE (v0.4.0)

Der Evidence Layer trennt Behauptungen (Claims) von messbarer Realität (Evidence).

```
Claim
 ├── statement  (Was wird behauptet?)
 ├── domain     (Welcher Bereich?)
 ├── evidences  (Was beweist es?)
 │    ├── type       (SOURCE | RUNTIME | TEST | REPLAY | HUMAN)
 │    ├── confidence  (0.0 – 1.0)
 │    ├── source      (Herkunft)
 │    └── timestamp
 └── status     (UNVERIFIED → SUPPORTED → CONFIRMED | CONFLICTED)
```

Ein gespeicherter Fakt besitzt nicht automatisch Wahrheit. Er besitzt nur Aussage,
Herkunft, Evidenztyp, Confidence und Zeitbezug. Status wird vom ConfidenceResolver
aus den Evidenzen abgeleitet — nicht behauptet.

Confidence-Limits pro Typ: SOURCE 0.4, RUNTIME 0.9, TEST 0.7, REPLAY 0.95, HUMAN 1.0.

---

## Falsification Gate — Status: STABLE (v0.4.0)

Das Gate fungiert nicht mehr ausschließlich als Validator. Es ist ein Evidence Producer:

```
Probe → FalsificationResult → Evidence Producer → Claim Resolver
```

Unterstützte Probe-Modi:
1. **Modern API** — `FalsificationProbe(name, domain, severity, execute_fn)` mit `FalsificationResult` (8-arg)
2. **Legacy API** — `FalsificationResult(name, passed, evidence_str)` (3-arg, auto-mapped)

Der Compatibility Layer ist bewusst Teil des Framework-Vertrags. Entfernen bricht externe Plugins.

---

## Knowledge Graph — Status: PARTIAL (v0.4.0)

```
Graph Storage       ✓  Schema v3, SQLite-Backed
Graph Edges         ✓  Relations-API, CLI, Traversal
Data Robustheit     ✓  Dicts + Arrays + Skalare als Fact-Werte
Evidence Binding    ✗  Edges ohne Evidence-IDs oder Confidence
Claim Resolution    ✗  Graph kennt Beziehungen, nicht deren Begründung
Semantic Traversal  ✗  Traversal kennt Claim-Status nicht
```

Der Graph darf nicht sagen "diese Claims sind wahr", sondern nur "diese Claims hängen zusammen, und das ist die Evidenz dafür."

---

*Stand: 2026-07-17 — 36 Tests grün, Evidence Layer stabil, Knowledge Graph partiell*
