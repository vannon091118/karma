import pytest
from karma.orchestrator import MemoryCore

def test_orchestrator_initialization(tmp_path):
    # Just a basic test to ensure the Orchestrator (L1) can be initialized
    # or that MemoryCore which it heavily relies on works.
    core = MemoryCore(str(tmp_path / "test_proj.db"))
    assert core is not None
