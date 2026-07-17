"""Meta-test: the falsification gate must be able to FAIL (P0-5).

A gate that always passes is worthless. This proves the gate detects a
falsifiable condition (missing output artifact) and returns not-passed.
"""

import tempfile
from pathlib import Path

from llm_middleware.core.persistence import PersistenceConfig, PersistenceLayer
from llm_middleware.core.falsification_gate import run_falsification_gate


def _persistence(tmp: Path) -> PersistenceLayer:
    config = PersistenceConfig(framework_dir=tmp / "db", db_filename="mw.db")
    p = PersistenceLayer(config)
    p.create_project("proj")
    return p


def test_gate_fails_when_output_artifact_missing():
    """Gate must return all_passed=False when the step's output file is absent."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = _persistence(tmp)
        missing = str(tmp / "does_not_exist.md")

        all_passed, results = run_falsification_gate(
            p, "proj", "execute", "execution", missing, {"steps": []}
        )

        assert all_passed is False, "gate wrongly passed with missing output artifact"
        assert any(not r.passed for r in results), "no probe reported a failure"


def test_gate_passes_when_artifact_present_and_documented():
    """Sanity counterpart: a well-formed artifact should NOT be failed by the
    assumptions probe (proves the gate is not a constant-False stub)."""
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = _persistence(tmp)
        artifact = tmp / "out.md"
        artifact.write_text(
            "# Result\n\n"
            "Assumptions: none contradicting project facts.\n"
            "Tests: added coverage for new behavior.\n"
            "Deterministic: uses KernelRNG seed.\n"
        )

        _, results = run_falsification_gate(
            p, "proj", "execute", "execution", str(artifact), {"steps": []}
        )
        assumptions = [r for r in results if r.probe_name == "assumptions"]
        assert assumptions and assumptions[0].passed, "assumptions probe failed on valid artifact"
