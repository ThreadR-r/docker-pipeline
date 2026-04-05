# Builder stage using uv-managed Python
FROM ghcr.io/astral-sh/uv:bookworm-slim AS builder
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

# Omit development dependencies
ENV UV_NO_DEV=1

# Configure the Python directory so it is consistent
ENV UV_PYTHON_INSTALL_DIR=/python

# Only use the managed Python version
ENV UV_PYTHON_PREFERENCE=only-managed

WORKDIR /app

# Sync locked deps without installing the project first for caching
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-install-project

# Copy the project and perform the final sync (this installs the project into the venv)
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked

# Final image
FROM debian:bookworm-slim

# Setup a non-root user
RUN groupadd --system --gid 999 nonroot \
 && useradd --system --gid 999 --uid 999 --create-home nonroot

# Copy the Python runtime from the builder
COPY --from=builder /python /python

# Copy the application from the builder
COPY --from=builder --chown=nonroot:nonroot /app /app

# Place the venv's bin at the front of PATH so the managed python is used
ENV PATH="/app/.venv/bin:${PATH}"

# Use the non-root user
USER nonroot

# Working directory
WORKDIR /app

# Defaults (overridable at runtime)
ENV PIPELINE_FILE=/app/pipelines/example_pipeline.yaml
ENV DOCKER_BASE_URL=unix:///var/run/docker.sock

# Run the application using uv which uses the uv-managed venv
ENTRYPOINT ["python", "-m", "pipeline_scheduler.interfaces.cli"]
CMD ["--help"]