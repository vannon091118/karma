#!/usr/bin/env python3
"""Unit tests for memory_bus.py."""

import importlib
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path


class TestMemoryBus(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix="syxcraft_memory_bus_test_")
        os.environ["LLM_MIDDLEWARE_ROOT"] = self.tmpdir
        from karma.experimental_runtime import memory_bus
        importlib.reload(memory_bus)
        self.memory_bus = memory_bus

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        os.environ.pop("LLM_MIDDLEWARE_ROOT", None)

    def test_ensure_db_creates_file(self):
        # Setting a fact should create the project database file
        self.memory_bus.main(["memory_bus.py", "set", "engine", "package_map", '{"fact":"POP.tot()","source":"POP.java","confidence":"high","verified_by":"source"}'])
        db_path = Path(self.tmpdir) / "projects" / "default.db"
        self.assertTrue(db_path.exists())

    def test_set_and_get_fact(self):
        self.memory_bus.main(["memory_bus.py", "set", "engine", "package_map", '{"fact":"POP.tot()","source":"POP.java","confidence":"high","verified_by":"source"}'])
        
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.memory_bus.main(["memory_bus.py", "get", "engine", "package_map"])
        
        data = json.loads(f.getvalue().strip())
        self.assertEqual(data["fact"], "POP.tot()")

    def test_update_merges_dicts(self):
        self.memory_bus.main(["memory_bus.py", "set", "engine", "package_map", '{"fact":"POP.tot()","source":"POP.java","confidence":"high","verified_by":"source"}'])
        self.memory_bus.main(["memory_bus.py", "update", "engine", "package_map", '{"confidence":"medium","verified_by":"runtime"}'])
        
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.memory_bus.main(["memory_bus.py", "get", "engine", "package_map"])
        
        data = json.loads(f.getvalue().strip())
        self.assertEqual(data["fact"], "POP.tot()")
        self.assertEqual(data["confidence"], "medium")
        self.assertEqual(data["verified_by"], "runtime")

    def test_delete_key(self):
        self.memory_bus.main(["memory_bus.py", "set", "engine", "package_map", '{"fact":"POP.tot()","source":"POP.java","confidence":"high","verified_by":"source"}'])
        self.memory_bus.main(["memory_bus.py", "delete", "engine", "package_map"])
        
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.memory_bus.main(["memory_bus.py", "get", "engine", "package_map"])
        
        self.assertEqual(f.getvalue().strip(), "null")

    def test_delete_domain(self):
        self.memory_bus.main(["memory_bus.py", "set", "engine", "package_map", '{"fact":"POP.tot()","source":"POP.java","confidence":"high","verified_by":"source"}'])
        self.memory_bus.main(["memory_bus.py", "delete", "engine"])
        
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.memory_bus.main(["memory_bus.py", "get", "engine"])
        
        self.assertEqual(f.getvalue().strip(), "{}")

    def test_dynamic_domain(self):
        self.memory_bus.main(["memory_bus.py", "set", "custom_domain", "key", '{"fact":"custom","source":"custom.md","confidence":"low","verified_by":"test"}'])
        
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.memory_bus.main(["memory_bus.py", "get", "custom_domain"])
        
        data = json.loads(f.getvalue().strip())
        self.assertIn("key", data)

    def test_get_missing_key_returns_empty(self):
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.memory_bus.main(["memory_bus.py", "get", "engine", "missing_key"])
        self.assertEqual(f.getvalue().strip(), "null")

    def test_list_shows_domains(self):
        self.memory_bus.main(["memory_bus.py", "set", "runtime", "tick_loop", '{"fact":"tick < 2ms","source":"runtime.md","confidence":"medium","verified_by":"source"}'])
        import io
        from contextlib import redirect_stdout
        f = io.StringIO()
        with redirect_stdout(f):
            self.memory_bus.main(["memory_bus.py", "list"])
        output = f.getvalue()
        self.assertIn("runtime", output)

    def test_missing_verified_by_rejected(self):
        import io
        from contextlib import redirect_stderr
        f = io.StringIO()
        with redirect_stderr(f), self.assertRaises(SystemExit):
            self.memory_bus.main(["memory_bus.py", "set", "engine", "package_map", '{"fact": "x", "source": "y", "confidence": "high"}'])

    def test_invalid_confidence_rejected(self):
        import io
        from contextlib import redirect_stderr
        f = io.StringIO()
        with redirect_stderr(f), self.assertRaises(SystemExit):
            self.memory_bus.main(["memory_bus.py", "set", "engine", "package_map", '{"fact": "x", "source": "y", "confidence": "wrong", "verified_by": "z"}'])


if __name__ == "__main__":
    unittest.main()
