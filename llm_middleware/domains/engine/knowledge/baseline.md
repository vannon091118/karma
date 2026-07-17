# Engine Baseline — Snake2D V71.63 (Immutable Facts)

---
verified_against: "pom.xml game.version.minor>63 + SyxCraft/src/"
verified_at: "2026-07-16"
staleness_risk: "high"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
  - "class:SyxCraft/src:SyxCraftInstance"
  - "class:SyxCraft/src:EventBus"
  - "class:SyxCraft/src:ReflectionUtil"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml` (`game.version.minor>63`).
> **Source Priority:** Source Code > Official Docs > Runtime > Design Notes > Assumptions
> **Last Verified:** 2026-07-16 against `SongsOfSyx-sources.jar` + live V71.63 JAR

---

## Core Identity

| Fact | Value | Source |
|------|-------|--------|
| Engine name in code | `snake2d.*` (Package) | Package declaration |
| Display name | "Snake2D" (not "Snake Engine 2") | Code convention |
| Base framework | LWJGL 3.x | Imports |
| Language | Java (originally 1.8, runs on 21) | Build config |
| Source location | `info/SongsOfSyx-sources.jar` in game install | Distribution |
| Modder access | Only via 4 pathways (see below) | Official Mod Example |

### 4 Modder Access Pathways
1. **Official Modding API** — `script.SCRIPT` / `SCRIPT_INSTANCE` interface
2. **Reflection** — On engine internals (risky, runtime failures)
3. **Config Files** — `.txt` in `data.zip` / Mod override
4. **Sprite/Assets Override** — PNG + `sprites.txt` in mod folder

---

## Packages Used in SyxCraft (Verified in Source)

| Package | Purpose | SyxCraft Usage |
|---------|---------|----------------|
| `snake2d` | Core entry points | `MButt`, `Renderer` |
| `snake2d.util.file` | File I/O abstraction | `FileGetter`, `FilePutter` (Save/Load) |
| `snake2d.util.datatypes` | Custom collections | `COORDINATE`, `ArrayList` (not java.util) |
| `snake2d.util.gui` | UI framework | `GuiSection` |
| `snake2d.CORE` | Engine bootstrap | Render/Update loop control |
| `snake2d.Updater` | Game loop | Tick/Render separation |
| `game` | Core game logic | `GAME`, `VERSION`, `EVENTS`, `FACTIONS` |
| `game.boosting` | Booster system | `BOOSTABLES` |
| `init` | Data initialization | `Main`, `MainLaunchLauncher`, `MainProcess`, `paths.PATHS` |
| `init.race` | Race system | `RACES` |
| `init.resources` | Resources | `RESOURCES` |
| `init.settings` | Settings | `S` |
| `init.sprite` | Sprites | `SPRITES`, `UI.UI` |
| `init.tech` | Tech tree | `TECHS` |
| `init.constant` | Constants | `C` (screen dims, etc.) |
| `util.text` | Text/translation | `D` (¤¤ injection) |
| `init.type` | Types | `DISEASES` |
| `integrations` | Steam | `INTEGRATIONS` |
| `menu` | Main menu | `ScMain` |
| `script` | Mod API | `SCRIPT`, `SCRIPT_INSTANCE` |
| `settlement` | City building | `SETT`, `STATS`, `LAW`, `STANDINGS` |
| `settlement.entity.humanoid.ai` | AI | Citizen behavior |
| `settlement.job` | Jobs | Job definitions |
| `settlement.room` | Rooms | Room logic |
| `snake2d.util.gui` | UI | `GuiSection` |
| `snake2d.util.datatypes` | Collections | `COORDINATE`, custom `ArrayList` |
| `snake2d.util.file` | I/O | `FileGetter`, `FilePutter` |
| `view` | Rendering | `VIEW` (world, settlement, battle) |
| `world` | Overworld | World map logic |

---

## Critical Engine Classes (Verified in Source)

| Class | Role | Key Methods/Fields |
|-------|------|-------------------|
| `snake2d.CORE` | Engine bootstrap | `init()`, `update()`, `render()` |
| `snake2d.Updater` | Game loop | `update(delta)`, `render()` |
| `snake2d.Renderer` | Rendering pipeline | `draw()`, `flush()` |
| `snake2d.MButt` | Input | `mouseClick()`, `keyPush()` |
| `snake2d.util.gui.GuiSection` | UI container | Layout, children |
| `snake2d.util.datatypes.COORDINATE` | 2D coords | `x`, `y` |
| `snake2d.util.sets.ArrayList` | Custom list | NOT `java.util.ArrayList` |
| `snake2d.util.file.FileGetter` | Read abstraction | `i()`, `f()`, `b()`, `s()`, `bool()` |
| `snake2d.util.file.FilePutter` | Write abstraction | `i()`, `f()`, `b()`, `s()`, `bool()` |

---

## SCRIPT Interface (Mod Entry Point — Verified)

```java
// script.SCRIPT
public interface SCRIPT {
    CharSequence name();
    CharSequence desc();
    void initBeforeGameCreated();
    void initBeforeGameInited();
    SCRIPT_INSTANCE createInstance();  // CALLED EXACTLY ONCE PER GAME
}

