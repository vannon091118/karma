# LLM Middleware Runtime — Onboarding

Dieses Dokument erklärt Menschen (nicht nur Agenten), was das System ist und
wie man es in einem eigenen Projekt in Betrieb nimmt.

---

## 1. Was ist das?

Die LLM Middleware Runtime ist **keine Künstliche Intelligenz**. Sie ist eine
*Infrastruktur-Schicht* zwischen dir (Mensch) bzw. deinem Agenten (Claude,
Hermes, OpenCode, Cursor, Windsurf, Copilot) und den Sprachmodellen.

Sie löst ein Problem: Modelle vergessen. Ein Gespräch endet, das nächste
beginnt, der Zusammenhang fehlt. Projekte vermischen sich, Informationen
gehen verloren.

Das System ist die "Verwaltung" für KI-Systeme — wie in einem Unternehmen,
wo nicht jeder Mitarbeiter an allem arbeitet, sondern eine zentrale Stelle
dafür sorgt, dass jeder die richtigen Informationen hat.

---

## 2. Vier Kernkonzepte

| Konzept | Bedeutung |
|----------|------------|
| **Projekte** | Jedes Projekt hat einen isolierten Arbeitsbereich. Memory wird nie zwischen Projekten gemischt. |
| **Domains** | Wissensbereiche (engine, runtime, ui, world, …). Definiert in `karma/domains/{core,technology,infrastructure,projects/<proj>}/<domain>.json` als Single Source of Truth. `karma/domains/MANIFEST.json` ist seit Phase 4 als deprecated markiert und wird in Phase 4.6 migriert. |
| **Skills** | Wiederverwendbare Agenten-Anweisungen, gemappt auf Domains. Liegen in Root-Ordnern mit `SKILL.md`. |
| **Falsification** | Jedes Ergebnis wird durch einen Prüf-Gate gezogen, bevor es als verlässlich gilt. |

---

## 3. Installation

```bash
cd /path/to/karma
python3 -m venv .venv && . .venv/bin/activate
pip install -e ./karma
# → erstellt globalen Befehl: karma
```

Test:
```bash
karma --help
```

---

## 4. Ein Projekt in Betrieb nehmen

Zwei Wege:

### A) Schnell — `init`

Im Projektordner ausführen:
```bash
cd /path/to/mein-projekt
karma init
```
Erstellt `.karma/` mit:
- `index.md` — Domain-Übersicht (TOC)
- `inventory.md` — Skill-Manifest (welche Skills → welche Domains)
- `scopes.md` — aktive Domains für dieses Projekt
- `CLAUDE.md`-Snippet — damit dein Agent weiss, dass das Projekt middleware-verwaltet ist

### B) Geführt — `onboard`

Ein interaktiver Wizard, der die Konzepte erklärt, nach Projektname und
relevanten Domains fragt und dann `init` für dich ausführt:
```bash
karma onboard
```

---

## 5. Tägliche Arbeit

```bash
karma status --project mein-projekt     # Sync-Status ansehen
karma memory get engine version_compat   # eine Fakt lesen
karma memory set ui '{"theme":"dark"}'      # eine Fakt schreiben
karma skill list                          # verfügbare Skills
karma dispatch "Baue das UI-Menü" --project mein-projekt  # Skills auto-wählen + Delegate-Tasks bauen
karma prompt generate --platform claude   # Prompt für Zielplattform
```

---

## 6. Architektur (kurz)

```
karma/
├── cli.py              # Einstiegspunkt (karma)
├── core/
│   ├── persistence.py  # SQLite (WAL) — projekt-isoliert, idempotente Migration
│   ├── memory.py       # MemoryBus, Projekt-Memory, Fakt-Index
│   ├── index.py       # granularer Index, Token-Schätzung, Relevance-Scoring
│   └── cache.py       # Thread-sicherer Cache mit Hit/Miss-Stats
├── skills/
│   ├── registry.py    # Skill-Discovery via SKILL.md-Indizes; Capability-Resolution via loader.resolve_skills() (Rule 4)
│   ├── creator.py     # Skill-Erzeugung + Plattform-Detection
│   └── loader.py     # Export zu .mdc/.md/.json (Cursor, OpenCode, …)
├── runtime/
│   ├── orchestrator.py       # Cascade-Pipeline + Falsification-Gate
│   ├── falsification_gate.py # 6 Probes (assumptions, tests, contradictions, …)
│   ├── context_optimizer.py  # Context-Assembling + Token-Budget
│   ├── prompt_engine.py      # Prompt-Generierung für 6 Plattformen
│   └── platform_adapter.py   # Agent-spezifische Formate
├── middleware/AGENT_FORMATS.json  # Plattform-Schemata
├── domains/                       # Phase 4 Domain System (JSON-basiert, jsonschema-validiert)
│   ├── schema.json                #   Single Source of Truth für Domain-Definitionen
│   ├── loader.py                  #   DomainLoader (Public API: load(scope, project))
│   ├── core/                      #   Universal: repository, security, quality, testing, architecture
│   ├── technology/                #   Python, Rust, TypeScript, …
│   ├── infrastructure/            #   Docker, K8s, Cloud, …
│   └── projects/<projekt>/        #   Projekt-spezifische Domains (z.B. syxcraft, vigilguard)
└── domains/MANIFEST.json          # ⚠️ DEPRECATED seit Phase 4 — Phase 4.6 setzt {deprecated: true, replacement: ...}-Marker
```

---

## 7. Wichtige Prinzipien

- **Determinismus ist heilig** — keine zufälligen Ergebnisse ohne Seed.
- **Falsification zuerst** — ein Ergebnis gilt erst als verlässlich, wenn der
  Gate es nicht widerlegen konnte.
- **SSOT** — Pro Domain genau eine JSON-Datei: `karma/domains/{core|technology|infrastructure|projects/<name>}/<id>.json`. Das alte monolithische `karma/domains/MANIFEST.json` ist seit Phase 4 als deprecated markiert; Phase 4.6 setzt `{deprecated: true, replacement: <neue Domain>}`-Marker. Loader ist die einzige Public API.
- **5 Architektur-Regeln** — Pipeline ≠ Domain, Keywords gehören in Domain, Capability-Registry ist provider-basiert, Loader ist die Public API, Domains tragen keine Skills. Single Source: [README.md](README.md) §"Five architecture invariants" + [ARCHITECTURE.md](ARCHITECTURE.md) §"Phase 4 Plan" §"5 Architektur-Regeln" + [karma/domains/global/DOMAIN_ARCHITECTURE.md](karma/domains/global/DOMAIN_ARCHITECTURE.md) §8.
- **Projekt-Isolation** — jede Persistence ist eine eigene SQLite-Datei
  (`~/.karma/projects/<projekt>.db`).
- **Keine API-Keys** — vollständig lokal, dateibasiert.
