from pydantic import BaseModel, Field, field_validator
from typing import Optional, List, Dict, Any


class StepModel(BaseModel):
    name: Optional[str] = None
    image: str
    cmd: Optional[Any] = None
    env: Optional[Dict[str, str]] = None
    volumes: Optional[List[str]] = None
    pull_policy: Optional[str] = "if-not-present"
    retry: Optional[int] = Field(default=None, ge=0)
    timeout: Optional[int] = Field(default=None, ge=0)
    on_failure: Optional[str] = "abort"
    # new removal policy: final-state removal
    remove: Optional[str] = "always"
    # intermediate attempt removal policy
    remove_intermediate: Optional[str] = "always"

    # optional step to run when this step finally fails (follows StepModel schema)
    on_failure_step: Optional["StepModel"] = None
    # optional step to run when an attempt fails and will be retried
    on_retry_step: Optional["StepModel"] = None

    @field_validator("on_failure")
    def on_failure_must_be_valid(cls, v):
        if v is None:
            return v
        if v not in ("abort", "continue"):
            raise ValueError("on_failure must be 'abort' or 'continue'")
        return v

    @field_validator("pull_policy")
    def pull_policy_must_be_valid(cls, v):
        if v is None:
            return v
        if v not in ("always", "never", "if-not-present"):
            raise ValueError(
                "pull_policy must be one of 'always', 'never', 'if-not-present'"
            )
        return v

    @field_validator("remove")
    def validate_remove(cls, v):
        if v is None:
            return v
        allowed = {"always", "never", "on_success", "on_failure"}
        if v not in allowed:
            raise ValueError("remove must be one of: " + ", ".join(sorted(allowed)))
        return v

    @field_validator("remove_intermediate")
    def validate_remove_intermediate(cls, v):
        if v is None:
            return v
        allowed = {"always", "never", "on_final_success"}
        if v not in allowed:
            raise ValueError(
                "remove_intermediate must be one of: " + ", ".join(sorted(allowed))
            )
        return v

    @field_validator("on_failure_step", mode="after")
    def coerce_on_failure_step(cls, v):
        # allow nested mapping for on_failure_step and coerce to StepModel
        if v is None:
            return None
        if isinstance(v, dict):
            return StepModel(**v)  # type: ignore[arg-type]
        return v

    @field_validator("on_retry_step", mode="after")
    def coerce_on_retry_step(cls, v):
        # allow nested mapping for on_retry_step and coerce to StepModel
        if v is None:
            return None
        if isinstance(v, dict):
            return StepModel(**v)  # type: ignore[arg-type]
        return v


class PipelineMetadata(BaseModel):
    name: Optional[str] = None
    params: Optional[Dict[str, Any]] = {}
    # New canonical schedule field (cron expression). If absent, pipeline won't be auto-scheduled.
    schedule: Optional[str] = None
    start_pipeline_at_start: Optional[bool] = False
    # Whether this pipeline can be triggered via the HTTP API.
    allow_api_trigger: Optional[bool] = True


class PipelineModel(BaseModel):
    metadata: PipelineMetadata = PipelineMetadata()
    steps: List[StepModel]


class AppConfig(BaseModel):
    cron_schedule: Optional[str] = None
    pipeline_file: str = "/app/pipelines/example_pipeline_simple.yaml"
    pipeline_params: Dict[str, Any] = {}
    docker_base_url: Optional[str] = "unix:///var/run/docker.sock"
    retry_on_fail: int = 0
    step_timeout: int = 0
    log_level: str = "INFO"
    api_host: str = "0.0.0.0"
    api_port: int = 8080
