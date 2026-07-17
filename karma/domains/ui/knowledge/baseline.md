# UI Domain — Snake2D V71.63

---
verified_against: "SyxCraft/src/ + SongsOfSyx-sources.jar"
verified_at: "2026-07-16"
staleness_risk: "low"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Responsibility:** Snake2D GUI system, debug panels, mod menus, tooltips, text injection
> **Owner:** UI Domain Agent

---

## Snake2D GUI System (Verified)

### Core Classes

| Class | Package | Purpose |
|-------|---------|---------|
| `GuiSection` | `snake2d.util.gui` | Container/layout for UI elements |
| `GBox` | `snake2d.util.gui` | Bounding box / layout helper |
| `IDebugPanel` | `view.interrupter` | Debug panel registration |
| `D` | `util.text` | Text injection / localization |

---

## Debug Panel (Verified)

### Registration

```java
// In MainScript.initBeforeGameInited()
import view.interrupter.IDebugPanel;
import util.gui.misc.GBox;

IDebugPanel.add("SyxCraft: Geist Status", () -> {
    return "Geist: " + String.format("%.2f", geistManager.getGeist()) 
         + " | Viability: " + String.format("%.2f", geistManager.getVillageViability());
});
```

**Parameters:**
- Label: String (shown in debug panel)
- Supplier<String>: Called every frame for live update

---

## Text Injection (Engine Rule E-2)

### Pattern (Required for All Player-Visible Text)

```java
public class MyClass {
    // Field with marker prefix
    private static CharSequence ¤¤warningText = "Warning: Rebellion imminent!";
    
    // Static initializer block
    static { D.ts(MyClass.class); }
}
```

### Config File

```
# File: assets/text/fully.qualified.MyClass.txt
# Key = field name (without ¤¤)
warningText=Warnung: Rebellion droht!
```

### Engine Resolution

1. Engine finds `D.ts(MyClass.class)` call
2. Loads `assets/text/fully.qualified.MyClass.txt`
3. Replaces `¤¤fieldName` with config value at runtime
4. Java literal is fallback only

---

## Custom UI Elements (Advanced)

### GuiSection Usage

```java
import snake2d.util.gui.GuiSection;
import snake2d.util.datatypes.COORDINATE;

public class CustomPanel extends GuiSection {
    public CustomPanel() {
        setLayout(new VerticalLayout());
        addChild(new Label("Title"));
        addChild(new Button("Action", this::onAction));
    }
    
    private void onAction() {
        // Handle click
    }
}
```

### Layout System

| Layout | Behavior |
|--------|----------|
| `VerticalLayout` | Stack children vertically |
| `HorizontalLayout` | Stack children horizontally |
| `GridLayout` | Grid arrangement |
| `AbsoluteLayout` | Manual positioning |

---

## Text Injection Checklist

- [ ] No hardcoded player-visible strings in Java
- [ ] All player text uses `¤¤fieldName` pattern
- [ ] `static { D.ts(YourClass.class); }` present
- [ ] Config file exists at `assets/text/fully.qualified.ClassName.txt`
- [ ] Keys match field names exactly
- [ ] Fallback English text in Java field
- [ ] No `System.out.println` for player text

---

*UI Domain — User Interface Authority*