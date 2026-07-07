import docker

from pipeline_scheduler.infrastructure.docker_client import get_client


class FakeDockerClient:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


def test_get_client_tcp_with_tls_env(tmp_path, monkeypatch):
    for name in ("cert.pem", "key.pem", "ca.pem"):
        (tmp_path / name).write_text("dummy")

    monkeypatch.setenv("DOCKER_CERT_PATH", str(tmp_path))
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(docker, "DockerClient", FakeDockerClient)

    client = get_client("tcp://1.2.3.4:2375")

    assert client.kwargs["base_url"] == "tcp://1.2.3.4:2375"
    assert isinstance(client.kwargs["tls"], docker.tls.TLSConfig)


def test_get_client_tcp_without_tls_env(monkeypatch):
    monkeypatch.delenv("DOCKER_CERT_PATH", raising=False)
    monkeypatch.delenv("DOCKER_TLS_VERIFY", raising=False)
    monkeypatch.delenv("DOCKER_HOST", raising=False)
    monkeypatch.setattr(docker, "DockerClient", FakeDockerClient)

    client = get_client("tcp://1.2.3.4:2375")

    assert client.kwargs["base_url"] == "tcp://1.2.3.4:2375"
    assert "tls" not in client.kwargs


def test_get_client_unix_socket_unaffected(monkeypatch):
    monkeypatch.setenv("DOCKER_CERT_PATH", "/nonexistent")
    monkeypatch.setenv("DOCKER_TLS_VERIFY", "1")
    monkeypatch.setattr(docker, "DockerClient", FakeDockerClient)

    client = get_client("unix:///var/run/docker.sock")

    assert client.kwargs == {"base_url": "unix:///var/run/docker.sock"}
