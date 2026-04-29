"""Regression tests for NBB health-check classification."""

from __future__ import annotations

import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "backend"))

db = types.ModuleType("db")
db.fetch_all = lambda *_args, **_kwargs: []
db.fetch_one = lambda *_args, **_kwargs: None
db.execute = lambda *_args, **_kwargs: None

requests = types.ModuleType("requests")

class RequestException(Exception):
    pass


class ReadTimeout(RequestException):
    pass


requests.exceptions = types.SimpleNamespace(
    RequestException=RequestException,
    ReadTimeout=ReadTimeout,
)
requests.get = lambda *_args, **_kwargs: None

_missing = object()
_original_db = sys.modules.get("db", _missing)
sys.modules["db"] = db
try:
    import scripts.alert_digest as alert_digest
finally:
    if _original_db is _missing:
        sys.modules.pop("db", None)
    else:
        sys.modules["db"] = _original_db


class NbbHealthCheckTests(unittest.TestCase):
    def test_classify_status_codes(self):
        self.assertEqual(
            alert_digest._classify_nbb_probe_status(401),
            ("auth", "HTTP 401 (auth failure — likely rotated)"),
        )
        self.assertEqual(
            alert_digest._classify_nbb_probe_status(503),
            ("transient", "HTTP 503 (transient/upstream)"),
        )
        self.assertEqual(alert_digest._classify_nbb_probe_status(200), (None, None))
        self.assertEqual(alert_digest._classify_nbb_probe_status(404), (None, None))

    @patch.dict(
        os.environ,
        {
            "NBB_AUTHENTIC_KEY": "auth-key",
            "NBB_EXTRACT_KEY": "extract-key",
            "NBB_BASE_URL": "https://example.test",
        },
        clear=False,
    )
    @patch("scripts.alert_digest.time.sleep", return_value=None)
    def test_timeouts_are_transient_not_auth(self, _sleep):
        responses = [
            SimpleNamespace(status_code=200),
            requests.exceptions.ReadTimeout(),
            requests.exceptions.ReadTimeout(),
        ]

        def fake_get(*_args, **_kwargs):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        with patch.dict(sys.modules, {"requests": requests}):
            with patch("requests.get", side_effect=fake_get):
                status = alert_digest._check_nbb_keys(send=False, alert_to=None)

        self.assertEqual(status, alert_digest.HEALTH_CHECK_TRANSIENT_FAILURE)

    @patch.dict(
        os.environ,
        {
            "NBB_AUTHENTIC_KEY": "auth-key",
            "NBB_EXTRACT_KEY": "extract-key",
            "NBB_BASE_URL": "https://example.test",
        },
        clear=False,
    )
    @patch("scripts.alert_digest.time.sleep", return_value=None)
    def test_auth_failure_wins_over_transient_failures(self, _sleep):
        responses = [
            SimpleNamespace(status_code=401),
            SimpleNamespace(status_code=200),
        ]

        with patch.dict(sys.modules, {"requests": requests}):
            with patch("requests.get", side_effect=responses):
                status = alert_digest._check_nbb_keys(send=False, alert_to=None)

        self.assertEqual(status, alert_digest.HEALTH_CHECK_AUTH_FAILURE)


if __name__ == "__main__":
    unittest.main()
