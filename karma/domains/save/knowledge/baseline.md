# Save Domain — Snake2D V71.63

---
verified_against: "SyxCraft/src/main/java/com/syxcraft/core/StateManager.java"
verified_at: "2026-07-16"
staleness_risk: "high"
stale_checks:
  - "version:SyxCraft/src/main/java/com/syxcraft/core/StateManager.java:SAVE_VERSION = 2"
  - "grep:SyxCraft/src/main/java/com/syxcraft/core/StateManager.java:FilePutter"
  - "grep:SyxCraft/src/main/java/com/syxcraft/core/StateManager.java:FileGetter"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.
> **Responsibility:** Save/Load implementation, versioning, migration, schema evolution
> **Owner:** Save Domain Agent

---

## FilePutter / FileGetter API (Verified)

### FilePutter (Writing)

| Method | Signature | Use For |
|--------|-----------|---------|
| `i(int)` | `void i(int value)` | int (32-bit signed) |
| `l(long)` | `void l(long value)` | long (64-bit) |
| `f(float)` | `void f(float value)` | float (32-bit) |
| `d(double)` | `void d(double value)` | double (64-bit) |
| `b(boolean)` | `void b(boolean value)` | boolean (1 byte) |
| `s(String)` | `void s(String value)` | String (UTF-8, length-prefixed) |

### FileGetter (Reading)

| Method | Signature | Returns |
|--------|-----------|---------|
| `i()` | `int i()` | int |
| `l()` | `long l()` | long |
| `f()` | `float f()` | float |
| `d()` | `double d()` | double |
| `b()` | `boolean b()` | boolean |
| `s()` | `String s()` | String |

---

## Save Versioning Strategy

### Version Constants
```java
// ACHTUNG: Tatsächlicher Wert im Mod-Code (StateManager.java) = 2, nicht 4.
// Dieses Template zeigt Version 4 als Beispiel für zukünftige Migration.
public static final int SAVE_VERSION = 2;  // Increment on schema change
```

### Save Format
```
[SAVE_VERSION: int]
[Mod-specific fields...]
[State objects...]
```

---

## Save Implementation Template

```java
@Override
public void save(FilePutter putter) throws IOException {
    // 1. Always write version FIRST
    putter.i(SAVE_VERSION);
    
    // 2. Primitive fields
    putter.i(citizenPopulation);
    putter.i(workforceCount);
    putter.f(moonwaterLevel);
    putter.b(isEventActive);
    putter.s(eventName);
    
    // 3. Complex state objects (each handles own version)
    geistState.save(putter);
    moonwaterState.save(putter);
    buildingGateState.save(putter);
    conversionState.save(putter);
    slaveTradeState.save(putter);
    blightState.save(putter);
}
```

---

## Load Implementation Template

```java
@Override
public void load(FileGetter getter) throws IOException {
    int version = getter.i();
    
    // Version 1: Basic population
    if (version >= 1) {
        citizenPopulation = getter.i();
        workforceCount = getter.i();
    }
    
    // Version 2: Added moonwater
    if (version >= 2) {
        moonwaterLevel = getter.f();
    }
    
    // Version 3: Added event system
    if (version >= 3) {
        isEventActive = getter.b();
        eventName = getter.s();
    }
    
    // Version 4: Added state objects
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

## State Object Pattern (Required for Complex State)

### Standard Interface
```java
public interface Saveable {
    void save(FilePutter putter) throws IOException;
    void load(FileGetter getter) throws IOException;
    int getSaveVersion();
}
```

### Implementation Example
```java
public class GeistState implements Saveable {
    private static final int VERSION = 2;
    
    private float geist = 0.3f;
    private float fear = 0.0f;
    private float control = 0.0f;
    private boolean rebellionActive = false;
    private int rebellionCooldown = 0;
    
    @Override
    public void save(FilePutter putter) throws IOException {
        putter.i(VERSION);
        putter.f(geist);
        putter.f(fear);
        putter.f(control);
        putter.b(rebellionActive);
        putter.i(rebellionCooldown);
    }
    
    @Override
    public void load(FileGetter getter) throws IOException {
        int version = getter.i();
        
        if (version >= 1) {
            geist = getter.f();
            fear = getter.f();
            control = getter.f();
        }
        if (version >= 2) {
            rebellionActive = getter.b();
            rebellionCooldown = getter.i();
        }
    }
    
    @Override
    public int getSaveVersion() {
        return VERSION;
    }
}
```

---

## Migration Strategy

### Version History
| Version | Added | Migration |
|---------|-------|-----------|
| 1 | Population, workforce | — |
| 2 | Moonwater level, controller state | Default 0.0f |
| 3 | Event system (PLANNED) | Default false/"" |
| 4 | State objects (PLANNED) | Load each with own version |

### Migration Rules
1. **Never remove fields** — only add
2. **Always provide defaults** for new fields
3. **Log migrations** — `INFO "Migrated save from v{old} to v{SAVE_VERSION}"`
4. **Test all versions** — keep test saves for v1, v2, v3, v4

---

## Validation & Error Handling

### Save Validation
```java
private void validateBeforeSave() {
    if (citizenPopulation < 0) throw new IllegalStateException("Negative population");
    if (moonwaterLevel < 0 || moonwaterLevel > 10000) throw new IllegalStateException("Invalid moonwater");
    // ...
}
```

### Load Error Handling
```java
@Override
public void load(FileGetter getter) throws IOException {
    try {
        int version = getter.i();
        // ... load logic
    } catch (IOException | IllegalArgumentException e) {
        System.err.println("[SYXCRAFT-SAVE] Load failed: " + e.getMessage());
        // Reset to defaults
        resetToDefaults();
        throw e;  // Re-throw to let engine handle
    }
}
```

---

## Testing Checklist

- [ ] Save → Load round-trip preserves all state
- [ ] Load v1 save into v4 code works
- [ ] Load v2 save into v4 code works
- [ ] Load v3 save into v4 code works
- [ ] Load v4 save into v4 code works
- [ ] Corrupted save handled gracefully
- [ ] Version mismatch logged
- [ ] Default values reasonable

---

*Save Domain — Persistence Authority*