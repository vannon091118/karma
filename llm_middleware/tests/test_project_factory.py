"""Tests for the project-scoped persistence factory (DRY consolidation)."""

from pathlib import Path

from llm_middleware.core.persistence import create_project_persistence, PersistenceLayer


def test_factory_returns_project_scoped_db_path():
    """Factory must point each project at its own DB file under projects/."""
    p = create_project_persistence("alpha")
    assert isinstance(p, PersistenceLayer)
    assert p.config.db_path.name == "alpha.db"
    assert p.config.db_path.parent.name == "projects"


def test_factory_isolates_projects():
    """Two projects must resolve to distinct DB files."""
    a = create_project_persistence("iso_a")
    b = create_project_persistence("iso_b")
    assert a.config.db_path != b.config.db_path
