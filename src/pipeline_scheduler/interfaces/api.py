import os
import uuid
import asyncio
from typing import Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException
from fastapi import status as http_status
from fastapi.security.api_key import APIKeyHeader

from pipeline_scheduler.infrastructure.templating import render_pipeline
from pipeline_scheduler.domain.models import (
    PipelineModel,
    AppConfig,
    JobModel,
    StepStatus,
)
from pipeline_scheduler.application.runner import run_pipeline
from pipeline_scheduler import state
from pipeline_scheduler.domain.models import now_iso
from pipeline_scheduler.utils.tree import (
    build_static_tree,
    build_live_tree,
    render_tree_ascii,
)

API_KEY_HEADER_NAME = "X-API-Key"
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)

# Module-level AppConfig instance to be set by the server so API handlers
# reuse the same configuration (otherwise standalone API will create a new AppConfig).
CONFIG: AppConfig | None = None


def set_config(cfg: AppConfig) -> None:
    """Set the AppConfig used by API handlers (called by server.main)."""
    global CONFIG
    CONFIG = cfg


def _allowed_keys() -> list:
    single = os.getenv("API_KEY")
    multi = os.getenv("API_KEYS")
    if single:
        return [single]
    if multi:
        return [k.strip() for k in multi.split(",") if k.strip()]
    return []


def get_api_key(key: Optional[str] = Depends(api_key_header)):
    allowed = _allowed_keys()
    if not allowed:
        raise HTTPException(
            status_code=http_status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="API key not configured",
        )
    if not key or key not in allowed:
        raise HTTPException(
            status_code=http_status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    return key


app = FastAPI(title="Pipeline Scheduler API", version="1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/trigger")
async def trigger(payload: Dict[str, Any], api_key: str = Depends(get_api_key)):
    """Trigger the pipeline run..."""

    # Merge parameters: start from config.pipeline_params then overlay payload pipeline_params
    assert CONFIG is not None, "CONFIG must be set before handling requests"
    config_params = dict(CONFIG.pipeline_params or {})
    config_params.update(payload.get("pipeline_params", {}))

    try:
        raw = render_pipeline(path=CONFIG.pipeline_file, params=config_params)
        pipeline = PipelineModel(**raw)
    except Exception as e:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(e))

    # Respect pipeline metadata: disallow API-triggered runs when explicitly disabled
    if not getattr(pipeline.metadata, "allow_api_trigger", True):
        raise HTTPException(
            status_code=http_status.HTTP_403_FORBIDDEN,
            detail="API trigger disabled for this pipeline",
        )

    # concurrency guard
    if state.running.get("job"):
        raise HTTPException(
            status_code=http_status.HTTP_409_CONFLICT, detail="Pipeline already running"
        )

    job_id = str(uuid.uuid4())

    # Build initial JobModel with per-step entries
    steps = [
        StepStatus(index=i + 1, total=len(pipeline.steps), name=(s.name or s.image))
        for i, s in enumerate(pipeline.steps)
    ]

    job = JobModel(
        job_id=job_id,
        pipeline=pipeline.metadata.name or "",
        submitted_by="api_triggered",
        steps=steps,
    )

    # store job under lock and mark running guard
    with state.jobs_lock:
        state.jobs[job_id] = job
        state.running["job"] = job_id

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, run_pipeline, pipeline, CONFIG, job_id)

    def _done_cb(f):
        try:
            ok = f.result()
            with state.jobs_lock:
                j: JobModel | None = state.jobs.get(job_id)
                assert j is not None, "JobModel should exist in state.jobs"
                if j:
                    j.status = "success" if ok else "failed"
                    if j.ended_at is None:
                        j.ended_at = now_iso()
                state.running["job"] = False
        except Exception:
            with state.jobs_lock:
                j: JobModel | None = state.jobs.get(job_id)
                assert j is not None, "JobModel should exist in state.jobs"
                if j:
                    j.status = "error"
                    if j.ended_at is None:
                        j.ended_at = now_iso()
                state.running["job"] = False

    fut.add_done_callback(_done_cb)
    return {"status": "accepted", "job_id": job_id, "pipeline": pipeline.metadata.name}


@app.get("/api/v1/status")
async def status(job_id: Optional[str] = None, api_key: str = Depends(get_api_key)):
    if job_id:
        j: JobModel | None = state.jobs.get(job_id)
        if not j:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND, detail="job not found"
            )
        return j
    return {
        "running": state.running.get("job"),
        "jobs_count": len(state.jobs),
        "jobs": state.jobs,
    }


@app.get("/api/v1/show")
async def show(
    job_id: Optional[str] = None,
    color: bool = False,
    api_key: str = Depends(get_api_key),
):
    """Show a pipeline tree.

    If `job_id` is provided, return a live view based on current job state.
    Otherwise return a static view of the configured pipeline.
    """
    if job_id:
        with state.jobs_lock:
            j: JobModel | None = state.jobs.get(job_id)
            if not j:
                raise HTTPException(
                    status_code=http_status.HTTP_404_NOT_FOUND, detail="job not found"
                )
            sp = build_live_tree(j, pipeline=None)
        text = render_tree_ascii(sp, color=False)
        if color:
            text_ansi = render_tree_ascii(sp, color=True)
            return {"tree": sp.dict(), "text": text, "text_ansi": text_ansi}
        return {"tree": sp.dict(), "text": text}

    # static view from configured pipeline
    assert CONFIG is not None, "CONFIG must be set before handling requests"
    try:
        raw = render_pipeline(
            path=CONFIG.pipeline_file, params=CONFIG.pipeline_params or {}
        )
        pipeline = PipelineModel(**raw)
    except Exception as e:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(e))
    sp = build_static_tree(pipeline)
    text = render_tree_ascii(sp, color=False)
    if color:
        text_ansi = render_tree_ascii(sp, color=True)
        return {"tree": sp.dict(), "text": text, "text_ansi": text_ansi}
    return {"tree": sp.dict(), "text": text}
