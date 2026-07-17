#!/usr/bin/env python3
"""
SyxCraft V71 Framework — Staleness Check

Validates agent-generated domain baselines against Stufe-1 sources
(actual code, pom.xml, _Info.txt) before they are loaded as context.

The problem this solves:
  Agent output accumulates without expiry. A baseline that was correct
  at V71.44 is now wrong at V71.63. Without self-invalidation, stale
  files generate wrong code in new sessions.

Usage:
    staleness_check.py scan                 # Check all high-risk files
    staleness_check.py check <file>         # Check a single file
    staleness_check.py report               # Full staleness report
    staleness_check.py header <file>        # Show parsed header from a file

Staleness headers (YAML-like, in first 20 lines):
---
verified_against: "pom.xml game.version.minor=63"
verified_at: "2026-07-16"
staleness_risk: "high"
stale_checks:
  - "grep:SyxCraft/pom.xml:game.version.minor=63"
  - "class:SyxCraft/src:ReflectionUtil"
  - "version:SyxCraft/src/.../StateManager.java:SAVE_VERSION=2"
---
"""

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ─── Paths ──────────────────────────────────────────────────────────────────

FRAMEWORK_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = FRAMEWORK_ROOT.parent  # Next/
MOD_SRC = PROJECT_ROOT / "SyxCraft" / "src"
POM_XML = PROJECT_ROOT / "SyxCraft" / "pom.xml"

# ─── Data ───────────────────────────────────────────────────────────────────

@dataclass
class StalenessHeader:
    verified_against: str = ""
    verified_at: str = ""
    staleness_risk: str = "low"  # low, medium, high
    stale_checks: List[str] = field(default_factory=list)
    raw_header: str = ""


@dataclass
class CheckResult:
    check: str
    passed: bool
    detail: str


@dataclass
class FileReport:
    file: str
    risk: str
    header: Optional[StalenessHeader]
    checks: List[CheckResult]
    stale: bool
    summary: str

# ─── Header parsing ─────────────────────────────────────────────────────────

def parse_header(file_path: Path) -> Optional[StalenessHeader]:
    """Parse staleness header from first 20 lines of a markdown file."""
    try:
        content = file_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None

    lines = content.split("\n")[:20]
    header = StalenessHeader()

    # Find --- delimited block
    in_block = False
    block_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped == "---":
            if in_block:
                break
            in_block = True
            continue
        if in_block:
            block_lines.append(stripped)

    if not block_lines:
        return None

    header.raw_header = "\n".join(block_lines)

    for line in block_lines:
        if line.startswith("verified_against:"):
            header.verified_against = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("verified_at:"):
            header.verified_at = line.split(":", 1)[1].strip().strip('"\'')
        elif line.startswith("staleness_risk:"):
            header.staleness_risk = line.split(":", 1)[1].strip().strip('"\'').lower()
        elif line.startswith("stale_checks:"):
            continue  # list items follow
        elif line.startswith("- ") and header.stale_checks is not None:
            header.stale_checks.append(line[2:].strip().strip('"\''))

    return header

# ─── Check execution ────────────────────────────────────────────────────────

def _run_grep(pattern: str, file_path: str) -> Tuple[bool, str]:
    """Check if pattern exists in file."""
    target = PROJECT_ROOT / file_path
    if not target.exists():
        return False, f"File not found: {file_path}"
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if pattern in content:
            return True, f"Found '{pattern}' in {file_path}"
        return False, f"NOT FOUND: '{pattern}' in {file_path}"
    except OSError as e:
        return False, f"Error reading {file_path}: {e}"


def _run_class_check(class_name: str, source_dir: str) -> Tuple[bool, str]:
    """Check if a Java class exists in the source tree."""
    target = PROJECT_ROOT / source_dir
    if not target.exists():
        return False, f"Directory not found: {source_dir}"
    for java_file in target.rglob("*.java"):
        try:
            content = java_file.read_text(encoding="utf-8", errors="replace")
            if f"class {class_name}" in content or f"interface {class_name}" in content:
                return True, f"Class '{class_name}' found in {java_file.relative_to(PROJECT_ROOT)}"
        except OSError:
            continue
    return False, f"Class '{class_name}' NOT FOUND in {source_dir}"


