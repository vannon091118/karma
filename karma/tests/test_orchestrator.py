import pytest
from karma.core.persistence import PersistenceLayer, PersistenceConfig
from pathlib import Path

def test_orchestrator_initialization(tmp_path):
    # Just a basic test to ensure the PersistenceLayer works.
    config = PersistenceConfig(framework_dir=Path(tmp_path))
    core = PersistenceLayer(config)
    assert core is not None
