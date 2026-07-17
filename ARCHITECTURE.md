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
| **Knowledge Graph** | 🟡 Partiell | Schema v3, Relations-API, CLI, Graph-Traversal — `evidence_ids/ confidence/ status` auf Edges fehlt (Phase 5+) |
| **Domain System** | 🟡 Im Aufbau | JSON-Schema validiert, Loader + 10 Domain-JSONs (5 core + 1 tech + 1 infra + 3 project). Phase 4.1 done. Phase 4.3–4.6 offen. |

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

## Phase 4 Plan — Domain System Hartziehen

Phase-Reihenfolge (gelockt und validiert mit Thinker-Validierung):

| # | Phase | Status | Liefert |
|---|---|---|---|
| 0 | Vertrag | ✅ | 5 Regeln + Loader-as-API-Constraint |
| 1 | **4.1** Dispatcher-Decoupling | ✅ | `cli.py::capability_to_skills` raus, `_select_skills` Pipeline-Skills only, architektur-tests grün |
| 2 | **4.3** Loader Public API | 🔜 | `load(scope, project)` Pflicht, `load_all()` entfernt, `LoadedDomains`-Wrapper mit `has_domain/get_domain/list_capabilities` |
| 3 | **4.4** Strukturtests | 🔜 | Architecture-Tests ohne Resolver, kein Private-Access, Layer-Isolation |
| 4 | **4.2** Capability Resolver + Registry | 🔜 | `karma/capabilities/registry.json` provider-basiert, Resolver vom Loader importiert (Rule 4) |
| 5 | **4.5** Dispatcher Wiring | 🔜 | `cli.py::_match_domains` auf Domain-JSONs, `_select_skills` ruft `loader.resolve_skills()` |
| 6 | **4.6** Legacy-Migration | 🔜 | `engine/runtime/save/reflection/assets/ui/world` → `projects/syxcraft/*.json` mit `matching.keywords`. `documentation/release/research/performance` → Capabilities. Alt-MANIFEST mit `{deprecated: true, replacement: ...}`. |

**Out-of-Band (Phase 5+):** `karma/pipeline/` Top-Level-Modul, KnowledgeGraph-`evidence_ids` auf Edges, `evidence.py frozen=True`.

### 5 Architektur-Regeln (Non-Negotiable)

| Regel | Begründung |
|---|---|
| **Pipeline ist keine Domain** | Pipeline = Orchestrierung, nicht Wissen. `dump-analyse/konzept/...` leben in `karma/pipeline/`, nicht in `karma/domains/`. |
| **Keywords gehören in die Domain** | `matching.keywords` im Domain-JSON. Keine separate Keyword-Datei. |
| **Capability-Registry ist provider-basiert** | `{cap: {providers: [{skill, priority, requires?, weight?}]}}` — kein flacher Skill-String-Lookup, erweiterbar ohne Schema-Bump. |
| **Loader ist die Public API** | `cli.py` importiert niemals direkt den `resolver.py`. Loader importiert Resolver und exposiert `resolve_skills_for_domains()`. |
| **Domains tragen keine Skills** | `additionalProperties: false` im Schema + Test `test_domain_cannot_define_skills` lehnen `skills: [...]` ab. |

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
