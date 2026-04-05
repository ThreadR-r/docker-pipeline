import os
import json
import sys
from loguru import logger as _loguru_logger
from typing import Optional, Dict, Any

import typer

from pipeline_scheduler.domain.models import AppConfig, PipelineModel
from pipeline_scheduler.infrastructure.templating import render_pipeline
from pipeline_scheduler.application.scheduler import start_scheduler
from pipeline_scheduler.interfaces import server
from pipeline_scheduler import state

logger = _loguru_logger.bind(module=__name__)

app = typer.Typer()


def build_config(
    pipeline_path: Optional[str] = None,
    docker_url: Optional[str] = None,
    retry: Optional[int] = None,
    step_timeout: Optional[int] = None,
    on_failure: Optional[str] = None,
    log_level: Optional[str] = None,
    params: Optional[str] = None,
) -> AppConfig:
    """Construct AppConfig from CLI parameters and environment variables.

    Precedence: explicit CLI args > environment variables > defaults.
    ``params`` is expected to be a JSON string which will be parsed to populate
    `AppConfig.pipeline_params`.
    """
    env = os.environ
    cli_params: Dict[str, Any] = {}
    if params:
        try:
            cli_params = json.loads(params)
        except Exception:
            logger.error("Failed to parse --params JSON")
            raise SystemExit(2)

    # parse integer fallbacks carefully
    def _int_or(value, fallback: int) -> int:
        if value is None:
            return fallback
        try:
            return int(value)
        except Exception:
            return fallback

    cfg = AppConfig(
        cron_schedule=(env.get("CRON_SCHEDULE") or None),
        pipeline_file=(
            pipeline_path
            or env.get("PIPELINE_FILE")
            or "/app/pipelines/example_pipeline.yaml"
        ),
        docker_base_url=(
            docker_url or env.get("DOCKER_BASE_URL") or "unix:///var/run/docker.sock"
        ),
        retry_on_fail=_int_or(
            retry if retry is not None else env.get("RETRY_ON_FAIL"), 0
        ),
        step_timeout=_int_or(
            step_timeout if step_timeout is not None else env.get("STEP_TIMEOUT"), 0
        ),
        on_failure=(on_failure or env.get("ON_FAILURE") or "abort"),
        log_level=(log_level or env.get("LOG_LEVEL") or "INFO"),
        pipeline_params=cli_params or json.loads(env.get("PIPELINE_PARAMS") or "{}"),
        template_strict=(not (env.get("TEMPLATE_STRICT") in ("0", "false", "False"))),
    )
    return cfg


@app.command()
def main(
    pipeline_path: Optional[str] = typer.Option(None, "--pipeline"),
    docker_url: Optional[str] = typer.Option(None, "--docker-url"),
    retry: Optional[int] = typer.Option(None, "--retry"),
    step_timeout: Optional[int] = typer.Option(None, "--step-timeout"),
    on_failure: Optional[str] = typer.Option(None, "--on-failure"),
    log_level: Optional[str] = typer.Option(None, "--log-level"),
    params: Optional[str] = typer.Option(None, "--params"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    config = build_config(
        pipeline_path=pipeline_path,
        docker_url=docker_url,
        retry=retry,
        step_timeout=step_timeout,
        on_failure=on_failure,
        log_level=log_level,
        params=params,
    )

    # configure loguru to write to stdout with the requested level
    logger.remove()
    logger.add(sys.stdout, level=config.log_level.upper())

    # render pipeline
    try:
        raw = render_pipeline(
            config.pipeline_file, config.pipeline_params, strict=config.template_strict
        )
    except Exception:
        logger.exception("Failed to load/render pipeline file %s", config.pipeline_file)
        raise SystemExit(2)

    try:
        pipeline = PipelineModel(**raw)
    except Exception:
        logger.exception("Pipeline validation error")
        raise SystemExit(2)

    # pipeline metadata schedule override
    schedule_expr = getattr(pipeline.metadata, "schedule", None)
    if schedule_expr and not os.environ.get("CRON_SCHEDULE"):
        config.cron_schedule = schedule_expr

    if dry_run:
        logger.info("Dry run: pipeline validated and rendered. Steps:")
        for s in pipeline.steps:
            logger.info("- {}: {}", s.name or s.image, s.cmd)
        return

    # Decide mode based on environment: API vs CLI
    api_enabled = os.getenv("API_ENABLED", "true").lower() not in ("0", "false")

    # Determine if pipeline has a schedule (new 'schedule')
    schedule_expr = getattr(pipeline.metadata, "schedule", None)

    if api_enabled:
        # start server which will look at pipeline.metadata.schedule to decide scheduling
        try:
            server.main(
                start_scheduler=bool(schedule_expr), config=config, pipeline=pipeline
            )
        except Exception:
            logger.exception("Failed to start server")
            raise SystemExit(3)
    else:
        # CLI-only: start scheduler in foreground only if schedule present
        if schedule_expr:
            try:
                config.cron_schedule = schedule_expr
                start_scheduler(config, pipeline)
            except Exception:
                logger.exception("Failed to start scheduler")
                raise SystemExit(3)
        else:
            logger.error(
                "Pipeline is untrigable: no schedule in pipeline metadata and API is disabled. The pipeline will never run. Exiting."
            )
            raise SystemExit(4)


if __name__ == "__main__":
    app()
