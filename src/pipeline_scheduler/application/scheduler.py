from loguru import logger as _loguru_logger
import signal
import threading
from datetime import datetime
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

import uuid
from pipeline_scheduler.domain.models import (
    AppConfig,
    PipelineModel,
    JobModel,
    StepStatus,
    now_iso,
)
from pipeline_scheduler.infrastructure.docker_client import get_client, ping_client
from pipeline_scheduler.application.runner import run_pipeline
from pipeline_scheduler import state

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

    def job_func():
        # Concurrency guard using shared state
        if state.running.get("job"):
            logger.warning("Previous job still running, skipping this run")
            return

        job_id = str(uuid.uuid4())

        # Build initial JobModel for scheduler
        steps = [
            StepStatus(index=i + 1, total=len(pipeline.steps), name=(s.name or s.image))
            for i, s in enumerate(pipeline.steps)
        ]
        job = JobModel(
            job_id=job_id,
            pipeline=pipeline.metadata.name or "",
            submitted_by="scheduler",
            steps=steps,
        )

        with state.jobs_lock:
            state.jobs[job_id] = job
            state.running["job"] = job_id

        logger.info("Starting pipeline run: {}", pipeline.metadata.name or "unnamed")
        try:
            success = run_pipeline(pipeline, config, job_id)
            if success:
                logger.info("Pipeline finished successfully")
            else:
                logger.error("Pipeline finished with failures")
        except Exception:
            logger.exception("Unhandled exception during pipeline run")
        finally:
            with state.jobs_lock:
                # ensure running flag cleared
                state.running["job"] = False
                j = state.jobs.get(job_id)
                if j and j.ended_at is None:
                    j.ended_at = now_iso()

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

    # Register signal handlers only if running in the main thread. When the
    # scheduler is started in a background thread (e.g. by the API server),
    # registering signal handlers will raise ValueError. In that case skip
    # registration and rely on the process-wide signal handlers (e.g. Uvicorn)
    # to shut down the scheduler.
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _shutdown)
        signal.signal(signal.SIGINT, _shutdown)
    else:
        logger.warning(
            "Scheduler running in non-main thread; skipping signal registration. "
            "Main process should handle signals and shutdown scheduler explicitly."
        )

    logger.info("Scheduler starting with cron: {}", config.cron_schedule)
    scheduler.start()
