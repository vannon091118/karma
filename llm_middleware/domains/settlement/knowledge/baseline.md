# Settlement Domain — Snake2D V71.63

---
verified_against: "SyxCraft/src/ + V71/assets/init/race/"
verified_at: "2026-07-16"
staleness_risk: "medium"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
  - "class:SyxCraft/src:UndeadController"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Responsibility:** Settlement mechanics, population, rooms, jobs, economy, laws
> **Owner:** Settlement Domain Agent

---

## Core Systems

### Population (settlement.stats.POP)

| Query | Method | Parameters |
|-------|--------|------------|
| Total citizens | `tot()` | — |
| By class/race | `tot(HCLASS, Race)` | HCLASS, Race |
| Physical | `physical(HCLASS, Race)` | HCLASS, Race |
| Base pop | `pop(HCLASS, Race)` | HCLASS, Race |

**HCLASS Constants:** `HCLASSES.CITIZEN()`, `HCLASSES.SLAVE()`, `HCLASSES.NOBLE()`

### Workforce (settlement.stats.STATS.WORK())

| Query | Method | Parameters |
|-------|--------|------------|
| Total workforce | `workforce()` | — |
| By race | `workforce(Race)` | Race |
| Historical | `workforce(Race, daysBack)` | Race, int |

### Rooms (settlement.room.main.util.RoomsCreator)

| Aspect | Access |
|--------|--------|
| Employment | `SETT.ROOMS().employment` → reflection on `all` / `allS` fields |
| Room creation | `RoomsCreator.registerRoom()` |
| Room config | `assets/init/room/*.txt` |

---

## Race Config Keys (Verified)

```properties
_ignoreVanilla: true,
PLAYABLE: true/false,
PROPERTIES: {
    HEIGHT, WIDTH,
    BABY_DAYS, CHILD_DAYS,
    CORPSE_DECAY, SLEEPS,
    SLAVE_PRICE
},
BIO_FILE: Normal,
KING_FILE: Normal,
HOME: RACE_ID,
TECH: [*,],
PREFERRED: {
    FOOD: [...], DRINK: [...],
    OTHER_RACES: { RACE: affinity },
    ROAD: { *: 1.0, STONE1: 0.5 },
    STRUCTURE: { MOUNTAIN: 0.8, FOREST: 0.3 }
},
POPULATION: {
    MAX, GROWTH,
    CLIMATE: { COLD: 1.0, TEMPERATE: 1.0, HOT: 0.8 },
    TERRAIN: { MOUNTAIN: 0.8, FOREST: 0.3, NONE: 1.0 }
},
TRAITS: { RACE_TRAIT: 1.0 },
RESOURCE: { RESOURCE: amount },
BOOST: { BOOST_KEY>OP: value },
SPRITE_FILE: RACE_ID,
ICON_SMALL: 24->race->RACE_ID->0,
ICON_BIG: 32->race->RACE_ID->0,
```

---

## Building Gates (SyxCraft Mechanic)

| Gate | Condition | Effect |
|------|-----------|--------|
| Conversion Altar | Human Village exists | Enables Conversion |
| Necropolis | Population > 50 | Unlocks advanced Undead |
| Soul Forge | Essence > 100 | Upgrades conversion rate |

---

## Events (SyxCraft)

| Event | Trigger | Effect |
|-------|---------|--------|
| `VILLAGE_REBELLION` | Geist > 0.7 | Worker strike, conversion slow |
| `MOONWELL_RAIDED` | Orc raid on Night Elf | Moonwater -50% |
| `NIGHTELF_TRADE_OFFER` | Peace + Moonwater > 50 | Essence trade |

---

* Settlement Domain — Civic Systems Authority *