from typing import Dict, Any
import threading

from pipeline_scheduler.domain.models import (
    JobModel,
)

# Shared in-memory state for scheduler and API
# `running["job"]` holds either False or the current job_id
running: Dict[str, Any] = {"job": False}
# jobs holds JobModel instances (from domain models) when API or scheduler
# create job entries; guarded by jobs_lock for thread-safety
jobs_lock = threading.Lock()
# store arbitrary job objects (Pydantic models) keyed by job_id
jobs: Dict[str, JobModel] = {}
