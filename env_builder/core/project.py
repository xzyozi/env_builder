"""プロジェクト単位の設定ルートを解決する。"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import BUILD_ENV_DIR, DESIRED_STATE_DIR, INVENTORY_DIR, REPO_ROOT

PROJECT_ROOT_ENV = "ENVB_PROJECT_ROOT"
_DEFAULT_PROJECTS_ROOT = REPO_ROOT / "projects"
_PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")


def validate_project_id(project_id: str) -> str:
    """プロジェクトIDを検証し、安全なIDを返す。"""
    if not isinstance(project_id, str) or not _PROJECT_ID_RE.fullmatch(project_id):
        raise ValueError(
            "プロジェクトIDは英数字で始まり、英数字・ハイフン・アンダースコアを 1〜64文字で指定してください。"
        )
    return project_id


@dataclass(frozen=True)
class ProjectProfile:
    """1プロジェクトの設定・成果物ルート。認証情報は保持しない。"""

    project_id: Optional[str]
    root_dir: Path
    inventory_path: Path
    desired_state_dir: Path
    build_env_dir: Path

    @property
    def is_legacy(self) -> bool:
        """既存のリポジトリ直下設定を使うprofileか判定する。"""
        return self.project_id is None


class ProjectRegistry:
    """プロジェクトIDから設定・成果物のパスを解決する。"""

    def __init__(self, projects_root: Optional[Path] = None):
        configured_root = projects_root
        if configured_root is None:
            env_root = os.environ.get(PROJECT_ROOT_ENV)
            configured_root = Path(env_root).expanduser() if env_root else _DEFAULT_PROJECTS_ROOT
        self.projects_root = Path(configured_root).expanduser().resolve()

    def resolve(self, project_id: Optional[str] = None, *, allow_missing: bool = False) -> ProjectProfile:
        """プロジェクトIDをprofileへ解決する。未指定時はlegacy経路を返す。"""
        if project_id is None:
            return ProjectProfile(
                project_id=None,
                root_dir=REPO_ROOT,
                inventory_path=INVENTORY_DIR / "servers.json",
                desired_state_dir=DESIRED_STATE_DIR,
                build_env_dir=BUILD_ENV_DIR,
            )

        project_id = validate_project_id(project_id)
        project_root = (self.projects_root / project_id).resolve()
        try:
            project_root.relative_to(self.projects_root)
        except ValueError as exc:
            raise ValueError(f"プロジェクトIDが設定ルート外を指しています: {project_id}") from exc

        if not allow_missing and not project_root.is_dir():
            raise FileNotFoundError(f"プロジェクト '{project_id}' が見つかりません: {project_root}")

        return ProjectProfile(
            project_id=project_id,
            root_dir=project_root,
            inventory_path=project_root / "inventory" / "servers.json",
            desired_state_dir=project_root / "desired_state",
            build_env_dir=project_root / "build_env",
        )

    def list_projects(self) -> list[str]:
        """設定ルート直下の安全なプロジェクトIDを名前順で返す。"""
        if not self.projects_root.is_dir():
            return []

        project_ids: list[str] = []
        for child in self.projects_root.iterdir():
            if not child.is_dir():
                continue
            try:
                project_ids.append(validate_project_id(child.name))
            except ValueError:
                continue
        return sorted(project_ids)
