# Runtime Baseline — Snake2D V71.63

---
verified_against: "SyxCraft/src/main/java/com/syxcraft/core/SyxCraftInstance.java"
verified_at: "2026-07-16"
staleness_risk: "high"
stale_checks:
  - "grep:SyxCraft/src/main/java/com/syxcraft/core/SyxCraftInstance.java:EventBus.get().publish"
  - "class:SyxCraft/src:EventBus"
  - "class:SyxCraft/src:ReflectionUtil"
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.
> **Responsibility:** Tick loop, save/load, update cycle, reflection integration, DEGRADED handling
> **Owner:** Runtime Domain Agent

---

## Tick Loop Architecture

### Engine Loop (Snake2D Core)
```
Game Loop (Updater)
    │
    ├─► CORE.update()           // Engine core update
    │
    ├─► SCRIPT_INSTANCE.update()  // Mod hook — YOUR CODE HERE
    │       │
    │       └─► EventBus.get().publish(CYCLE_TICK, tickData)  // A-1: Einzige Kopplungsstelle
    │               │
    │               ├─► UndeadController.onTick()   (via bus.subscribe)
    │               ├─► OrcController.onTick()      (via bus.subscribe)
    │               ├─► HumanController.onTick()    (via bus.subscribe)
    │               └─► NightElfController.onTick() (via bus.subscribe)
    │
    │       └─► EventBus.get().publish(SLAVE_TRADE, orcPresence)
    │
    ├─► CORE.render()           // Engine render
    │
    └─► SCRIPT_INSTANCE.render()  // Mod render hook
```

**A-1 Regel:** Kein Controller referenziert einen anderen direkt. EventBus Only.
Quelle: `SyxCraftInstance.java:118`, `EventBus.java`, alle Controller via `bus.subscribe()`.

### Update Method Contract
```java
@Override
public void update(double deltaSeconds) {
    // deltaSeconds = time since last tick (typically ~0.033s for 30 TPS)
    // Called on MAIN THREAD (game logic thread)
    // DO NOT BLOCK — target < 2ms per tick
    
    try {
        updateManagers(deltaSeconds);
    } catch (Exception e) {
        System.err.println("[SYXCRAFT] Update error: " + e.getMessage());
    }
}
```

---

## Save/Load Integration

### Hook Points
```java
@Override
public void save(FilePutter putter) throws IOException {
    putter.i(SAVE_VERSION);  // ALWAYS FIRST
    
    // Core state
    putter.i(citizenPopulation);
    putter.i(workforceCount);
    putter.f(moonwaterLevel);
    putter.b(isEventActive);
    putter.s(eventName);
    
    // Delegate to state objects
    geistState.save(putter);
    moonwaterState.save(putter);
    buildingGateState.save(putter);
    conversionState.save(putter);
    slaveTradeState.save(putter);
    blightState.save(putter);
}

@Override
public void load(FileGetter getter) throws IOException {
    int version = getter.i();
    
    if (version >= 1) {
        citizenPopulation = getter.i();
        workforceCount = getter.i();
    }
    if (version >= 2) {
        moonwaterLevel = getter.f();
    }
    if (version >= 3) {
        isEventActive = getter.b();
        eventName = getter.s();
    }
    if (version >= 4) {
        geistState.load(getter);
        moonwaterState.load(getter);
        buildingGateState.load(getter);
        conversionState.load(getter);
        slaveTradeState.load(getter);
        blightState.load(getter);
    }
    
    // Post-load validation
    validateLoadedState();
}
```

---

## DEGRADED State Handling

