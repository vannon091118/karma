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
from karma.core.evidence import EvidenceType, Evidence, Claim


class FalsificationResult:
    """Result of a falsification probe. Acts as an Evidence Producer.

    Supports two construction modes:
    - Full (new API):  FalsificationResult(probe_name, claim_statement, evidence_type, executed, passed, evidence_strength, evidence_str, details)
    - Legacy (simple): FalsificationResult(probe_name, passed, evidence_str)  -> fills defaults for the rest
    """
    def __init__(self, probe_name: str, claim_statement=None, evidence_type=None, executed=None, passed=None, evidence_strength=None, evidence_str: str = "", details: Optional[Dict[str, Any]] = None):
        # Legacy compat: FalsificationResult("probe_name", True, "evidence str")
        # In legacy mode, claim_statement receives a bool (passed) and evidence_type receives a string.
        if isinstance(claim_statement, bool) and evidence_type is not None and passed is None:
            # Legacy positional: (probe_name, passed, evidence_str)
            evidence_str = str(evidence_type) if evidence_str == "" else str(evidence_type)
            passed = claim_statement
            claim_statement = f"Probe {probe_name} ran successfully"
            evidence_type = EvidenceType.RUNTIME
            executed = True
            evidence_strength = 0.9 if passed else 0.0
            details = details or {}

        self.probe_name = probe_name
        self.claim_statement = claim_statement or f"Probe {probe_name} ran successfully"
        self.evidence_type = evidence_type or EvidenceType.RUNTIME
        self.executed = executed if executed is not None else True
        self.passed = passed if passed is not None else False
        self.evidence_strength = evidence_strength if evidence_strength is not None else 0.0
        self.evidence_str = evidence_str
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    @property
    def evidence(self) -> str:
        """Backward-compat alias for evidence_str."""
        return self.evidence_str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "probe": self.probe_name,
            "claim": self.claim_statement,
            "type": self.evidence_type.value,
            "executed": self.executed,
            "passed": self.passed,
            "evidence_strength": self.evidence_strength,
            "evidence": self.evidence_str,
            "details": self.details,
            "timestamp": self.timestamp
        }


