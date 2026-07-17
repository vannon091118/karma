"""Meta-test: the falsification gate must be able to FAIL (P0-5).

A gate that always passes is worthless. This proves the gate detects a
falsifiable condition (missing output artifact) and returns not-passed.
"""

import tempfile
from pathlib import Path

from karma.core.persistence import PersistenceConfig, PersistenceLayer
from karma.core.falsification_gate import run_falsification_gate


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


def test_custom_probe_registration():
    """Verify that a custom domain probe can be registered and run."""
    from karma.core.falsification_gate import FalsificationGate, FalsificationResult
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = _persistence(tmp)
        gate = FalsificationGate(p, "proj")
        
        # Define a custom research-domain probe
        def _research_source_check(step_name, skill_name, output_file, cascade_state):
            return FalsificationResult("research_sources", True, "All sources verified against academic index")
            
        gate.register_probe(_research_source_check)
        
        artifact = tmp / "research.md"
        artifact.write_text("Academic paper draft")
        
        # We run the gate manually to verify our custom probe ran
        all_passed, results = gate.run("execute", "research", str(artifact), {"steps": []})
        
        # The custom probe is run last
        custom_probe_results = [r for r in results if r.probe_name == "research_sources"]
        assert len(custom_probe_results) == 1
        assert custom_probe_results[0].passed is True
        assert custom_probe_results[0].evidence == "All sources verified against academic index"


def test_structured_probe_registration():
    """Verify that a FalsificationProbe object can be registered and run."""
    from karma.core.falsification_gate import FalsificationGate, FalsificationProbe, FalsificationResult
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = _persistence(tmp)
        gate = FalsificationGate(p, "proj")
        
        def _check_sources(step_name, skill_name, output_file, cascade_state):
            return FalsificationResult("academic_sources", True, "Sources look valid")
            
        probe = FalsificationProbe(
            name="academic_sources",
            domain="research",
            version="1.2",
            severity="critical",
            execute_fn=_check_sources
        )
        
        gate.register_probe(probe)
        
        artifact = tmp / "academic.md"
        artifact.write_text("Academic paper draft")
        
        all_passed, results = gate.run("execute", "research", str(artifact), {"steps": []})
        
        custom_probe_results = [r for r in results if r.probe_name == "academic_sources"]
        assert len(custom_probe_results) == 1
        assert custom_probe_results[0].passed is True


def test_warning_severity_does_not_fail_gate():
    """Verify that a failing probe with severity='warning' does not fail the gate."""
    from karma.core.falsification_gate import FalsificationGate, FalsificationProbe, FalsificationResult
    
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        p = _persistence(tmp)
        
        # We construct a gate, but mock the default probes to prevent their failures
        gate = FalsificationGate(p, "proj")
        # Clear default critical probes for clean test isolation
        gate.probes = []
        
        def _check_style(step_name, skill_name, output_file, cascade_state):
            return FalsificationResult("style_warning", False, "Style violates recommendation X")
            
        warning_probe = FalsificationProbe(
            name="style_warning",
            domain="generic",
            version="1.0",
            severity="warning",
            execute_fn=_check_style
        )
        
        gate.register_probe(warning_probe)
        
        artifact = tmp / "style.md"
        artifact.write_text("Style check file")
        
        all_passed, results = gate.run("execute", "style", str(artifact), {"steps": []})
        
        # The probe itself returned passed=False
        probe_result = [r for r in results if r.probe_name == "style_warning"][0]
        assert probe_result.passed is False
        
        # But because the severity was "warning", the entire gate run still reports all_passed=True!
        assert all_passed is True
