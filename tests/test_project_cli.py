import json
from pathlib import Path

from env_builder.cli.apply_packages import _load_packages
from env_builder.cli.run_build import _load_targets
from env_builder.cli.sync_files import _load_files
from env_builder.core.project import ProjectRegistry


def test_run_build_loader_uses_selected_project_state(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "project-a"
    desired_state_dir = project_root / "desired_state"
    desired_state_dir.mkdir(parents=True)
    (desired_state_dir / "build_targets.local.json").write_text(
        json.dumps({"targets": [{"name": "project-a-build"}]}),
        encoding="utf-8",
    )
    profile = ProjectRegistry(projects_root=tmp_path / "projects").resolve("project-a")

    config = _load_targets(profile.desired_state_dir)

    assert config["targets"][0]["name"] == "project-a-build"


def test_apply_packages_loader_uses_selected_project_state(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "project-a"
    desired_state_dir = project_root / "desired_state"
    desired_state_dir.mkdir(parents=True)
    (desired_state_dir / "packages.json").write_text(
        json.dumps({"package_manager": "dnf", "packages": [{"name": "project-a-package"}]}),
        encoding="utf-8",
    )
    profile = ProjectRegistry(projects_root=tmp_path / "projects").resolve("project-a")

    config = _load_packages(profile.desired_state_dir)

    assert config["packages"][0]["name"] == "project-a-package"


def test_sync_files_loader_uses_selected_project_state(tmp_path: Path) -> None:
    project_root = tmp_path / "projects" / "project-a"
    desired_state_dir = project_root / "desired_state"
    desired_state_dir.mkdir(parents=True)
    (desired_state_dir / "files.json").write_text(
        json.dumps({"files": [{"src_path": "/src/project-a", "dst_path": "/dst/project-a"}]}),
        encoding="utf-8",
    )
    profile = ProjectRegistry(projects_root=tmp_path / "projects").resolve("project-a")

    config = _load_files(profile.desired_state_dir)

    assert config["files"][0]["src_path"] == "/src/project-a"
