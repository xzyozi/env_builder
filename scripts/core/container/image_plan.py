"""containerからのimage取得・移送計画を生成する。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Optional

from .engines import EngineAdapter
from .models import ContainerProjectConfig, ImageTransferPlan

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9_.-]+")


def _timestamp(value: Optional[datetime]) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).strftime("%Y%m%d-%H%M%S")


def snapshot_image_ref(image: str, timestamp: Optional[datetime] = None) -> str:
    """既存image名へUTC timestamp tagを付ける。digestはsnapshot tagへ変換する。"""
    stamp = _timestamp(timestamp)
    repository = image.split("@", 1)[0]
    slash = repository.rfind("/")
    colon = repository.rfind(":")
    if colon > slash:
        repository = repository[:colon]
    return f"{repository}:{stamp}"


def _archive_name(project_id: str, timestamp: Optional[datetime]) -> str:
    stamp = _timestamp(timestamp)
    safe_project = _SAFE_NAME_RE.sub("-", project_id).strip("-._") or "project"
    return f"{safe_project}-container-{stamp}.tar"


def build_image_transfer_plan(
    config: ContainerProjectConfig,
    adapter: EngineAdapter,
    project_id: Optional[str] = None,
    timestamp: Optional[datetime] = None,
) -> ImageTransferPlan:
    """リモートworkspaceをplaceholderにした、承認前の移送計画を作る。"""
    project_name = project_id or "legacy"
    archive_name = _archive_name(project_name, timestamp)
    target_image = snapshot_image_ref(config.image, timestamp)
    source_archive = f"/tmp/env_builder-<work-id>-XXXXXX/{archive_name}"
    destination_archive = f"/tmp/env_builder-<work-id>-XXXXXX/{archive_name}"

    if config.transfer_mode == "export":
        source_commands = (adapter.export_command(config.container, source_archive),)
        destination_commands = (adapter.import_command(destination_archive, target_image),)
        warnings = (
            "export/importはfilesystemを移送しますが、元imageの履歴・親子関係は保持しません。",
            "bind mount、named volume、secret/config、device/GPU、networkはarchiveに含まれません。",
        )
    else:
        commit = adapter.commit_command(config.container, target_image)
        save = adapter.save_command(target_image, source_archive)
        source_commands = (f"{commit} && {save}",)
        destination_commands = (adapter.load_command(destination_archive),)
        warnings = (
            "commitは移送元のimage storeを変更するため、明示承認が必要です。",
            "bind mount、named volume、secret/config、device/GPU、networkはimageに含まれません。",
        )

    return ImageTransferPlan(
        engine=config.engine,
        mode=config.transfer_mode,
        source_target=config.source_target,
        destination_target=config.destination_target,
        source_container=config.container,
        source_image=config.image,
        target_image=target_image,
        archive_name=archive_name,
        source_commands=source_commands,
        destination_commands=destination_commands,
        warnings=warnings,
    )
