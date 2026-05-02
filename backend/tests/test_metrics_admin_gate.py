"""Regression tests for the admin-gated Prometheus metrics endpoint."""

import os
import sys
from pathlib import Path


os.environ.setdefault("SUPABASE_HS256_FALLBACK", "1")
os.environ.setdefault("ACTIVITY_LOG_IP_SALT", "test-salt")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main  # noqa: E402
from routers import admin  # noqa: E402


def _metrics_route():
    for route in main.app.routes:
        if getattr(route, "path", None) == "/metrics":
            return route
    raise AssertionError("/metrics route not found")


def test_metrics_route_requires_admin_dependency():
    route = _metrics_route()

    dependencies = getattr(route, "dependant").dependencies

    assert any(dep.call is admin._require_admin for dep in dependencies)


def test_metrics_route_keeps_prometheus_media_type():
    response = main.metrics_response()

    assert response.media_type == "text/plain; version=0.0.4"
    assert "datasnoop_request_phase_duration_ms_bucket" in response.body.decode()
