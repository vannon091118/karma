# KARMA Domain Architecture — Konzept

> **Status:** TEILWEISE IMPLEMENTIERT (Phase 0–4.1 done, 2026-07-17)
> **Version:** 1.1
> **Datum:** 2026-07-17 (letztes Update)
> **Autor:** Vannon / KARMA Core Team
>
> **Implementierungsstand 2026-07-17:**
> - ✅ Domain JSON Schema (`karma/domains/schema.json`) — geschrieben + jsonschema-validiert
> - ✅ DomainLoader (`karma/domains/loader.py`) — Layer-Isolation, Project-Override, jsonschema.validate()-Pfad
> - ✅ 5 Core Domains: `repository`, `security`, `quality`, `testing`, `architecture`
> - ✅ 1 Technology Domain: `python`
> - ✅ 1 Infrastructure Domain: `docker`
> - ✅ 3 Project Domains: `syxcraft`, `syxcraft-engine`, `vigilguard-compliance`
> - ✅ Phase 4.1: `cli.py::capability_to_skills` Hardcoding entfernt; `_select_skills` ist 6-Zeilen-Stub (Pipeline-Skills only)
> - ✅ Architecture-Tests (`karma/tests/test_architecture.py`): 25 grün / 1 KG-OOS-Fail
> - 🔜 Phase 4.3: Loader Public API (`LoadedDomains`-Wrapper)
> - 🔜 Phase 4.2: Capability-Resolver + Provider-Registry (`karma/capabilities/registry.json`)
> - 🔜 Phase 4.6: Legacy-MANIFEST-Migration + Deprecation-Marker

---

## 1. Problem: Was aktuell kaputt ist

Aktueller Zustand (`karma/domains/MANIFEST.json`):

```json
{
  "domains": {
    "engine": { ... },      // SyxCraft
    "runtime": { ... },     // SyxCraft
    "save": { ... },        // SyxCraft
    "repository": { ... },  // Neu, aber global
    "security": { ... },    // Neu, aber global
    "python": { ... },      // Neu, aber global
  }
}
```

Dispatcher-Logik (`cli.py:_select_skills`):

```python
domain_to_group = {
    "engine": "syxcraft",
    "repository": "quality",   // hart verdrahtet
    "security": "quality",
}
```

**Fehler:** Der globale MANIFEST ist gleichzeitig:
- Domänenkatalog
- Projektspezialisierung
- Skill-Router
- Wissensindex

**Folge:** Ein VigilGuard-Repo bekommt `engine`/`runtime`/`save` Domains, weil der Dispatcher auf Keywords ("docker") matched, keine Domain findet, und auf `engine`/`runtime` fällt — dann lädt er `execution` Skill (SyxCraft-Weltmodell).

---

## 2. Zielarchitektur: Layered Domain Model

karma/domains/
├── core/                    # Layer 0: Universal Engineering
│   ├── repository.json      # Codebasis verstehen, Struktur, Dependencies
│   ├── quality.json         # Code Quality, Technical Debt, Maintainability
│   ├── testing.json         # Test Infrastructure, Coverage, Strategy
│   ├── architecture.json    # Architectural Decisions, Patterns, Boundaries
│   ├── documentation.json   # Docs, ADRs, Knowledge Transfer
│   ├── release.json         # Versioning, Changelog, Deployment
│   └── security.json        # Vulnerabilities, Secrets, Hardening, Compliance
├── technology/              # Layer 1: Language Ecosystems
│   ├── python.json
│   ├── rust.json
│   ├── typescript.json
│   ├── java.json
│   └── cpp.json
├── infrastructure/          # Layer 2: Runtime/Platform
│   ├── docker.json
│   ├── kubernetes.json
│   ├── linux.json
│   ├── database.json
│   └── cloud.json
└── projects/                # Layer 3: Project-Specific (Override/Extend)
    ├── syxcraft/
    │   └── MANIFEST.json    # snake2d, save, world, modding, events
    └── vigilguard/
        └── MANIFEST.json    # license, drift, policy, compliance

**Prinzip:** Jedes Layer kennt nur sich selbst und darunter. Kein Layer 3 Import in Layer 0.

---

## 3. Domain Definition Format (v2)

Jede Domain ist eine selbstbeschreibende JSON mit Evidence-Regeln:

