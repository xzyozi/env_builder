"""ops.container がセッションを引数で受け取ることの検証。接続は使わず fake に差し替える。"""

import json
from typing import Any, List

import pytest

from env_builder.core.container.engines import get_engine_adapter
from env_builder.core.container.models import ContainerProjectConfig
from env_builder.core.ssh import SSHResult
from env_builder.ops.container import ContainerOperationError, inspect_container, inspect_runtime_context


class FakeSession:
    def __init__(self, results: List[SSHResult], opened: List[str], target: str) -> None:
        self._results = results
        self.opened = opened
        self.target = target
        self.commands: List[str] = []

    def __enter__(self) -> "FakeSession":
        self.opened.append(self.target)
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def run(self, command: str, timeout: int = 600, **kwargs: Any) -> SSHResult:
        self.commands.append(command)
        return self._results.pop(0)


@pytest.fixture
def config() -> ContainerProjectConfig:
    return ContainerProjectConfig(
        engine="podman",
        image="registry.example/app:stable",
        source_target="src",
        destination_target="dst",
        container="app",
    )


def test_inspect_container_uses_injected_session(config: ContainerProjectConfig) -> None:
    opened: List[str] = []
    raw = {"Id": "cid", "Name": "/app", "Config": {"Cmd": ["serve"]}, "HostConfig": {}}
    results = [SSHResult(0, json.dumps([raw]), "")]

    inspection = inspect_container(
        lambda target: FakeSession(results, opened, target), config, get_engine_adapter("podman")
    )

    assert opened == ["src"]
    assert inspection.container_id == "cid"


def test_inspect_container_reports_failure_as_operation_error(config: ContainerProjectConfig) -> None:
    results = [SSHResult(1, "", "no such container")]

    with pytest.raises(ContainerOperationError):
        inspect_container(lambda target: FakeSession(results, [], target), config, get_engine_adapter("podman"))


def test_inspect_runtime_context_uses_injected_session() -> None:
    opened: List[str] = []
    results = [SSHResult(0, "1000\n", ""), SSHResult(0, "{}", "")]

    inspect_runtime_context(lambda target: FakeSession(results, opened, target), "dst", get_engine_adapter("podman"))

    assert opened == ["dst"]
