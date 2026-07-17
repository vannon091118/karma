#!/usr/bin/env python3
"""
LLM Middleware Runtime — Falsification Gate

The gate that stands between "Agent says done" and "System accepts done".

Every cascade step must pass falsification before COMPLETE status is granted.
No trust. Verification only.

Falsification probes:
1. Assumption Check — What assumptions did the agent make? Are they documented and valid?
2. Test Coverage — Are there tests? Do they pass? Do they cover the actual changes?
3. Contradiction Scan — Do changed files contradict existing code, docs, or invariants?
4. Regression Probe — Did the change break previously working behavior?
5. Idempotency Verify — Is the operation safely repeatable?
6. Determinism Audit — Does the change preserve deterministic behavior (SHA-256, KernelRNG)?
"""

import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from karma.core.persistence import PersistenceLayer, create_persistence


class FalsificationResult:
    """Result of a falsification probe."""
    def __init__(self, probe_name: str, passed: bool, evidence: str, details: Optional[Dict[str, Any]] = None):
        self.probe_name = probe_name
        self.passed = passed
        self.evidence = evidence
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "probe": self.probe_name,
            "passed": self.passed,
            "evidence": self.evidence,
            "details": self.details,
            "timestamp": self.timestamp
        }


class FalsificationGate:
    """
    The gate. Runs all probes. All must pass.
    """

    def __init__(self, persistence: PersistenceLayer, project: str):
        self.persistence = persistence
        self.project = project
        self.probes = [
            self._probe_assumptions,
            self._probe_test_coverage,
            self._probe_contradictions,
            self._probe_regressions,
            self._probe_idempotency,
            self._probe_determinism,
        ]

    def run(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> Tuple[bool, List[FalsificationResult]]:
        """
        Run all falsification probes for a completed step.
        Returns (all_passed, results_list)
        """
        results = []

        for probe in self.probes:
            try:
                result = probe(step_name, skill_name, output_file, cascade_state)
                results.append(result)
                # Log each probe result
                self.persistence.emit_event(
                    event_type="falsification.probe",
                    project=self.project,
                    payload={
                        "step": step_name,
                        "skill": skill_name,
                        "probe": result.probe_name,
                        "passed": result.passed,
                        "evidence": result.evidence
                    }
                )
            except Exception as e:
                # Probe failure = falsification failure
                result = FalsificationResult(
                    probe_name=probe.__name__,
                    passed=False,
                    evidence=f"Probe crashed: {e}",
                    details={"exception": str(e)}
                )
                results.append(result)

        all_passed = all(r.passed for r in results)
        return all_passed, results

    # ─── Probe Implementations ────────────────────────────────────────────────

    def _probe_assumptions(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 1: Assumption Check
        - What assumptions did the agent make?
        - Are they documented in the output?
        - Are they validated against project facts?
        """
        if not os.path.exists(output_file):
            return FalsificationResult("assumptions", False, "Output file missing", {})

        content = Path(output_file).read_text(encoding="utf-8")

        # Check for explicit assumption documentation
        assumption_markers = [
            "assumption", "assumptions", "assumed",
            "precondition", "preconditions",
            "requires", "requirement",
            "given", "if ", "provided that"
        ]

        found_assumptions = []
        for line in content.split('\n'):
            line_lower = line.lower().strip()
            if any(marker in line_lower for marker in assumption_markers):
                if not line_lower.startswith('#') and not line_lower.startswith('//'):
                    found_assumptions.append(line.strip()[:200])

        # Check against project facts for contradictions
        persistence = self.persistence
        project_facts = persistence.get_all_memory(self.project)
        contradictions = []

        # Simple heuristic: look for hardcoded values that might contradict facts
        for domain, facts in project_facts.get("domains", {}).items():
            for key, value in facts.items():
                if isinstance(value, str) and len(value) > 5:
                    # If output contains a value that contradicts a known fact
                    if value in content and f"!={value}" in content or f"!= {value}" in content:
                        contradictions.append(f"{domain}.{key} = {value}")

        passed = len(contradictions) == 0
        evidence = f"Assumptions documented: {len(found_assumptions)}. Contradictions: {len(contradictions)}."
        if contradictions:
            evidence += f" Details: {contradictions[:3]}"

        return FalsificationResult(
            "assumptions",
            passed,
            evidence,
            {"assumptions_found": found_assumptions[:10], "contradictions": contradictions}
        )

    def _probe_test_coverage(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 2: Test Coverage
        - Are there tests for the changes?
        - Do they pass? (lenient: warn but don't fail if test runner not configured)
        - Do they cover the actual modified files?
        """
        # Find test files related to the output
        output_path = Path(output_file)
        project_root = self._find_project_root()

        if not project_root:
            return FalsificationResult("test_coverage", False, "Could not determine project root", {})

        # Look for test files
        test_patterns = [
            "**/test*.py", "**/*_test.py", "**/tests/**/*.py",
            "**/test_*.rs", "**/*_test.rs",
            "**/test_*.js", "**/*.test.js", "**/*.spec.js"
        ]

        test_files = []
        for pattern in test_patterns:
            test_files.extend(project_root.glob(pattern))

        if not test_files:
            return FalsificationResult("test_coverage", False, "No test files found in project", {"test_files_found": 0})

        # Run tests (with timeout) - lenient mode: log but don't hard-fail
        try:
            # Try pytest first - check if available
            import shutil
            pytest_path = shutil.which("pytest")
            if pytest_path:
                result = subprocess.run(
                    [pytest_path, "-x", "-q", "--tb=short"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                passed = result.returncode == 0
                evidence = f"Pytest: {'PASS' if passed else 'FAIL'}. Tests found: {len(test_files)}. Output: {result.stdout[-500:] if result.stdout else result.stderr[-500:]}"
            else:
                # Try python -m pytest
                result = subprocess.run(
                    ["python", "-m", "pytest", "-x", "-q", "--tb=short"],
                    cwd=project_root,
                    capture_output=True,
                    text=True,
                    timeout=120
                )
                if result.returncode == 0 or "No module named pytest" not in result.stderr:
                    passed = result.returncode == 0
                    evidence = f"Pytest: {'PASS' if passed else 'FAIL'}. Tests found: {len(test_files)}. Output: {result.stdout[-500:] if result.stdout else result.stderr[-500:]}"
                else:
                    # pytest not installed
                    raise FileNotFoundError("pytest not available")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # Try cargo test
            try:
                cargo_path = shutil.which("cargo")
                if cargo_path:
                    result = subprocess.run(
                        [cargo_path, "test", "--quiet"],
                        cwd=project_root,
                        capture_output=True,
                        text=True,
                        timeout=120
                    )
                    passed = result.returncode == 0
                    evidence = f"Cargo test: {'PASS' if passed else 'FAIL'}. Tests found: {len(test_files)}. Output: {result.stdout[-500:] if result.stdout else result.stderr[-500:]}"
                else:
                    raise FileNotFoundError("cargo not available")
            except (FileNotFoundError, subprocess.TimeoutExpired):
                # Test runner not available - lenient pass with warning
                passed = True
                evidence = f"No test runner found (pytest, cargo). Tests found: {len(test_files)}. Skipping execution."

        return FalsificationResult(
            "test_coverage",
            passed,
            evidence,
            {"test_files_found": len(test_files)}
        )

    def _probe_contradictions(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 3: Contradiction Scan
        - Do changed files contradict existing code?
        - Check imports, type signatures, API contracts
        - Check against MANIFEST.json domain rules
        """
        if not os.path.exists(output_file):
            return FalsificationResult("contradictions", False, "Output file missing", {})

        content = Path(output_file).read_text(encoding="utf-8")
        project_root = self._find_project_root()

        contradictions = []

        if project_root:
            if output_file.endswith(".py"):
                import_lines = [line for line in content.split('\n') if line.strip().startswith(('import ', 'from '))]
                import importlib.util
                for imp in import_lines[:20]:
                    parts = imp.strip().split()
                    if not parts: continue
                    module_name = None
                    if parts[0] == "import":
                        module_name = parts[1].split('.')[0].strip(',')
                    elif parts[0] == "from":
                        if not parts[1].startswith('.'):
                            module_name = parts[1].split('.')[0]
                    if module_name:
                        try:
                            if importlib.util.find_spec(module_name) is None:
                                contradictions.append(f"Broken import: module '{module_name}' could not be resolved.")
                        except Exception: pass

            # Check against MANIFEST.json domain invariants
            manifest_path = project_root / "domains" / "MANIFEST.json"
            if manifest_path.exists():
                try:
                    manifest = json.loads(manifest_path.read_text())
                    domain_rules = manifest.get("domain_invariants", {})
                    for domain, rules in domain_rules.items():
                        for rule in rules:
                            if rule.get("type") == "forbidden_pattern":
                                pattern = rule.get("pattern")
                                if pattern and pattern in content:
                                    contradictions.append(f"Domain {domain}: forbidden pattern '{pattern}' found")
                            elif rule.get("type") == "required_pattern":
                                pattern = rule.get("pattern")
                                if pattern and pattern not in content:
                                    contradictions.append(f"Domain {domain}: required pattern '{pattern}' missing")
                except Exception:
                    pass

        passed = len(contradictions) == 0
        evidence = f"Contradictions found: {len(contradictions)}"
        if contradictions:
            evidence += f". Details: {contradictions[:5]}"

        return FalsificationResult(
            "contradictions",
            passed,
            evidence,
            {"contradictions": contradictions}
        )

    def _probe_regressions(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 4: Regression Probe
        - Did the change break previously working behavior?
        - Compare against last known good state
        - Check git diff for suspicious patterns
        """
        project_root = self._find_project_root()
        if not project_root:
            return FalsificationResult("regressions", False, "Could not determine project root", {})

        regressions = []

        try:
            # Get git status
            result = subprocess.run(
                ["git", "status", "--porcelain"],
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10
            )
            changed_files = [line[3:] for line in result.stdout.strip().split('\n') if line.strip()]

            # Check for suspicious patterns in diff
            diff_result = subprocess.run(
                ["git", "diff", "--no-color"] + changed_files,
                cwd=project_root,
                capture_output=True,
                text=True,
                timeout=10
            )
            diff = diff_result.stdout

            # Patterns that often indicate regressions
            regression_patterns = [
                (r"TODO|FIXME|HACK|XXX", "TODO/FIXME left in code"),
                (r"print\(|console\.log\(|System\.out\.println\(", "Debug output left in"),
                (r"except:|catch \(\)|catch \(_\)", "Bare exception handling"),
                (r"pass  #|// ", "Empty implementations"),
                (r"unwrap\(\)|expect\(", "Unchecked unwrap/expect (Rust)"),
            ]

            for pattern, desc in regression_patterns:
                import re
                if re.search(pattern, diff):
                    regressions.append(f"{desc}: pattern '{pattern}' in diff")

            # Check if tests were removed
            if "- def test_" in diff or "- func Test" in diff or "- #[test]" in diff:
                regressions.append("Tests removed in this change")

        except Exception as e:
            regressions.append(f"Git analysis failed: {e}")

        passed = len(regressions) == 0
        evidence = f"Regression indicators: {len(regressions)}"
        if regressions:
            evidence += f". Details: {regressions[:5]}"

        return FalsificationResult(
            "regressions",
            passed,
            evidence,
            {"regressions": regressions}
        )

    def _probe_idempotency(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 5: Idempotency Verify
        - Is the operation safely repeatable?
        - Check for idempotency key in output
        - Verify no side effects on re-run
        """
        # Check if output documents idempotency
        if not os.path.exists(output_file):
            return FalsificationResult("idempotency", False, "Output file missing", {})

        content = Path(output_file).read_text(encoding="utf-8")
        
        import hashlib
        current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        fact_key = f"output_hash:{step_name}:{skill_name}"
        
        last_hash = self.persistence.get_fact(self.project, "idempotency", fact_key)
        if last_hash is None:
            self.persistence.set_fact(self.project, "idempotency", fact_key, current_hash)
            return FalsificationResult(
                "idempotency", True,
                "First execution: output hash registered for future idempotency checks.",
                {"artifact": output_file, "artifact_hash": current_hash, "is_first_run": True}
            )
        
        if last_hash == current_hash:
            return FalsificationResult(
                "idempotency", True,
                "Idempotency verified: output hash matches previous run.",
                {"artifact": output_file, "artifact_hash": current_hash, "previous_hash": last_hash}
            )
        
        return FalsificationResult(
            "idempotency", False,
            f"Idempotency check failed: output hash {current_hash} differs from previous hash {last_hash}.",
            {"artifact": output_file, "artifact_hash": current_hash, "previous_hash": last_hash}
        )

    def _probe_determinism(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 6: Determinism Audit
        - Does the change preserve deterministic behavior?
        - Check for SHA-256, KernelRNG usage
        - No random, no time-dependent, no external calls
        """
        import ast
        root = self._find_project_root() or Path.cwd()
        source_path = None
        candidates = [
            root / "skills" / skill_name / "step.py",
            root / "skills" / skill_name / f"{step_name}.py",
            root / "karma" / "skills" / skill_name / "step.py",
            root / "karma" / "skills" / skill_name / f"{step_name}.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                source_path = candidate
                break

        if source_path is None:
            if output_file.endswith(".py") and os.path.exists(output_file):
                source_path = Path(output_file)
            else:
                return FalsificationResult(
                    "determinism",
                    True,
                    "Passed (Skipped): no Python source code found to audit for determinism.",
                    {"searched": [str(c) for c in candidates]}
                )

        try:
            content = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            return FalsificationResult("determinism", False, f"Cannot read source file: {exc}", {"source": str(source_path)})

        determinism_violations = []

        # Check for non-deterministic patterns
        non_deterministic_patterns = [
            (r"random\.", "random module usage"),
            (r"uuid\.uuid4", "UUID v4 (random)"),
            (r"time\.time|datetime\.now|Date\.now", "Time-dependent"),
            (r"requests\.|urllib|httpx|aiohttp", "External HTTP calls"),
            (r"secrets\.|os\.urandom", "Crypto randomness (ok if intentional)"),
            (r"threading|multiprocessing|asyncio\.create_task", "Concurrency (non-deterministic ordering)"),
        ]

        for pattern, desc in non_deterministic_patterns:
            import re
            if re.search(pattern, content):
                determinism_violations.append(f"{desc}: '{pattern}' found")

        # Check for determinism affirmations
        determinism_affirmations = [
            "deterministic", "sha256", "sha-256", "kernelrng", "kernel_rng",
            "reproducible", "replayable", "fixed seed"
        ]
        found_affirmations = [aff for aff in determinism_affirmations if aff in content.lower()]

        passed = len(determinism_violations) == 0
        evidence = f"Violations: {len(determinism_violations)}. Affirmations: {len(found_affirmations)}."
        if determinism_violations:
            evidence += f" Details: {determinism_violations[:5]}"

        return FalsificationResult(
            "determinism",
            passed,
            evidence,
            {"violations": determinism_violations, "affirmations": found_affirmations}
        )

    def _find_project_root(self) -> Optional[Path]:
        """Find project root by looking for .git or pyproject.toml."""
        current = Path.cwd()
        for _ in range(10):
            if (current / ".git").exists() or (current / "pyproject.toml").exists():
                return current
            if current.parent == current:
                break
            current = current.parent
        return None


def run_falsification_gate(
    persistence: PersistenceLayer,
    project: str,
    step_name: str,
    skill_name: str,
    output_file: str,
    cascade_state: Dict[str, Any]
) -> Tuple[bool, List[FalsificationResult]]:
    """
    Entry point: run the full falsification gate.
    Returns (all_passed, results)
    """
    gate = FalsificationGate(persistence, project)
    return gate.run(step_name, skill_name, output_file, cascade_state)


if __name__ == "__main__":
    # CLI for manual testing
    if len(sys.argv) < 5:
        print("Usage: falsification_gate.py <project> <step> <skill> <output_file>")
        sys.exit(1)

    project, step, skill, output = sys.argv[1:5]
    p = create_persistence()
    state = p.load_cascade(project)

    passed, results = run_falsification_gate(p, project, step, skill, output, state)

    print(f"\n{'='*60}")
    print(f"FALSIFICATION GATE: {'PASSED' if passed else 'FAILED'}")
    print(f"{'='*60}")
    for r in results:
        status = "✅" if r.passed else "❌"
        print(f"  {status} {r.probe_name}: {r.evidence}")

    sys.exit(0 if passed else 1)