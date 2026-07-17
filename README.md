<div align="center">

<br/>

```
██╗  ██╗ █████╗ ██████╗ ███╗   ███╗ █████╗
██║ ██╔╝██╔══██╗██╔══██╗████╗ ████║██╔══██╗
█████╔╝ ███████║██████╔╝██╔████╔██║███████║
██╔═██╗ ██╔══██║██╔══██╗██║╚██╔╝██║██╔══██║
██║  ██╗██║  ██║██║  ██║██║ ╚═╝ ██║██║  ██║
╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝     ╚═╝╚═╝  ╚═╝
```

**Knowledge-Aware Runtime Memory Architecture**  
A learning system that falsifies its own outputs before it calls anything "done."

<br/>

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue?style=flat-square)](https://www.python.org)
[![Architecture](https://img.shields.io/badge/architecture-event--sourced-purple?style=flat-square)](#architecture)
[![Learning](https://img.shields.io/badge/learning-falsification--gated-orange?style=flat-square)](#falsification-gate)
[![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)](LICENSE)

</div>

---

## The Manifesto

Every first letter of every rule below spells the name of this project. That is not a coincidence.

- **K**eep every execution immutable. What happened, happened. The past is not a draft.
- **A**ssume nothing, falsify everything. Confidence without evidence is a bug dressed as a feature.
- **R**ewards are interpretations, not facts — only the raw event is ground truth.
- **M**emory without lineage is organized gossip. You need to know where knowledge came from.
- **A**gents that cannot explain their own decisions are not intelligent. They are expensive autocomplete with unusually good PR.

---

## The Problem

Most "AI agent frameworks" follow the same implicit pattern:

```
Request → LLM → Response
```

And then they call it a day.

The result is a system that can *act* but cannot *explain*, *learn*, or *correct itself*. If the output was wrong, you don't know why. If it improved, you don't know what caused it. If the model drifts, you find out when production breaks.

**KARMA doesn't solve the symptom. It builds the feedback loops first.**

---

## What This Is

A Python runtime kernel that wraps the LLM execution pipeline with:

- **An immutable audit trail** of every execution, in raw form, forever
- **A falsification gate** that validates outputs before they're accepted as truth
- **A learning pipeline** that derives patterns, rewards, and a knowledge graph from that audit trail
- **Reproducibility**: if you change the reward model tomorrow, you can replay all historical experiences through the new rules

```
Request → ContextOptimizer → Prompt → LLM → FalsificationGate
                                                     │
                                              ┌──────┴──────────┐
                                       passed │                 │ failed
                                              ↓                 ↓
                               ExperienceStore (immutable)    failure_type
                                              │
                              ┌───────────────┼───────────────┐
                              ↓               ↓               ↓
                         RewardModel    PatternLearner   KnowledgeGraph
                              │               │               │
                              └───────────────┴───────────────┘
                                              │
                                       ReplayEngine
                                       (re-derive everything
                                        when rules change)
```

---

## Domain System (Phase 4)

Since v0.4, KARMA's knowledge structure migrated from a flat `karma/domains/MANIFEST.json`
to a layered, evidence-backed domain JSON system:

karma/domains/
├── core/                    # Universal engineering (repository, security, quality, testing, architecture)
├── technology/              # Language ecosystems (python, rust, typescript, …)
├── infrastructure/          # Runtime/platform (docker, kubernetes, cloud, …)
└── projects/<name>/         # Project-specific overrides (syxcraft, vigilguard, …)

Each domain JSON declares `capabilities`, `evidence_rules`, `claims`, `ownership`,
and (Phase 4.3c) `matching.keywords`. Skill routing now flows:

```
Domain → matching.keywords → matched domains
                          → capabilities
                          → capability → Provider (skill, priority, requires?)
                          → Resolver sorts → selected skills
```

The legacy `karma/domains/MANIFEST.json` is being phased out (Phase 4.6 migration
with deprecation markers).

**Five architecture invariants** that prevent the new system from rotting like the old one:

1. **Pipeline is not a Domain.** `dump-analyse / konzept / execution / tests / workflow / loop`
   live in `karma/pipeline/` once separated; they are NOT domains.
2. **Keywords belong in the Domain definition.** No separate dispatch/index file.
3. **Capability registry is provider-based**, not a flat list. `Trufflehog / Semgrep / Custom`
   join later through priority, no schema bump.
4. **The Loader is the public API.** `cli.py` never imports the Resolver directly — the Loader imports
   it and exposes a stable interface.
5. **Domains carry no Skills.** Adding "skills": [...]" to a Domain JSON fails schema validation.

> See `karma/domains/global/DOMAIN_ARCHITECTURE.md` for the full design and `ARCHITECTURE.md`
> for the Phase 4 plan with status per phase.

---

## Architecture

The system is split into three layers. They have exactly one communication direction: downward.

```
┌─────────────────────────────────────────────────────────────┐
│  L3 — Runtime Governance                                    │
│  Policy versions · Experiment management · Drift detection  │
│  Telemetry · Schema evolution · Replay orchestration        │
└───────────────────────────┬─────────────────────────────────┘
                            │ injects Policy
┌───────────────────────────▼─────────────────────────────────┐
│  L2 — Learning Layer                                        │
│  ExperienceStore · RewardModel · PatternLearner             │
│  KnowledgeGraph · ReplayEngine · ContextSnapshotStore       │
└───────────────────────────┬─────────────────────────────────┘
                            │ reads derived state
┌───────────────────────────▼─────────────────────────────────┐
│  L1 — Execution Layer                                       │
│  Orchestrator · ContextOptimizer · PromptEngine             │
│  FalsificationGate · SkillEngine · NeedsEngine              │
└─────────────────────────────────────────────────────────────┘
```

> **Rule:** No governance logic lives in L1 or L2. No hardcoded thresholds. No magic numbers. All of that comes from a versioned `Policy` object injected by L3.

---

## Key Components

### 🔒 Experience Store
> *"The past is not a suggestion."*

Every execution writes one immutable record to SQLite. That's it. No updates. No deletes. The schema stores:

- The full ID chain: `RequestID → ExecutionID → LLMCallID → ExperienceID`
- The algorithm versions that were active: `RewardModel v1.2`, `Gate Ruleset 2026-07`, etc.
- The `ContextSnapshotID` pointing to a compressed, hashed snapshot of the exact context that was presented to the LLM

If the context file changes tomorrow, the historical experience still knows exactly what the model saw.

---

### ⚡ Falsification Gate
> *"The Gate decides, not the Agent."*

Before any output is accepted, it passes 6 probes:

| Probe | Checks |
|-------|--------|
| **Assumptions** | Are all claims documented with sources? |
| **Test Coverage** | Do tests exist and pass? |
| **Contradictions** | Does the output violate project invariants? |
| **Regressions** | Were tests removed? Debug output left in? |
| **Idempotency** | Is the artifact SHA-256 stable across runs? |
| **Determinism** | No `random`, `uuid`, or `time` in hot paths? |

If the Gate blocks, the `failure_type` is captured (syntax / hallucination / timeout / policy / validation) and flows directly into the learning pipeline.

---

### 🧠 Knowledge Graph
> *"A graph should be as unspectacular as a SQL view."*

The Knowledge Graph is not a database. It is a **derived view** of the Experience Store.

It maps tasks to facts via two relation types:
- `improves_with` — this fact was present when the reward was high
- `confused_by` — this fact was present when the reward was low

Both relations carry `weight`, `confidence`, and `last_seen`. The `ContextOptimizer` reads these when selecting facts for the next execution: facts that have historically caused confusion are penalized and potentially excluded.

**Phase 5+ note:** edges will additionally carry `evidence_ids` and `status` so the graph
can answer "which Claims back this relation?" rather than acting as an isolated belief store.

---

### ♻️ Replay Engine
> *"Our system can explain why it learned."*

When the RewardModel logic changes, the past shouldn't be silently invalidated. The Replay Engine:

1. Reads all immutable Experiences in chronological order
2. Wipes derived state (Patterns, KG edges) for the target policy version
3. Re-scores every historical experience through the **current** rules
4. Rebuilds Patterns and KG edges from scratch

This makes it possible to compare `Policy v1` against `Policy v2` without destroying the baseline.

---

## Project Structure

karma/
├── cli/
├── core/
├── ml/
├── experimental_runtime/
├── skills/
├── domains/
│   ├── schema.json                 # Phase 4 SSOT for Domain-JSON definitions
│   ├── loader.py                   # DomainLoader (becomes Public API in 4.3)
│   └── core/ technology/ infrastructure/ projects/<name>/
└── cli.py

---

## Quickstart

```bash
# Clone and install
git clone https://github.com/vannon091118/runtime
cd runtime
pip install -e .

# Initialize a project
karma project create my-project

# Store some knowledge
karma memory set my-project engine architecture "Cascade pipeline with falsification"

# Generate a cascade prompt
karma prompt generate my-project --step research

# Complete a step (triggers the full ML feedback loop)
karma cascade complete my-project research output.md
```

---

## The Learning Loop in Practice

Every time a step completes:

```python
# 1. Falsification Gate evaluates the output
gate_passed, gate_results = gate.run(step_name, skill, output_file, state)

# 2. Immutable experience is recorded
exp = Experience(
    execution_id=execution_id,
    prompt_variant_id=variant_id,
    gate_passed=gate_passed,
    failure_type=failure_type,      # "syntax" | "idempotency" | "hallucination" | ...
    reward_model_version="1.0",     # version of the rules that scored this
    gate_version="2026-07",         # version of the gate ruleset
)
experience_store.record(exp)        # append-only, forever

# 3. Reward is calculated, patterns are learned, KG is updated
breakdown = reward_model.score(signal)
pattern_learner.store(task, outcome, score)
knowledge_graph.update_from_experience(exp.id, breakdown.final)
```

The next execution uses the updated KG to select better facts. Better context → better output → better reward → improved KG. The loop closes.

---

## Phase 4 in Motion

**Current state:** learning kernel + emerging Domain System. Architecture-Tests: 25 grün / 1 KG-OOS-Fail.

Phase 4 progress (architecture is locked, code in flight):

- [x] **4.0** Architecture contract: 5 rules + Loader-as-API-constraint, signed
- [x] **4.1** `cli.py::capability_to_skills` Hardcoding entfernt; `_select_skills` ist 6-Zeilen-Stub mit `list(PIPELINE_SKILLS)` Return; `PIPELINE_SKILLS` als Modul-Constant mit `TODO(Phase 5+)`-Marker
- [ ] **4.3** DomainLoader Public API: stateless Factory, `load(scope, project)` Pflicht, `load_all()` entfernt (Tresor-Prinzip), `LoadedDomains`-Wrapper mit `has_domain/get_domain/list_capabilities`; Layer-Isolation `core→project depends_on` per `ValueError`
- [ ] **4.4** Architecture-Tests: kein Private-`loader._domains`-Access, neue Tests wie `test_dispatcher_uses_loader`, `test_project_domains_are_isolated`, `test_domain_cannot_define_skills`, `test_core_domains_cannot_depend_on_project_domains`
- [ ] **4.2** `karma/capabilities/registry.json` (provider-basiert) + `karma/capabilities/resolver.py` (**Rule 4**: Loader importiert Resolver, cli.py NICHT)
- [ ] **4.5** `cli.py::_match_domains` auf Domain-JSONs (`matching.keywords`); `_select_skills` ruft `loader.resolve_skills()`
- [ ] **4.6** Legacy-MANIFEST-Migration: `engine/runtime/save/...` → `projects/syxcraft/*.json` mit `matching.keywords`; `documentation/release/research/performance` → Capabilities; Deprecation-Marker im Alt-MANIFEST

**Out-of-Band (Phase 5+):** `karma/pipeline/` Top-Level-Modul (Pipeline ≠ Domain); KnowledgeGraph-Edges mit `evidence_ids, status, confidence`; `evidence.py frozen=True`.

## Roadmap

The current state: **a learning kernel with full traceability, now hybridizing into an evidence-backed Domain System**.

The next layer — **Runtime Governance** — will introduce:

- [ ] **Policy Engine:** Centralized, versioned configuration for all hyperparameters
- [ ] **Experiment Management:** Named replay runs that produce isolated derived views for comparison
- [ ] **Drift Detection:** Automated monitoring of rolling reward degradation per task
- [ ] **Decision Learning:** Capturing the *decision space* (alternatives not taken) to enable counterfactual replay
- [ ] **Observability CLI:** `karma stats` aggregating failure trends, prompt variant health, KG fact churn
- [ ] **Schema Governance:** Alembic-backed migrations with version history

> See [ARCHITECTURE.md](ARCHITECTURE.md) for the full technical design, and the [Runtime Governance Design](docs/governance.md) for the L3 specification.

---

## Design Philosophy

Three rules that shape every architectural decision:

**1. The Gate decides, not the Agent.**  
No output enters the learning pipeline without passing falsification. The agent's confidence is irrelevant.

**2. The past is immutable.**  
Rewards, patterns, and graph edges are interpretations. Experiences are facts. Interpretations can be recalculated. Facts cannot be changed.

**3. Learning must be explainable.**  
If the system can't tell you *why* it learned something, it hasn't learned — it has accumulated.

---

<div align="center">

*"Der Prototyp ist tot. Das ist ein ernstzunehmender Runtime-Kern."*

</div>