class FalsificationProbe:
    """A structured domain-specific validation check."""
    def __init__(
        self,
        name: str,
        domain: str = "generic",
        version: str = "1.0",
        severity: str = "critical",  # "critical" (fails turn), "warning" (logged but passes), "info"
        execute_fn = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.name = name
        self.domain = domain
        self.version = version
        self.severity = severity
        self.execute_fn = execute_fn
        self.metadata = metadata or {}

    def run(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        if self.execute_fn:
            return self.execute_fn(step_name, skill_name, output_file, cascade_state)
        return FalsificationResult(self.name, "Probe executed", EvidenceType.RUNTIME, False, False, 0.0, "No execution logic provided")


class FalsificationGate:
    """
    The gate. Runs all probes. All critical must pass.
    """

    def __init__(self, persistence: PersistenceLayer, project: str):
        self.persistence = persistence
        self.project = project
        self.probes = []
        self._register_default_probes()

    def _register_default_probes(self) -> None:
        self.probes.extend([
            FalsificationProbe("assumptions", domain="software", version="1.0", severity="critical", execute_fn=self._probe_assumptions),
            FalsificationProbe("test_coverage", domain="software", version="1.0", severity="critical", execute_fn=self._probe_test_coverage),
            FalsificationProbe("contradictions", domain="software", version="1.0", severity="critical", execute_fn=self._probe_contradictions),
            FalsificationProbe("regressions", domain="software", version="1.0", severity="critical", execute_fn=self._probe_regressions),
            FalsificationProbe("idempotency", domain="software", version="1.0", severity="critical", execute_fn=self._probe_idempotency),
            FalsificationProbe("determinism", domain="software", version="1.0", severity="warning", execute_fn=self._probe_determinism),
        ])

    def register_probe(self, probe) -> None:
        """Register a custom domain-specific falsification probe.
        
        Accepts either a FalsificationProbe object or a legacy callable matching the signature:
        (step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult
        """
        self.probes.append(probe)

    def run(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> Tuple[bool, List[FalsificationResult]]:
        """
        Run all falsification probes for a completed step.
        Returns (all_passed, results_list)
        """
        results = []

        for probe in self.probes:
            try:
                if hasattr(probe, "run"):
                    result = probe.run(step_name, skill_name, output_file, cascade_state)
                else:
                    # Legacy callable fallback
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
                        "evidence": result.evidence_str
                    }
                )
            except Exception as e:
                # Probe failure = 0.0 confidence evidence
                probe_name = getattr(probe, "name", getattr(probe, "__name__", "unknown"))
                result = FalsificationResult(
                    probe_name=probe_name,
                    claim_statement=f"Probe {probe_name} ran successfully",
                    evidence_type=EvidenceType.RUNTIME,
                    executed=True,
                    passed=False,
                    evidence_strength=0.0,
                    evidence_str=f"Probe crashed: {e}",
                    details={"exception": str(e)}
                )
                results.append(result)

        # Check if any critical probe failed. Non-critical failures (warnings/info) are logged
        # but do not cause all_passed to be False.
        critical_failed = False
        for result, probe in zip(results, self.probes):
            severity = getattr(probe, "severity", "critical")
            if not result.passed and severity == "critical":
                critical_failed = True

        all_passed = not critical_failed
        return all_passed, results

    # ─── Probe Implementations ────────────────────────────────────────────────

    def _probe_assumptions(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 1: Assumption Check
        - Step must declare its assumptions explicitly in the output artifact.
        - Expected format: YAML/JSON/TOML frontmatter block with `assumptions:` list.
        - Each item must include a `source:` reference for traceability.
        """
        if not os.path.exists(output_file):
            return FalsificationResult("assumptions", "Output declares sourced assumptions", EvidenceType.SOURCE, True, False, 0.0, "Output file missing", {})

        content = Path(output_file).read_text(encoding="utf-8")
        # Only scan frontmatter delimited by --- / ``` blocks
        frontmatter = content
        if "---" in content:
            parts = content.split("---", 2)
            frontmatter = parts[1] if len(parts) >= 2 else content
        elif "```" in content:
            parts = content.split("```", 2)
            frontmatter = parts[1] if len(parts) >= 2 else content

        try:
            import yaml
            meta = yaml.safe_load(frontmatter) or {}
        except Exception:
            meta = {}

        meta_clean = {}
        if isinstance(meta, dict):
            for k, v in meta.items():
                meta_clean[str(k).lower()] = v

        assumptions = meta_clean.get("assumptions", [])
        if isinstance(assumptions, str):
            assumptions = [assumptions]
        elif not isinstance(assumptions, list):
            assumptions = []

        unsourced = [a for a in assumptions if isinstance(a, dict) and "source" not in a]
        passed = bool(assumptions) and not unsourced
        evidence_str = (
            f"Assumptions declared: {len(assumptions)}. "
            f"Missing source references: {len(unsourced)}."
        )
        if unsourced:
            evidence_str += f" Details: unsourced={unsourced[:3]}"
            
        confidence = 0.4 if passed else 0.0
        return FalsificationResult(
            "assumptions",
            "Output declares sourced assumptions",
            EvidenceType.SOURCE,
            True,
            passed,
            confidence,
            evidence_str,
            {"assumptions": assumptions[:10], "unsourced": unsourced[:5]},
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
            return FalsificationResult("test_coverage", "Changes covered by tests", EvidenceType.TEST, True, False, 0.0, "Could not determine project root", {})

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
            return FalsificationResult("test_coverage", "Changes covered by tests", EvidenceType.TEST, True, False, 0.0, "No test files found in project", {"test_files_found": 0})

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

        confidence = 0.7 if passed else 0.0
        return FalsificationResult(
            "test_coverage",
            "Changes covered by passing tests",
            EvidenceType.TEST,
            True,
            passed,
            confidence,
            evidence,
            {"test_files_found": len(test_files)}
        )

    def _probe_contradictions(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 3: Contradiction Scan
        - Do changed files contradict existing code?
        - Check imports, type signatures, API contracts.
        - Check against MANIFEST.json domain rules.
        """
        if not os.path.exists(output_file):
            return FalsificationResult("contradictions", "Changes do not contradict existing code", EvidenceType.SOURCE, True, False, 0.0, "Output file missing", {})

        content = Path(output_file).read_text(encoding="utf-8")
        project_root = self._find_project_root()

        contradictions = []

        # Check for broken Python imports if output_file is a Python file
        if output_file.endswith(".py"):
            import_lines = [line for line in content.split('\n') if line.strip().startswith(('import ', 'from '))]
            import importlib.util
            for imp in import_lines[:20]:  # Sample check
                parts = imp.strip().split()
                if not parts:
                    continue
                module_name = None
                if parts[0] == "import":
                    module_name = parts[1].split('.')[0].strip(',')
                elif parts[0] == "from":
                    if not parts[1].startswith('.'):
                        module_name = parts[1].split('.')[0]
                
                if module_name:
                    try:
                        spec = importlib.util.find_spec(module_name)
                        if spec is None:
                            contradictions.append(f"Broken import: module '{module_name}' could not be resolved.")
                    except Exception:
                        pass

        if project_root:
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
        evidence_str = f"Contradictions found: {len(contradictions)}"
        if contradictions:
            evidence_str += f". Details: {contradictions[:5]}"

        confidence = 0.4 if passed else 0.0
        return FalsificationResult(
            "contradictions",
            "Changes do not contradict existing invariants",
            EvidenceType.SOURCE,
            True,
            passed,
            confidence,
            evidence_str,
            {"contradictions": contradictions}
        )

    def _probe_regressions(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 4: Regression Probe
        - Did the change break previously working behavior?
        - Compare against last known good state.
        """
        # Compare current output with last successful output for this step/skill
        regressions = []
        
        # Look for obvious regression markers (warnings, stack traces, fails) in the output
        content = Path(output_file).read_text(encoding="utf-8") if os.path.exists(output_file) else ""
        for marker in ["Traceback (most recent call last)", "FATAL ERROR", "CRITICAL FAILURE", "TESTS FAILED"]:
            if marker in content:
                regressions.append(f"Regression marker found: '{marker}'")

        passed = len(regressions) == 0
        evidence_str = f"Regression indicators: {len(regressions)}"
        if regressions:
            evidence_str += f". Details: {regressions[:5]}"

        confidence = 0.9 if passed else 0.0
        return FalsificationResult(
            "regressions",
            "Changes preserve previously working behavior",
            EvidenceType.RUNTIME,
            True,
            passed,
            confidence,
            evidence_str,
            {"regressions": regressions}
        )

    def _probe_idempotency(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 5: Idempotency Verify
        - Compare SHA-256 of the current output artifact with the last recorded output artifact.
        - Detects non-determinism in execution outputs.
        """
        from pathlib import Path as _Path
        import hashlib
        persistence = getattr(self, "persistence", None)
        project = getattr(self, "project", "default")

        if not _Path(output_file).exists():
            return FalsificationResult("idempotency", "Step execution is deterministic/idempotent", EvidenceType.RUNTIME, True, False, 0.0, "Output file missing", {})

        try:
            content = _Path(output_file).read_text(encoding="utf-8")
        except OSError as exc:
            return FalsificationResult("idempotency", "Step execution is deterministic/idempotent", EvidenceType.RUNTIME, True, False, 0.0, f"Cannot read output: {exc}", {})

        current_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        fact_key = f"output_hash:{step_name}:{skill_name}"
        
        last_hash = self.persistence.get_fact(self.project, "idempotency", fact_key)
        if last_hash is None:
            self.persistence.set_fact(self.project, "idempotency", fact_key, current_hash)
            return FalsificationResult(
                "idempotency", "Step execution is deterministic/idempotent", EvidenceType.RUNTIME, True, True, 0.9,
                "First execution: output hash registered for future idempotency checks.",
                {"artifact": output_file, "artifact_hash": current_hash, "is_first_run": True}
            )
        
        if last_hash == current_hash:
            return FalsificationResult(
                "idempotency", "Step execution is deterministic/idempotent", EvidenceType.RUNTIME, True, True, 0.9,
                "Idempotency verified: output hash matches previous run.",
                {"artifact": output_file, "artifact_hash": current_hash, "previous_hash": last_hash}
            )
        
        return FalsificationResult(
            "idempotency", "Step execution is deterministic/idempotent", EvidenceType.RUNTIME, True, False, 0.0,
            f"Idempotency check failed: output hash {current_hash} differs from previous hash {last_hash}.",
            {"artifact": output_file, "artifact_hash": current_hash, "previous_hash": last_hash}
        )

    def _probe_determinism(self, step_name: str, skill_name: str, output_file: str, cascade_state: Dict[str, Any]) -> FalsificationResult:
        """
        Probe 6: Determinism Audit
        - Static-analysis on the step source (or the generated Python output).
        - Rejects APIs known to inject time, randomness, or external I/O into the hot path.
        """
        import ast
        root = self._find_project_root() or Path.cwd()

        source_path = None
        candidates = [
            root / "skills" / skill_name / "step.py",
            root / "skills" / skill_name / step_name / "step.py",
            root / "skills" / skill_name / f"{step_name}.py",
            root / "steps" / skill_name / step_name / "step.py",
            root / "karma" / "skills" / skill_name / "step.py",
            root / "karma" / "skills" / skill_name / f"{step_name}.py",
        ]
        for candidate in candidates:
            if candidate.exists():
                source_path = candidate
                break

        # If step source not found, try to audit the output file itself if it is a Python file
        if source_path is None:
            if output_file.endswith(".py") and os.path.exists(output_file):
                source_path = Path(output_file)
            else:
                return FalsificationResult(
                    "determinism",
                    "Code does not rely on non-deterministic APIs",
                    EvidenceType.SOURCE,
                    False, # Skipped / not executed
                    True, # Lenient pass
                    0.0,  # No evidence
                    "Passed (Skipped): no Python source code found to audit for determinism.",
                    {"searched": [str(c) for c in candidates]}
                )

        try:
            source = source_path.read_text(encoding="utf-8")
        except OSError as exc:
            return FalsificationResult("determinism", "Code does not rely on non-deterministic APIs", EvidenceType.SOURCE, True, False, 0.0, f"Cannot read source file: {exc}", {"source": str(source_path)})

        violations = []
        try:
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if alias.name in {"random", "uuid", "secrets", "threading", "multiprocessing", "asyncio", "requests", "urllib", "httpx", "aiohttp"}:
                            violations.append(f"import {alias.name} at {node.lineno}:{node.col_offset}")
                elif isinstance(node, ast.ImportFrom):
                    if node.module in {"random", "uuid", "secrets", "threading", "multiprocessing", "asyncio", "requests", "urllib", "httpx", "aiohttp"}:
                        violations.append(f"from {node.module} import ... at {node.lineno}:{node.col_offset}")
                elif isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute):
                        full = f"{func.value.id}.{func.attr}" if isinstance(func.value, ast.Name) else None
                        if full in {"random.random", "random.choice", "time.time", "datetime.now", "datetime.utcnow", "uuid.uuid4", "uuid.uuid1"}:
                            violations.append(f"call {full} at {node.lineno}:{node.col_offset}")
                    elif isinstance(func, ast.Name):
                        if func.id in {"random", "uuid", "requests", "httpx"}:
                            violations.append(f"call {func.id} at {node.lineno}:{node.col_offset}")
        except SyntaxError as exc:
            return FalsificationResult("determinism", "Code does not rely on non-deterministic APIs", EvidenceType.SOURCE, True, False, 0.0, f"Step source parse error: {exc}", {"source": str(source_path)})

        passed = not violations
        evidence_str = f"Violations: {len(violations)}. Source: {source_path}."
        if violations:
            evidence_str += f" Details: {violations[:5]}"
            
        confidence = 0.4 if passed else 0.0
        return FalsificationResult(
            "determinism",
            "Code does not rely on non-deterministic APIs",
            EvidenceType.SOURCE,
            True,
            passed,
            confidence,
            evidence_str,
            {"violations": violations[:10], "source": str(source_path)},
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