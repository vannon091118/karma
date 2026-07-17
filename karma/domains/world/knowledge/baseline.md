# World Domain — Snake2D V71.63

---
verified_against: "SyxCraft/src/ + V71/assets/init/"
verified_at: "2026-07-16"
staleness_risk: "medium"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Responsibility:** Overworld map, factions, diplomacy, world events, seasons
> **Owner:** World Domain Agent

---

## World System (Verified)

### Core Classes

| Class | Package | Purpose |
|-------|---------|---------|
| `WORLD` | `world` | Overworld singleton |
| `WorldMap` | `world` | Map data, regions, biomes |
| `Faction` | `game.faction` | NPC factions |
| `FactionNPC` | `game.faction.npc` | Individual NPC factions |
| `Diplomacy` | `game.faction` | Relations, wars, trade |

---

## Faction System (Verified)

### FactionNPC API

```java
// Access all NPC factions
Iterable<FactionNPC> npcs = FACTIONS.NPCs();

// Per faction
Race race = npc.race();           // Race of faction
double power = npc.offensivePower();  // Military strength
double relation = npc.getRelation(PLAYER_FACTION);  // -1.0 to 1.0
```

### Diplomacy

| Action | Method | Effect |
|--------|--------|--------|
| Improve relations | `changeRelation(faction, amount)` | Trade, gifts |
| Declare war | `declareWar(faction)` | Hostile |
| Make peace | `makePeace(faction)` | End war |
| Trade agreement | `offerTrade(faction, resources)` | Economic boost |

---

## World Events (Verified)

| Event | Trigger | Effect |
|-------|---------|--------|
| Raid | Faction hostility | Units attack settlement |
| Migration | Population pressure | New settlers arrive |
| Plague | Low health | Population loss |
| Festival | High happiness | Morale boost |
| Season change | Calendar | Biome effects |

### Event Hooks (Reflection Only)

```java
// Engine events — no direct mod hooks
// Must poll or use reflection on:
// game.events.EVENTS
// game.faction.FACTIONS
```

---

## Overworld Map

### Regions

| Property | Access |
|----------|--------|
| Biome | `region.getBiome()` |
| Owner | `region.getOwnerFaction()` |
| Resources | `region.getResources()` |
| Climate | `region.getClimate()` |

### Settlement Placement

```java
// Engine handles — mod can influence via:
// - Race preferences (PREFERRED.TERRAIN)
// - Faction expansion logic
```

---

## Season & Calendar

```java
// game.time.TIME
int day = TIME.day();      // 1-30
int month = TIME.month();  // 1-12
int year = TIME.year();    // Year count
Season season = TIME.getSeason(); // SPRING, SUMMER, AUTUMN, WINTER
```

### Season Effects

| Season | Crop Growth | Movement | Morale |
|--------|-------------|----------|--------|
| Spring | 1.2x | Normal | +0.1 |
| Summer | 1.0x | Normal | Normal |
| Autumn | 0.8x | Normal | -0.1 |
| Winter | 0.3x | -0.2 | -0.2 |

---

*World Domain — Overworld Authority*