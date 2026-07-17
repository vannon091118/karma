# Assets Domain — Snake2D V71.63

---
verified_against: "SyxCraft/V71/assets/sprite/ + AGENTS.md §6"
verified_at: "2026-07-16"
staleness_risk: "medium"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Responsibility:** Sprite sheets, animations, sprites.txt, fonts, texture management
> **Owner:** Assets Domain Agent

---

## Sprite System V71 (Verified)

### Format

| Aspect | Specification |
|--------|---------------|
| File | `<RACE>.png` (192×128 pixels) |
| Layout | Numbered grid (0–17+) |
| Config | `sprites.txt` in same folder |
| Race Config Key | `SPRITE_FILE: RACE` (no .png) |

---

## sprites.txt Format (Verified)

```text
# Frame mappings (frame index → animation)
STANDING_1: 0,
STEP_VARIANT_1: 1,
STANDING_2: 2,
STEP_VARIANT_2: 3,
STANDING_3: 4,
UNKNOWN_1: 5,
BODY_STILL: 6,
RIGHT_ARM_1: 7,
RIGHT_ARM_2: 8,
RIGHT_ARM_3: 9,
LEFT_ARM_1: 10,
LEFT_ARM_2: 11,
LEFT_ARM_3: 12,
BOTH_ARMS: 13,
BOTH_ARMS_WIDE: 14,
HEAD: 15,
SHADOW: 16,
# Diagonal frames follow (17+)
```

### Frame Indices (Standard)

| Index | Animation | Direction |
|-------|-----------|-----------|
| 0 | Standing 1 | Forward |
| 1 | Step Variant 1 | Forward |
| 2 | Standing 2 | Forward |
| 3 | Step Variant 2 | Forward |
| 4 | Standing 3 | Forward |
| 5 | Unknown | — |
| 6 | Body Still | Forward |
| 7 | Right Arm 1 | Forward |
| 8 | Right Arm 2 | Forward |
| 9 | Right Arm 3 | Forward |
| 10 | Left Arm 1 | Forward |
| 11 | Left Arm 2 | Forward |
| 12 | Left Arm 3 | Forward |
| 13 | Both Arms | Forward |
| 14 | Both Arms Wide | Forward |
| 15 | Head | Forward |
| 16 | Shadow | Forward |
| 17–33 | Diagonal variants | Diagonal |
| 34–42 | Lying down | — |
| 43+ | Addons (armor, hair, beard) | — |

---

## Race Config Keys (V71)

```properties
SPRITE_FILE: RACE,           # Required — maps to RACE.png
ICON_SMALL: 24->race->RACE->0,
ICON_BIG: 32->race->RACE->0,
```

### Do NOT Use (Legacy / Ignored)

| Key | Status |
|-----|--------|
| `HEAD_FILE` | Ignored |
| `HAIR_FILE` | Ignored |
| `BEARD_FILE` | Ignored |
| `ARMOR_FILE` | Ignored |
| `CIVILIAN_FILE` | Ignored |
| `WORKER_FILE` | Ignored |
| `SOLDIER_FILE` | Ignored |
| `PORTRAIT_FILE` | Ignored |

---

## Sprite Creation Pipeline

### Source Assets

```
/assets/source/
├── races/
│   ├── UNDEAD/
│   │   ├── body_front.png (12×16 per frame)
│   │   ├── head_front.png (8×8)
│   │   ├── armor_front.png
│   │   └── ...
│   ├── ORC/
│   ├── HUMAN/
│   └── NIGHT_ELF/
```

### Compilation (Automated)

```python
# combine_sprites.py
# 1. Load all frame layers
# 2. Composite at correct offsets
# 3. Write 192x128 PNG
# 4. Generate sprites.txt from frame map
# 5. Output to V71/assets/sprite/race/
```

### Frame Layout (192×128)

```
16px × 8 frames = 128px width (forward)
16px × 8 frames = 128px width (diagonal)
16px × 4 frames = 64px width (lying)
16px × 4 frames = 64px width (addons)

Total: 192×128
```

---

## Icon References

```properties
ICON_SMALL: 24->race->RACE->0,   # 24px, race category, RACE sprite, frame 0
ICON_BIG: 32->race->RACE->0,     # 32px, race category, RACE sprite, frame 0
```

---

## Animation Timing

| Animation | FPS | Loop |
|-----------|-----|------|
| Walking | 8 | Yes |
| Working | 4 | Yes |
| Idle | 2 | Yes |
| Shadow | 1 | Yes |

---

## Asset Validation Checklist

- [ ] 192×128 PNG per race
- [ ] `sprites.txt` with all frame mappings
- [ ] `SPRITE_FILE` key in race config
- [ ] No legacy keys (`HEAD_FILE`, etc.)
- [ ] Icon references correct (24/32→race→RACE→0)
- [ ] Transparent background (not white)
- [ ] Frame alignment consistent
- [ ] In-game test: all animations visible

---

*Assets Domain — Visual Fidelity Authority*