```json
{
  "name": "security",
  "layer": "core",
  "version": "1.0",
  "description": "Vulnerability scanning, secret detection, license compliance, dependency audit",
  "capabilities": [
    "license_analysis",
    "secret_detection",
    "dependency_audit",
    "drift_detection",
    "compliance_check"
  ],
  "skills": [
    "repository",
    "falsification",
    "audit"
  ],
  "evidence_rules": {
    "license_analysis": {
      "claim": "Project has license compliance checking",
      "evidence_types": ["SOURCE", "TEST", "RUNTIME"],
      "sources": [
        "license.py",
        "license_check.sh",
        ".github/workflows/license.yml"
      ],
      "min_confidence": 0.6
    },
    "secret_detection": {
      "claim": "Project scans for secrets in codebase",
      "evidence_types": ["source", "test"],
      "sources": [
        ".gitleaks.toml",
        ".github/workflows/secret-scan.yml",
        "trufflehog"
      ],
      "min_confidence": 0.7
    }
  },
  "depends_on": ["repository"],
  "conflicts_with": []
}
```

**Wichtig:**
- `capabilities` = Was die Domain *kann* (für Skill Resolution)
- `skills` = Welche Skills dafür nötig sind (nicht `skill_group` Mapping!)
- `evidence_rules` = Wie Claims verifiziert werden (Scanner nutzt das)
- `depends_on` = Layer 0 Dependencies (Security braucht Repository)

---

## 4. Project Profile (Minimal)

```
~/.karma/projects/<name>/
  project.json
```

```json
{
  "name": "vigilguard",
  "root": "/tmp/vigilguard",
  "created": "2026-07-17T10:30:00Z",
  "domains": [
    "repository",
    "python",
    "security",
    "docker",
    "quality"
  ],
  "status": "onboarded",
  "evidence": {
    "repository": {
      "claims": ["has_pyproject_toml", "has_git_history"],
      "confidence": 0.8
    },
    "python": {
      "claims": ["uses_pytest", "has_type_hints"],
      "confidence": 0.7
    }
  }
}
```

**Keine Domain-Kopien.** Der Project Profile referenziert nur Domain-Namen. Der Resolver lädt zur Laufzeit:
1. Global Domain (core/technology/infrastructure)
2. Project Override (projects/<name>/MANIFEST.json) — falls existiert
3. Merged View für Dispatcher

---

## 5. Onboarding Scanner — Evidence-First Pipeline

**Regel:** *Kein Domain Match ohne Evidence.*

```
Repository Scanner → Evidence Generator → Claim Creation → Claim Resolver → Project Profile
```

### 5.1 Scanner Output (Roh-Evidence)

```python
@dataclass
class RawEvidence:
    source_path: str           # z.B. "docker-compose.yml"
    evidence_type: EvidenceType # SOURCE
    content_hash: str          # SHA-256
    matched_patterns: List[str] # ["services:", "volumes:"]
    confidence: float          # 0.4 (nur File-Existenz)
```

### 5.2 Claim Generation

Aus RawEvidence → Claim Hypothesen:

```python
@dataclass
class ClaimHypothesis:
    domain: str                # "docker"
    claim: str                 # "Project uses Docker Compose"
    evidence: List[RawEvidence]
    proposed_confidence: float # 0.4
    status: ClaimStatus        # UNVERIFIED
```

### 5.3 Resolver

Lädt Domain `evidence_rules`, prüft:

```python
def resolve_claim(hypothesis: ClaimHypothesis, domain_def: DomainDef) -> ResolvedClaim:
    rules = domain_def.evidence_rules.get(hypothesis.claim, {})
    required_types = rules.get("evidence_types", ["SOURCE"])
    min_conf = rules.get("min_confidence", 0.5)
    
    type_confidence = {}
    for ev in hypothesis.evidence:
        if ev.evidence_type in required_types:
            type_confidence[ev.evidence_type] = max(
                type_confidence.get(ev.evidence_type, 0),
                ev.confidence
            )
    
    overall = max(type_confidence.values()) if type_confidence else 0.0
    status = "CONFIRMED" if overall >= min_conf else "UNVERIFIED"
    
    return ResolvedClaim(
        claim=hypothesis.claim,
        domain=hypothesis.domain,
        confidence=overall,
        status=status,
        evidence=hypothesis.evidence
    )
```

### 5.4 Example: VigilGuard Onboarding

