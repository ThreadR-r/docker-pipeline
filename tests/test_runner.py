import types
import pytest

from pipeline_scheduler.application import runner as runner_mod
from pipeline_scheduler.application.runner import run_pipeline
from pipeline_scheduler.domain.models import PipelineModel, StepModel, AppConfig


class FakeContainer:
    def __init__(self, image, exit_code, cid):
        self._image = image
        self._exit_code = exit_code
        self.id = cid
        self.status = "running"
        self.killed = False
        self.removed = False

    def logs(self, stream=False, follow=False):
        # yield a small log chunk then stop
        yield b"fake-log\n"

    def reload(self):
        # immediately mark as exited for simplicity
        self.status = "exited"

    def wait(self):
        return {"StatusCode": self._exit_code}

    def kill(self):
        self.killed = True

    def remove(self):
        self.removed = True


class FakeClient:
    def __init__(self, behavior_map):
        # behavior_map: image -> list of exit codes (one per run invocation)
        self.behavior_map = {k: list(v) for k, v in behavior_map.items()}
        self.containers = types.SimpleNamespace()
        self.containers.run = self._run
        self.images = types.SimpleNamespace()

        # simple get that raises if no mapping exists
        def get(name):
            if name not in self.behavior_map:
                raise Exception("Image not found")
            return True

        self.images.get = get
        self._runs = []
        self._cid = 1

    def _run(self, image, command=None, environment=None, volumes=None, detach=True):
        # record the run
        env_copy = dict(environment) if environment else {}
        self._runs.append((image, command, env_copy))
        # determine exit code for this run
        if image in self.behavior_map and self.behavior_map[image]:
            code = self.behavior_map[image].pop(0)
        else:
            # default to success
            code = 0
        cid = f"cid-{self._cid}"
        self._cid += 1
        return FakeContainer(image, code, cid)

    @property
    def runs(self):
        return list(self._runs)


def test_on_retry_step_runs_and_receives_env(monkeypatch):
    # busybox fails first (1) then succeeds (0); retry-hook succeeds
    behavior = {"busybox": [1, 0], "retry-hook": [0]}
    fake_client = FakeClient(behavior)

    # patch get_client and pull_image used by runner
    monkeypatch.setattr(runner_mod, "get_client", lambda base_url=None: fake_client)
    monkeypatch.setattr(runner_mod, "pull_image", lambda c, image: True)

    # Build pipeline with a step that will be retried and has an on_retry_step
    primary = StepModel(
        name="primary",
        image="busybox",
        cmd="/bin/sh -c 'exit 1'",
        pull_policy="never",
        retry=1,
        on_retry_step=StepModel(
            image="retry-hook", cmd="echo hook", pull_policy="never"
        ),
    )

    pipeline = PipelineModel(steps=[primary])
    config = AppConfig(retry_on_fail=0, step_timeout=5, docker_base_url=None)

    ok = run_pipeline(pipeline, config)
    assert ok is True

    # Expect runs: busybox (attempt1), retry-hook, busybox (attempt2)
    images_run = [r[0] for r in fake_client.runs]
    assert images_run == ["busybox", "retry-hook", "busybox"]

    # Check env injected into retry-hook run
    _, _, retry_env = fake_client.runs[1]
    assert retry_env["RETRY_FOR_STEP"] == "primary"
    assert retry_env["LAST_EXIT_CODE"] == "1"
    assert retry_env["RETRY_ATTEMPT"] == "1"


def test_on_failure_step_runs_and_receives_env(monkeypatch):
    # bad image fails (1); failure-hook succeeds
    behavior = {"bad": [1], "failure-hook": [0]}
    fake_client = FakeClient(behavior)

    monkeypatch.setattr(runner_mod, "get_client", lambda base_url=None: fake_client)
    monkeypatch.setattr(runner_mod, "pull_image", lambda c, image: True)

    primary = StepModel(
        name="badstep",
        image="bad",
        cmd="/bin/sh -c 'exit 1'",
        pull_policy="never",
        retry=0,
        on_failure_step=StepModel(
            image="failure-hook", cmd="echo fail", pull_policy="never"
        ),
    )

    pipeline = PipelineModel(steps=[primary])
    config = AppConfig(retry_on_fail=0, step_timeout=5, docker_base_url=None)

    ok = run_pipeline(pipeline, config)
    # pipeline should be considered failed overall (on_failure default is abort)
    assert ok is False

    images_run = [r[0] for r in fake_client.runs]
    assert images_run == ["bad", "failure-hook"]

    # Check env injected into failure-hook run
    _, _, fail_env = fake_client.runs[1]
    assert fail_env["FAILED_STEP"] == "badstep"
    assert fail_env["FAILED_EXIT_CODE"] == "1"
    # FAILED_ATTEMPT should be '1' (single final attempt)
    assert fail_env["FAILED_ATTEMPT"] == "1"
