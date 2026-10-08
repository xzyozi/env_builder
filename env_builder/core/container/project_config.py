"""desired_state/container.local.json の読込と検証。"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from ..config import load_json
from .models import ContainerProjectConfig

_SUPPORTED_ENGINES = {"podman", "docker"}
_SUPPORTED_TRANSFER_MODES = {"export", "commit"}
_ENV_PREFIX_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def _required_text(data: Mapping[str, Any], key: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"container設定の {key} は空でない文字列で指定してください。")
    return value.strip()


def _validate_filename(path: Path) -> None:
    if path.name != path.as_posix().split("/")[-1] or path.name != path.name.strip():
        raise ValueError(f"container設定のファイル名が不正です: {path.name!r}")
    if path.name != Path(path.name).name:
        raise ValueError(f"container設定はdesired_state直下に置いてください: {path}")


def load_container_config(path: Path) -> ContainerProjectConfig:
    """コンテナ設定を読み込み、実行時に安全に使える形へ検証する。"""
    _validate_filename(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} がありません。プロジェクトのdesired_stateに、imageと対象containerを指定してください。"
        )

    raw = load_json(path)
    if not isinstance(raw, dict):
        raise ValueError(f"{path.name} はJSON objectで指定してください。")

    engine = _required_text(raw, "engine").lower()
    if engine not in _SUPPORTED_ENGINES:
        raise ValueError(f"engineは {_SUPPORTED_ENGINES} のいずれかで指定してください: {engine!r}")

    transfer_mode = str(raw.get("transfer_mode", "export")).strip().lower()
    if transfer_mode not in _SUPPORTED_TRANSFER_MODES:
        raise ValueError(f"transfer_modeは {_SUPPORTED_TRANSFER_MODES} のいずれかで指定してください: {transfer_mode!r}")

    secret_env_prefix = str(raw.get("secret_env_prefix", "ENVB_CONTAINER_")).strip().upper()
    if not _ENV_PREFIX_RE.fullmatch(secret_env_prefix.rstrip("_")):
        raise ValueError("secret_env_prefixは英大文字・数字・アンダースコアで指定してください。")
    if not secret_env_prefix.endswith("_"):
        secret_env_prefix += "_"

    return ContainerProjectConfig(
        engine=engine,
        image=_required_text(raw, "image"),
        source_target=_required_text(raw, "source_target"),
        destination_target=_required_text(raw, "destination_target"),
        container=_required_text(raw, "container"),
        transfer_mode=transfer_mode,
        secret_env_prefix=secret_env_prefix,
    )
