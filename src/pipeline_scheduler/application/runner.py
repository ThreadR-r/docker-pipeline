import copy
import time

from loguru import logger
import docker
import docker.errors

from pipeline_scheduler.domain.models import PipelineModel
from pipeline_scheduler.domain.models import StepModel
from pipeline_scheduler.domain.models import AppConfig
from pipeline_scheduler.infrastructure.docker_client import get_client, pull_image

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
            logger.info(f"Starting step '{name}' attempt {attempt}/{retries + 1}")
            try:
                volumes = _parse_volumes(step.volumes)

                pull_policy = (
                    getattr(step, "pull_policy", "if-not-present") or "if-not-present"
                )
                try:
                    if pull_policy == "always":
                        logger.info(f"Pulling image {step.image} (policy=always)")
                        pull_image(client, step.image)
                    elif pull_policy == "if-not-present":
                        try:
                            client.images.get(step.image)
                            logger.debug(f"Image {step.image} present locally")
                        except Exception as e:
                            # ImageNotFound may not be exposed in some docker client versions here
                            if getattr(docker, "errors", None) and getattr(
                                docker.errors, "ImageNotFound", None
                            ):
                                from docker.errors import ImageNotFound

                                if isinstance(e, ImageNotFound):
                                    logger.info(
                                        f"Image {step.image} not present locally, pulling"
                                    )
                                    pull_image(client, step.image)
                                else:
                                    raise
                            else:
                                # fallback: attempt to pull if get() failed
                                logger.info(
                                    f"Image {step.image} not present locally (get() failed), attempting pull"
                                )
                                pull_image(client, step.image)
                            logger.info(
                                f"Image {step.image} not present locally, pulling"
                            )
                            pull_image(client, step.image)
                    elif pull_policy == "never":
                        logger.debug(
                            f"pull_policy=never, skipping pull for {step.image}"
                        )
                    else:
                        logger.debug(
                            f"Unknown pull_policy '{pull_policy}' for {step.image}, skipping pull"
                        )
                except docker.errors.APIError as e:
                    logger.error(f"Failed to pull image {step.image}: {e}")
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
                    logger.exception(f"Error while streaming logs for {name}")

                while True:
                    container.reload()
                    status = container.status
                    if status in ("exited", "dead"):
                        break
                    if timeout and (time.time() - start) > timeout:
                        logger.warning(f"Timeout reached for step '{name}', killing container")
                        try:
                            container.kill()
                        except Exception:
                            logger.exception(f"Failed to kill timed out container for {name}")
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
                    logger.info(f"Step '{name}' succeeded")
                    step_succeeded = True
                else:
                    logger.error(f"Step '{name}' failed with exit code {code}")

                # Handle intermediate attempt removal policies (apply only to non-final attempts)
                try:
                    ri = getattr(step, "remove_intermediate", "always") or "always"
                    if not final_attempt:
                        if ri == "always":
                            try:
                                container.remove()
                            except Exception:
                                logger.debug(
                                    f"Failed to remove intermediate container for {name}"
                                )
                        elif ri == "on_final_success":
                            # keep id for possible removal if final succeeds
                            try:
                                intermediate_containers.append(container.id)
                            except Exception:
                                logger.debug(
                                    f"Failed to record intermediate container id for {name}"
                                )
                            else:
                                # ri == 'never' -> keep container
                                pass
                except Exception:
                    logger.exception(
                        f"Error handling intermediate removal policy for {name}"
                    )

                # If this attempt failed and there will be a retry, run on_retry_step if present
                try:
                    if (not final_attempt) and getattr(step, "on_retry_step", None):
                        try:
                            raw_nested = getattr(step, "on_retry_step", None)
                            assert raw_nested is not None
                            retry_nested: StepModel = copy.deepcopy(raw_nested)
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
                                f"Attempt {attempt} for step '{name}' failed — running on_retry_step '{retry_nested.name or retry_nested.image}' before next retry"
                            )
                            # run the retry hook (recursion allowed)
                            run_single_step(retry_nested)
                        except Exception:
                            logger.exception(
                                f"Exception while running on_retry_step for {name}"
                            )
                except Exception:
                    logger.exception(
                        f"Error preparing or running on_retry_step for {name}"
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
                                        f"Failed to remove intermediate container {cid} for {name}"
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
                                logger.debug(f"Failed to remove final container for {name}")
                    except Exception:
                        logger.exception(f"Error handling final removal policy for {name}")

                # If step succeeded, stop retrying, otherwise decide on retry/backoff
                if step_succeeded:
                    break
                else:
                    if attempt <= retries:
                        backoff = 2 ** (attempt - 1)
                        logger.info(f"Retrying in {backoff} seconds")
                        time.sleep(backoff)
                    else:
                        logger.error(f"No more retries for step '{name}'")

            except Exception:
                logger.exception(f"Exception while running step '{name}'")
                if attempt <= retries:
                    backoff = 2 ** (attempt - 1)
                    time.sleep(backoff)
                else:
                    logger.error(f"No more retries for step '{name}' after exception")

        # If the step failed after all retries and there is an on_failure_step, run it
        if not step_succeeded and getattr(step, "on_failure_step", None):
            try:
                raw_nested = getattr(step, "on_failure_step", None)
                assert raw_nested is not None
                nested: StepModel = copy.deepcopy(raw_nested)
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
                    f"Step '{name}' failed — running on_failure_step '{nested.name or nested.image}'"
                )
                # recursion allowed: nested may have its own on_failure_step
                run_single_step(nested)
                logger.info(
                    f"on_failure_step '{nested.name or nested.image}' for '{name}' completed"
                )
            except Exception:
                logger.exception(f"Exception while running on_failure_step for {name}")

        return step_succeeded

    # main pipeline loop: run each step via helper and honor on_failure string after running any on_failure_step
    for i, step in enumerate(pipeline.steps):
        name = step.name or step.image

        ok = run_single_step(step)

        if not ok:
            overall_success = False
            if step.on_failure == "abort":
                logger.error(f"Aborting pipeline due to failure in step '{name}'")
                try:
                    remaining = pipeline.steps[i + 1 :]
                except Exception:
                    remaining = []

                if remaining:
                    logger.info(
                        f"The following {len(remaining)} step(s) were NOT executed due to abort:"
                    )
                    for idx, s in enumerate(remaining, start=i + 2):
                        step_label = s.name or s.image
                        logger.info(f"  {idx}. {step_label}  cmd={s.cmd}")
                else:
                    logger.info("No remaining steps to run after failure.")

                break
            else:
                logger.warning(
                    f"Continuing pipeline after failure in step '{name}' (on_failure=continue)"
                )

    return overall_success
