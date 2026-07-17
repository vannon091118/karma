# Engine Hooks — Snake2D V71.63 (Verified)

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Source:** `SongsOfSyx-sources.jar` decompiled + Example Mod `MainScript.java`
> **Status:** All hooks confirmed in source

---

## SCRIPT Interface (Mod Entry Point)

```java
package script;

public interface SCRIPT {
    CharSequence name();
    CharSequence desc();
    void initBeforeGameCreated();
    void initBeforeGameInited();
    SCRIPT_INSTANCE createInstance();  // Called ONCE per game
}
```

## SCRIPT_INSTANCE Interface (Complete Lifecycle)

```java
package script;

public interface SCRIPT_INSTANCE {
    // Initialization
    void init();                           // Mod initialization
    void initBeforeGameInited();           // Post-world-gen init

    // Game Loop
    void update(double deltaSeconds);      // Every tick (deltaSeconds ~0.033s)
    void render(Renderer renderer, float deltaSeconds);  // Every frame

    // Persistence
    void save(FilePutter putter) throws IOException;
    void load(FileGetter getter) throws IOException;

    // Input
    void keyPush(KEYS keys);
    void mouseClick(MButt button);
    void hover(COORDINATE mCoo, boolean mouseHasMoved);
    void hoverTimer(double mouseTimer, GBox text);

    // Save Recovery
    boolean handleBrokenSavedState();
}
```

---

## Hook Call Order (Verified)

```
1. SCRIPT.initBeforeGameCreated()     // Pre-world-gen
2. World Generation
3. SCRIPT.initBeforeGameInited()      // Post-world-gen, pre-first-tick
4. SCRIPT.createInstance() → instance  // ONCE per game
5. instance.init()                     // Mod initialization
6. Game Loop:
   ├─ instance.update(deltaSeconds)    // Every tick
   ├─ instance.render(renderer, dt)    // Every frame
   ├─ Input → keyPush/mouseClick/hover
   ├─ Save → instance.save(putter)
   └─ Load → instance.load(getter)
```

---

## Input Events (Verified)

| Event | Parameters | Notes |
|-------|------------|-------|
| `keyPush(KEYS keys)` | `snake2d.view.keyboard.KEYS` | Key pressed |
| `mouseClick(MButt button)` | `snake2d.MButt` (LEFT/RIGHT/MIDDLE) | Mouse button |
| `hover(COORDINATE mCoo, boolean mouseHasMoved)` | Coord + moved flag | Mouse move |
| `hoverTimer(double mouseTimer, GBox text)` | Timer + tooltip box | Tooltip hover |

---

## Debug Panel Hook (Verified in Example Mod)

```java
// In initBeforeGameInited()
import view.interrupter.IDebugPanel;

IDebugPanel.add("SyxCraft: Geist Status", () -> {
    return "Geist: " + String.format("%.2f", geistManager.getGeist()) 
         + " | Viability: " + String.format("%.2f", geistManager.getVillageViability());
});
```

**Package:** `view.interrupter.IDebugPanel`
**Method:** `add(String label, Supplier<String> supplier)`

---

## Mod Lifecycle Events (Verified)

| Event | When | Mod Can |
|-------|------|---------|
| `initBeforeGameCreated()` | Pre-world-gen | Register configs early |
| `initBeforeGameInited()` | Post-world-gen | Hook debug panel, late init |
| `createInstance()` | Once per game | Return `SCRIPT_INSTANCE` |
| `init()` | Mod init | Register hooks, init managers |
| `update(delta)` | Every tick | Game logic |
| `render()` | Every frame | Custom rendering |
| `save(putter)` | On save | Persist state |
| `load(getter)` | On load | Restore state |
| `handleBrokenSavedState()` | Corrupt save | Recovery logic |

---

## Reflection Access Points (Verified in Source)

| Target | Package.Class | Access Pattern |
|--------|---------------|----------------|
| Population | `settlement.stats.POP` | `POP.tot(HCLASS, Race)` |
| Workforce | `settlement.stats.STATS.WORK()` | `workforce()`, `workforce(Race)` |
| Factions | `game.faction.FACTIONS` | `FACTIONS.NPCs()` → `FactionNPC.race()`, `offensivePower()` |
| Rooms | `settlement.room.main.employment.RoomEmploymentSimple` | Reflection on `SETT.ROOMS().employment` → `all` / `allS` |
| Settings | `init.settings.S` | Game settings |
| Constants | `init.constant.C` | Screen dims, etc. |
| Text | `util.text.D` | `D.ts(Class)` for ¤¤ injection |
| Time | `game.time.TIME` | Day, month, year |
| Resources | `init.resources.RESOURCES` | Resource registry |
| Techs | `init.tech.TECHS` | Tech tree |
| Races | `init.race.RACES` | Race registry |

---

## Save/Load API (Verified)

```java
// FilePutter (Writing)
putter.i(int)      // int
putter.l(long)     // long
putter.f(float)    // float
putter.d(double)   // double
putter.b(boolean)  // boolean
putter.s(String)   // String
putter.bool(boolean) // alias for b()

// FileGetter (Reading)
getter.i()  // int
getter.l()  // long
getter.f()  // float
getter.d()  // double
getter.b()  // boolean
getter.s()  // String
getter.bool() // boolean
```

**Protocol:** Write version first, read version first. Handle version migration in `load()`.

---

## Text Injection (¤¤ + D.ts) — Verified

```java
public class MyClass {
    private static CharSequence ¤¤warning = "Warning: Rebellion!";
    static { D.ts(MyClass.class); }
}

// Config: fully.qualified.MyClass.txt
// warning=Warnung: Rebellion!
```

**Mechanism:** Static initializer calls `D.ts(Class)` → loads `assets/text/fully.qualified.ClassName.txt` → replaces `¤¤field` at runtime.

---

*Verified against V71.63 source. Update only after source re-verification.*