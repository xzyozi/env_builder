"""Docker/PodmanのCLI差分を閉じ込めるengine adapter。"""

from __future__ import annotations

import shlex
from dataclasses import dataclass
from typing import Dict


@dataclass(frozen=True)
class EngineAdapter:
    """同一engineのCLIコマンドを安全に組み立てる。"""

    name: str
    executable: str

    def _identifier(self, value: str) -> str:
        return shlex.quote(value)

    def _image(self, value: str) -> str:
        return shlex.quote(value)

    def inspect_container_command(self, identifier: str) -> str:
        template = shlex.quote("{{json .}}")
        return f"{self.executable} inspect --format {template} -- {self._identifier(identifier)}"

    def inspect_image_command(self, image: str) -> str:
        template = shlex.quote("{{json .}}")
        return f"{self.executable} image inspect --format {template} -- {self._image(image)}"

    def export_command(self, identifier: str, archive_path: str) -> str:
        return f"{self.executable} export -- {self._identifier(identifier)} > {shlex.quote(archive_path)}"

    def import_command(self, archive_path: str, image: str) -> str:
        return f"{self.executable} import {shlex.quote(archive_path)} {self._image(image)}"

    def commit_command(self, identifier: str, image: str) -> str:
        return f"{self.executable} commit -- {self._identifier(identifier)} {self._image(image)}"

    def save_command(self, image: str, archive_path: str) -> str:
        return f"{self.executable} save --output {shlex.quote(archive_path)} {self._image(image)}"

    def load_command(self, archive_path: str) -> str:
        return f"{self.executable} load --input {shlex.quote(archive_path)}"

    def info_command(self) -> str:
        template = shlex.quote("{{json .}}")
        return f"{self.executable} info --format {template}"

    def version_command(self) -> str:
        return f"{self.executable} --version"

    def to_dict(self) -> Dict[str, str]:
        return {"name": self.name, "executable": self.executable}


_ADAPTERS = {
    "podman": EngineAdapter(name="podman", executable="podman"),
    "docker": EngineAdapter(name="docker", executable="docker"),
}


def get_engine_adapter(name: str) -> EngineAdapter:
    """engine名に対応するadapterを返す。"""
    try:
        return _ADAPTERS[name.lower()]
    except KeyError as exc:
        raise ValueError(f"未対応のcontainer engineです: {name!r}") from exc
