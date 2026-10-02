from pathlib import Path

import pytest

from scripts.core.config import BUILD_ENV_DIR, DESIRED_STATE_DIR, INVENTORY_DIR, REPO_ROOT
from scripts.core.project import ProjectRegistry


def test_resolve_without_project_preserves_legacy_paths() -> None:
    profile = ProjectRegistry(projects_root=Path("unused")).resolve()

    assert profile.project_id is None
    assert profile.root_dir == REPO_ROOT
    assert profile.inventory_path == INVENTORY_DIR / "servers.json"
    assert profile.desired_state_dir == DESIRED_STATE_DIR
    assert profile.build_env_dir == BUILD_ENV_DIR


def test_resolve_project_uses_project_root(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    project_root = projects_root / "project-a"
    project_root.mkdir(parents=True)

    profile = ProjectRegistry(projects_root=projects_root).resolve("project-a")

    assert profile.project_id == "project-a"
    assert profile.root_dir == project_root.resolve()
    assert profile.inventory_path == project_root / "inventory" / "servers.json"
    assert profile.desired_state_dir == project_root / "desired_state"
    assert profile.build_env_dir == project_root / "build_env"


def test_resolve_can_allow_missing_project_for_initialization(tmp_path: Path) -> None:
    profile = ProjectRegistry(projects_root=tmp_path / "projects").resolve("new-project", allow_missing=True)

    assert profile.project_id == "new-project"
    assert not profile.root_dir.exists()


@pytest.mark.parametrize(
    "project_id",
    ["", ".", "..", "../other", "project/child", "project\\child", "/absolute", "-starts-with-dash", "a" * 65],
)
def test_resolve_rejects_unsafe_project_id(tmp_path: Path, project_id: str) -> None:
    with pytest.raises(ValueError):
        ProjectRegistry(projects_root=tmp_path / "projects").resolve(project_id)


def test_resolve_rejects_unknown_project(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="project-a"):
        ProjectRegistry(projects_root=tmp_path / "projects").resolve("project-a")


def test_list_projects_returns_only_valid_project_directories(tmp_path: Path) -> None:
    projects_root = tmp_path / "projects"
    (projects_root / "project-b").mkdir(parents=True)
    (projects_root / "project-a").mkdir()
    (projects_root / "not a project").mkdir()
    (projects_root / "notes.txt").write_text("not a directory", encoding="utf-8")

    assert ProjectRegistry(projects_root=projects_root).list_projects() == ["project-a", "project-b"]