def _run_version_check(file_path: str, pattern: str) -> Tuple[bool, str]:
    """Check a version/value pattern in a file (e.g., SAVE_VERSION=2)."""
    target = PROJECT_ROOT / file_path
    if not target.exists():
        return False, f"File not found: {file_path}"
    try:
        content = target.read_text(encoding="utf-8", errors="replace")
        if pattern in content:
            return True, f"Found '{pattern}' in {file_path}"
        return False, f"NOT FOUND: '{pattern}' in {file_path}"
    except OSError as e:
        return False, f"Error reading {file_path}: {e}"


def execute_check(check_str: str) -> CheckResult:
    """Execute a single staleness check.
    
    Formats:
      grep:<file>:<pattern>      — pattern must exist in file
      class:<dir>:<ClassName>    — class must exist in dir
      version:<file>:<pattern>   — version pattern must exist in file
    """
    parts = check_str.split(":", 2)
    if len(parts) < 3:
        return CheckResult(check=check_str, passed=False, detail=f"Invalid check format: {check_str}")

    check_type, target, pattern = parts[0].strip(), parts[1].strip(), parts[2].strip()

    if check_type == "grep":
        passed, detail = _run_grep(pattern, target)
    elif check_type == "class":
        passed, detail = _run_class_check(pattern, target)
    elif check_type == "version":
        passed, detail = _run_version_check(target, pattern)
    else:
        return CheckResult(check=check_str, passed=False, detail=f"Unknown check type: {check_type}")

    return CheckResult(check=check_str, passed=passed, detail=detail)

# ─── File scanning ──────────────────────────────────────────────────────────

def scan_file(file_path: Path) -> FileReport:
    """Scan a single file for staleness."""
    header = parse_header(file_path)
    rel_path = str(file_path.relative_to(FRAMEWORK_ROOT))

    if header is None:
        return FileReport(
            file=rel_path,
            risk="unknown",
            header=None,
            checks=[],
            stale=False,
            summary="No staleness header found",
        )

    checks = []
    for check_str in header.stale_checks:
        checks.append(execute_check(check_str))

    failed = [c for c in checks if not c.passed]
    stale = len(failed) > 0

    if stale:
        summary = f"STALE — {len(failed)}/{len(checks)} checks failed"
    elif checks:
        summary = f"OK — {len(checks)}/{len(checks)} checks passed"
    else:
        summary = f"No checks defined (risk={header.staleness_risk})"

    return FileReport(
        file=rel_path,
        risk=header.staleness_risk,
        header=header,
        checks=checks,
        stale=stale,
        summary=summary,
    )


def find_high_risk_files() -> List[Path]:
    """Find all markdown files with staleness headers in the framework."""
    files = []
    for md_file in sorted(FRAMEWORK_ROOT.rglob("*.md")):
        rel = md_file.relative_to(FRAMEWORK_ROOT)
        # Skip non-knowledge files
        if "knowledge" not in str(rel) and "baseline" not in str(rel).lower():
            # Also check checklists and references
            if "checklists" not in str(rel) and "references" not in str(rel):
                continue
        header = parse_header(md_file)
        if header and header.staleness_risk in ("high", "medium"):
            files.append(md_file)
    return files

# ─── Commands ───────────────────────────────────────────────────────────────