// script.SCRIPT.SCRIPT_INSTANCE
public interface SCRIPT_INSTANCE {
    void init();                          // Mod initialization
    void update(double deltaSeconds);     // Every tick
    void save(FilePutter file) throws IOException;
    void load(FileGetter file) throws IOException;
    void render(Renderer renderer, float deltaSeconds);
    void keyPush(KEYS keys);
    void mouseClick(MButt button);
    void hover(COORDINATE mCoo, boolean mouseHasMoved);
    void hoverTimer(double mouseTimer, GBox text);
    boolean handleBrokenSavedState();
}
```

**CRITICAL:** `createInstance()` called **exactly once** per running game. One `SCRIPT_INSTANCE` per mod. Engine enforces this.

---

## Save/Load Protocol (Verified)

```java
// SCRIPT_INSTANCE
void save(FilePutter putter) throws IOException {
    putter.i(SAVE_VERSION);  // int
    // ... write primitive types only
}

void load(FileGetter getter) throws IOException {
    int version = getter.i();  // MUST read version first
    // ... read in same order
}
```

**FilePutter methods:** `i(int)`, `l(long)`, `f(float)`, `d(double)`, `b(boolean)`, `s(String)`, `bool(boolean)`
**FileGetter methods:** `i()`, `l()`, `f()`, `d()`, `b()`, `s()`, `bool()`

---

## V71 Sprite System (CORRECTED — Verified Against Example Mod)

| Aspect | V70 (Legacy) | **V71 (Current)** |
|--------|--------------|-------------------|
| Structure | 1 spritesheet (192×128) + `sprites.txt` | **13 individual PNGs per race** |
| Layout | Numbered grid | **Horizontal frame strips** |
| Config Keys | `SPRITE_SHEET` + `sprites.txt` | `SPRITE_FILE`, `HEAD_FILE`, `HAIR_FILE`, `CIVILIAN_FILE`, `WORKER_FILE`, `SOLDIER_FILE`, `PORTRAIT_FILE`, `ICON_FILE`, `BEARD_FILE`, `ARMOR_FILE`, `ARMOR2_FILE`, `BACKPACK_FILE`, `HAIR2_FILE` |
| Race Config | `SPRITE_SHEET: race` | `SPRITE_FILE: race` + 12 more keys |
| Icons | In spritesheet | Separate `ICON_FILE` + `PORTRAIT_FILE` |

### V71 Race Sprite Config Keys (13 PNGs per Race)

```properties
# Body Parts (Horizontal Frame Strips)
SPRITE_FILE: 'RACE',           # Main body
HEAD_FILE: 'RACE_Face',        # Heads
HAIR_FILE: 'RACE_Hair',        # Hair styles
BEARD_FILE: 'RACE_Beard',      # Beards
ARMOR_FILE: 'RACE_Armor',      # Armor
ARMOR2_FILE: 'RACE_Armor2',    # Armor variant
BACKPACK_FILE: 'RACE_Backpack', # Backpacks

# State Variants
CIVILIAN_FILE: 'RACE_Civilian',
WORKER_FILE: 'RACE_Worker',
SOLDIER_FILE: 'RACE_Soldier',

# UI
PORTRAIT_FILE: 'RACE_Portrait',
ICON_FILE: 'RACE_Icon',
```

**Icon References in Race Config:**
```properties
ICON_SMALL: 24->race->RACE->0,
ICON_BIG: 32->race->RACE->0,
```

### Frame Strip Format
- **Dimensions:** Variable width × fixed height per part
- **Frames:** Horizontal strip (frame 0, 1, 2... left to right)
- **Standard counts:** Body ~18 frames, Head ~7, Hair ~5, Armor ~3-5, etc.
- **Transparency:** Alpha channel for empty frames

---

## Mod Folder Structure (V71 Standard)

```
ModName/
├── _Info.txt                          # REQUIRED — Maven-filtered
├── V71/                               # Major version folder ONLY
│   ├── assets/
│   │   ├── init/
│   │   │   ├── race/                  # Race configs
│   │   │   ├── room/                  # Room configs
│   │   │   ├── resource/              # Resource configs
│   │   │   ├── tech/                  # Tech configs
│   │   │   ├── event/                 # Event configs
│   │   │   ├── law/                   # Law configs
│   │   │   ├── animal/                # Animal configs
│   │   │   ├── disease/               # Disease configs
│   │   │   ├── religion/              # Religion configs
│   │   │   ├── config/                # Game configs
│   │   │   ├── settlement/            # Settlement configs
│   │   │   ├── world/                 # World configs
│   │   │   └── trait/                 # Trait configs
│   │   └── sprite/
│   │       └── race/                  # 13 PNGs + sprites.txt per race
│   │       ├── RACE.png
│   │       ├── RACE_Face.png
│   │       ├── RACE_Hair.png
│   │       ├── RACE_Beard.png
│   │       ├── RACE_Armor.png
│   │       ├── RACE_Armor2.png
│   │       ├── RACE_Backpack.png
│   │       ├── RACE_Civilian.png
│   │       ├── RACE_Worker.png
│   │       ├── RACE_Soldier.png
│   │       ├── RACE_Portrait.png
│   │       ├── RACE_Icon.png
│   │       └── sprites.txt
│   └── script/
│       ├── ModName.jar                # Compiled mod
│       └── _src/                      # Sources (optional, for debug)
```

### _Info.txt (Maven-Filtered)
```properties
INFO: "Description",
NAME: "ModName",
AUTHOR: "Author",
VERSION: "1.0.0",
GAME_VERSION_MAJOR: 71,
GAME_VERSION_MINOR: 44,
```

---

## Build Pipeline (Maven — Verified)

```bash
# 1. After game update: install new JAR as dependency
mvn clean validate

