import time
from loguru import logger
from typing import Any

from pipeline_scheduler.domain.models import PipelineModel
from pipeline_scheduler.domain.models import StepModel
from pipeline_scheduler.domain.models import AppConfig
from pipeline_scheduler.infrastructure.docker_client import get_client, pull_image

try:
    import docker
except Exception:
    docker = None
import copy

logger = logger.bind(module=__name__)


def _parse_volumes(vols):
    if not vols:
        return None
    binds = {}
    for item in vols:
        parts = item.split(":")
        if len(parts) >= 2:
            host = parts[0]
            container = parts[1]
            mode = "rw"
            if len(parts) == 3:
                mode = parts[2]
            binds[host] = {"bind": container, "mode": mode}
    return binds


def run_pipeline(pipeline: PipelineModel, config: AppConfig) -> bool:
    try:
        client = get_client(config.docker_base_url)
    except Exception:
        logger.exception("Failed to create Docker client")
        return False

    overall_success = True

    # helper: run a single StepModel (including retries, timeouts, removal policies)
    def run_single_step(step: StepModel) -> bool:
        name = step.name or step.image
        retries = step.retry if step.retry is not None else config.retry_on_fail
        timeout = step.timeout if step.timeout is not None else config.step_timeout

        attempt = 0
        step_succeeded = False
        intermediate_containers = []
        last_exit_code = None

        while attempt <= retries:
            attempt += 1
            logger.info("Starting step '%s' attempt %d/%d", name, attempt, retries + 1)
            try:
                volumes = _parse_volumes(step.volumes)

                pull_policy = (
                    getattr(step, "pull_policy", "if-not-present") or "if-not-present"
                )
                try:
                    if pull_policy == "always":
                        logger.info("Pulling image %s (policy=always)", step.image)
                        pull_image(client, step.image)
                    elif pull_policy == "if-not-present":
                        try:
                            client.images.get(step.image)
                            logger.debug("Image %s present locally", step.image)
                        except Exception as e:
                            # ImageNotFound may not be exposed in some docker client versions here
                            if getattr(docker, "errors", None) and getattr(
                                docker.errors, "ImageNotFound", None
                            ):
                                from docker.errors import ImageNotFound

                                if isinstance(e, ImageNotFound):
                                    logger.info(
                                        "Image %s not present locally, pulling",
                                        step.image,
                                    )
                                    pull_image(client, step.image)
                                else:
                                    raise
                            else:
                                # fallback: attempt to pull if get() failed
                                logger.info(
                                    "Image %s not present locally (get() failed), attempting pull",
                                    step.image,
                                )
                                pull_image(client, step.image)
                            logger.info(
                                "Image %s not present locally, pulling", step.image
                            )
                            pull_image(client, step.image)
                    elif pull_policy == "never":
                        logger.debug(
                            "pull_policy=never, skipping pull for %s", step.image
                        )
                    else:
                        logger.debug(
                            "Unknown pull_policy '%s' for %s, skipping pull",
                            pull_policy,
                            step.image,
                        )
                except docker.errors.APIError as e:
                    logger.error("Failed to pull image %s: %s", step.image, e)
                    msg = str(e)
                    if "not implemented: media type" in msg:
                        logger.error(
                            "Docker daemon refused to pull the image due to unsupported manifest media type. "
                            "Rebuild or republish the image with a modern manifest (v2) or use a compatible registry/daemon."
                        )
                    raise

                container = client.containers.run(
                    step.image,
                    command=step.cmd,
                    environment=step.env,
                    volumes=volumes,
                    detach=True,
                )

                start = time.time()
                try:
                    for chunk in container.logs(stream=True, follow=True):
                        try:
                            msg = chunk.decode("utf-8", errors="replace")
                        except Exception:
                            msg = str(chunk)
                        logger.info(msg.rstrip("\n"))
                except Exception:
                    logger.exception("Error while streaming logs for %s", name)

                while True:
                    container.reload()
                    status = container.status
                    if status in ("exited", "dead"):
                        break
                    if timeout and (time.time() - start) > timeout:
                        logger.warning(
                            "Timeout reached for step '%s', killing container", name
                        )
                        try:
                            container.kill()
                        except Exception:
                            logger.exception(
                                "Failed to kill timed out container for %s", name
                            )
                        break
                    time.sleep(0.5)

                res = container.wait()
                code = res.get("StatusCode") if isinstance(res, dict) else None
                if code is None:
                    code = res
                last_exit_code = code

                # determine whether this is the final attempt for this step
                final_attempt = attempt == (retries + 1)

                if code == 0:
                    logger.info("Step '%s' succeeded", name)
                    step_succeeded = True
                else:
                    logger.error("Step '%s' failed with exit code %s", name, code)

                # Handle intermediate attempt removal policies (apply only to non-final attempts)
                try:
                    ri = getattr(step, "remove_intermediate", "always") or "always"
                    if not final_attempt:
                        if ri == "always":
                            try:
                                container.remove()
                            except Exception:
                                logger.debug(
                                    "Failed to remove intermediate container for %s",
                                    name,
                                )
                        elif ri == "on_final_success":
                            # keep id for possible removal if final succeeds
                            try:
                                intermediate_containers.append(container.id)
                            except Exception:
                                logger.debug(
                                    "Failed to record intermediate container id for %s",
                                    name,
                                )
                            else:
                                # ri == 'never' -> keep container
                                pass
                except Exception:
                    logger.exception(
                        "Error handling intermediate removal policy for %s", name
                    )

                # If this attempt failed and there will be a retry, run on_retry_step if present
                try:
                    if (not final_attempt) and getattr(step, "on_retry_step", None):
                        try:
                            retry_nested = copy.deepcopy(step.on_retry_step)
                            retry_nested.env = retry_nested.env or {}
                            retry_nested.env.update(
                                {
                                    "RETRY_FOR_STEP": step.name or step.image,
                                    "LAST_EXIT_CODE": str(code)
                                    if code is not None
                                    else "unknown",
                                    "RETRY_ATTEMPT": str(attempt),
                                }
                            )
                            logger.info(
                                "Attempt %d for step '%s' failed — running on_retry_step '%s' before next retry",
                                attempt,
                                name,
                                retry_nested.name or retry_nested.image,
                            )
                            # run the retry hook (recursion allowed)
                            run_single_step(retry_nested)
                        except Exception:
                            logger.exception(
                                "Exception while running on_retry_step for %s", name
                            )
                except Exception:
                    logger.exception(
                        "Error preparing or running on_retry_step for %s", name
                    )

                # If this is the final attempt, handle final-state removal and cleanup of intermediates
                if final_attempt:
                    try:
                        remove_policy = getattr(step, "remove", "always") or "always"
                        final_success = code == 0

                        # If intermediates should be removed on final success and we succeeded, remove them now
                        if (
                            getattr(step, "remove_intermediate", "always")
                            == "on_final_success"
                            and final_success
                        ):
                            for cid in intermediate_containers:
                                try:
                                    c = client.containers.get(cid)
                                    c.remove()
                                except Exception:
                                    logger.debug(
                                        "Failed to remove intermediate container %s for %s",
                                        cid,
                                        name,
                                    )

                        # Decide whether to remove the final attempt container based on policy
                        do_remove_final = False
                        if remove_policy == "always":
                            do_remove_final = True
                        elif remove_policy == "never":
                            do_remove_final = False
                        elif remove_policy == "on_success":
                            do_remove_final = final_success
                        elif remove_policy == "on_failure":
                            do_remove_final = not final_success

                        if do_remove_final:
                            try:
                                container.remove()
                            except Exception:
                                logger.debug(
                                    "Failed to remove final container for %s", name
                                )
                    except Exception:
                        logger.exception(
                            "Error handling final removal policy for %s", name
                        )

                # If step succeeded, stop retrying, otherwise decide on retry/backoff
                if step_succeeded:
                    break
                else:
                    if attempt <= retries:
                        backoff = 2 ** (attempt - 1)
                        logger.info("Retrying in %s seconds", backoff)
                        time.sleep(backoff)
                    else:
                        logger.error("No more retries for step '%s'", name)

            except Exception:
                logger.exception("Exception while running step '%s'", name)
                if attempt <= retries:
                    backoff = 2 ** (attempt - 1)
                    time.sleep(backoff)
                else:
                    logger.error("No more retries for step '%s' after exception", name)

        # If the step failed after all retries and there is an on_failure_step, run it
        if not step_succeeded and getattr(step, "on_failure_step", None):
            try:
                nested = copy.deepcopy(step.on_failure_step)
                # inject failure context env vars
                nested.env = nested.env or {}
                nested.env.update(
                    {
                        "FAILED_STEP": step.name or step.image,
                        "FAILED_EXIT_CODE": str(last_exit_code)
                        if last_exit_code is not None
                        else "unknown",
                        "FAILED_ATTEMPT": str(attempt),
                    }
                )
                logger.info(
                    "Step '%s' failed — running on_failure_step '%s'",
                    name,
                    nested.name or nested.image,
                )
                # recursion allowed: nested may have its own on_failure_step
                run_single_step(nested)
                logger.info(
                    "on_failure_step '%s' for '%s' completed",
                    nested.name or nested.image,
                    name,
                )
            except Exception:
                logger.exception("Exception while running on_failure_step for %s", name)

        return step_succeeded

    # main pipeline loop: run each step via helper and honor on_failure string after running any on_failure_step
    for i, step in enumerate(pipeline.steps):
        name = step.name or step.image
        on_failure = (
            step.on_failure if step.on_failure is not None else config.on_failure
        )

        ok = run_single_step(step)

        if not ok:
            overall_success = False
            if on_failure == "abort":
                logger.error("Aborting pipeline due to failure in step '%s'", name)
                try:
                    remaining = pipeline.steps[i + 1 :]
                except Exception:
                    remaining = []

                if remaining:
                    logger.info(
                        "The following %d step(s) were NOT executed due to abort:",
                        len(remaining),
                    )
                    for idx, s in enumerate(remaining, start=i + 2):
                        step_label = s.name or s.image
                        logger.info("  %d. %s  cmd=%s", idx, step_label, s.cmd)
                        try:
                            print(f"SKIPPED: {idx}. {step_label} cmd={s.cmd}")
                        except Exception:
                            print(
                                "SKIPPED: {}. {} cmd={}".format(idx, step_label, s.cmd)
                            )
                else:
                    logger.info("No remaining steps to run after failure.")

                break
            else:
                logger.warning(
                    "Continuing pipeline after failure in step '%s' (on_failure=continue)",
                    name,
                )

    return overall_success
