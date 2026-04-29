"""Regression tests for profile-loader reference normalization."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
import types
import unittest


ROOT = os.path.join(os.path.dirname(__file__), "..")
TARGET = os.path.join(ROOT, "backend", "routers", "companies", "financials.py")


class FakeBackgroundTasks:
    def __init__(self):
        self.tasks = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


def _load_financials_module():
    """Import the router module with tiny stubs for its heavy dependencies."""
    stub_names = (
        "fastapi",
        "httpx",
        "psycopg2",
        "psycopg2.extras",
        "db",
        "auth",
        "utils",
        "nbb_governance",
        "routers",
        "routers.companies",
        "routers.companies._helpers",
        "routers.companies.financials",
    )
    missing = object()
    originals = {name: sys.modules.get(name, missing) for name in stub_names}

    fastapi = types.ModuleType("fastapi")

    class DummyRouter:
        def post(self, *_args, **_kwargs):
            return lambda fn: fn

        def get(self, *_args, **_kwargs):
            return lambda fn: fn

    class DummyHttpException(Exception):
        def __init__(self, status_code: int, detail: str):
            super().__init__(detail)
            self.status_code = status_code
            self.detail = detail

    fastapi.APIRouter = lambda: DummyRouter()
    fastapi.BackgroundTasks = object
    fastapi.Depends = lambda dep: dep
    fastapi.HTTPException = DummyHttpException
    fastapi.Query = lambda default=None, **_kwargs: default
    fastapi.Response = object
    sys.modules["fastapi"] = fastapi

    httpx = types.ModuleType("httpx")
    httpx.AsyncClient = object
    httpx.RequestError = Exception
    sys.modules["httpx"] = httpx

    psycopg2 = types.ModuleType("psycopg2")
    psycopg2_extras = types.ModuleType("psycopg2.extras")
    psycopg2.extras = psycopg2_extras
    sys.modules["psycopg2"] = psycopg2
    sys.modules["psycopg2.extras"] = psycopg2_extras

    db = types.ModuleType("db")
    db.fetch_all = lambda *_args, **_kwargs: []
    db.fetch_one = lambda *_args, **_kwargs: None
    db.get_connection = lambda: None
    db.put_connection = lambda _conn: None
    sys.modules["db"] = db

    auth = types.ModuleType("auth")
    auth.optional_user = lambda: None
    sys.modules["auth"] = auth

    utils = types.ModuleType("utils")
    utils.clean_cbe = lambda value: value
    sys.modules["utils"] = utils

    nbb_governance = types.ModuleType("nbb_governance")
    nbb_governance.store_governance_snapshot = lambda *_args, **_kwargs: {}
    sys.modules["nbb_governance"] = nbb_governance

    routers_pkg = types.ModuleType("routers")
    routers_pkg.__path__ = []  # mark as package
    companies_pkg = types.ModuleType("routers.companies")
    companies_pkg.__path__ = []
    helpers_mod = types.ModuleType("routers.companies._helpers")
    helpers_mod._serialize_row = lambda row: row
    sys.modules["routers"] = routers_pkg
    sys.modules["routers.companies"] = companies_pkg
    sys.modules["routers.companies._helpers"] = helpers_mod

    spec = importlib.util.spec_from_file_location("routers.companies.financials", TARGET)
    module = importlib.util.module_from_spec(spec)
    sys.modules["routers.companies.financials"] = module
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


class FinancialReferenceNormalizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.financials = _load_financials_module()

    def test_pascal_case_reference_normalizes(self):
        result = self.financials._normalise_reference(
            {
                "ReferenceNumber": "2024-12345",
                "DepositDate": "2024-08-31",
                "ModelType": "VOL",
                "ExerciseDates": {"endDate": "2023-12-31"},
            }
        )
        self.assertEqual(result["reference_number"], "2024-12345")
        self.assertEqual(result["deposit_date"], "2024-08-31")
        self.assertEqual(result["model_type"], "VOL")
        self.assertEqual(result["fiscal_year"], 2023)

    def test_camel_case_reference_normalizes(self):
        result = self.financials._normalise_reference(
            {
                "referenceNumber": "2024-67890",
                "depositDate": "2024-09-15",
                "modelType": "MIC-p",
                "exerciseDates": {"endDate": "2024-03-31"},
            }
        )
        self.assertEqual(result["reference_number"], "2024-67890")
        self.assertEqual(result["deposit_date"], "2024-09-15")
        self.assertEqual(result["model_type"], "MIC-p")
        self.assertEqual(result["fiscal_year"], 2024)

    def test_auth_failure_during_filing_fetch_stays_503(self):
        class FakeResponse:
            def __init__(self, status_code, payload=None, text=""):
                self.status_code = status_code
                self._payload = payload
                self.text = text

            def json(self):
                return self._payload

        class FakeClient:
            responses = [
                FakeResponse(
                    200,
                    [
                        {
                            "referenceNumber": "2024-67890",
                            "depositDate": "2024-09-15",
                            "modelType": "VOL",
                            "exerciseDates": {"endDate": "2024-03-31"},
                        }
                    ],
                ),
                FakeResponse(401, text="rotated"),
            ]

            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *_args, **_kwargs):
                return type(self).responses.pop(0)

        class FakeCursor:
            def execute(self, *_args, **_kwargs):
                return None

            def fetchone(self):
                return None

            def close(self):
                return None

        class FakeConnection:
            status = 1

            def __init__(self):
                self.rolled_back = False

            def cursor(self):
                return FakeCursor()

            def rollback(self):
                self.rolled_back = True

            def commit(self):
                return None

        fake_conn = FakeConnection()
        original_client = self.financials.httpx.AsyncClient
        original_get_connection = self.financials.get_connection
        original_put_connection = self.financials.put_connection
        original_sleep = self.financials.asyncio.sleep
        self.financials.httpx.AsyncClient = FakeClient
        self.financials.get_connection = lambda: fake_conn
        self.financials.put_connection = lambda _conn: None

        async def _fast_sleep(_seconds):
            return None

        self.financials.asyncio.sleep = _fast_sleep
        self.addCleanup(setattr, self.financials.httpx, "AsyncClient", original_client)
        self.addCleanup(setattr, self.financials, "get_connection", original_get_connection)
        self.addCleanup(setattr, self.financials, "put_connection", original_put_connection)
        self.addCleanup(setattr, self.financials.asyncio, "sleep", original_sleep)

        with self.assertRaises(self.financials.HTTPException) as ctx:
            asyncio.run(
                self.financials._do_load(
                    "0403091220",
                    None,
                    "auth-key",
                    "https://ws.cbso.nbb.be",
                    FakeBackgroundTasks(),
                )
            )
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertTrue(fake_conn.rolled_back)

    def test_already_loaded_filing_backfills_missing_nbb_admins(self):
        class FakeResponse:
            def __init__(self, status_code, payload=None, text=""):
                self.status_code = status_code
                self._payload = payload
                self.text = text

            def json(self):
                return self._payload

        class FakeClient:
            responses = [
                FakeResponse(
                    200,
                    [
                        {
                            "referenceNumber": "2024-67890",
                            "depositDate": "2024-09-15",
                            "modelType": "VOL",
                            "exerciseDates": {"endDate": "2024-03-31"},
                        }
                    ],
                ),
                FakeResponse(200, {"administrators": {"naturalPersons": []}}),
            ]

            def __init__(self, *_args, **_kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *_args, **_kwargs):
                return type(self).responses.pop(0)

        class FakeCursor:
            def __init__(self):
                self.last_sql = ""

            def execute(self, sql, *_args, **_kwargs):
                self.last_sql = " ".join(str(sql).split())

            def fetchone(self):
                if "FROM nbb_load_log" in self.last_sql and "COUNT(*)" in self.last_sql:
                    return (True, 0)
                return None

            def close(self):
                return None

        class FakeConnection:
            status = 1

            def __init__(self):
                self.rolled_back = False
                self.cursor_obj = FakeCursor()

            def cursor(self):
                return self.cursor_obj

            def rollback(self):
                self.rolled_back = True

            def commit(self):
                return None

        fake_conn = FakeConnection()
        original_client = self.financials.httpx.AsyncClient
        original_get_connection = self.financials.get_connection
        original_put_connection = self.financials.put_connection
        original_sleep = self.financials.asyncio.sleep
        original_store = self.financials.store_governance_snapshot
        original_refresh = self.financials._refresh_materialized_for_company
        self.financials.httpx.AsyncClient = FakeClient
        self.financials.get_connection = lambda: fake_conn
        self.financials.put_connection = lambda _conn: None
        governance_calls = []
        self.financials.store_governance_snapshot = (
            lambda conn, cbe, deposit_key, fiscal_year, filing_json: governance_calls.append(
                (conn, cbe, deposit_key, fiscal_year, filing_json)
            ) or {
                "administrators": 2,
                "shareholders": 0,
                "participating_interests": 0,
            }
        )
        self.financials._refresh_materialized_for_company = lambda *_args, **_kwargs: None

        async def _fast_sleep(_seconds):
            return None

        self.financials.asyncio.sleep = _fast_sleep
        self.addCleanup(setattr, self.financials.httpx, "AsyncClient", original_client)
        self.addCleanup(setattr, self.financials, "get_connection", original_get_connection)
        self.addCleanup(setattr, self.financials, "put_connection", original_put_connection)
        self.addCleanup(setattr, self.financials.asyncio, "sleep", original_sleep)
        self.addCleanup(setattr, self.financials, "store_governance_snapshot", original_store)
        self.addCleanup(setattr, self.financials, "_refresh_materialized_for_company", original_refresh)

        result = asyncio.run(
            self.financials._do_load(
                "0403091220",
                None,
                "auth-key",
                "https://ws.cbso.nbb.be",
                FakeBackgroundTasks(),
            )
        )

        self.assertEqual(result["filings_loaded"], 0)
        self.assertEqual(result["rubrics_loaded"], 0)
        self.assertEqual(result["governance_loaded"]["administrators"], 2)
        self.assertEqual(result["status"], "governance_backfilled")
        self.assertEqual(len(governance_calls), 1)
        self.assertFalse(fake_conn.rolled_back)


if __name__ == "__main__":
    unittest.main()
