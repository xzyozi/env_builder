"""共通run仕様をengine別の安全な表示コマンドへ変換する。"""

from __future__ import annotations

import re
import shlex
from typing import List

from .models import ContainerRunSpec, EnvironmentEntry, MountSpec, PortSpec

_SAFE_REFERENCE_RE = re.compile(r"^\$\{([A-Z][A-Z0-9_]*)\}$")


def _append_option(parts: List[str], option: str, value: str) -> None:
    parts.append(option)
    parts.append(shlex.quote(value))


def _render_environment(parts: List[str], entry: EnvironmentEntry) -> None:
    parts.append("--env")
    if entry.reference:
        match = _SAFE_REFERENCE_RE.fullmatch(entry.reference)
        if match:
            parts.append(f'{entry.name}="${match.group(1)}"')
            return
    if entry.value is None:
        parts.append(shlex.quote(entry.name))
    else:
        parts.append(shlex.quote(f"{entry.name}={entry.value}"))


def _render_mount(mount: MountSpec) -> str:
    fields = [f"type={mount.kind}"]
    if mount.source:
        fields.append(f"src={mount.source}")
    fields.append(f"dst={mount.destination}")
    if mount.read_only:
        fields.append("readonly")
    return ",".join(fields)


def _render_port(port: PortSpec) -> str:
    container = f"{port.container_port}/{port.protocol}"
    if not port.host_port:
        return container
    if port.host_ip:
        return f"{port.host_ip}:{port.host_port}:{container}"
    return f"{port.host_port}:{container}"


def render_run_command(spec: ContainerRunSpec) -> str:
    """run候補をshell表示用文字列にする。値はshell quoteして出力する。"""
    parts = [shlex.quote(spec.engine), "run", "-d"]

    if spec.name:
        _append_option(parts, "--name", spec.name)
    if spec.hostname:
        _append_option(parts, "--hostname", spec.hostname)
    if spec.user:
        _append_option(parts, "--user", spec.user)
    if spec.workdir:
        _append_option(parts, "--workdir", spec.workdir)
    if spec.entrypoint:
        _append_option(parts, "--entrypoint", spec.entrypoint[0])
    for entry in spec.environment:
        _render_environment(parts, entry)
    for mount in spec.mounts:
        _append_option(parts, "--mount", _render_mount(mount))
    for port in spec.ports:
        _append_option(parts, "--publish", _render_port(port))
    if spec.network:
        _append_option(parts, "--network", spec.network)
    if spec.restart:
        _append_option(parts, "--restart", spec.restart)

    parts.append(shlex.quote(spec.image))
    parts.extend(shlex.quote(argument) for argument in spec.command)
    return " ".join(parts)