def cmd_scan(as_json: bool = False) -> None:
    """Check all high-risk files."""
    files = find_high_risk_files()
    if not files:
        if as_json:
            print(json.dumps({"stale_files": [], "total": 0, "stale_count": 0}))
        else:
            print("No high-risk files found with staleness headers.")
            print("Run 'staleness_check.py report' to see all files.")
        return

    results = []
    stale_count = 0
    for f in files:
        report = scan_file(f)
        if report.stale:
            stale_count += 1
        results.append({
            "file": report.file,
            "risk": report.risk,
            "stale": report.stale,
            "summary": report.summary,
            "failed_checks": [c.detail for c in report.checks if not c.passed],
        })

    if as_json:
        print(json.dumps({
            "stale_files": [r for r in results if r["stale"]],
            "fresh_files": [r for r in results if not r["stale"]],
            "total": len(results),
            "stale_count": stale_count,
        }, indent=2))
    else:
        print(f"Scanning {len(files)} high-risk files...\n")
        for r in results:
            icon = "🔴" if r["stale"] else "🟢"
            print(f"  {icon} {r['file']}")
            print(f"     {r['summary']}")
            if r["stale"]:
                for detail in r["failed_checks"]:
                    print(f"     ❌ {detail}")
            print()

        print(f"Result: {stale_count}/{len(files)} files stale")
        if stale_count > 0:
            print("⚠️  Stale files will be flagged when loaded as context via /team dispatch.")

    if stale_count > 0:
        sys.exit(1)


def cmd_check(file_path: str) -> None:
    """Check a single file."""
    target = Path(file_path)
    if not target.is_absolute():
        target = FRAMEWORK_ROOT / file_path
    if not target.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    report = scan_file(target)
    print(f"File: {report.file}")
    print(f"Risk: {report.risk}")
    print(f"Status: {report.summary}")
    print()

    if report.header:
        print(f"Verified against: {report.header.verified_against}")
        print(f"Verified at: {report.header.verified_at}")
        print(f"Checks: {len(report.checks)}")
        for c in report.checks:
            icon = "✅" if c.passed else "❌"
            print(f"  {icon} {c.detail}")
    else:
        print("No staleness header found.")


def cmd_report() -> None:
    """Full staleness report for all framework markdown files."""
    all_files = []
    for md_file in sorted(FRAMEWORK_ROOT.rglob("*.md")):
        header = parse_header(md_file)
        if header:
            all_files.append((md_file, header))

    print(f"Staleness Report — {len(all_files)} files with headers\n")
    print(f"{'RISK':<8} {'FILE':<55} {'VERIFIED_AT':<12} {'CHECKS'}")
    print("─" * 90)

    for f, h in sorted(all_files, key=lambda x: {"high": 0, "medium": 1, "low": 2}.get(x[1].staleness_risk, 3)):
        rel = str(f.relative_to(FRAMEWORK_ROOT))
        checks = len(h.stale_checks)
        print(f"{h.staleness_risk:<8} {rel:<55} {h.verified_at:<12} {checks}")

    high = sum(1 for _, h in all_files if h.staleness_risk == "high")
    medium = sum(1 for _, h in all_files if h.staleness_risk == "medium")
    low = sum(1 for _, h in all_files if h.staleness_risk == "low")
    print(f"\nTotal: {high} high, {medium} medium, {low} low")


def cmd_header(file_path: str) -> None:
    """Show parsed header from a file."""
    target = Path(file_path)
    if not target.is_absolute():
        target = FRAMEWORK_ROOT / file_path
    if not target.exists():
        print(f"File not found: {file_path}", file=sys.stderr)
        sys.exit(1)

    header = parse_header(target)
    if header is None:
        print("No staleness header found.")
        return

    print(f"verified_against: {header.verified_against}")
    print(f"verified_at: {header.verified_at}")
    print(f"staleness_risk: {header.staleness_risk}")
    print(f"stale_checks:")
    for c in header.stale_checks:
        print(f"  - {c}")


# ─── CLI ────────────────────────────────────────────────────────────────────

def main(argv: List[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 1

    command = argv[1]
    as_json = "--json" in argv

    if command == "scan":
        cmd_scan(as_json=as_json)
    elif command == "check":
        if len(argv) < 3:
            print("Usage: staleness_check.py check <file>", file=sys.stderr)
            return 1
        cmd_check(argv[2])
    elif command == "report":
        cmd_report()
    elif command == "header":
        if len(argv) < 3:
            print("Usage: staleness_check.py header <file>", file=sys.stderr)
            return 1
        cmd_header(argv[2])
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
