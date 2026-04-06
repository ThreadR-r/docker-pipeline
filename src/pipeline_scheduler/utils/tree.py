"""Utilities to build and render a pipeline execution tree.

This module provides helpers to build a static representation of a pipeline
(`ShowPipeline`) and a live representation from `JobModel` state, and to
render an ASCII tree for human-friendly display.

Functions:
- build_static_tree(pipeline) -> ShowPipeline
- build_live_tree(job, pipeline=None) -> ShowPipeline
- render_tree_ascii(show_pipeline) -> str

All state reads are done with minimal locking in build_live_tree; callers
should ensure the job snapshot is consistent if used concurrently.
"""

from __future__ import annotations

from typing import List, Optional
from pipeline_scheduler.domain.models import (
    ShowPipeline,
    ShowStep,
    AttemptInfo,
    PipelineModel,
    StepModel,
    JobModel,
    StepStatus,
)
from pipeline_scheduler.domain.models import now_iso
from pipeline_scheduler import state
import copy


def _step_to_show_static(i: int, total: int, step: StepModel) -> ShowStep:
    """Convert a StepModel to ShowStep (static)."""
    children: List[ShowStep] = []
    if getattr(step, "on_retry_step", None) is not None:
        assert step.on_retry_step is not None
        c = _step_to_show_static(0, 0, step.on_retry_step)
        c.hook = "on_retry_step"
        children.append(c)
    if getattr(step, "on_failure_step", None) is not None:
        assert step.on_failure_step is not None
        c = _step_to_show_static(0, 0, step.on_failure_step)
        c.hook = "on_failure_step"
        children.append(c)

    return ShowStep(
        index=i,
        total=total,
        name=step.name or step.image,
        configured_retry=step.retry,
        configured_timeout=step.timeout,
        status="pending",
        attempts=[],
        children=children,
    )


def build_static_tree(pipeline: PipelineModel) -> ShowPipeline:
    """Build a static ShowPipeline from a PipelineModel.

    The static tree includes configured retries/timeouts and nested hooks as
    children, but no run-time timestamps or attempt history.
    """
    sp = ShowPipeline(name=pipeline.metadata.name)
    total = len(pipeline.steps)
    for i, s in enumerate(pipeline.steps, start=1):
        sp.steps.append(_step_to_show_static(i, total, s))
    return sp


def build_live_tree(
    job: JobModel, pipeline: Optional[PipelineModel] = None
) -> ShowPipeline:
    """Build a ShowPipeline from live JobModel state.

    The function snapshots job state under `state.jobs_lock` and converts it
    to a ShowPipeline including attempt history and statuses.
    """
    # snapshot to avoid holding lock while we build objects
    with state.jobs_lock:
        job_snapshot = copy.deepcopy(job)

    sp = ShowPipeline(name=job_snapshot.pipeline, created_at=job_snapshot.created_at)
    total = len(job_snapshot.steps)
    for ss in job_snapshot.steps:
        attempts: List[AttemptInfo] = []
        for a_idx, a in enumerate(ss.attempts or [], start=1):
            attempts.append(
                AttemptInfo(
                    attempt=a_idx,
                    exit_code=a.get("exit_code"),
                    started_at=a.get("started_at"),
                    ended_at=a.get("ended_at"),
                    note=a.get("note"),
                )
            )

        # build children from pipeline if available to show hook roles
        children: List[ShowStep] = []
        if pipeline is not None and ss.index - 1 < len(pipeline.steps):
            pstep = pipeline.steps[ss.index - 1]
            if getattr(pstep, "on_retry_step", None) is not None:
                assert pstep.on_retry_step is not None
                c = _step_to_show_static(0, 0, pstep.on_retry_step)
                c.hook = "on_retry_step"
                children.append(c)
            if getattr(pstep, "on_failure_step", None) is not None:
                assert pstep.on_failure_step is not None
                c = _step_to_show_static(0, 0, pstep.on_failure_step)
                c.hook = "on_failure_step"
                children.append(c)

        step = ShowStep(
            index=ss.index,
            total=total,
            name=ss.name,
            configured_retry=None,
            configured_timeout=None,
            status=ss.status,
            attempts=attempts,
            children=children,
        )
        sp.steps.append(step)
    return sp


def _render_step(
    lines: List[str],
    step: ShowStep,
    prefix: str = "",
    is_last: bool = True,
    color: bool = False,
) -> None:
    """Render a single ShowStep (and its children) into lines.

    If `color` is True, wrap parts of the output in ANSI color codes.
    """
    branch = "└─ " if is_last else "├─ "

    # helper: simple ANSI color wrapper
    CSI = "\x1b["
    RESET = CSI + "0m"
    COLORS = {
        "green": CSI + "32m",
        "red": CSI + "31m",
        "yellow": CSI + "33m",
        "cyan": CSI + "36m",
        "magenta": CSI + "35m",
        "dim": CSI + "2m",
        "bold": CSI + "1m",
    }

    def color_wrap(text: str, color_name: str) -> str:
        if not color:
            return text
        code = COLORS.get(color_name)
        return f"{code}{text}{RESET}" if code else text

    hook_suffix = f" [{step.hook}]" if getattr(step, "hook", None) else ""

    status_color = {
        "succeeded": "green",
        "success": "green",
        "failed": "red",
        "error": "red",
        "running": "yellow",
        "pending": "dim",
    }.get(step.status, None)

    label = f"{step.index}/{step.total} {step.name}{hook_suffix} ({step.status})"
    if status_color:
        label = color_wrap(label, status_color)

    lines.append(f"{prefix}{branch}{label}")
    child_prefix = prefix + ("   " if is_last else "│  ")

    # render attempts
    for i, a in enumerate(step.attempts, start=1):
        a_line = f"Attempt {a.attempt} — exit={a.exit_code} started={a.started_at} ended={a.ended_at}"
        if color:
            a_line = color_wrap(a_line, "cyan")
        lines.append(f"{child_prefix}├─ {a_line}")

    # children
    for idx, ch in enumerate(step.children):
        _render_step(
            lines, ch, child_prefix, idx == (len(step.children) - 1), color=color
        )


def render_tree_ascii(sp: ShowPipeline, color: bool = False) -> str:
    """Render the ShowPipeline as an ASCII tree string.

    If `color` is True, the output contains ANSI color codes.
    """
    lines: List[str] = []
    header = sp.name or "pipeline"
    if sp.created_at:
        header = f"{header} (created={sp.created_at})"

    if color:
        header = "\x1b[1m" + header + "\x1b[0m"

    lines.append(header)

    for idx, step in enumerate(sp.steps):
        _render_step(lines, step, "", idx == (len(sp.steps) - 1), color=color)

    return "\n".join(lines)
