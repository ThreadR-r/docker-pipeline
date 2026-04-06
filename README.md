
# Docker-Pipeline 🚀

<p align="center">
  <a href="README.md">English</a> | <a href="README.fr.md">Français</a>
</p>

[![CI/CD](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml/badge.svg?branch=main)](https://github.com/ThreadR-r/docker-pipeline/actions/workflows/ci-cd.yml)


Docker-Pipeline — lightweight declarative orchestrator to run Docker steps.

A compact scheduler and runner for YAML pipelines: each step runs a real Docker container with options for pull policy, retries, timeouts and removal rules. Hooks can be attached for remediation or notification on failures.

Tired of having to use heavy orchestrators like Kestra or Apache Airflow just to run simple pipelines, I created Docker-Pipeline as a lightweight, auditable alternative.

**Why use Docker-Pipeline** 💡
- **Audit-friendly**: pipelines are plain YAML — easy to review and version.
- **Real behavior**: steps run inside Docker containers (same as CI).
- **Fine-grained control**: retries, timeouts, pull policies and removal rules.
- **Hooks**: `on_retry_step` and `on_failure_step` for automatic actions.

**Highlights** ✨
- Pydantic-validated models for safety and auditability.
- Container-first runner: every step runs in an isolated container.
- Small HTTP API for ad-hoc triggers and run status (API-key protected).
- Lightweight cron scheduling via `metadata.schedule`.

## Usage modes
- **API + Scheduler** (default): API enabled and pipeline provides `metadata.schedule`. Useful for pipelines that need both scheduled runs and ad-hoc triggers.
- **API-only**: API enabled, no `metadata.schedule`. Useful for pipelines that are triggered manually or by external systems, without internal scheduling.
- **Scheduler-only**: API disabled, pipeline scheduled via `metadata.schedule`. Useful for pipelines that should run on a fixed schedule without external triggers.
- **CLI-only**: no schedule and no API → one-shot runs / validation. Useful for ad-hoc runs or CI jobs.


# Quick start 🧪
## Dry-Run validation
### Validate the pipeline without Docker via the package :

```bash
uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline_simple.yaml --dry-run
```

### You can also use Docker to validate the pipeline :

```bash
docker run --rm \
  -v ./example_pipeline_simple.yaml:/pipelines/example_pipeline_simple.yaml:ro \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /pipelines/example_pipeline_simple.yaml --dry-run
```

## Run the pipeline

### Run the container as a service with API enabled (default):

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ./pipelines/example_pipeline_simple.yaml:/app/pipelines/example_pipeline_simple.yaml:ro \
  -e API_ENABLED=true \
  -e API_KEY=your_api_key_here \
  -e API_PORT=8080 \
  -p 8080:8080 \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /app/pipelines/example_pipeline_simple.yaml
```

From here you can trigger runs via the API (e.g. `curl -X POST http://localhost:8080/api/v1/trigger -H "X-API-Key: your_api_key_here"`) and check the status (e.g. `curl -X GET http://localhost:8080/api/v1/status -H "X-API-Key: your_api_key_here"`) and the health (e.g. `curl -X GET http://localhost:8080/health`).

If a schedule is defined in the pipeline YAML (`metadata.schedule`), the pipeline will also run automatically according to that schedule.

Note: mounting the Docker socket gives control over the host Docker — use with care.

## One-shot runs (`--run-once` / `RUN_ONCE`)

Use `--run-once` to execute the rendered pipeline a single time and then exit. This is useful for ad-hoc runs or CI jobs where you don't want the scheduler to run.

Examples:

```bash
uv run python -m pipeline_scheduler.interfaces.cli --pipeline pipelines/example_pipeline_simple.yaml --run-once
```

```bash
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v ./pipelines/example_pipeline_simple.yaml:/app/pipelines/example_pipeline_simple.yaml:ro \
  ghcr.io/threadr-r/docker-pipeline:latest \
  --pipeline /app/pipelines/example_pipeline_simple.yaml --run-once
```

## Configuration (env & CLI) ⚙️
| Env parameter | CLI parameter | Type | Description |
|---------------|---------------|------|-------------|
| `PIPELINE_FILE` | `--pipeline` | string | Path to pipeline YAML (default `/app/pipelines/example_pipeline_simple.yaml`) |
| `PIPELINE_PARAMS` | `--params` | string (JSON) | Pipeline template parameters as JSON string (default `{}`) |
| `CRON_SCHEDULE` | `--cron-schedule` | string | Override schedule (cron expression) |
| `DOCKER_BASE_URL` | `--docker-url` | string | Docker API URL (default `unix:///var/run/docker.sock`) |
| `API_ENABLED` | `--api-enabled` | boolean | Enable/disable API (default `true`) |
| `API_HOST` | `--api-host` | string | API host (default `0.0.0.0`) |
| `API_PORT` | `--api-port` | integer | API port (default `8080`) |
| `API_KEY`, `API_KEYS` | (no CLI) | string or comma-separated list | API authentication keys; header name read from `API_KEY_HEADER` (default `X-API-Key`) |
| `API_KEY_HEADER` | (no CLI) | string | Header name used to provide API key (default `X-API-Key`) |
| `RETRY_ON_FAIL` | `--retry` | integer | Global retry fallback (default `0`) |
| `STEP_TIMEOUT` | `--step-timeout` | integer | Default step timeout (seconds) (default `0`) |
| `RUN_ONCE` | `--run-once` | boolean | If set, execute the pipeline once immediately and exit |
| `LOG_LEVEL` | `--log-level` | string | Logging level (default `INFO`) |

## Pipeline schema (short) 🗂️
- Top-level: `metadata` (name, params, schedule, start_pipeline_at_start) and `steps` (ordered list).
- StepModel: `name`, `image`, `cmd`, `env`, `volumes`, `pull_policy`, `retry`, `timeout`, `on_failure`, `on_retry_step`, `on_failure_step`, `remove`, `remove_intermediate`.

## Hooks — summary 🔁
- `on_retry_step`: runs after a failed attempt before the next retry. Injected env vars: `RETRY_FOR_STEP`, `LAST_EXIT_CODE`, `RETRY_ATTEMPT`.
- `on_failure_step`: runs after retries are exhausted. Injected env vars: `FAILED_STEP`, `FAILED_EXIT_CODE`, `FAILED_ATTEMPT`.

Hooks do not change the runner's decision (retry or final failure); they are for remediation/notification.

## Simple example

`pipelines/example_pipeline_simple.yaml`:

```yaml
metadata:
  name: simple-pipeline
  params: {}

steps:
  - name: hello
    image: alpine:3.18
    cmd: ["sh","-c","echo Hello world"]
    retry: 0
    timeout: 10
    on_failure: continue
```

## Advanced example

```yaml
metadata:
  name: advanced-pipeline
  schedule: "0 * * * *"
  params: {}
  start_pipeline_at_start: true

steps:
  - name: build
    image: alpine:3.18
    cmd: ["sh","-c","echo building; exit 1"]
    retry: 2
    timeout: 30
    pull_policy: if-not-present
    on_retry_step:
      name: cleanup
      image: alpine:3.18
      cmd: ["sh","-c","echo cleanup before retry for ${RETRY_FOR_STEP}"]
    on_failure_step:
      name: notify
      image: alpine:3.18
      cmd: ["sh","-c","echo pipeline failed for ${FAILED_STEP} code=${FAILED_EXIT_CODE}"]
    on_failure: abort
  - name: notify-final
    image: alpine:3.18
    cmd: ["sh","-c","echo pipeline end"]
    retry: 0
```

## Development & testing 🧰
- Dry-run validation: `uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline_simple.yaml --dry-run`.
- Unit tests: add `pytest` mocks for the Docker client to assert hooks order and env injection.
- CI recommendation: validate all YAML in `pipelines/` and run unit tests.

## Contributing
- Keep changes small and focused; add tests for behaviour changes.

## Useful links
- Pipeline docs: [docs/pipeline.md](docs/pipeline.md)
- Models: [src/pipeline_scheduler/domain/models.py](src/pipeline_scheduler/domain/models.py)
- Runner: [src/pipeline_scheduler/application/runner.py](src/pipeline_scheduler/application/runner.py)
- CLI: [src/pipeline_scheduler/interfaces/cli.py](src/pipeline_scheduler/interfaces/cli.py)

License MIT
