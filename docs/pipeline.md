# Pipeline format

This document describes the pipeline YAML format used by the scheduler. The running code validates pipelines using pydantic models in `src/pipeline_scheduler/domain/models.py`.

Contents
- Overview
- Top-level schema
- Step fields (per-step)
- Templating (Jinja2)
- Example pipeline
- Common errors and troubleshooting
- Advanced options

---

## Overview

A pipeline is a YAML file that declares `metadata` and a list of `steps`. Each step runs a Docker container (sequentially). Steps are executed in order; if a step fails the pipeline follows the configured `on_failure` policy.

Default location: `pipelines/example_pipeline.yaml`. The path can be overridden with the `PIPELINE_FILE` env var or `--pipeline` CLI flag.

The code validates pipelines using pydantic:
- Models: `PipelineModel`, `PipelineMetadata`, `StepModel`
- Implementation reference: `src/pipeline_scheduler/domain/models.py`

---

## Top-level schema

Top-level keys:
- `metadata` (map)
  - `name` (string, optional): human-friendly pipeline name.
  - `params` (map, optional): default template parameters available to Jinja2.
  - `schedule` (string, optional): cron expression used for automatic scheduling; if omitted the pipeline is not auto-scheduled.
  - `start_pipeline_at_start` (bool, optional, default `false`): schedule immediate one-off run when orchestrator starts.
- `steps` (list of step objects, required): ordered list of steps to run.

---

## Step fields (per-step)

Each step is an object with the following fields:

- `name` (string, optional)
  - Friendly name used in logs; if omitted `image` is used.

- `image` (string, required)
  - Docker image reference (e.g. `alpine:3.18`, `docker/whalesay:latest`).

- `cmd` (string or sequence, optional)
  - Command to run inside the container. A sequence is preferred for exact argv semantics:
    - `cmd: ["sh", "-c", "echo hello"]`
  - If omitted the container's default `CMD` runs.

- `env` (map of string->string, optional)
  - Environment variables to pass into the container.

- `volumes` (list of strings, optional)
  - Host to container volume bindings in the simple `host_path:container_path[:mode]` format, e.g.:
    - `/data:/app/data:ro`
  - The runner converts this list to docker-py `volumes` mapping.

- `pull_policy` (string, optional, default `if-not-present`)
  - Image pull policy: one of `always`, `never`, `if-not-present`.
  - `if-not-present`: use local image if present, otherwise pull.
  - `never`: do not pull; requires local image to exist.
  - `always`: always pull before running.

- `retry` (int, optional)
  - Number of retry attempts after initial failure (0 means no retries). If not set, global `RETRY_ON_FAIL` applies.

- `timeout` (int seconds, optional)
  - Timeout for the step; if exceeded the container is killed and step treated as failed. If not set, global `STEP_TIMEOUT` applies.

- `on_failure` (string, optional, default from pipeline or global config)
  - Policy when final step failure occurs: `abort` or `continue`.
  - `abort`: stop the pipeline and report failure (default).
  - `continue`: log the error but continue to next step.

- `remove` (string, optional, default `always`)
  - Final-state removal policy for the step's container. One of:
    - `always` — remove the container after the step finishes (default).
    - `never` — never remove the container; it remains available for inspection.
    - `on_success` — remove only when the step finishes successfully.
    - `on_failure` — remove only when the step fails.

- `remove_intermediate` (string, optional, default `always`)
  - Controls removal of intermediate attempt containers when a step is retried. One of:
    - `always` — remove each failed attempt's container immediately (default).
    - `never` — keep intermediate attempt containers.
    - `on_final_success` — keep intermediate attempt containers until a final attempt succeeds, then remove them.

Note: legacy `remove_on_success` support has been removed. Use `remove: on_success` instead.

---

## Templating (Jinja2)

- Pipelines are rendered with Jinja2 before validation.
- Template context is built from:
  1. `metadata.params` (pipeline file) — defaults
  2. `PIPELINE_PARAMS` env var or `--params` JSON (CLI) — overrides metadata params
- Strict mode:
  - Default is strict: undefined variables raise an error.
  - Controlled by `TEMPLATE_STRICT` env var; set `TEMPLATE_STRICT=false` to be permissive.

Example usage in templates:
```yaml
metadata:
  params:
    TAG: latest
steps:
  - image: alpine:3.18
    cmd: ["sh", "-c", "echo building tag {{ TAG }}"]
```

---

## Example pipeline

Example `pipelines/example_pipeline.yaml`:

