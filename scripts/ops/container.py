"""SSHSessionを使うコンテナ調査・image移送処理。"""

from __future__ import annotations

import json
import posixpath
from typing import Any, Dict, Optional

from core.config import Inventory, load_inventory
from core.container.context import RuntimeContext, normalize_runtime_context
from core.container.engines import EngineAdapter
from core.container.inspect import InspectionError, normalize_container_inspection, parse_inspect_json
from core.container.models import ContainerInspection, ContainerProjectConfig, ImageTransferPlan
from core.logging_utils import get_logger, new_run_dir
from core.project import ProjectProfile
from core.ssh import SSHSession
from core.work_context import WorkContext


class ContainerOperationError(RuntimeError):
    """リモートcontainer操作に失敗した場合のエラー。"""


def inspect_container(
    inventory: Inventory,
    config: ContainerProjectConfig,
    adapter: EngineAdapter,
    timeout: int = 120,
) -> ContainerInspection:
    """移送元のcontainer inspectを読み取り、共通モデルへ変換する。"""
    with SSHSession(inventory, config.source_target) as ssh:
        result = ssh.run(adapter.inspect_container_command(config.container), timeout=timeout)
    if not result.ok:
        detail = result.stderr.strip() or result.stdout.strip() or "詳細不明"
        raise ContainerOperationError(f"container inspectに失敗しました: exit={result.exit_code}: {detail[:500]}")
    try:
        raw = parse_inspect_json(result.stdout)
        return normalize_container_inspection(raw, config)
    except InspectionError as exc:
        raise ContainerOperationError(f"container inspectの解析に失敗しました: {exc}") from exc


def inspect_runtime_context(
    inventory: Inventory,
    target: str,
    adapter: EngineAdapter,
    timeout: int = 120,
) -> RuntimeContext:
    """SSHユーザーとengine infoからruntime contextを読み取る。"""
    with SSHSession(inventory, target) as ssh:
        uid_result = ssh.run("id -u", timeout=timeout)
        info_result = ssh.run(adapter.info_command(), timeout=timeout)
    if not uid_result.ok:
        raise ContainerOperationError(f"runtimeユーザーのUID取得に失敗しました: target={target}")
    if not info_result.ok:
        detail = info_result.stderr.strip() or info_result.stdout.strip() or "詳細不明"
        raise ContainerOperationError(f"container engine infoに失敗しました: target={target}: {detail[:500]}")
    try:
        info = parse_inspect_json(info_result.stdout)
    except InspectionError as exc:
        raise ContainerOperationError(f"container engine infoの解析に失敗しました: target={target}: {exc}") from exc
    return normalize_runtime_context(adapter.name, uid_result.stdout, info)


