import os
import uuid
import asyncio
from typing import Optional, Dict, Any

from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.security.api_key import APIKeyHeader

from pipeline_scheduler.infrastructure.templating import render_pipeline
from pipeline_scheduler.domain.models import PipelineModel, AppConfig
from pipeline_scheduler.application.runner import run_pipeline
from pipeline_scheduler import state

API_KEY_HEADER_NAME = os.getenv("API_KEY_HEADER", "X-API-Key")
api_key_header = APIKeyHeader(name=API_KEY_HEADER_NAME, auto_error=False)


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
        raise HTTPException(status_code=500, detail="API key not configured")
    if not key or key not in allowed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key"
        )
    return key


app = FastAPI(title="Pipeline Scheduler API", version="1.0")


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/v1/trigger")
async def trigger(payload: Dict[str, Any], api_key: str = Depends(get_api_key)):
    """Trigger a pipeline run. Payload may include 'pipeline_file' and 'params'."""
    pipeline_file = payload.get("pipeline_file")
    params = payload.get("params") or {}

    config = AppConfig()
    file = pipeline_file or config.pipeline_file

    try:
        raw = render_pipeline(file, params, strict=config.template_strict)
        pipeline = PipelineModel(**raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    # concurrency guard
    if state.running.get("job"):
        raise HTTPException(status_code=409, detail="Pipeline already running")

    job_id = str(uuid.uuid4())
    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, run_pipeline, pipeline, config)

    state.jobs[job_id] = {"status": "running", "pipeline": pipeline.metadata.name}

    def _done_cb(f):
        try:
            ok = f.result()
            state.jobs[job_id]["status"] = "success" if ok else "failed"
        except Exception:
            state.jobs[job_id]["status"] = "error"

    fut.add_done_callback(_done_cb)
    return {"status": "accepted", "job_id": job_id, "pipeline": pipeline.metadata.name}


@app.get("/api/v1/status")
async def status(job_id: Optional[str] = None):
    if job_id:
        j = state.jobs.get(job_id)
        if not j:
            raise HTTPException(status_code=404, detail="job not found")
        return j
    return {"running": state.running.get("job"), "jobs_count": len(state.jobs)}
