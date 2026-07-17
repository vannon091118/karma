"""Unit tests for knowledge_graph.py."""

import os
import shutil
import tempfile
import unittest
from pathlib import Path

from llm_middleware.core.persistence import PersistenceConfig, PersistenceLayer
from llm_middleware.core.knowledge_graph import KnowledgeGraph, NodeTypes, RelationTypes


class TestKnowledgeGraph(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="llm_mw_kg_test_")
        self.config = PersistenceConfig(
            framework_dir=Path(self.tmpdir) / "db",
            db_filename="mw.db"
        )
        self.persistence = PersistenceLayer(self.config)
        self.persistence.create_project("test_proj")
        self.kg = KnowledgeGraph(self.persistence, "test_proj")

    def tearDown(self):
        self.persistence.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_add_and_get_relations(self):
        # Add repository -> module
        self.kg.add_relation(
            source_type=NodeTypes.REPOSITORY,
            source_id="my_repo",
            relation_type=RelationTypes.CONTAINS,
            target_type=NodeTypes.MODULE,
            target_id="core_module",
            metadata={"description": "Main core logic module"}
        )

        # Add module -> file
        self.kg.add_relation(
            source_type=NodeTypes.MODULE,
            source_id="core_module",
            relation_type=RelationTypes.CONTAINS,
            target_type=NodeTypes.FILE,
            target_id="persistence.py"
        )

        # Query outgoing from repository
        outgoing = self.kg.get_outgoing("my_repo", NodeTypes.REPOSITORY)
        self.assertEqual(len(outgoing), 1)
        self.assertEqual(outgoing[0]["target_id"], "core_module")
        self.assertEqual(outgoing[0]["metadata"]["description"], "Main core logic module")

        # Query incoming to core_module
        incoming = self.kg.get_incoming("core_module", NodeTypes.MODULE)
        self.assertEqual(len(incoming), 1)
        self.assertEqual(incoming[0]["source_id"], "my_repo")

    def test_delete_relation(self):
        self.kg.add_relation(
            source_type=NodeTypes.FILE,
            source_id="persistence.py",
            relation_type=RelationTypes.DEPENDS_ON,
            target_type=NodeTypes.FILE,
            target_id="memory.py"
        )

        outgoing_before = self.kg.get_outgoing("persistence.py", NodeTypes.FILE)
        self.assertEqual(len(outgoing_before), 1)

        deleted = self.kg.delete_relation(
            source_type=NodeTypes.FILE,
            source_id="persistence.py",
            relation_type=RelationTypes.DEPENDS_ON,
            target_type=NodeTypes.FILE,
            target_id="memory.py"
        )
        self.assertTrue(deleted)

        outgoing_after = self.kg.get_outgoing("persistence.py", NodeTypes.FILE)
        self.assertEqual(len(outgoing_after), 0)

    def test_traverse_graph(self):
        # Setup path: Repo -> Module -> File -> Class
        self.kg.add_relation(NodeTypes.REPOSITORY, "repo1", RelationTypes.CONTAINS, NodeTypes.MODULE, "mod1")
        self.kg.add_relation(NodeTypes.MODULE, "mod1", RelationTypes.CONTAINS, NodeTypes.FILE, "file1.py")
        self.kg.add_relation(NodeTypes.FILE, "file1.py", RelationTypes.CONTAINS, NodeTypes.CLASS, "MyClass")

        subgraph = self.kg.traverse("repo1", max_depth=3)
        self.assertIn("repo1", subgraph["nodes"])
        
        edges = subgraph["edges"]
        self.assertEqual(len(edges), 3)
        
        sources = {e["source"] for e in edges}
        self.assertEqual(sources, {"repo1", "mod1", "file1.py"})

        targets = {e["target"] for e in edges}
        self.assertEqual(targets, {"mod1", "file1.py", "MyClass"})


if __name__ == "__main__":
    unittest.main()