```yaml
metadata:
  name: example-pipeline
  params:
    TAG: latest
  schedule: "*/1 * * * *"
  start_pipeline_at_start: true

steps:
  - name: print-tag
    image: alpine:3.18
    cmd: ["sh", "-c", "echo Running pipeline with TAG={{ TAG }}"]
    retry: 1
    # keep intermediate failed attempts until a final success, then remove them
    remove_intermediate: on_final_success

  - name: sleep-step
    image: alpine:3.18
    cmd: ["sh", "-c", "sleep 1 && echo done"]

  - name: final-step
    image: alpine:3.18
    cmd: ["sh", "-c", "echo This is the final step"]
    # never remove the final container so you can inspect it after runs
    remove: never

  - name: whale-say
    image: docker/whalesay:latest
    pull_policy: never
    cmd: ["cowsay", "Hello, World!"]
    # keep the final whalesay container for inspection
    remove: never
```

- Notes:
- `start_pipeline_at_start: true` triggers a one-off immediate run on scheduler start (in addition to scheduled runs).
- `pull_policy: never` prevents pulling the `docker/whalesay` image (useful if your builder/daemon can't pull it); if local image absent the step will fail.

---

## CLI & env overrides (priority: CLI > ENV > pipeline file > defaults)

Important runtime knobs:
- `CRON_SCHEDULE` / `--cron` — override pipeline cron.
- `PIPELINE_FILE` / `--pipeline` — pipeline path.
- `DOCKER_BASE_URL` — docker daemon URL (e.g. `unix:///var/run/docker.sock`).
- `RETRY_ON_FAIL` / `--retry` — default retry count.
- `STEP_TIMEOUT` — default per-step timeout.
- `ON_FAILURE` — global default `abort|continue`.
- `PIPELINE_PARAMS` / `--params` — JSON string for template vars.
- `TEMPLATE_STRICT` — `true|false` strict rendering.
- `UV_ENABLED` — whether entrypoint uses `uv run`.

Examples:
```bash
uv run python -m pipeline_scheduler.interfaces.cli \
  --pipeline ./pipelines/example_pipeline.yaml \
  --params '{"TAG":"v1.3.0"}' \
  --dry-run
```

---

## Validation & errors

- The runner validates the rendered YAML with pydantic. Common validation problems:
  - Missing required keys (e.g. `steps` is required).
  - Field type mismatch (e.g. `retry` must be integer).
  - Template render errors (undefined variables if strict mode).
- When a step fails after retries:
  - If `on_failure == "abort"` the pipeline aborts and the runner logs which subsequent steps were NOT executed (printed as `SKIPPED: ...`).
  - If `on_failure == "continue"` the runner continues to the next step.

Example error messages:
- `Pipeline validation error` — YAML/Schema problem.
- `Failed to pull image foo: ...` — registry/manifest/daemon problem. Use `pull_policy` to control behavior or ensure the image is compatible with your runtime.

---

## Volumes examples

- Bind mount host to container (read-write):
  - `/host/data:/container/data`
- Read-only:
  - `/host/data:/container/data:ro`

The runner expects the `host` path to be accessible inside the environment where the scheduler runs (commonly host Docker socket mount).

---

## Troubleshooting

- "No such image" and manifest errors:
  - Some container runtimes don't support old manifest formats. If you see errors like:
    ```
    not implemented: media type "application/vnd.docker.distribution.manifest.v1+prettyjws" is no longer supported...
    ```
    Either rebuild/publish the image with a modern manifest format or set `pull_policy: never` and provide a local image compatible with your daemon.

- Docker unreachable:
  - Ensure `/var/run/docker.sock` is mounted into the scheduler container or `DOCKER_BASE_URL` points to a reachable Docker API.

- Step times out:
  - Increase `timeout` for the step or adjust global `STEP_TIMEOUT`.

---

## Advanced ideas (future)

- Add per-step `on_image_pull_fail: abort|skip|retry` to customize behavior when image pull fails.
- Add a `dry-run` CI job that renders and validates all pipelines in `pipelines/` using the pydantic models.
- Support artifact outputs / step result passing between steps (requires richer DSL).

---

## Implementation notes / references

- Pydantic models: `src/pipeline_scheduler/domain/models.py`
- Runner: `src/pipeline_scheduler/application/runner.py`
- Scheduler: `src/pipeline_scheduler/application/scheduler.py`
- CLI: `src/pipeline_scheduler/interfaces/cli.py`
- Templating: `src/pipeline_scheduler/infrastructure/templating.py`

---

## Applying this doc

When you're ready I can:
1. Create `docs/pipeline.md` with the content above.
2. Add a link from `README.md -> docs/pipeline.md`.
3. Add a CI job to validate pipelines (optional).
4. Document `on_retry_step` usage and examples.

Reply `apply` to create the doc now, or `ci` to also add the pipeline validation CI. If you want changes to any section, tell me which bullet(s) to change.
