from typer.testing import CliRunner
import os

from pipeline_scheduler.interfaces.cli import app, build_config


def test_build_config_default_cron(monkeypatch):
    # Ensure no CRON_SCHEDULE in env
    monkeypatch.delenv("CRON_SCHEDULE", raising=False)
    cfg = build_config()
    assert cfg.cron_schedule is None


def test_cli_dry_run(monkeypatch, tmp_path):
    runner = CliRunner()
    # create a simple pipeline file
    pipeline_yaml = tmp_path / "p.yml"
    pipeline_yaml.write_text(
        """metadata:\n  name: t\nsteps:\n  - image: alpine:3.18\n    cmd: ['echo','hi']\n"""
    )
    result = runner.invoke(app, ["--pipeline", str(pipeline_yaml), "--dry-run"])
    assert result.exit_code == 0
    assert "Dry run: pipeline validated and rendered. Steps:" in result.output
