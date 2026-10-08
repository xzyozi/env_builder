"""コンテナ機能で共有する、秘密値を保持しないデータモデル。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple


@dataclass(frozen=True)
class ContainerProjectConfig:
    """プロジェクトのコンテナ設定。実行時の秘密値は保持しない。"""

    engine: str
    image: str
    source_target: str
    destination_target: str
    container: str
    transfer_mode: str = "export"
    secret_env_prefix: str = "ENVB_CONTAINER_"

    def to_dict(self) -> Dict[str, str]:
        return {
            "engine": self.engine,
            "image": self.image,
            "source_target": self.source_target,
            "destination_target": self.destination_target,
            "container": self.container,
            "transfer_mode": self.transfer_mode,
            "secret_env_prefix": self.secret_env_prefix,
        }


@dataclass(frozen=True)
class EnvironmentEntry:
    """コンテナ環境変数。秘密値はreferenceだけを保持する。"""

    name: str
    value: Optional[str] = None
    reference: Optional[str] = None

    @property
    def is_reference(self) -> bool:
        return self.reference is not None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "name": self.name,
            "value": None if self.is_reference else self.value,
            "reference": self.reference,
        }


@dataclass(frozen=True)
class MountSpec:
    """コンテナ内へ公開されるmount。"""

    kind: str
    source: Optional[str]
    destination: str
    read_only: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "source": self.source,
            "destination": self.destination,
            "read_only": self.read_only,
        }


@dataclass(frozen=True)
class PortSpec:
    """公開port。"""

    container_port: str
    protocol: str = "tcp"
    host_port: Optional[str] = None
    host_ip: Optional[str] = None

    def to_dict(self) -> Dict[str, Optional[str]]:
        return {
            "container_port": self.container_port,
            "protocol": self.protocol,
            "host_port": self.host_port,
            "host_ip": self.host_ip,
        }


@dataclass(frozen=True)
class ContainerRunSpec:
    """inspect結果から生成した、基本的なrun候補。"""

    engine: str
    image: str
    name: Optional[str] = None
    hostname: Optional[str] = None
    user: Optional[str] = None
    workdir: Optional[str] = None
    entrypoint: Tuple[str, ...] = field(default_factory=tuple)
    command: Tuple[str, ...] = field(default_factory=tuple)
    environment: Tuple[EnvironmentEntry, ...] = field(default_factory=tuple)
    mounts: Tuple[MountSpec, ...] = field(default_factory=tuple)
    ports: Tuple[PortSpec, ...] = field(default_factory=tuple)
    network: Optional[str] = None
    restart: Optional[str] = None
    warnings: Tuple[str, ...] = field(default_factory=tuple)
    unsupported: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "image": self.image,
            "name": self.name,
            "hostname": self.hostname,
            "user": self.user,
            "workdir": self.workdir,
            "entrypoint": list(self.entrypoint),
            "command": list(self.command),
            "environment": [entry.to_dict() for entry in self.environment],
            "mounts": [mount.to_dict() for mount in self.mounts],
            "ports": [port.to_dict() for port in self.ports],
            "network": self.network,
            "restart": self.restart,
            "warnings": list(self.warnings),
            "unsupported": list(self.unsupported),
        }


@dataclass(frozen=True)
class ContainerInspection:
    """秘密値を除去したcontainer inspectの要約。"""

    container_id: str
    name: str
    status: Optional[str]
    source_image: Optional[str]
    run_spec: ContainerRunSpec

    def to_dict(self) -> Dict[str, Any]:
        return {
            "container_id": self.container_id,
            "name": self.name,
            "status": self.status,
            "source_image": self.source_image,
            "run_spec": self.run_spec.to_dict(),
        }


@dataclass(frozen=True)
class ImageTransferPlan:
    """image移送の承認前計画。リモートパスはplaceholderで表す。"""

    engine: str
    mode: str
    source_target: str
    destination_target: str
    source_container: str
    source_image: str
    target_image: str
    archive_name: str
    source_commands: Tuple[str, ...]
    destination_commands: Tuple[str, ...]
    warnings: Tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "engine": self.engine,
            "mode": self.mode,
            "source_target": self.source_target,
            "destination_target": self.destination_target,
            "source_container": self.source_container,
            "source_image": self.source_image,
            "target_image": self.target_image,
            "archive_name": self.archive_name,
            "source_commands": list(self.source_commands),
            "destination_commands": list(self.destination_commands),
            "warnings": list(self.warnings),
        }
