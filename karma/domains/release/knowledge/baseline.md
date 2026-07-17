# Release Domain — Snake2D V71.63

---
verified_against: "SyxCraft/pom.xml + SyxCraft/_Info.txt"
verified_at: "2026-07-16"
staleness_risk: "high"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor>63"
  - "grep:SyxCraft/pom.xml:game.version.major>71"
---

> **⚠️ STATUS:** Agentgenerierte Referenz — KEINE Stufe-1-Quelle. Kanonisch: `SyxCraft/src/` + `pom.xml`.

> **Responsibility:** Version bump, packaging, GitHub release, CI/CD, changelog
> **Owner:** Release Domain Agent

---

## Versioning (SemVer)

| Component | Location | Rule |
|-----------|----------|------|
| `project.version` | `pom.xml` | MAJOR.MINOR.PATCH |
| `GAME_VERSION_MAJOR` | `pom.xml` | Must match target game |
| `GAME_VERSION_MINOR` | `pom.xml` | Must match target game |
| `VERSION` | `_Info.txt` | Maven-filtered from `project.version` |
| `GAME_VERSION_MAJOR` | `_Info.txt` | Maven-filtered |
| `GAME_VERSION_MINOR` | `_Info.txt` | Maven-filtered |

### Version Bump Rules

| Change | Version Bump |
|--------|--------------|
| New feature | MINOR |
| Bug fix | PATCH |
| Breaking engine API | MAJOR (new game major) |
| Save format change | MINOR + migration |

---

## Build Pipeline

### Local Release

```bash
# 1. Ensure clean
mvn clean

# 2. Run full test suite
mvn test

# 3. Install game JAR (if game updated)
mvn validate

# 4. Build release
mvn clean install -P linux

# 5. Verify mod in game folder
ls ~/.local/share/songsofsyx/mods/SyxCraft/

# 6. Launch game, verify mod loads
```

### CI Pipeline (GitHub Actions)

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '21'
      - name: Build
        run: mvn clean install -P linux
      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: SyxCraft-Mod
          path: target/out/SyxCraft/
```

---

## Release Checklist

### Pre-Release

- [ ] All P0/P1 tickets closed
- [ ] `mvn clean test` passes
- [ ] `mvn clean install -P linux` succeeds
- [ ] Mod installs and loads in game
- [ ] Save/Load tested
- [ ] No DEGRADED after 30 min play
- [ ] CHANGELOG.md updated
- [ ] Version bumped in `pom.xml`

### Release

- [ ] Tag created: `git tag v<version>`
- [ ] GitHub Release created
- [ ] Release notes = CHANGELOG entry
- [ ] Artifact attached (mod folder zip)
- [ ] Steam Workshop upload (if applicable)

### Post-Release

- [ ] Next development version in `pom.xml` (SNAPSHOT)
- [ ] CHANGELOG.md "Unreleased" section cleared
- [ ] Milestone closed
- [ ] Issues closed

---

## Packaging

### Mod Structure (Output)

```
target/out/SyxCraft/
├── _Info.txt
├── V71/
│   ├── assets/
│   │   ├── init/
│   │   │   ├── race/
│   │   │   ├── room/
│   │   │   ├── event/
│   │   │   ├── tech/
│   │   │   ├── resource/
│   │   │   ├── config/
│   │   │   ├── law/
│   │   │   ├── animal/
│   │   │   ├── disease/
│   │   │   ├── religion/
│   │   │   ├── world/
│   │   │   ├── settlement/
│   │   │   └── trait/
│   │   └── sprite/
│   │       └── race/
│   │       ├── UNDEAD.png
│   │       ├── UNDEAD/sprites.txt
│   │       ├── ORC.png
│   │       ├── ORC/sprites.txt
│   │       ├── HUMAN.png
│   │       ├── HUMAN/sprites.txt
│   │       ├── NIGHT_ELF.png
│   │       └── NIGHT_ELF/sprites.txt
│   └── script/
│       ├── SyxCraft.jar
│       └── _src/
└── (no other files)
```

### Package Script

```bash
#!/bin/bash
# package-release.sh

VERSION=$(mvn help:evaluate -Dexpression=project.version -q -DforceStdout)
MOD_DIR="target/out/SyxCraft"
ZIP="SyxCraft-v${VERSION}.zip"

cd target/out
zip -r "../../${ZIP}" SyxCraft/
echo "Created ${ZIP}"
```

---

## CI/CD Pipeline (GitHub Actions)

```yaml
# .github/workflows/release.yml
name: Release

on:
  push:
    tags:
      - 'v*'

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-java@v4
        with:
          distribution: 'temurin'
          java-version: '21'
      - name: Build
        run: mvn clean install -P linux
      - name: Upload Artifact
        uses: actions/upload-artifact@v4
        with:
          name: SyxCraft-Mod
          path: target/out/SyxCraft/

  release:
    needs: build
    runs-on: ubuntu-latest
    steps:
      - uses: actions/download-artifact@v4
        with:
          name: SyxCraft-Mod
      - uses: softprops/action-gh-release@v1
        with:
          files: SyxCraft-*.zip
          generate_release_notes: true
```

---

## Post-Release

```bash
# 1. Verify mod installs correctly
# 2. Verify GitHub release page
# 3. Update Discord/Community
# 4. Close milestone
# 5. Plan next sprint
```

---

*Release Domain — Delivery Authority*