def execute_image_transfer(
    profile: ProjectProfile,
    config: ContainerProjectConfig,
    adapter: EngineAdapter,
    plan: ImageTransferPlan,
    timeout: int = 600,
) -> Dict[str, Any]:
    """承認済みのimage移送をsrc→手元→dstの順に実行する。"""
    inventory = load_inventory(profile.inventory_path)
    logger = get_logger(project_id=profile.project_id)
    local_run_dir = new_run_dir(
        label="container_image",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    )

    result_payload: Dict[str, Any] = {
        "status": "failed",
        "mode": plan.mode,
        "target_image": plan.target_image,
        "archive_name": plan.archive_name,
        "source_target": plan.source_target,
        "destination_target": plan.destination_target,
        "run_dir": str(local_run_dir),
    }

    with WorkContext(
        "container-image",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    ) as work:
        local_archive = work.stage_dir / plan.archive_name
        source_workspace = None
        destination_workspace = None
        source_archive = None
        destination_archive = None
        try:
            logger.info("移送元(%s)でimage archiveを作成します", config.source_target)
            with SSHSession(inventory, config.source_target) as source_ssh:
                source_workspace = work.create_remote_workspace(source_ssh, config.source_target, timeout=timeout)
                source_archive = posixpath.join(source_workspace, plan.archive_name)
                if plan.mode == "commit":
                    _ensure_image_absent(source_ssh, adapter, plan.target_image, timeout, location="移送元")
                source_commands = _source_commands(adapter, config, plan, source_archive)
                source_result = source_ssh.run(source_commands, timeout=timeout)
                if not source_result.ok:
                    raise ContainerOperationError(
                        f"移送元のimage archive作成に失敗しました: exit={source_result.exit_code}: "
                        f"{source_result.stderr.strip()[:500]}"
                    )
                source_ssh.get_file(source_archive, str(local_archive))
                logger.info("archiveを取得しました: %s (%d bytes)", local_archive.name, local_archive.stat().st_size)
                if not work.cleanup_remote_workspace(source_ssh, config.source_target, source_workspace, timeout):
                    raise ContainerOperationError("移送元の一時作業領域をcleanupできませんでした。")
                source_workspace = None

            logger.info("移送先(%s)へimage archiveを転送します", config.destination_target)
            with SSHSession(inventory, config.destination_target) as destination_ssh:
                destination_workspace = work.create_remote_workspace(
                    destination_ssh,
                    config.destination_target,
                    timeout=timeout,
                )
                destination_archive = posixpath.join(destination_workspace, plan.archive_name)
                destination_ssh.put_file(str(local_archive), destination_archive)
                _ensure_image_absent(
                    destination_ssh,
                    adapter,
                    plan.target_image,
                    timeout,
                    location="移送先",
                )
                destination_commands = _destination_commands(adapter, plan, destination_archive)
                destination_result = destination_ssh.run(destination_commands, timeout=timeout)
                if not destination_result.ok:
                    raise ContainerOperationError(
                        f"移送先へのimage import/loadに失敗しました: exit={destination_result.exit_code}: "
                        f"{destination_result.stderr.strip()[:500]}"
                    )
                verify_result = destination_ssh.run(
                    adapter.inspect_image_command(plan.target_image),
                    timeout=timeout,
                )
                if not verify_result.ok:
                    raise ContainerOperationError(
                        f"移送先imageの検証に失敗しました: exit={verify_result.exit_code}: "
                        f"{verify_result.stderr.strip()[:500]}"
                    )
                if not work.cleanup_remote_workspace(
                    destination_ssh,
                    config.destination_target,
                    destination_workspace,
                    timeout,
                ):
                    raise ContainerOperationError("移送先の一時作業領域をcleanupできませんでした。")
                destination_workspace = None

            result_payload.update({"status": "completed", **_extract_image_identity(verify_result.stdout)})
            work.complete()
        except Exception as exc:
            result_payload["error"] = str(exc)
            logger.error("image移送に失敗しました: %s", exc)
        finally:
            if source_workspace:
                _cleanup_workspace(work, inventory, config.source_target, source_workspace, timeout, logger)
            if destination_workspace:
                _cleanup_workspace(work, inventory, config.destination_target, destination_workspace, timeout, logger)

    (local_run_dir / "transfer-result.json").write_text(
        json.dumps(result_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result_payload


def _source_commands(
    adapter: EngineAdapter,
    config: ContainerProjectConfig,
    plan: ImageTransferPlan,
    archive_path: str,
) -> str:
    if plan.mode == "export":
        return adapter.export_command(config.container, archive_path)
    commit = adapter.commit_command(config.container, plan.target_image)
    save = adapter.save_command(plan.target_image, archive_path)
    return f"{commit} && {save}"


def _destination_commands(adapter: EngineAdapter, plan: ImageTransferPlan, archive_path: str) -> str:
    if plan.mode == "export":
        return adapter.import_command(archive_path, plan.target_image)
    return adapter.load_command(archive_path)


def _cleanup_workspace(work, inventory, target: str, path: str, timeout: int, logger) -> None:
    try:
        with SSHSession(inventory, target) as ssh:
            if not work.cleanup_remote_workspace(ssh, target, path, timeout):
                logger.error("リモート一時作業領域のcleanupに失敗しました: target=%s path=%s", target, path)
    except Exception as exc:
        logger.error("リモート一時作業領域のcleanup確認に失敗しました: %s", exc)


def _ensure_image_absent(
    ssh,
    adapter: EngineAdapter,
    image: str,
    timeout: int,
    *,
    location: str,
) -> None:
    result = ssh.run(adapter.inspect_image_command(image), timeout=timeout)
    if result.ok:
        raise ContainerOperationError(f"{location}に同名imageが既に存在します。上書きしません: {image}")
    detail = (result.stderr or result.stdout).lower()
    missing_markers = ("no such image", "image not known", "not found", "does not exist")
    if not any(marker in detail for marker in missing_markers):
        raise ContainerOperationError(
            f"{location}の既存image確認に失敗しました: exit={result.exit_code}: "
            f"{(result.stderr or result.stdout).strip()[:500]}"
        )


def _extract_image_identity(stdout: str) -> Dict[str, Optional[str]]:
    try:
        raw = parse_inspect_json(stdout)
    except InspectionError:
        return {"image_id": None, "digest": None}

    image_id = raw.get("Id") or raw.get("ID")
    digest = raw.get("Digest")
    repo_digests = raw.get("RepoDigests")
    if not digest and isinstance(repo_digests, list) and repo_digests:
        first_digest = str(repo_digests[0])
        digest = first_digest.split("@", 1)[1] if "@" in first_digest else first_digest
    return {
        "image_id": str(image_id) if image_id else None,
        "digest": str(digest) if digest else None,
    }
