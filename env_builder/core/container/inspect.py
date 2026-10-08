"""Docker/Podman inspect JSONを共通のrun仕様へ正規化する。"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from json import JSONDecodeError
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from .models import (
    ContainerInspection,
    ContainerProjectConfig,
    ContainerRunSpec,
    EnvironmentEntry,
    MountSpec,
    PortSpec,
)

_SECRET_KEY_RE = re.compile(
    r"(?:PASSWORD|PASSWD|TOKEN|SECRET|API[_-]?KEY|PRIVATE[_-]?KEY|CREDENTIAL|AUTH)",
    re.IGNORECASE,
)
_SAFE_ENV_NAME_RE = re.compile(r"[^A-Za-z0-9_]+")


class InspectionError(ValueError):
    """inspect結果を解析できない場合のエラー。"""


def parse_inspect_json(stdout: str) -> dict:
    """ログインシェルの余分な出力を許容しつつ、最初のJSON objectを読む。"""
    text = stdout.strip()
    if not text:
        raise InspectionError("container inspectのstdoutが空です。")

    try:
        value = json.loads(text)
    except JSONDecodeError:
        decoder = json.JSONDecoder()
        for index, char in enumerate(text):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(text[index:])
            except JSONDecodeError:
                continue
            break
        else:
            raise InspectionError("container inspectのstdoutからJSON objectを見つけられません。")

    if isinstance(value, list):
        if len(value) != 1 or not isinstance(value[0], dict):
            raise InspectionError("container inspectのJSONは単一のobjectを返してください。")
        value = value[0]
    if not isinstance(value, dict):
        raise InspectionError("container inspectのJSONがobjectではありません。")
    return value


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first_text(mapping: Mapping[str, Any], *keys: str) -> Optional[str]:
    for key in keys:
        value = mapping.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _as_tuple(value: Any) -> Tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(item) for item in value if item is not None)
    return ()


def _secret_reference(prefix: str, key: str) -> str:
    safe_key = _SAFE_ENV_NAME_RE.sub("_", key.upper()).strip("_") or "VALUE"
    return f"${{{prefix}{safe_key}}}"


def _parse_environment(config: Mapping[str, Any], prefix: str) -> Tuple[EnvironmentEntry, ...]:
    raw_env = config.get("Env", [])
    entries: List[EnvironmentEntry] = []
    if isinstance(raw_env, Mapping):
        raw_items: Iterable[Any] = [f"{key}={value}" for key, value in raw_env.items()]
    elif isinstance(raw_env, Sequence) and not isinstance(raw_env, (str, bytes, bytearray)):
        raw_items = raw_env
    else:
        raw_items = []

    for item in raw_items:
        if not isinstance(item, str):
            continue
        if "=" in item:
            name, value = item.split("=", 1)
        else:
            name, value = item, None
        if not name:
            continue
        if _SECRET_KEY_RE.search(name):
            entries.append(EnvironmentEntry(name=name, reference=_secret_reference(prefix, name)))
        else:
            entries.append(EnvironmentEntry(name=name, value=value))
    return tuple(entries)


def _mount_from_mapping(item: Mapping[str, Any]) -> Optional[MountSpec]:
    destination = _first_text(item, "Destination", "destination", "Target", "target")
    if not destination:
        return None
    source = _first_text(item, "Source", "source", "Src", "src")
    kind = _first_text(item, "Type", "type") or "bind"
    options = item.get("Options", item.get("options", []))
    option_values = {str(option).lower() for option in options} if isinstance(options, Sequence) else set()
    read_only = item.get("RW") is False or item.get("ReadOnly") is True or "ro" in option_values
    return MountSpec(kind=kind, source=source, destination=destination, read_only=read_only)


def _mount_from_bind(value: str) -> Optional[MountSpec]:
    parts = value.split(":")
    if len(parts) < 2:
        return None
    source, destination = parts[0], parts[1]
    options = {part.lower() for part in parts[2:]}
    return MountSpec(kind="bind", source=source, destination=destination, read_only="ro" in options)


def _parse_mounts(raw: Mapping[str, Any], host_config: Mapping[str, Any]) -> Tuple[MountSpec, ...]:
    result: List[MountSpec] = []
    raw_mounts = raw.get("Mounts")
    if isinstance(raw_mounts, Sequence) and not isinstance(raw_mounts, (str, bytes, bytearray)):
        for item in raw_mounts:
            if isinstance(item, Mapping):
                mount = _mount_from_mapping(item)
                if mount:
                    result.append(mount)

    binds = host_config.get("Binds", [])
    if isinstance(binds, Sequence) and not isinstance(binds, (str, bytes, bytearray)):
        for item in binds:
            if isinstance(item, str):
                mount = _mount_from_bind(item)
                if mount:
                    result.append(mount)

    unique: List[MountSpec] = []
    seen = set()
    for mount in result:
        key = (mount.kind, mount.source, mount.destination, mount.read_only)
        if key not in seen:
            unique.append(mount)
            seen.add(key)
    return tuple(unique)


def _parse_ports(raw: Mapping[str, Any], host_config: Mapping[str, Any]) -> Tuple[PortSpec, ...]:
    network = _mapping(raw.get("NetworkSettings"))
    raw_ports = network.get("Ports") or host_config.get("PortBindings") or {}
    result: List[PortSpec] = []
    if not isinstance(raw_ports, Mapping):
        return ()

    for container_key, bindings in raw_ports.items():
        key = str(container_key)
        if "/" in key:
            container_port, protocol = key.split("/", 1)
        else:
            container_port, protocol = key, "tcp"
        if bindings is None:
            continue
        if isinstance(bindings, Mapping):
            bindings = [bindings]
        if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes, bytearray)):
            continue
        for binding in bindings:
            binding_map = _mapping(binding)
            host_port = _first_text(binding_map, "HostPort", "hostPort", "host_port")
            host_ip = _first_text(binding_map, "HostIp", "HostIP", "hostIP", "host_ip")
            result.append(
                PortSpec(
                    container_port=container_port,
                    protocol=protocol,
                    host_port=host_port,
                    host_ip=host_ip,
                )
            )
    return tuple(result)


def _unsupported_fields(host_config: Mapping[str, Any], config: Mapping[str, Any]) -> Tuple[str, ...]:
    fields = []
    checks = (
        ("privileged", host_config.get("Privileged")),
        ("capabilities", host_config.get("CapAdd") or host_config.get("CapDrop")),
        ("devices", host_config.get("Devices")),
        ("ulimits", host_config.get("Ulimits")),
        ("resource_limits", host_config.get("Resources")),
        ("readonly_rootfs", host_config.get("ReadonlyRootfs")),
        ("healthcheck", config.get("Healthcheck")),
    )
    for name, value in checks:
        if value:
            fields.append(name)
    return tuple(fields)


def normalize_container_inspection(
    raw: Mapping[str, Any],
    project_config: ContainerProjectConfig,
) -> ContainerInspection:
    """Docker/Podmanのinspect objectを秘密値なしの共通モデルへ変換する。"""
    config = _mapping(raw.get("Config"))
    host_config = _mapping(raw.get("HostConfig"))
    state = _mapping(raw.get("State"))
    network = _mapping(raw.get("NetworkSettings"))

    container_id = _first_text(raw, "Id", "ID") or "unknown"
    name = (_first_text(raw, "Name", "Name") or project_config.container).lstrip("/")
    status = _first_text(state, "Status", "status")
    source_image = _first_text(raw, "ImageName", "Image", "image") or _first_text(config, "Image")

    warnings: List[str] = []
    if source_image and source_image != project_config.image:
        warnings.append(
            f"参照containerのimage ({source_image}) とプロジェクトimage ({project_config.image}) が異なります。"
        )
    if not source_image:
        warnings.append("参照containerの元imageをinspectから取得できません。")

    network_mode = _first_text(host_config, "NetworkMode", "network_mode")
    if network_mode in {"", "default", "bridge"}:
        network_mode = None

    restart_policy = _mapping(host_config.get("RestartPolicy"))
    restart = _first_text(restart_policy, "Name", "name")
    unsupported = _unsupported_fields(host_config, config)
    if unsupported:
        warnings.append("高度な設定はrun候補へ反映せず、unsupportedとして記録します。")

    volumes = config.get("Volumes")
    if volumes:
        warnings.append("imageまたはcontainerのvolume宣言は自動移送せず、別途確認が必要です。")

    run_spec = ContainerRunSpec(
        engine=project_config.engine,
        image=project_config.image,
        name=name or None,
        hostname=_first_text(config, "Hostname", "hostname"),
        user=_first_text(config, "User", "user"),
        workdir=_first_text(config, "WorkingDir", "working_dir"),
        entrypoint=_as_tuple(config.get("Entrypoint")),
        command=_as_tuple(config.get("Cmd")) or _as_tuple(raw.get("Args")),
        environment=_parse_environment(config, project_config.secret_env_prefix),
        mounts=_parse_mounts(raw, host_config),
        ports=_parse_ports(raw, host_config),
        network=network_mode or _first_text(network, "NetworkMode"),
        restart=restart,
        warnings=tuple(warnings),
        unsupported=unsupported,
    )
    return ContainerInspection(
        container_id=container_id,
        name=name,
        status=status,
        source_image=source_image,
        run_spec=run_spec,
    )
