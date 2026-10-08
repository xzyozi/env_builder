"""作業単位のローカル／リモート一時領域を管理する。"""

from __future__ import annotations

import json
import posixpath
import re
import secrets
import shlex
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from .config import BUILD_ENV_DIR
from .project import validate_project_id

if TYPE_CHECKING:
    from .ssh import CommandRunner


_REMOTE_WORK_PREFIX = "env_builder-"
_REMOTE_MARKER = ".env_builder_marker"
_SAFE_LABEL_RE = re.compile(r"[^A-Za-z0-9_-]+")


def _safe_label(label: str) -> str:
    """作業IDに利用できるラベルへ変換する。"""
    normalized = _SAFE_LABEL_RE.sub("-", label).strip("-_")
    return (normalized or "work")[:24]


def _new_work_id(label: str) -> str:
    """衝突しにくく、shellへ安全に渡せる作業IDを生成する。"""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"{_safe_label(label)}-{timestamp}-{secrets.token_hex(4)}"


def _validate_remote_workspace(path: str, work_id: str) -> None:
    """cleanup対象として安全なリモート作業ディレクトリか検証する。"""
    normalized = posixpath.normpath(path)
    expected_prefix = f"{_REMOTE_WORK_PREFIX}{work_id}-"
    name = posixpath.basename(normalized)

    if path != normalized or posixpath.dirname(normalized) != "/tmp":
        raise ValueError(f"リモート作業領域が /tmp 直下ではありません: {path!r}")
    if not name.startswith(expected_prefix) or len(name) == len(expected_prefix):
        raise ValueError(f"リモート作業領域の形式が不正です: {path!r}")


@dataclass
class WorkContext:
    """1回の作業に必要な一時領域とcleanup結果を管理する。"""

    label: str
    keep_workdir: bool = False
    build_env_dir: Path = BUILD_ENV_DIR
    project_id: Optional[str] = None
    work_id: str = field(init=False)
    work_dir: Path = field(init=False)
    stage_dir: Path = field(init=False)
    manifest_path: Path = field(init=False)
    _completed: bool = field(default=False, init=False)
    _remote_workspaces: list[dict[str, Any]] = field(default_factory=list, init=False)

    def __post_init__(self) -> None:
        if self.project_id is not None:
            validate_project_id(self.project_id)
        self.work_id = _new_work_id(self.label)

    def __enter__(self) -> "WorkContext":
        local_root = self.build_env_dir / "work"
        local_root.mkdir(parents=True, exist_ok=True)

        self.work_dir = local_root / self.work_id
        self.work_dir.mkdir(mode=0o700)
        self.stage_dir = self.work_dir / "stage"
        self.stage_dir.mkdir(mode=0o700)

        manifest_dir = self.build_env_dir / "logs" / f"work_{self.work_id}"
        manifest_dir.mkdir(parents=True, exist_ok=True)
        self.manifest_path = manifest_dir / "manifest.json"
        self._write_manifest(status="running", local_cleanup="pending")
        return self

    def complete(self) -> None:
        """作業本体が成功したことを記録する。"""
        self._completed = True

    def create_remote_workspace(self, ssh: "CommandRunner", target: str, timeout: int = 120) -> str:
        """リモートの /tmp 直下に専用作業ディレクトリを作成する。"""
        template = f"/tmp/{_REMOTE_WORK_PREFIX}{self.work_id}-XXXXXX"
        quoted_template = shlex.quote(template)
        quoted_work_id = shlex.quote(self.work_id)
        command = (
            "set -eu; "
            "work_dir=''; "
            'trap \'if [ -n "$work_dir" ]; then rm -rf -- "$work_dir"; fi\' EXIT HUP INT TERM; '
            f"work_dir=$(mktemp -d -- {quoted_template}); "
            f"printf '%s\\n' {quoted_work_id} > \"$work_dir/{_REMOTE_MARKER}\"; "
            f'chmod 600 "$work_dir/{_REMOTE_MARKER}"; '
            "trap - EXIT HUP INT TERM; "
            "printf '%s\\n' \"$work_dir\""
        )
        result = ssh.run(command, timeout=timeout)
        if not result.ok:
            raise RuntimeError(f"リモート作業領域の作成に失敗しました: target={target} exit={result.exit_code}")

        lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if not lines:
            raise RuntimeError(f"リモート作業領域のパスを取得できませんでした: target={target}")
        path = lines[-1]
        _validate_remote_workspace(path, self.work_id)
        self._remote_workspaces.append(
            {
                "target": target,
                "path": path,
                "cleanup": "pending",
            }
        )
        self._write_manifest(status="running", local_cleanup="pending")
        return path

    def cleanup_remote_workspace(
        self,
        ssh: "CommandRunner",
        target: str,
        path: str,
        timeout: int = 120,
    ) -> bool:
        """markerを検証して専用リモート作業ディレクトリを削除する。"""
        record = self._find_remote_record(target, path)
        try:
            _validate_remote_workspace(path, self.work_id)
            quoted_path = shlex.quote(path)
            quoted_marker = shlex.quote(posixpath.join(path, _REMOTE_MARKER))
            quoted_work_id = shlex.quote(self.work_id)
            command = (
                "set -eu; "
                f"test -d {quoted_path}; "
                f"test ! -L {quoted_path}; "
                f'test "$(stat -c %u {quoted_path})" = "$(id -u)"; '
                f"test -f {quoted_marker}; "
                f"test ! -L {quoted_marker}; "
                f'test "$(stat -c %u {quoted_marker})" = "$(id -u)"; '
                f'test "$(cat {quoted_marker})" = {quoted_work_id}; '
                f"rm -rf -- {quoted_path}"
            )
            result = ssh.run(command, timeout=timeout)
        except Exception as exc:
            record["cleanup"] = "failed"
            record["cleanup_error"] = type(exc).__name__
            self._write_manifest(status="running", local_cleanup="pending")
            return False

        if result.ok:
            record["cleanup"] = "removed"
            self._write_manifest(status="running", local_cleanup="pending")
            return True

        record["cleanup"] = "failed"
        record["cleanup_exit_code"] = result.exit_code
        self._write_manifest(status="running", local_cleanup="pending")
        return False

    def _find_remote_record(self, target: str, path: str) -> dict[str, Any]:
        for record in self._remote_workspaces:
            if record["target"] == target and record["path"] == path:
                return record
        raise ValueError(f"登録されていないリモート作業領域です: target={target}, path={path}")

    def _write_manifest(self, status: str, local_cleanup: str, error_type: Optional[str] = None) -> None:
        local_workspace = f"build_env/work/{self.work_id}" if self.project_id is None else str(self.work_dir)
        payload = {
            "schema_version": 1,
            "work_id": self.work_id,
            "label": self.label,
            "status": status,
            "local_cleanup": local_cleanup,
            "local_workspace": local_workspace,
            "project_id": self.project_id,
            "remote_workspaces": self._remote_workspaces,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if error_type:
            payload["error_type"] = error_type
        self.manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def __exit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        status = "success" if exc_type is None and self._completed else "failed"
        error_type = exc_type.__name__ if exc_type else None
        local_cleanup = "kept" if self.keep_workdir else "pending"
        self._write_manifest(status=status, local_cleanup=local_cleanup, error_type=error_type)

        if not self.keep_workdir:
            try:
                shutil.rmtree(self.work_dir)
            except OSError as exc:
                status = "failed"
                local_cleanup = "failed"
                error_type = type(exc).__name__
            else:
                local_cleanup = "removed"
            self._write_manifest(status=status, local_cleanup=local_cleanup, error_type=error_type)
