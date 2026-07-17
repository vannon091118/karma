# Reflection Domain — Snake2D V71.63

---
verified_against: "SyxCraft/src/main/java/com/syxcraft/core/ReflectionUtil.java"
verified_at: "2026-07-16"
staleness_risk: "high"
stale_checks:
  - "class:SyxCraft/src:ReflectionUtil"
  - "grep:SyxCraft/src/main/java/com/syxcraft/core/ReflectionUtil.java:getFieldValue"
  - "grep:SyxCraft/src/main/java/com/syxcraft/core/ReflectionUtil.java:isDegraded"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/main/java/com/syxcraft/core/ReflectionUtil.java`.
> **Responsibility:** Safe reflection access, version detection, fallback chains, runtime validation
> **Owner:** Reflection Domain Agent

---

## Core Principle

> **Reflection is a runtime privilege, not a compile-time right.**
> Every access must be validated at runtime with evidence.

---

## ReflectionUtil API (ACTUAL — from Mod Code)

> **Quelle:** `SyxCraft/src/main/java/com/syxcraft/core/ReflectionUtil.java`
> **NICHT** `SafeReflection` — diese Klasse existiert nicht im Mod.

```java
public final class ReflectionUtil {
    
    // Field read
    public static Object getFieldValue(Object instance, String fieldName) {
        // Returns null on failure (not fallback — caller must handle)
        // Logs: [SYXCRAFT-REFL] getField failed: ...
    }
    
    // Degraded state check
    public static boolean isDegraded() {
        // Returns true if too many reflection failures accumulated
    }
}
```

**Verwendung im Mod (Stufe-1-Beweis):**
```java
// MainScript.java:46
if (ReflectionUtil.isDegraded()) { ... }

// UndeadController.java:154-155
Object allList = ReflectionUtil.getFieldValue(roomEmps, "all");
if (allList == null) allList = ReflectionUtil.getFieldValue(roomEmps, "allS");
```

---

## ⚠️ Template: SafeReflection (ENTFERNT)

> Das `SafeReflection`-Template wurde entfernt weil es Agents dazu verleitet hat,
> eine nicht-existierende Klasse zu importieren.
> **Nutze stattdessen:** `ReflectionUtil` (core/ReflectionUtil.java) — siehe oben.
> Falls ein erweitertes Reflection-Template benötigt wird, gegen echten Mod-Code ableiten.

---

## Degraded Tracker (Critical)

```java
public final class DegradedTracker {
    
    private static final Map<String, Integer> failures = new ConcurrentHashMap<>();
    private static final Map<String, Integer> successes = new ConcurrentHashMap<>();
    private static final int DEGRADED_THRESHOLD = 3;
    private static final int RECOVERY_THRESHOLD = 5;
    private static final Set<String> degraded = ConcurrentHashMap.newKeySet();
    
    public static void recordFailure(String key) {
        int count = failures.merge(key, 1, Integer::sum);
        successes.remove(key);
        
        if (count >= DEGRADED_THRESHOLD && !degraded.contains(key)) {
            degraded.add(key);
            System.err.println("[SYXCRAFT-DEGRADED] " + key + " marked DEGRADED after " + count + " failures");
        }
    }
    
    public static void recordSuccess(String key) {
        int count = successes.merge(key, 1, Integer::sum);
        failures.remove(key);
        
        if (count >= RECOVERY_THRESHOLD && degraded.contains(key)) {
            degraded.remove(key);
            System.out.println("[SYXCRAFT-RECOVERY] " + key + " recovered after " + count + " successes");
        }
    }
    
    public static boolean isDegraded(String key) {
        return degraded.contains(key);
    }
    
    public static int getFailureCount(String key) {
        return failures.getOrDefault(key, 0);
    }
    
    public static Set<String> getDegradedKeys() {
        return Set.copyOf(degraded);
    }
}
```

---

## Verified Reflection Access Map (V71.63)

### Population — `settlement.stats.POP`

| Access | Method | Parameters | Return | Validated |
|--------|--------|------------|--------|-----------|
| Total pop | `tot()` | — | int | ✅ |
| By class/race | `tot(HCLASS, Race)` | HCLASS, Race | int | ✅ |
| Physical | `physical(HCLASS, Race)` | HCLASS, Race | int | ✅ |
| Base pop | `pop(HCLASS, Race)` | HCLASS, Race | int | ✅ |

**HCLASS Constants:** `HCLASSES.CITIZEN()`, `HCLASSES.SLAVE()`, `HCLASSES.NOBLE()`

### Workforce — `settlement.stats.STATS.WORK`

| Access | Method | Parameters | Return | Validated |
|--------|--------|------------|--------|-----------|
| Total | `workforce()` | — | int | ✅ |
| By race | `workforce(Race)` | Race | int | ✅ |
| Historical | `workforce(Race, daysBack)` | Race, int | int | ✅ |

### Factions — `game.faction.FACTIONS`

| Access | Method | Parameters | Return | Validated |
|--------|--------|------------|--------|-----------|
| NPC factions | `NPCs()` | — | Iterable<FactionNPC> | ✅ |
| Faction race | `race()` | — | Race | ✅ |
| Offensive power | `offensivePower()` | — | double | ✅ |

### Rooms — `settlement.room.main.util.RoomsCreator`

| Access | Method | Notes |
|--------|--------|-------|
| Employment | `SETT.ROOMS().employment` | Field access — reflection required |
| All rooms | Iterate `employment.all` / `allS` | Requires iteration |

---

## Safe Access Patterns (Templates)

### Population Query (Template — using ReflectionUtil)

```java
public int getCitizenPopulation() {
    try {
        Object result = ReflectionUtil.getFieldValue(POP.class, "tot");
        return result instanceof Integer ? (int) result : 0;
    } catch (Exception e) {
        return 0;  // Caller must handle degradation
    }
}
```

### Faction Iteration (Template — using ReflectionUtil)

```java
public float getOrcPresence() {
    float totalPower = 0f;
    try {
        Object npcs = ReflectionUtil.getFieldValue(FACTIONS.class, "NPCs");
        if (npcs instanceof Iterable) {
            for (Object npc : (Iterable<?>) npcs) {
                Object race = ReflectionUtil.getFieldValue(npc, "race");
                if (race != null && "ORC".equals(race.toString())) {
                    Object power = ReflectionUtil.getFieldValue(npc, "offensivePower");
                    if (power instanceof Number) totalPower += ((Number) power).floatValue();
                }
            }
        }
    } catch (Exception e) {
        // ReflectionUtil already logged the failure
    }
    return Math.min(1.0f, totalPower / 10000f);
}
```

---

## Validation Rules (Enforced)

| Rule | Enforcement |
|------|-------------|
| Every reflection call uses `ReflectionUtil` | Code review gate |
| Every call handles null return | Architecture review |
| Every failure logged | Runtime validation |
| 3 failures → DEGRADED | `ReflectionUtil.isDegraded()` check |
| 5 successes → Recovery | Automated tracker |
| No silent null returns | Code pattern check |

---

*Reflection Domain — Runtime Access Authority. Korrigiert 2026-07-16: SafeReflection→ReflectionUtil.*