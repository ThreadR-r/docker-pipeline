"""Infrastructure helpers.

Keep docker client imports lazy so importing the package for templating/validation
does not require the `docker` package to be installed. This allows dry-run
validation (rendering + pydantic validation) in environments without docker.
"""

from .templating import render_pipeline


def get_client(*args, **kwargs):
    from .docker_client import get_client as _get_client

    return _get_client(*args, **kwargs)


def ping_client(*args, **kwargs):
    from .docker_client import ping_client as _ping_client

    return _ping_client(*args, **kwargs)


def pull_image(*args, **kwargs):
    from .docker_client import pull_image as _pull_image

    return _pull_image(*args, **kwargs)


__all__ = ["get_client", "ping_client", "pull_image", "render_pipeline"]
