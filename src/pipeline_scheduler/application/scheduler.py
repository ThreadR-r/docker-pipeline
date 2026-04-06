from loguru import logger as _loguru_logger
import signal
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from pipeline_scheduler.domain.models import AppConfig, PipelineModel
from pipeline_scheduler.infrastructure.docker_client import get_client, ping_client
from pipeline_scheduler.application.runner import run_pipeline

logger = _loguru_logger.bind(module=__name__)


def start_scheduler(config: AppConfig, pipeline: PipelineModel):
    # check docker connectivity
    if not getattr(config, "cron_schedule", None):
        raise ValueError("No cron schedule configured; scheduler should not be started")
    client = None
    try:
        client = get_client(config.docker_base_url)
    except Exception:
        logger.exception("Failed to create Docker client")
        raise

    if not ping_client(client):
        raise RuntimeError("Docker daemon is unreachable")

    scheduler = BlockingScheduler()
    running = {"job": False}

    def job_func():
        if running["job"]:
            logger.warning("Previous job still running, skipping this run")
            return
        running["job"] = True
        logger.info("Starting pipeline run: {}", pipeline.metadata.name or "unnamed")
        try:
            success = run_pipeline(pipeline, config)
            if success:
                logger.info("Pipeline finished successfully")
            else:
                logger.error("Pipeline finished with failures")
        except Exception:
            logger.exception("Unhandled exception during pipeline run")
        finally:
            running["job"] = False

    try:
        trigger = CronTrigger.from_crontab(config.cron_schedule)
    except Exception:
        logger.exception("Invalid cron schedule: {}", config.cron_schedule)
        raise

    scheduler.add_job(job_func, trigger=trigger)

    if getattr(pipeline.metadata, "start_pipeline_at_start", False):
        logger.info("Pipeline requests start-on-start: scheduling an immediate run")
        scheduler.add_job(job_func, next_run_time=datetime.now())

    def _shutdown(signum, frame):
        logger.info("Received signal {}, shutting down scheduler", signum)
        try:
            scheduler.shutdown(wait=False)
        except Exception as e:
            logger.error("Error during scheduler shutdown: {}", e)
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    logger.info("Scheduler starting with cron: {}", config.cron_schedule)
    scheduler.start()