```
$ karma onboard /tmp/vigilguard

[SCAN] pyproject.toml          → Evidence(SOURCE, 0.4) → Claim("uses_python")
[SCAN] pytest.ini + tests/     → Evidence(TEST, 0.7)    → Claim("has_test_infra")
[SCAN] docker-compose.yml      → Evidence(SOURCE, 0.5)  → Claim("uses_docker")
[SCAN] license.py + activation → Evidence(RUNTIME, 0.6) → Claim("has_license_enforcement")
[SCAN] checker.py (rules)      → Evidence(SOURCE, 0.5)  → Claim("has_config_validation")

[RESOLVE] python      0.7 → CONFIRMED (min 0.5)
[RESOLVE] docker      0.5 → CONFIRMED (min 0.5)  
[RESOLVE] security    0.6 → CONFIRMED (min 0.6)
[RESOLVE] repository  0.8 → CONFIRMED (min 0.5)

[PROFILE] Created vigilguard with domains: repository, python, docker, security, quality
```

---

## 6. Skill Resolution Model

**Nicht:** `domain → skill_group` (hart verdrahtet)

**Sondern:** `domain.capabilities → required_skills`

**Aktualisierung Phase 4.2:** Capabilities werden gegen eine provider-basierte Registry aufgelöst (kein flacher 1:1-Lookup).

```json
// karma/capabilities/registry.json
{
  "secret_detection": {
    "providers": [
      { "skill": "security",       "priority": 10, "requires": [] },
      { "skill": "falsification",  "priority":  5, "requires": [] }
    ]
  }
}
```

**Vorteil:**
- Mehrere Domains können gleiche Skills nutzen (`repository` für security + quality)
- Project Override kann Skills hinzufügen/entfernen
- Provider-Reihenfolge erweiterbar (Trufflehog, Semgrep, Custom später)
- Kein zentrales Mapping das veraltet

---

## 7. Migration vom alten MANIFEST

### Schritt 1: Global Domains extrahieren

```bash
karma migrate domains --from karma/domains/MANIFEST.json --to karma/domains/
```

Erzeugt:
- `karma/domains/core/repository.json` (aus engine/runtime/save shared keywords)
- `karma/domains/core/quality.json`
- `karma/domains/core/security.json`
- `karma/domains/technology/python.json`
- `karma/domains/infrastructure/docker.json`

### Schritt 2: SyxCraft Project Domain

```bash
karma migrate project-domain --name syxcraft --from karma/domains/MANIFEST.json
```

Erzeugt `karma/domains/projects/syxcraft/MANIFEST.json` mit:
- engine, runtime, save, reflection, assets, settlement, world, ui

### Schritt 3: Dispatcher Update

`cli.py:_select_skills` nutzt neue Resolution:
```python
project = load_project_profile(proj)
skills = resolve_skills(project.domains)
```

### Schritt 4: Onboarding implementieren

`karma onboard <path>` → Scanner → Resolver → Project Profile

---

## 8. 5 Architektur-Regeln (Non-Negotiable)

Diese Regeln sind mit `README.md` (Five architecture invariants) und `ARCHITECTURE.md` (Phase 4 Plan) identisch — Single Source of Truth, kein Drift.

| Regel | Begründung |
|-------|------------|
| **Pipeline ist keine Domain** | Pipeline (`dump-analyse / konzept / execution / tests / workflow / loop`) ist Orchestrierungslogik, nicht Wissen. Lebt ab Phase 5+ in `karma/pipeline/`, nicht in `karma/domains/`. |
| **Keywords gehören in die Domain** | `matching.keywords` direkt im Domain-JSON. Kein separates Index-, Keyword- oder Routing-File. |
| **Capability-Registry ist provider-basiert** | Schema `{capability: {providers: [{skill, priority, requires?, weight?}]}}` — erweiterbar ohne Schema-Bump. Trufflehog / Semgrep / Custom joinen über Priority, nicht über Code-Touch. |
| **Loader ist die Public API** | `cli.py` importiert niemals direkt `resolver.py`. Der Loader importiert den Resolver und exponiert `resolve_skills_for_domains()` als stabiles Interface. |
| **Domains tragen keine Skills** | `additionalProperties: false` im Schema + Test `test_domain_cannot_define_skills` lehnen `skills: [...]` ab. Skill-Routing ist Resolver-Aufgabe, nicht Domain-Aufgabe. |