# 2. Normal build + install to game mod folder
mvn clean install

# 3. With Mod SDK (optional profile)
mvn clean install -Pmod-sdk

# 4. Steam Workshop upload
mvn clean install -Pmods-uploader
```

**Profiles in pom.xml:**
- `mod-sdk` — Adds `sos-mod-sdk` dependency
- `mods-uploader` — Steam Workshop upload
- OS-specific: `linux`, `windows`, `mac` (mod install paths)

---

## Verified Engine APIs (Spike 0.1 + Runtime Proof)

### Population — `settlement.stats.POP` (All static)
| Method | Description |
|--------|-------------|
| `tot(HCLASS, Race)` | Total = physical + army |
| `tot(Race)` | = `tot(null, Race)` |
| `tot()` | All population |
| `physical(HCLASS, Race)` | Physically in settlement |
| `pop(HCLASS, Race)` | Base population (no children/criminals) |
| `next(HCLASS, Race)` | Current + incoming |
| `incoming(HCLASS, Race)` | Only incoming |

**HCLASS Constants:** `HCLASSES.CITIZEN()`, `SLAVE()`, `NOBLE()`

### Workforce — `settlement.stats.STATS.WORK()`
| Method | Description |
|--------|-------------|
| `workforce()` | Total (subjects + slaves - incapacitated) |
| `workforce(Race)` | Race-specific |
| `workforce(Race, daysBack)` | Historical |

### Factions — `game.faction.FACTIONS`
| Access | Description |
|--------|-------------|
| `NPCs()` | Iterable<FactionNPC> |
| `FactionNPC.race()` | Race of faction |
| `FactionNPC.offensivePower()` | Military strength |

### Room Employment — `settlement.room.main.employment.RoomEmploymentSimple`
| Method | Description |
|--------|-------------|
| `employed()` | Workers in room |
| `employed(WGROUP)` | Workers by group |

**Access:** `SETT.ROOMS().employment` → reflect `all` or `allS` field → iterate `RoomEmploymentSimple`

---

## Mod Template Reference (Official)

**Repo:** `https://github.com/4rg0n/songs-of-syx-mod-example`
- `doc/README` — Overview
- `doc/res/MAKE_A_MOD.txt` — Full modding guide
- `doc/howto/game_code.md` — Engine packages, classes
- `doc/howto/access_game_code.md` — Reflection patterns
- `doc/howto/modding_strategy.md` — Config vs Code decision
- `doc/explanation/race_sprite_rundown.md` — **V71 Sprite Format** (authoritative)
- `doc/config/race.md` — Race config keys
- `doc/config/room.md` — Room config format
- `doc/config/resource.md` — Resource format
- `doc/config/tech.md` — Tech tree format

---

## Key Constraints (Enforced by Engine)

| Constraint | Enforcement |
|------------|-------------|
| Single `SCRIPT_INSTANCE` | Engine calls `createInstance()` once |
| No `java.util.*` on engine collections | Use `snake2d.util.sets.*` |
| No Swing/JavaFX UI | Use `snake2d.util.gui.GuiSection` |
| Reflection = runtime risk | Validate at runtime, track failures |
| Silent fallback = data corruption | DEGRADED state after 3 failures |
| Mod folder = `V<major>/` only | `V71/` not `V71.63/` |

---

## Quick Reference: Modding Workflow

```bash
# 1. Game update → re-install JAR
mvn clean validate

# 2. Code changes
mvn test                    # Unit tests only
mvn clean install -P linux  # Build + install to ~/.local/share/songsofsyx/mods/

# 3. Test in game
# Launch game → Mods → Enable SyxCraft → New Game

# 4. Debug
# Game logs: ~/.local/share/songsofsyx/logs/
# Mod logs: System.out.println("[SYXCRAFT] ...")
```

---

*Authoritative Source: Snake2D V71.63 Source + Official Mod Example + Runtime Verification*
*This document is the single source of truth for Engine facts. Update only after source re-verification.*