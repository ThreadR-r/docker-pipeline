# API Trigger

This document describes the HTTP API to trigger pipelines on demand.

Overview
- The API is optional and controlled by `API_ENABLED` (default `true`).
- The API requires an API key supplied via the `X-API-Key` header. Configure keys using `API_KEY` (single) or `API_KEYS` (comma-separated).

Endpoints
- `POST /api/v1/trigger` — trigger a pipeline run
  - JSON body: `{ "pipeline_file": "/app/pipelines/example_pipeline.yaml", "params": {...} }` (both fields optional)
  - Returns 202 Accepted with `{ "status": "accepted", "job_id": "..." }` on success
  - Returns 400 on invalid pipeline, 401 on missing/invalid API key, 409 if a run is active

- `GET /api/v1/status` — get status; optional `job_id` query param to get specific job

- `GET /health` — basic health check

Authentication
- Header: `X-API-Key` (default header name configurable via `API_KEY_HEADER`)
- Env: `API_KEY` (single key) or `API_KEYS` (comma-separated)

Examples
- Trigger:

```bash
curl -X POST "http://localhost:8080/api/v1/trigger" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: $API_KEY" \
  -d '{"pipeline_file":"/app/pipelines/example_pipeline.yaml"}'
```

Notes & Security
- Keep API key secret. The endpoint controls Docker on the host via the scheduler — compromise of the API key is sensitive.
- For production, place the API behind a reverse proxy and use TLS.
