
# Docker-Pipeline 🚀

[![CI/CD](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml)

Lightweight declarative orchestrator for running sequences of Docker containers. Pipelines are plain YAML — each step runs in a real, isolated container with retries, timeouts, pull policies, removal rules, and lifecycle hooks. No Airflow, no Kestra. Just containers and YAML.

Airflow, Prefect, and Dagster all want you to define your workflow inside their framework — DAGs as Python objects, tasks as decorated functions — which fights against keeping business logic completely opaque inside a Docker image. Kestra is YAML-based like this project, but its more advanced features sit behind a paid plan. n8n wants to be a whole hosted app with its own database and UI. This project is deliberately just the thin layer underneath: run the container, watch the exit code, retry or run a failure hook, get out of the way. It never needs to know what's inside a step's image.

## Requirements

- Python `3.14.*` (pinned in `pyproject.toml`) and [`uv`](https://docs.astral.sh/uv/)
- A reachable Docker daemon (`/var/run/docker.sock` by default, or set `DOCKER_BASE_URL`)

## Features ✨

- Retries with exponential backoff and per-step timeouts
- Pull policies: `always`, `never`, `if-not-present`
- Container removal policies: `always`, `never`, `on_success`, `on_failure`
- Lifecycle hooks: `on_retry_step` and `on_failure_step` — each hook is itself a Docker container
- Jinja2-templated pipelines with variable injection via `--params`
- Cron scheduling via `metadata.schedule`
- HTTP API for ad-hoc triggers and run status (API-key protected)
- One-shot CLI execution with `--run-once`
- ASCII tree view of pipeline structure via `--show` (static), or live per-step status and attempt history via `GET /api/v1/show?job_id=`

## Quick Start 🧪

### Dry run — validate without executing

```bash
uv run python -m pipeline_scheduler.interfaces.cli \
  --pipeline ./pipelines/example_pipeline_simple.yaml --dry-run
```

```bash
docker run --rm \
  -v $(pwd)/pipelines/example_pipeline_simple.yaml:/app/pipelines/example_pipeline_simple.yaml:ro \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /app/pipelines/example_pipeline_simple.yaml --dry-run
```

### Run as a service — API + optional cron

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/pipelines/example_pipeline_simple.yaml:/app/pipelines/example_pipeline_simple.yaml:ro \
  -e API_KEY=your_api_key_here \
  -p 8080:8080 \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /app/pipelines/example_pipeline_simple.yaml
```

Trigger a run:
```bash
curl -X POST http://localhost:8080/api/v1/trigger \
  -H "X-API-Key: your_api_key_here" \
  -H "Content-Type: application/json" -d '{}'
```

Check status:
```bash
curl http://localhost:8080/api/v1/status -H "X-API-Key: your_api_key_here"
```

If `metadata.schedule` is defined in the pipeline YAML, it also runs automatically on that cron.

### Run once — one-shot execution

```bash
uv run python -m pipeline_scheduler.interfaces.cli \
  --pipeline ./pipelines/example_pipeline_simple.yaml --run-once
```

```bash
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/pipelines/example_pipeline_simple.yaml:/app/pipelines/example_pipeline_simple.yaml:ro \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /app/pipelines/example_pipeline_simple.yaml --run-once
```

### Show pipeline structure

```bash
uv run python -m pipeline_scheduler.interfaces.cli \
  --pipeline ./pipelines/example_pipeline_simple.yaml --show
```

## Configuration ⚙️

| Env var | CLI flag | Default | Description |
|---|---|---|---|
| `PIPELINE_FILE` | `--pipeline` | `/app/pipelines/example_pipeline_simple.yaml` | Path to pipeline YAML |
| `PIPELINE_PARAMS` | `--params` | `{}` | Jinja2 template params as JSON string |
| `CRON_SCHEDULE` | `--cron-schedule` | `None` | Override the schedule from pipeline metadata |
| `DOCKER_BASE_URL` | `--docker-url` | `unix:///var/run/docker.sock` | Docker socket, or `tcp://host:port` for a remote daemon. For `tcp://`, TLS is applied automatically if the standard Docker CLI env vars `DOCKER_TLS_VERIFY`/`DOCKER_CERT_PATH` are set |
| `API_ENABLED` | `--api-enabled` | `true` | Enable HTTP API |
| `API_HOST` | `--api-host` | `0.0.0.0` | API bind host |
| `API_PORT` | `--api-port` | `8080` | API port |
| `API_KEY` / `API_KEYS` | env only | none | API key(s); `API_KEYS` is comma-separated |
| `API_KEY_HEADER` | env only | `X-API-Key` | Header name for API key |
| `RETRY_ON_FAIL` | `--retry` | `0` | Global retry fallback (per-step setting overrides this) |
| `STEP_TIMEOUT` | `--step-timeout` | `0` | Default step timeout in seconds (`0` = no limit) |
| `RUN_ONCE` | `--run-once` | `false` | Execute pipeline once then exit |
| `LOG_LEVEL` | `--log-level` | `INFO` | Log level |

CLI flags take precedence over env vars.

## Pipeline Schema 🗂️

```yaml
metadata:
  name: string
  params: { key: value }              # default Jinja2 template params
  schedule: "0 * * * *"              # cron expression (optional)
  start_pipeline_at_start: false      # run once immediately on startup
  allow_api_trigger: true             # set to false to block API-triggered runs

steps:
  - name: string                      # optional, falls back to image name
    image: string                     # required
    cmd: ["arg1", "arg2"]            # optional, list or string
    env: { KEY: value }
    volumes: ["/host:/container:rw"]
    pull_policy: if-not-present       # always | never | if-not-present
    retry: 0                          # number of retry attempts
    timeout: 0                        # seconds, 0 = no limit
    on_failure: abort                 # abort | continue
    remove: always                    # always | never | on_success | on_failure
    remove_intermediate: always       # always | never | on_final_success
    on_retry_step:                    # runs between failed attempts
      image: string
      cmd: [...]
    on_failure_step:                  # runs after all retries exhausted
      image: string
      cmd: [...]
```

Pipelines are Jinja2 templates. Pass variables with `--params '{"key": "value"}'` — they merge over `metadata.params` defaults. Missing variables raise immediately (StrictUndefined).

### Simple example

See [`pipelines/example_pipeline_simple.yaml`](pipelines/example_pipeline_simple.yaml).

### Advanced example

See [`pipelines/example_pipeline_advanced.yaml`](pipelines/example_pipeline_advanced.yaml) — demonstrates retries, hooks, cron scheduling, and `start_pipeline_at_start`. The `build` step is intentionally set to fail (`exit 1`) to show retry and hook behavior.

## Hooks 🔁

Hooks are full pipeline steps — they can have their own retry logic and their own hooks.

- `on_retry_step` — runs after a failed attempt, before the next retry. Injected env: `RETRY_FOR_STEP`, `LAST_EXIT_CODE`, `RETRY_ATTEMPT`.
- `on_failure_step` — runs after all retries are exhausted. Injected env: `FAILED_STEP`, `FAILED_EXIT_CODE`, `FAILED_ATTEMPT`.

## API

All endpoints except `/health` require the API key header (`X-API-Key` by default).

| Endpoint | Method | Description |
|---|---|---|
| `/health` | GET | Health check — no auth required |
| `/api/v1/trigger` | POST | Trigger a pipeline run |
| `/api/v1/status` | GET | Run status; pass `?job_id=` for a specific job |
| `/api/v1/show` | GET | Pipeline tree; pass `?job_id=` for live state |

## Development 🧰

```bash
uv sync --group testing              # install deps including test group
just check                           # lint → type → test → security
just test                            # pytest -q tests -n auto, writes reports/coverage/index.html
uv run pytest tests/test_runner.py   # single file
uv run pytest tests/test_runner.py::test_name   # single test
```

`just test` also emits an HTML coverage report at `reports/coverage/index.html` (gitignored).

Pre-commit hooks (ruff, ty, basic file hygiene) run via [`prek`](https://github.com/j178/prek), invoked ephemerally with `uvx` — no extra install needed beyond `uv`:

```bash
just prek-install   # wire prek into .git/hooks, once
just prek           # run all hooks against the whole repo
```

## License

MIT
