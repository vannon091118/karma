# Documentation Domain — Snake2D V71.63

---
verified_against: "AGENTS.md + docs/"
verified_at: "2026-07-16"
staleness_risk: "low"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Responsibility:** ADRs, SSOT, CHANGELOG, templates, checklists, knowledge management
> **Owner:** Documentation Domain Agent

---

## Document Types & Lifecycle

### ADR (Architecture Decision Record)

**When:** Any architecture decision with tradeoffs
**Template:** `templates/adr.md`
**Location:** `ssot/ADR-XXX_<topic>.md`
**Review:** Required before implementation

**States:** PROPOSED → ACCEPTED | DEPRECATED | SUPERSEDED

---

### SSOT (Single Source of Truth)

| Document | Purpose | Update Trigger |
|----------|---------|----------------|
| `INDEX.md` | Navigation | Any SSOT change |
| `ENGINE_SNAKE2D.md` | Authoritative engine spec | New game version |
| `ARCHITECTURE.md` | System design | Architecture change |
| `REFLECTION_PATTERN.md` | Safe reflection standard | Reflection change |
| `TEXT_INJECTION.md` | Localization pattern | Text system change |
| `SAVE_LOAD.md` | Serialization protocol | Save format change |
| `V71_SPRITE_SPEC.md` | Asset format | Asset pipeline change |
| `ADR-XXX.md` | Decisions | New decision |
| `CODING_STANDARDS.md` | Code style | Style guide update |

**Rule:** SSOT updated in same PR as code change

---

### CHANGELOG (Keep a Changelog)

**Format:** `docs/changelog/CHANGELOG.md`

```markdown
## [Unreleased]

### Added
- 

### Changed
- 

### Fixed
- 

### Removed
- 
```

**Versioning:** SemVer — MAJOR.MINOR.PATCH in `pom.xml` + `_Info.txt`

---

## Templates

| Template | Location | Use For |
|----------|----------|---------|
| `adr.md` | `templates/adr.md` | Architecture decisions |
| `implementation-plan.md` | `templates/implementation-plan.md` | Feature planning |
| `validation-report.md` | `templates/validation-report.md` | QA validation |

---

## Checklists

| Checklist | Location | When |
|-----------|----------|------|
| `engine-compliance.md` | `checklists/engine-compliance.md` | Every commit/PR |
| `release.md` | `checklists/release.md` | Every release |
| `save-load.md` | `checklists/save-load.md` | Save format change |

---

## Knowledge Management

### Sources (Priority Order)

1. **Source code** (`SongsOfSyx-sources.jar`)
2. **Official docs** (Example Mod, ReadTheDocs)
3. **Runtime logs** (game output)
4. **Design notes** (ADRs, SSOT)
5. **Community** (Discord, Steam forums)

### Capture Process

1. Discover fact
2. Verify against source (1 or 2)
3. Add to appropriate SSOT doc
3. Cite source inline
4. Update INDEX.md if new doc

---

## Style Guide

### Markdown

- ATX headings (`#`, `##`, `###`)
- Tables for structured data
- Code blocks with language hints
- Relative links within repo
- No HTML

### Code Blocks

```java
// Always specify language
// Include imports if standalone
```

### Citations

```
| Fact | Source |
|------|--------|
| POP.tot() returns int | `SongsOfSyx-sources.jar` / `settlement/stats/POP.java` |
```

---

*Documentation Domain — Knowledge Integrity Authority*