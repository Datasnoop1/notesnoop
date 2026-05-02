# Week-4 observability SLO dashboard seed - 2026-05-02

## Metrics source

- Backend exposes Prometheus text at `/metrics`.
- `/metrics` is admin-gated through the same Supabase admin-role dependency
  used by `/api/admin/*`.
- Phase timing is emitted by `TimingMiddleware` as both `Server-Timing`
  response headers and Prometheus histograms:
  `datasnoop_request_phase_duration_ms_bucket{phase="..."}`.

## Initial dashboard panels

These panels are seeded from the Week-1d phase-timing histogram. They are
intended for Prometheus/Grafana or any equivalent PromQL-compatible view.

| Panel | PromQL |
|-------|--------|
| API total p95 | `datasnoop:request_phase_duration_ms:p95_5m{phase="total"}` |
| API DB p95 | `datasnoop:request_phase_duration_ms:p95_5m{phase="db"}` |
| API serialize p95 | `datasnoop:request_phase_duration_ms:p95_5m{phase="serialize"}` |
| API auth p95 | `datasnoop:request_phase_duration_ms:p95_5m{phase="auth"}` |
| API cache p95 | `datasnoop:request_phase_duration_ms:p95_5m{phase="cache"}` |
| API total p99 | `datasnoop:request_phase_duration_ms:p99_5m{phase="total"}` |

Recording and alert rules live in:

- `monitoring/prometheus/datasnoop-slo-rules.yml`

## Initial SLOs

These are deliberately broad first thresholds because the existing histogram is
phase-level, not route-level. Route-level SLOs can be added once labels are
split by endpoint without exploding cardinality.

| SLO | Threshold | Alert |
|-----|-----------|-------|
| API total p95 | under 1000 ms for 15 minutes | `DatasnoopApiTotalP95Slow` |
| API DB p95 | under 500 ms for 15 minutes | `DatasnoopApiDbP95Slow` |

## PgBouncer decision

PgBouncer is not installed in Week-4. Week-3 and Week-4 checks did not show a
current connection-budget incident after the ThreadedConnectionPool and cancel
pool hardening. Keep PgBouncer parked until connection budget evidence appears.
