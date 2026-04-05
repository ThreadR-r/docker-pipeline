 
# docker-pipeline

docker-pipeline — Declarative Docker step orchestrator

A compact scheduler and runner for declarative pipeline YAMLs. Define sequential steps that execute as Docker containers with configurable pull policies, retries, timeouts and removal rules. Hooks may be attached to steps to run remediation or notification tasks when retries occur or a step ultimately fails.

## Why docker-pipeline
- Audit-friendly: pipelines are plain YAML — easy to review and store in git.
- Runs steps as real Docker containers so CI and local runs behave the same.
- Fine-grained container removal policies to avoid stopped-container accumulation.
- Hooks: `on_retry_step` and `on_failure_step` let you run remediation or notification containers automatically.
- Lightweight and focused: simple to run locally or in Docker.

Highlights
- Schema-validated pipeline model for safe, auditable pipelines
- Container-first runner that executes each step as a real Docker container
- Per-step controls: retries, timeouts, pull policies and removal policies
- Small HTTP API for ad-hoc triggers and run status (API key protected)
- Lightweight cron scheduling for automated runs (via metadata.schedule)

## Quick start (dry-run validation)

Validate a pipeline without Docker (fast, safe):

```
uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline.yaml --dry-run
```

This renders and validates the pipeline YAML against the pydantic models without reaching out to Docker.

## Run in Docker

Build the image:

```
docker build -t docker-pipeline:latest .
```

Run the container:

```
docker run --rm -it \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(pwd)/pipelines:/app/pipelines:ro \
  -e API_KEY=your_api_key_here \
  docker-pipeline:latest
```

Note: Mounting the Docker socket grants the container control of host Docker — run with care.

## Single entrypoint
- Launch: `uv run python -m pipeline_scheduler.interfaces.cli` (or `python -m pipeline_scheduler.interfaces.cli`)
- Modes:
  1. API + Scheduler (default): API enabled and pipeline provides `metadata.schedule`
  2. API-only: API enabled, no `metadata.schedule`
  3. Scheduler-only: API disabled and pipeline has `metadata.schedule`
  4. CLI-only: no schedule and API disabled → exits with message that pipeline is untrigable

## Configuration (env & CLI)
- `PIPELINE_FILE` / `--pipeline` — path to pipeline YAML (default: `/app/pipelines/example_pipeline.yaml`)
- `CRON_SCHEDULE` — override the pipeline schedule expression (cron format)
- `DOCKER_BASE_URL` — Docker API URL (default `unix:///var/run/docker.sock`)
- `API_ENABLED` — `true|false` (default `true`)
- `API_KEY` / `API_KEYS` — API auth
- `RETRY_ON_FAIL` / `--retry` — global retry fallback
- `STEP_TIMEOUT` — default step timeout (seconds)
- `ON_FAILURE` — global default (abort|continue)

Pipeline schema (short)

- Top-level:
  - `metadata`:
    - `name` (optional)
    - `params` (map of defaults)
    - `schedule` (cron expression used for automatic scheduling)
    - `start_pipeline_at_start` (bool)
  - `steps`: ordered list of step objects

- StepModel key fields:
  - `name, image, cmd, env, volumes`
  - `pull_policy`: `always|never|if-not-present`
  - `retry`: integer
  - `timeout`: seconds
  - `on_failure`: `abort|continue` (behavior after final failure)
  - `on_failure_step`: optional StepModel — executed once after final failure, before honoring `on_failure`
  - `on_retry_step`: optional StepModel — executed after each failed attempt and before the next retry
  - `remove`: `always|never|on_success|on_failure` (default `always`)
  - `remove_intermediate`: `always|never|on_final_success` (default `always`)

Hooks behavior
- `on_retry_step` runs when a step attempt fails and will be retried; injected env vars:
  - `RETRY_FOR_STEP`, `LAST_EXIT_CODE`, `RETRY_ATTEMPT`
  - Its result does NOT affect whether the runner retries the primary step.
- `on_failure_step` runs after a step exhausts retries; injected env vars:
  - `FAILED_STEP`, `FAILED_EXIT_CODE`, `FAILED_ATTEMPT`
  - After the hook runs, the pipeline follows `on_failure` (`abort` or `continue`). The hook's result does not change that decision.

Simple example pipeline (pipelines/example_pipeline.yaml)

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

Advanced example (pipelines/example_pipeline.advanced.yaml)

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

Development & testing

- Dry-run validate pipelines locally:
  - uv run python -m pipeline_scheduler.interfaces.cli --pipeline ./pipelines/example_pipeline.yaml --dry-run
- Unit tests: add pytest mocks for docker client to verify hook execution order and env injection.
- CI recommendations:
  - validate (pydantic) all files in `pipelines/` on PRs
  - run unit tests

Contributing

- Keep changes small and focused; add tests for behavior changes.

Links & pointers

- Pipeline docs: docs/pipeline.md
- Models: src/pipeline_scheduler/domain/models.py
- Runner: src/pipeline_scheduler/application/runner.py
- CLI entrypoint: src/pipeline_scheduler/interfaces/cli.py

License MIT
