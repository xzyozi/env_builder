import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.core.container.context import compare_runtime_contexts, normalize_runtime_context
from scripts.core.container.engines import get_engine_adapter
from scripts.core.container.image_plan import build_image_transfer_plan, snapshot_image_ref
from scripts.core.container.inspect import InspectionError, normalize_container_inspection, parse_inspect_json
from scripts.core.container.models import ContainerProjectConfig
from scripts.core.container.project_config import load_container_config
from scripts.core.container.run_spec import render_run_command


@pytest.fixture
def project_config() -> ContainerProjectConfig:
    return ContainerProjectConfig(
        engine="podman",
        image="registry.example/app:stable",
        source_target="src",
        destination_target="dst",
        container="app",
    )


def test_load_container_config_validates_project_settings(tmp_path: Path) -> None:
    path = tmp_path / "container.local.json"
    path.write_text(
        json.dumps(
            {
                "engine": "docker",
                "image": "example/app:stable",
                "source_target": "src",
                "destination_target": "dst",
                "container": "app",
                "transfer_mode": "export",
            }
        ),
        encoding="utf-8",
    )

    config = load_container_config(path)

    assert config.engine == "docker"
    assert config.transfer_mode == "export"
    assert config.secret_env_prefix == "ENVB_CONTAINER_"


def test_load_container_config_rejects_unsupported_engine(tmp_path: Path) -> None:
    path = tmp_path / "container.local.json"
    path.write_text(
        json.dumps(
            {
                "engine": "nerdctl",
                "image": "example/app",
                "source_target": "src",
                "destination_target": "dst",
                "container": "app",
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="engine"):
        load_container_config(path)


def test_parse_inspect_json_accepts_shell_noise() -> None:
    value = parse_inspect_json('logout\n{"Id": "abc"}\n')

    assert value == {"Id": "abc"}


def test_parse_inspect_json_rejects_non_object() -> None:
    with pytest.raises(InspectionError):
        parse_inspect_json("[]")


def test_normalize_inspection_masks_secret_and_collects_basic_options(project_config: ContainerProjectConfig) -> None:
    raw = {
        "Id": "container-id",
        "Name": "/app",
        "ImageName": "registry.example/app:old",
        "State": {"Status": "running"},
        "Config": {
            "Hostname": "app-host",
            "User": "1000",
            "WorkingDir": "/work",
            "Entrypoint": ["/entrypoint.sh"],
            "Cmd": ["serve"],
            "Env": ["MODE=prod", "APP_PASSWORD=do-not-store"],
        },
        "HostConfig": {
            "Binds": ["/srv/app:/data:ro"],
            "NetworkMode": "app-net",
            "PortBindings": {"8080/tcp": [{"HostPort": "18080", "HostIp": "127.0.0.1"}]},
            "RestartPolicy": {"Name": "always"},
            "Privileged": True,
        },
    }

    inspection = normalize_container_inspection(raw, project_config)
    run_spec = inspection.run_spec

    assert inspection.container_id == "container-id"
    assert run_spec.image == project_config.image
    assert run_spec.environment[1].reference == "${ENVB_CONTAINER_APP_PASSWORD}"
    assert run_spec.environment[1].value is None
    assert run_spec.mounts[0].read_only is True
    assert run_spec.ports[0].host_port == "18080"
    assert run_spec.network == "app-net"
    assert "privileged" in run_spec.unsupported
    assert any("image" in warning for warning in run_spec.warnings)


def test_render_run_command_uses_environment_reference(project_config: ContainerProjectConfig) -> None:
    raw = {
        "Id": "container-id",
        "Name": "/app",
        "Config": {
            "Env": ["APP_TOKEN=secret"],
            "Cmd": ["serve"],
        },
        "HostConfig": {},
    }
    inspection = normalize_container_inspection(raw, project_config)

    command = render_run_command(inspection.run_spec)

    assert 'APP_TOKEN="$ENVB_CONTAINER_APP_TOKEN"' in command
    assert "secret" not in command
    assert "podman run" in command


def test_snapshot_image_ref_uses_utc_timestamp() -> None:
    timestamp = datetime(2026, 10, 6, 15, 30, tzinfo=timezone.utc)

    assert snapshot_image_ref("registry.example/app:stable", timestamp) == "registry.example/app:20261006-153000"
    assert snapshot_image_ref("registry.example/app@sha256:abc", timestamp) == "registry.example/app:20261006-153000"


def test_image_transfer_plan_has_safe_placeholders(project_config: ContainerProjectConfig) -> None:
    timestamp = datetime(2026, 10, 6, 15, 30, tzinfo=timezone.utc)
    adapter = get_engine_adapter(project_config.engine)

    plan = build_image_transfer_plan(project_config, adapter, "project-a", timestamp)

    assert plan.mode == "export"
    assert plan.target_image == "registry.example/app:20261006-153000"
    assert "<work-id>" in plan.source_commands[0]
    assert "podman export" in plan.source_commands[0]
    assert "podman import" in plan.destination_commands[0]


def test_commit_image_transfer_plan_contains_commit_and_save(project_config: ContainerProjectConfig) -> None:
    config = ContainerProjectConfig(
        engine=project_config.engine,
        image=project_config.image,
        source_target=project_config.source_target,
        destination_target=project_config.destination_target,
        container=project_config.container,
        transfer_mode="commit",
    )
    adapter = get_engine_adapter(config.engine)

    plan = build_image_transfer_plan(config, adapter, "project-a")

    assert "podman commit" in plan.source_commands[0]
    assert "podman save" in plan.source_commands[0]
    assert "podman load" in plan.destination_commands[0]


def test_runtime_context_warns_on_rootless_and_uid_difference() -> None:
    source = normalize_runtime_context(
        "podman",
        "1000\n",
        {"host": {"rootless": True}, "Version": "5.0"},
    )
    destination = normalize_runtime_context(
        "podman",
        "0\n",
        {"host": {"rootless": False}, "Version": "5.0"},
    )

    warnings = compare_runtime_contexts(source, destination)

    assert any("rootless/rootful" in warning for warning in warnings)
    assert any("UID" in warning for warning in warnings)
