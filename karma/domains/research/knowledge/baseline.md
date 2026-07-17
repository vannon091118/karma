# Research Domain — Baseline Knowledge

---
verified_against: "AGENTS.md + game-modding-research/"
verified_at: "2026-07-16"
staleness_risk: "low"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
---

## Zuständigkeit
Online-Recherche, Vanilla-Daten-Analyse, Engine-Verifikation.

## Quellen (Priorität)
1. `data.zip` (Vanilla-Spieldaten)
2. `SongsOfSyx-sources.jar` (Engine-Interna)
3. `songs-of-syx-mod-example` (Offizielle Modding-Doku)
4. `songs-of-syx.readthedocs.io` (Community-Doku, V70-Legacy)

## Verifikationspflicht
- Jede Recherche-Aussage braucht Fundort (Datei+Zeile oder URL)
- Vanilla-Format-Extraktion: `unzip -p data.zip 'data/assets/...'`
- Engine-API: `javap -classpath SongsOfSyx-sources.jar`

## Aktueller Stand
- SyxCraft 4-Race-Design recherchiert
- V71 Sprite-Format verifiziert (13 PNGs horizontal strips)
- Boost-Key-Registry extrahiert (0/9 SyxCraft-Keys in Vanilla)
- Snake2D Package-Map erstellt
