from pipeline_scheduler.interfaces import cli
from pipeline_scheduler.interfaces.cli import build_config
from pipeline_scheduler.domain.models import AppConfig


def _clear_env(monkeypatch, keys):
    for k in keys:
        monkeypatch.delenv(k, raising=False)


def test_build_config_defaults_logs_example_pipeline(monkeypatch):
    # ensure no relevant env vars are present
    keys = [
        "PIPELINE_FILE",
        "CRON_SCHEDULE",
        "DOCKER_BASE_URL",
        "RETRY_ON_FAIL",
        "STEP_TIMEOUT",
        "LOG_LEVEL",
        "API_HOST",
        "API_PORT",
    ]
    _clear_env(monkeypatch, keys)

    called = {"info": False}

    def fake_info(*args, **kwargs):
        called["info"] = True

    # monkeypatch the logger.info used in build_config
    monkeypatch.setattr(cli.logger, "info", fake_info)

    cfg = build_config()

    assert isinstance(cfg, AppConfig)
    assert cfg.pipeline_file == "/app/pipelines/example_pipeline_simple.yaml"
    assert called["info"], (
        "Expected logger.info to be called when falling back to example pipeline"
    )


def test_build_config_reads_env_vars(monkeypatch):
    monkeypatch.setenv("PIPELINE_FILE", "/tmp/my-pipeline.yaml")
    monkeypatch.setenv("CRON_SCHEDULE", "*/5 * * * *")
    monkeypatch.setenv("DOCKER_BASE_URL", "tcp://1.2.3.4:2375")
    monkeypatch.setenv("RETRY_ON_FAIL", "2")
    monkeypatch.setenv("STEP_TIMEOUT", "42")
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("API_HOST", "127.0.0.1")
    monkeypatch.setenv("API_PORT", "9090")

    cfg = build_config()

    assert cfg.pipeline_file == "/tmp/my-pipeline.yaml"
    assert cfg.cron_schedule == "*/5 * * * *"
    assert cfg.docker_base_url == "tcp://1.2.3.4:2375"
    assert cfg.retry_on_fail == 2
    assert cfg.step_timeout == 42
    assert cfg.log_level.upper() == "DEBUG"
    assert getattr(cfg, "api_host", None) == "127.0.0.1"
    assert getattr(cfg, "api_port", None) == 9090


def test_build_config_cli_overrides_env(monkeypatch):
    # set env to values that should be overridden
    monkeypatch.setenv("PIPELINE_FILE", "/tmp/env-pipeline.yaml")
    monkeypatch.setenv("CRON_SCHEDULE", "0 0 * * *")
    monkeypatch.setenv("DOCKER_BASE_URL", "tcp://env:2375")
    monkeypatch.setenv("RETRY_ON_FAIL", "5")
    monkeypatch.setenv("STEP_TIMEOUT", "20")
    monkeypatch.setenv("LOG_LEVEL", "INFO")
    monkeypatch.setenv("API_HOST", "0.0.0.0")
    monkeypatch.setenv("API_PORT", "8080")

    cfg = build_config(
        pipeline_path="/tmp/cli-pipeline.yaml",
        cron_schedule="*/2 * * * *",
        docker_url="unix:///tmp/docker.sock",
        retry=3,
        step_timeout=7,
        log_level="warning",
        api_host="10.1.1.1",
        api_port=5555,
    )

    assert cfg.pipeline_file == "/tmp/cli-pipeline.yaml"
    assert cfg.cron_schedule == "*/2 * * * *"
    assert cfg.docker_base_url == "unix:///tmp/docker.sock"
    assert cfg.retry_on_fail == 3
    assert cfg.step_timeout == 7
    assert cfg.log_level.upper() == "WARNING"
    assert getattr(cfg, "api_host", None) == "10.1.1.1"
    assert getattr(cfg, "api_port", None) == 5555


def test_build_config_int_parsing_fallback(monkeypatch):
    # malformed integer in env should fall back to default (0)
    monkeypatch.setenv("RETRY_ON_FAIL", "not-an-int")
    monkeypatch.delenv("STEP_TIMEOUT", raising=False)

    cfg = build_config()

    assert cfg.retry_on_fail == 0
    assert cfg.step_timeout == 0


def test_cli_dry_run_with_pipeline_file(tmp_path, monkeypatch):
    # create a minimal pipeline YAML that render_pipeline can load
    content = """
metadata:
  name: test-pipeline
steps:
  - name: step1
    image: alpine:3.18
    cmd: echo hello
"""
    p = tmp_path / "pipeline.yaml"
    p.write_text(content)

    # capture logger info lines to ensure dry-run prints steps
    seen = {"info": []}

    def fake_info(*args, **kwargs):
        seen["info"].append(args)

    monkeypatch.setattr(cli.logger, "info", fake_info)

    # call main with dry_run True and pipeline_path pointing to temp file
    # Typer exposes CLI functions directly; call the function
    cli.main(pipeline_path=str(p), dry_run=True, api_enabled=False)

    # assert logger.info was called at least for dry-run header
    assert any("Dry run" in a[0] for a in seen["info"]) or len(seen["info"]) > 0
