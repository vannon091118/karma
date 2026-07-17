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
| **Domains** | Wissensbereiche (engine, runtime, ui, world, …). Definiert in `domains/MANIFEST.json` als Single Source of Truth. |
| **Skills** | Wiederverwendbare Agenten-Anweisungen, gemappt auf Domains. Liegen in Root-Ordnern mit `SKILL.md`. |
| **Falsification** | Jedes Ergebnis wird durch einen Prüf-Gate gezogen, bevor es als verlässlich gilt. |

---

## 3. Installation

```bash
cd /path/to/LLM.Middleware.Conxtex.Framework
python3 -m venv .venv && . .venv/bin/activate
pip install -e ./llm_middleware
# → erstellt globalen Befehl: llm-mw
```

Test:
```bash
llm-mw --help
```

---

## 4. Ein Projekt in Betrieb nehmen

Zwei Wege:

### A) Schnell — `init`

Im Projektordner ausführen:
```bash
cd /path/to/mein-projekt
llm-mw init
```
Erstellt `.llm-mw/` mit:
- `index.md` — Domain-Übersicht (TOC)
- `inventory.md` — Skill-Manifest (welche Skills → welche Domains)
- `scopes.md` — aktive Domains für dieses Projekt
- `CLAUDE.md`-Snippet — damit dein Agent weiss, dass das Projekt middleware-verwaltet ist

### B) Geführt — `onboard`

Ein interaktiver Wizard, der die Konzepte erklärt, nach Projektname und
relevanten Domains fragt und dann `init` für dich ausführt:
```bash
llm-mw onboard
```

---

## 5. Tägliche Arbeit

```bash
llm-mw status --project mein-projekt     # Sync-Status ansehen
llm-mw memory get engine version_compat   # eine Fakt lesen
llm-mw memory set ui '{"theme":"dark"}'      # eine Fakt schreiben
llm-mw skill list                          # verfügbare Skills
llm-mw dispatch "Baue das UI-Menü" --project mein-projekt  # Skills auto-wählen + Delegate-Tasks bauen
llm-mw prompt generate --platform claude   # Prompt für Zielplattform
```

---

## 6. Architektur (kurz)

```
llm_middleware/
├── cli.py              # Einstiegspunkt (llm-mw)
├── core/
│   ├── persistence.py  # SQLite (WAL) — projekt-isoliert, idempotente Migration
│   ├── memory.py       # MemoryBus, Projekt-Memory, Fakt-Index
│   ├── index.py       # granularer Index, Token-Schätzung, Relevance-Scoring
│   └── cache.py       # Thread-sicherer Cache mit Hit/Miss-Stats
├── skills/
│   ├── registry.py    # Skill-Discovery, Domain-Mapping (liest domains/MANIFEST.json)
│   ├── creator.py     # Skill-Erzeugung + Plattform-Detection
│   └── loader.py     # Export zu .mdc/.md/.json (Cursor, OpenCode, …)
├── runtime/
│   ├── orchestrator.py       # Cascade-Pipeline + Falsification-Gate
│   ├── falsification_gate.py # 6 Probes (assumptions, tests, contradictions, …)
│   ├── context_optimizer.py  # Context-Assembling + Token-Budget
│   ├── prompt_engine.py      # Prompt-Generierung für 6 Plattformen
│   └── platform_adapter.py   # Agent-spezifische Formate
├── middleware/AGENT_FORMATS.json  # Plattform-Schemata
└── domains/MANIFEST.json         # Domain-SSOT (Root, von registry geladen)
```

---

## 7. Wichtige Prinzipien

- **Determinismus ist heilig** — keine zufälligen Ergebnisse ohne Seed.
- **Falsification zuerst** — ein Ergebnis gilt erst als verlässlich, wenn der
  Gate es nicht widerlegen konnte.
- **SSOT** — Domains leben einmalig in `domains/MANIFEST.json`.
- **Projekt-Isolation** — jede Persistence ist eine eigene SQLite-Datei
  (`~/.llm-middleware/projects/<projekt>.db`).
- **Keine API-Keys** — vollständig lokal, dateibasiert.
