"""Regression tests for NBB nightly backload bootstrap logic."""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import types
import unittest


ROOT = os.path.join(os.path.dirname(__file__), "..")
TARGET = os.path.join(ROOT, "scripts", "nbb_nightly_backload.py")


def _load_backload_module():
    stub_names = (
        "psycopg2",
        "psycopg2.extras",
        "requests",
        "db",
        "nbb_governance",
        "nbb_nightly_backload",
    )
    missing = object()
    originals = {name: sys.modules.get(name, missing) for name in stub_names}

    psycopg2 = types.ModuleType("psycopg2")
    psycopg2_extras = types.ModuleType("psycopg2.extras")
    psycopg2.extras = psycopg2_extras
    sys.modules["psycopg2"] = psycopg2
    sys.modules["psycopg2.extras"] = psycopg2_extras

    requests = types.ModuleType("requests")
    requests.Session = object
    sys.modules["requests"] = requests

    db = types.ModuleType("db")
    db.get_connection = lambda: None
    db.put_connection = lambda _conn: None
    db.fetch_one = lambda *_args, **_kwargs: None
    db.fetch_all = lambda *_args, **_kwargs: []
    db.execute = lambda *_args, **_kwargs: None
    sys.modules["db"] = db

    nbb_governance = types.ModuleType("nbb_governance")
    nbb_governance.store_governance_snapshot = lambda *_args, **_kwargs: {}
    sys.modules["nbb_governance"] = nbb_governance

    spec = importlib.util.spec_from_file_location("nbb_nightly_backload", TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["nbb_nightly_backload"] = module
    assert spec.loader is not None
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        for name, original in originals.items():
            if original is missing:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


class NbbNightlyBackloadBootstrapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_backload_module()

    def test_bootstrap_prefers_backend_directory_in_repo_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = os.path.join(tmp, "scripts")
            backend_dir = os.path.join(tmp, "backend")
            os.makedirs(scripts_dir)
            os.makedirs(backend_dir)
            open(os.path.join(backend_dir, "db.py"), "w", encoding="utf-8").close()
            script_path = os.path.join(scripts_dir, "nbb_nightly_backload.py")
            open(script_path, "w", encoding="utf-8").close()

            chosen = self.module._bootstrap_backend_path(script_path)

            self.assertEqual(chosen, [backend_dir])

    def test_bootstrap_falls_back_to_repo_root_in_container_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = os.path.join(tmp, "scripts")
            os.makedirs(scripts_dir)
            open(os.path.join(tmp, "db.py"), "w", encoding="utf-8").close()
            script_path = os.path.join(scripts_dir, "nbb_nightly_backload.py")
            open(script_path, "w", encoding="utf-8").close()

            chosen = self.module._bootstrap_backend_path(script_path)

            self.assertEqual(chosen, [tmp])

    def test_bootstrap_raises_when_backend_modules_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            scripts_dir = os.path.join(tmp, "scripts")
            os.makedirs(scripts_dir)
            script_path = os.path.join(scripts_dir, "nbb_nightly_backload.py")
            open(script_path, "w", encoding="utf-8").close()

            with self.assertRaises(RuntimeError):
                self.module._bootstrap_backend_path(script_path)


if __name__ == "__main__":
    unittest.main()
