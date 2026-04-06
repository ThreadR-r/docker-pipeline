import os
import sys
import json
from typing import Optional, Annotated

from loguru import logger as _loguru_logger
import typer

from pipeline_scheduler.domain.models import AppConfig, PipelineModel
from pipeline_scheduler.infrastructure.templating import render_pipeline
from pipeline_scheduler.application.scheduler import start_scheduler
from pipeline_scheduler.application.runner import run_pipeline
from pipeline_scheduler.interfaces import server
from pipeline_scheduler.utils.tree import build_static_tree, render_tree_ascii

logger = _loguru_logger.bind(module=__name__)

app = typer.Typer()


def build_config(
    pipeline_path: Optional[str] = None,
    pipeline_params: Optional[str] = None,
    docker_url: Optional[str] = None,
    cron_schedule: Optional[str] = None,
    retry: Optional[int] = None,
    step_timeout: Optional[int] = None,
    log_level: Optional[str] = None,
    api_port: Optional[int] = None,
    api_host: Optional[str] = None,
) -> AppConfig:
    """Construct AppConfig from CLI parameters and environment variables.

    Precedence: explicit CLI args > environment variables > defaults.
    ``params`` is expected to be a JSON string which will be parsed to populate
    `AppConfig.pipeline_params`.
    """
    env = os.environ

    # parse integer fallbacks carefully
    def _int_or(value, fallback: int) -> int:
        if value is None:
            return fallback
        try:
            return int(value)
        except Exception:
            return fallback

    cfg = AppConfig(
        cron_schedule=(cron_schedule or env.get("CRON_SCHEDULE") or None),
        # determine pipeline file and log if falling back to the example pipeline
        pipeline_file=(
            pipeline_path
            or env.get("PIPELINE_FILE")
            or "/app/pipelines/example_pipeline_simple.yaml"
        ),
        pipeline_params=(
            json.loads(pipeline_params)
            if pipeline_params is not None
            else json.loads(env.get("PIPELINE_PARAMS", "{}"))
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
        log_level=(log_level or env.get("LOG_LEVEL") or "INFO"),
        # pipeline params removed from AppConfig; they must be specified in YAML
        api_host=(api_host or env.get("API_HOST") or "0.0.0.0"),
        api_port=_int_or(
            api_port if api_port is not None else env.get("API_PORT"), 8080
        ),
    )
    # log when using bundled example pipeline (no CLI arg and no PIPELINE_FILE env)
    if not pipeline_path and not env.get("PIPELINE_FILE"):
        logger.info(
            "No pipeline specified via --pipeline or PIPELINE_FILE; using example pipeline: %s",
            cfg.pipeline_file,
        )
    return cfg


@app.command()
def main(
    pipeline_path: Annotated[Optional[str], typer.Option("--pipeline")] = None,
    pipeline_params: Annotated[Optional[str], typer.Option("--params")] = None,
    cron_schedule: Annotated[Optional[str], typer.Option("--cron-schedule")] = None,
    docker_url: Annotated[Optional[str], typer.Option("--docker-url")] = None,
    retry: Annotated[Optional[int], typer.Option("--retry")] = None,
    step_timeout: Annotated[Optional[int], typer.Option("--step-timeout")] = None,
    log_level: Annotated[Optional[str], typer.Option("--log-level")] = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    show: Annotated[
        bool,
        typer.Option("--show"),
    ] = False,
    run_once: Annotated[bool, typer.Option("--run-once")] = False,
    api_enabled: Annotated[bool, typer.Option("--api-enabled")] = True,
    api_port: Annotated[Optional[int], typer.Option("--api-port")] = None,
    api_host: Annotated[Optional[str], typer.Option("--api-host")] = None,
):
    config = build_config(
        pipeline_path=pipeline_path,
        pipeline_params=pipeline_params,
        cron_schedule=cron_schedule,
        docker_url=docker_url,
        retry=retry,
        step_timeout=step_timeout,
        log_level=log_level,
        api_port=api_port,
        api_host=api_host,
    )

    # configure loguru to write to stdout with the requested level
    logger.remove()
    logger.add(sys.stdout, level=config.log_level.upper())

    # render pipeline (params must be defined within the YAML file itself)
    try:
        raw = render_pipeline(config.pipeline_file)
    except Exception:
        logger.exception("Failed to load/render pipeline file %s", config.pipeline_file)
        raise SystemExit(2)

    try:
        pipeline = PipelineModel(**raw)
    except Exception:
        logger.exception("Pipeline validation error")
        raise SystemExit(2)

    # pipeline metadata schedule override: prefer explicit CLI/env over metadata
    schedule_expr = getattr(pipeline.metadata, "schedule", None)
    if schedule_expr and not config.cron_schedule:
        config.cron_schedule = schedule_expr

    if dry_run:
        logger.info("Dry run: pipeline validated and rendered. Steps:")
        for s in pipeline.steps:
            logger.info("- {}: {}", s.name or s.image, s.cmd)
        return

    if show:
        sp = build_static_tree(pipeline)
        print(render_tree_ascii(sp=sp, color=True))
        return

    # Decide mode based on environment: API vs CLI
    api_enabled = os.getenv("API_ENABLED", "true").lower() not in ("0", "false")

    # Determine if pipeline has a schedule (new 'schedule')
    schedule_expr = getattr(pipeline.metadata, "schedule", None)
    # Respect RUN_ONCE env var if set and CLI flag not given
    if not run_once:
        run_once = os.getenv("RUN_ONCE", "false").lower() in ("1", "true", "yes")

    # If user requested a one-shot run, execute pipeline once and exit
    if run_once:
        try:
            ok = run_pipeline(pipeline, config)
            if ok:
                logger.info("One-shot pipeline run completed successfully")
                return
            else:
                logger.error("One-shot pipeline run failed")
                raise SystemExit(3)
        except Exception:
            logger.exception("Failed to run pipeline once")
            raise SystemExit(3)

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
                "Pipeline is untrigable: no schedule in pipeline metadata and API is disabled. Use --run-once to execute once. Exiting."
            )
            raise SystemExit(4)


if __name__ == "__main__":
    app()
