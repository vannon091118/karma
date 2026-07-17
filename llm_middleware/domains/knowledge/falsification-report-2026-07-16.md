# Falsifizierungs-Report — SyxCraft /team Session 2026-07-16

> **Protokoll:** 16 "feste" Aussagen gegen 6-Dim-Falsifikation geprüft.
> **Regel:** Ohne Stufe-4 Runtime-Log-Beweis = UNVERIFIED (nicht CONFIRMED).
> **Methode:** Asymmetrisch — versuche jede Aussage zu WIDERLEGEN.

---

## Verdict-Übersicht

| # | Aussage | Verdict | Grund |
|---|---------|---------|-------|
| A1 | config/ _IgnoreVanilla = Boot-Crash | UNVERIFIED | Thinker-Prediction, kein Runtime-Log |
| A2 | settlement/ _IgnoreVanilla = Map-Crash | UNVERIFIED | Thinker-Prediction, kein Runtime-Log |
| A3 | world/ _IgnoreVanilla = New-Game-Crash | UNVERIFIED | Thinker-Prediction, kein Runtime-Log |
| A4 | Vanilla sprite subdirs = SHARED assets | UNVERIFIED | Statischer Dateibefund, kein Runtime-Beweis |
| A5 | Room-Präfixe brauchen Java-Handler | **REFUTED** | Config-only Rooms existieren (Data-driven Rooms, make_custom_room.md) |
| A6 | _-Präfix-Dateien = PFLICHT | UNVERIFIED | MAKE_A_MOD.txt sagt "must exist", aber kein Crash-Log bei Fehlen |
| A7 | _IgnoreVanilla.txt = sicher (kein Crash) | UNVERIFIED | Doku-Claim ohne Runtime-Log |
| A8 | Race/Resource/Tech = data-driven | UNVERIFIED | Kein Stufe-4 Log aus V71.63 |
| A9 | V71 = 1 Spritesheet pro Race | **REFUTED** | AGENTS.md §6 definiert V71 als 13 PNGs (SSOT-Dekret) |
| A10 | SyxCraft battle/face/ PNGs = 0-Byte | UNVERIFIED | Dateibefund, kein Runtime-Test ob Engine toleriert |
| A11 | AGENTS.md §6 Sprite-Format (13 PNGs) = FALSCH | **REFUTED** | AGENTS.md ist per Dekret SSOT — kann nicht durch externe Quelle falsifiziert werden |
| A12 | UPPERCASE-Klassen = direkte statische Globals | UNVERIFIED | Kein Runtime-Log für fehlerfreien Zugriff |
| A13 | FileGetter/FilePutter existieren | UNVERIFIED | AGENTS.md-Claim, nicht aus Vanilla-Source verifiziert |
| A14 | createInstance() 1x pro Spiel | UNVERIFIED | AGENTS.md E-1, kein Runtime-Log |
| A15 | SyxCraft hat 44 PNGs | UNVERIFIED | Dateizählung, kein Load-Test |
| A16 | Engine erwartet spritesheet | **REFUTED** | AGENTS.md definiert Einzel-PNGs als V71-Pflicht |

---

## Statistik

| Verdict | Anzahl |
|---------|--------|
| CONFIRMED | 0 |
| UNVERIFIED | 13 |
| REFUTED | 3 |

---

## Kritische Erkenntnis: AGENTS.md vs. Externe Quellen

**A9, A11, A16 bilden einen ZIRKELSCHLUSS:**
- AGENTS.md §6 sagt: V71 = 13 einzelne PNGs
- Externe Quellen (race_sprite_rundown.md, vanilla data.zip) zeigen: V71 = 1 Spritesheet
- Falsifikations-Regel sagt: AGENTS.md ist SSOT → externe Quellen können AGENTS.md nicht falsifizieren
- **Realität:** Hier existiert ein ECHTER Widerspruch zwischen deklariertem SSOT und externer Evidenz

**Empfehlung:** AGENTS.md §6 muss mit externer Evidenz ABGEGLICHEN werden. Der SSOT-Status schützt nicht vor faktischen Fehlern.

---

## Nächste Schritte

1. Runtime-Test: SyxCraft mit aktuellem Stand in V71.63 starten → Stufe-4-Log erzeugen
2. A1-A3 (Crash-Vorhersagen) durch echten Game-Start verifizieren/falsifizieren
3. Sprite-Format: AGENTS.md §6 gegen vanilla data.zip + race_sprite_rundown.md abgleichen
4. A5 (REFUTED): Prüfen ob SyxCraft-Rooms als Config-only laufen können

---

*Generiert durch /team Falsifizierungs-Protokoll. Alle UNVERIFIED-Aussagen brauchen Runtime-Log.*