**Ergänzende Constraints (aus Lock-Vertrag):**

- **Layer Isolation:** Core kennt nicht Technology, Technology kennt nicht Projects. Wird im **Loader** per Post-Load-Pass gegen `core→project` `depends_on` geprüft und mit `ValueError` abgelehnt (Schema kann das nicht).
- **Legacy-MANIFEST-Migration:** `engine / runtime / save / reflection / assets / ui / world / documentation / release / research / performance` werden Phase 4.6 in Domain-JSONs bzw. Capabilities migriert. Alt-MANIFEST trägt `{deprecated: true, replacement: ...}` Marker.
- **KG-Evidence:** Edges tragen `evidence_ids`, `status`, `confidence`. Out-of-Band Phase 5+.

---

## 9. Offene Fragen (für Review)

1. **Domain Versioning:** SemVer? Content-Hash? Wie brechen wir kompatibel?
2. **Cross-Project Domain Transfer:** Erlaubt? Wenn ja: nur über Evidence-Export?
3. **Scanner Extensibility:** Plugin-System für custom detectors?
4. **Claim Conflict Resolution:** Zwei Domains behaupten Gegensätzliches?
5. **Performance:** Resolver bei 50+ Domains — Caching-Strategie?

---

## 10. Nächste Schritte (Implementation Order — Phase 4)

| Phase | Deliverable | Status |
|-------|-------------|--------|
| 0 | Architecture-Vertrag (5 Regeln + Loader-as-API-Constraint + Hybrid-Migration) | ✅ Done |
| 4.1 | `cli.py` entgiften — `capability_to_skills` Hardcoding raus, dead `manifest = _load_manifest()` raus | ✅ Done |
| 4.3a | DomainLoader Public API: `load(scope, project)` Pflicht, `load_all()` entfernt, `LoadedDomains`-Wrapper mit `has_domain/get_domain/list_capabilities` | 🔜 Design gelockt |
| 4.3b | Loader-Level Layer-Isolation: `core→project depends_on` per `ValueError` abgelehnt (Schema kann das nicht) | 🔜 |
| 4.3c | Schema-Härtung: optionales `matching.keywords` (minItems 1); `import os`-Duplikat + ungenutzter `tomllib`-Import im loader.py raus | 🔜 |
| 4.4 | Architecture-Tests: kein Private-`loader._domains`, neue Tests (`test_dispatcher_uses_loader`, `test_project_domains_are_isolated`, etc.) | 🔜 |
| 4.2a | `karma/capabilities/registry.json` (provider-basiertes Schema) | 🔜 |
| 4.2b | `karma/capabilities/resolver.py` — Provider-Sortierung. **WICHTIG (Rule 4): Loader importiert Resolver; cli.py NICHT direkt** | 🔜 |
| 4.2c | Resolver-Tests: provider-Priority, missing-registry, ties-without-weight | 🔜 |
| 4.5 | `cli.py::_match_domains` auf Domain-JSONs (`matching.keywords`); `cli.py::_select_skills` ruft `loader.resolve_skills()` | 🔜 |
| 4.6a | Legacy-Domains `engine/runtime/save/reflection/assets/ui/world` → `karma/domains/projects/syxcraft/<sub>.json` mit `matching.keywords` | 🔜 |
| 4.6b | Meta-Kategorien `documentation/release/research/performance` → KEINE Domains, sondern Capabilities in `registry.json` | 🔜 |
| 4.6c | Deprecation-Marker im alten `karma/domains/MANIFEST.json` (`{deprecated: true, replacement: ...}`) | 🔜 |

**Out-of-Band (Phase 5+):**
- `karma/pipeline/` Top-Level-Modul (Regel 1: Pipeline ≠ Domain-Typ). Übernimmt `dump-analyse/konzept/execution/tests/workflow/loop` aus dem aktuellen Hardcoded-Stub.
- KnowledgeGraph-Edges mit `evidence_ids`, `status`, `confidence` (statt isolierter Behauptungen).
- `karma/core/evidence.py` mit `frozen=True` für Evidence-Immutability.

**Decision Gate:** Nach jedem Phase-Abschluss — Architecture-Tests grün?

> *Dieses Dokument ist der Single Source of Truth für KARMA Domain Architecture. Jede Implementation muss gegen diese 5 Regeln verifizierbar sein.*