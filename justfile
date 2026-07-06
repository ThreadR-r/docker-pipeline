# Makefile for ruff, ty (astral), pytest

default:
    just --list

all: check

check: lint type test security

lint:
    uv run --with ruff ruff check .

type:
    uv run --with ty ty check .

test:
    uv run --group testing pytest -q tests -n auto -d --cov=pipeline_scheduler --cov-report=html:reports/coverage --cov-report=term-missing

security:
    # Disabled binding to all interfaces as it is the user responsibility to run this in a secure environment;
    # also skip B101 (assert used) as it is used in case of nested steps.
    uv run --with bandit bandit --skip B104,B101 -r src

fix:
    uv run --with ruff ruff check . --fix

prek-install:
    uvx prek install

prek:
    uvx prek run --all-files
