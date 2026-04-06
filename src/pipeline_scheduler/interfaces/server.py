import os
import threading
import logging

import uvicorn

from pipeline_scheduler.domain.models import AppConfig, PipelineModel
from pipeline_scheduler.infrastructure.templating import render_pipeline
from pipeline_scheduler.application.scheduler import start_scheduler

logger = logging.getLogger(__name__)


def _start_scheduler_in_thread(config: AppConfig, pipeline: PipelineModel):
    t = threading.Thread(target=start_scheduler, args=(config, pipeline), daemon=True)
    t.start()
    return t


def main(
    start_scheduler: bool = True,
    config: AppConfig | None = None,
    pipeline: PipelineModel | None = None,
):
    # Load config and pipeline if not provided
    if config is None:
        config = AppConfig()
    if pipeline is None:
        raw = render_pipeline(path=config.pipeline_file, params=config.pipeline_params)
        pipeline = PipelineModel(**raw)

    # Decide whether to start scheduler based on pipeline metadata 'schedule'
    schedule_expr = getattr(pipeline.metadata, "schedule", None)
    if schedule_expr:
        # propagate schedule into config for scheduler
        config.cron_schedule = schedule_expr
        _start_scheduler_in_thread(config, pipeline)
    else:
        logger.info(
            "No schedule found in pipeline metadata; automatic scheduling disabled for this pipeline"
        )

    # Start FastAPI server: prefer config values, fall back to environment
    host = getattr(config, "api_host", None) or os.getenv("API_HOST", "0.0.0.0")
    port = int(getattr(config, "api_port", None) or os.getenv("API_PORT", "8080"))
    logger.info("Starting API server on %s:%s", host, port)
    uvicorn.run(
        "pipeline_scheduler.interfaces.api:app", host=host, port=port, log_level="info"
    )


if __name__ == "__main__":
    main()
