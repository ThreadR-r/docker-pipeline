from loguru import logger as _loguru_logger
from typing import Optional

logger = _loguru_logger.bind(module=__name__)


def _import_docker():
    try:
        import docker

        return docker
    except Exception:
        raise


def get_client(base_url: Optional[str] = None):
    docker = _import_docker()
    if base_url:
        return docker.DockerClient(base_url=base_url)
    return docker.from_env()


def ping_client(client) -> bool:
    try:
        client.ping()
        return True
    except Exception:
        logger.exception("Docker ping failed")
        return False


def pull_image(client, image: str):
    try:
        client.images.pull(image)
        return True
    except Exception as e:
        logger.exception("Failed to pull image %s: %s", image, e)
        raise