### When Engine APIs Fail
```java
public void update(double delta) {
    boolean anyDegraded = false;
    
    // Check reflection health
    if (DegradedTracker.isDegraded("POP.tot")) {
        System.err.println("[SYXCRAFT-DEGRADED] Population API unavailable — using cached values");
        citizenPopulation = cachedPopulation;
        anyDegraded = true;
    }
    
    if (DegradedTracker.isDegraded("STATS.WORK")) {
        System.err.println("[SYXCRAFT-DEGRADED] Workforce API unavailable");
        workforceCount = cachedWorkforce;
        anyDegraded = true;
    }
    
    if (anyDegraded) {
        // Reduce functionality gracefully
        updateDegraded(delta);
        return;
    }
    
    // Normal update
    updateNormal(delta);
}
```

### DEGRADED Triggers
| Condition | Trigger | Behavior |
|-----------|---------|----------|
| 3 reflection failures | `ReflectionUtil` failure count | Set DEGRADED flag, use cache |
| Engine API returns null | `ReflectionUtil.getFieldValue()` returns null | Log warning, continue |
| Save/Load exception | Catch in `load()` | Log, use defaults, mark degraded |

### Recovery
| Condition | Action |
|-----------|--------|
| 5 consecutive successes | `DegradedTracker.recordSuccess()` → clear DEGRADED |
| Game reload (save/load) | Reset DEGRADED flags on load |

---

## Runtime Validation Protocol

### Startup Validation (Mod Load)
```java
public static void validateRuntime() {
    ValidationReport report = new ValidationReport();
    
    // 1. Reflection health
    report.check("POP.tot()", () -> POP.tot() >= 0);
    report.check("STATS.WORK().workforce()", () -> STATS.WORK().workforce() >= 0);
    report.check("FACTIONS.NPCs()", () -> FACTIONS.NPCs() != null);
    report.check("SETT.ROOMS().employment", () -> SETT.ROOMS().employment != null);
    
    // 2. Asset validation
    report.check("Race sprites", () -> validateRaceSprites());
    
    // 3. Config validation
    report.check("Race configs", () -> validateRaceConfigs());
    
    // 4. Version compatibility
    // Version aus pom.xml: game.version.major=71, game.version.minor>63
    report.check("Game version", () -> GAME.VERSION().equals("71.63"));
    
    if (report.hasFailures()) {
        throw new RuntimeException("Runtime validation failed: " + report);
    }
}
```

### Per-Tick Monitoring
```java
// In update() — log once per minute
if (System.currentTimeMillis() - lastLog > 60000) {
    System.out.println("[SYXCRAFT-RUNTIME] Pop=" + citizenPopulation + 
        " Work=" + workforceCount + 
        " Geist=" + geistManager.getGeist() +
        " Blight=" + blightManager.getBlightLevel());
    lastLog = System.currentTimeMillis();
}
```

---

## Engine Hook Verification

### Required Hooks (Must Exist)
| Hook | Interface | Called By Engine | Implementation |
|------|-----------|------------------|----------------|
| `init()` | `SCRIPT_INSTANCE` | Once at mod load | `SyxCraftInstance.init()` |
| `update(delta)` | `SCRIPT_INSTANCE` | Every tick | `SyxCraftInstance.update()` |
| `save(putter)` | `SCRIPT_INSTANCE` | On save | `SyxCraftInstance.save()` |
| `load(getter)` | `SCRIPT_INSTANCE` | On load | `SyxCraftInstance.load()` |
| `render(renderer)` | `SCRIPT_INSTANCE` | Every frame | `SyxCraftInstance.render()` |
| `keyPush(keys)` | `SCRIPT_INSTANCE` | Key press | `SyxCraftInstance.keyPush()` |
| `mouseClick(button)` | `SCRIPT_INSTANCE` | Mouse click | `SyxCraftInstance.mouseClick()` |

---

## Tick Budget (Performance)

| Operation | Budget | Monitoring |
|-----------|--------|------------|
| Engine API queries | < 0.5ms | Reflection call count |
| Manager updates | < 1.0ms | Per-manager timer |
| Save serialization | < 2.0ms | On save only |
| Total mod tick | < 2.0ms | Per-tick timer |

---

*Runtime Domain — Tick Loop Authority. Korrigiert 2026-07-16 gegen echten Mod-Code.*