"""desired_state/ の定義ファイル読み込み（env_builder.core.desired_state）の検証。"""

import json
from pathlib import Path

import pytest

from env_builder.core.desired_state import load_build_targets, load_files, load_packages
from env_builder.core.project import ProjectRegistry


def _desired_state_dir(tmp_path: Path) -> Path:
    directory = tmp_path / "projects" / "project-a" / "desired_state"
    directory.mkdir(parents=True)
    return directory


def test_run_build_loader_uses_selected_project_state(tmp_path: Path) -> None:
    desired_state_dir = _desired_state_dir(tmp_path)
    (desired_state_dir / "build_targets.local.json").write_text(
        json.dumps({"targets": [{"name": "project-a-build"}]}),
        encoding="utf-8",
    )
    profile = ProjectRegistry(projects_root=tmp_path / "projects").resolve("project-a")

    config = load_build_targets(profile.desired_state_dir)

    assert config["targets"][0]["name"] == "project-a-build"


def test_apply_packages_loader_uses_selected_project_state(tmp_path: Path) -> None:
    desired_state_dir = _desired_state_dir(tmp_path)
    (desired_state_dir / "packages.json").write_text(
        json.dumps({"package_manager": "dnf", "packages": [{"name": "project-a-package"}]}),
        encoding="utf-8",
    )
    profile = ProjectRegistry(projects_root=tmp_path / "projects").resolve("project-a")

    config = load_packages(profile.desired_state_dir)

    assert config["packages"][0]["name"] == "project-a-package"


def test_sync_files_loader_uses_selected_project_state(tmp_path: Path) -> None:
    desired_state_dir = _desired_state_dir(tmp_path)
    (desired_state_dir / "files.json").write_text(
        json.dumps({"files": [{"src_path": "/src/project-a", "dst_path": "/dst/project-a"}]}),
        encoding="utf-8",
    )
    profile = ProjectRegistry(projects_root=tmp_path / "projects").resolve("project-a")

    config = load_files(profile.desired_state_dir)

    assert config["files"][0]["src_path"] == "/src/project-a"


def test_build_targets_prefers_local_file_over_legacy_file(tmp_path: Path) -> None:
    desired_state_dir = _desired_state_dir(tmp_path)
    (desired_state_dir / "build_targets.json").write_text(json.dumps({"source": "legacy"}), encoding="utf-8")
    (desired_state_dir / "build_targets.local.json").write_text(json.dumps({"source": "local"}), encoding="utf-8")

    assert load_build_targets(desired_state_dir) == {"source": "local"}


def test_build_targets_falls_back_to_legacy_file(tmp_path: Path) -> None:
    desired_state_dir = _desired_state_dir(tmp_path)
    (desired_state_dir / "build_targets.json").write_text(json.dumps({"source": "legacy"}), encoding="utf-8")

    assert load_build_targets(desired_state_dir) == {"source": "legacy"}


def test_build_targets_error_asks_for_the_local_file(tmp_path: Path) -> None:
    desired_state_dir = _desired_state_dir(tmp_path)

    with pytest.raises(FileNotFoundError) as excinfo:
        load_build_targets(desired_state_dir)

    message = str(excinfo.value)
    assert "build_targets.local.json がありません" in message
    assert "Git 管理外" in message


@pytest.mark.parametrize(
    ("loader", "name", "sample"),
    [
        (load_packages, "packages.json", "packages.sample.json"),
        (load_files, "files.json", "files.sample.json"),
    ],
)
def test_missing_file_error_names_the_file_and_its_sample(loader, name: str, sample: str, tmp_path: Path) -> None:
    desired_state_dir = _desired_state_dir(tmp_path)

    with pytest.raises(FileNotFoundError) as excinfo:
        loader(desired_state_dir)

    assert str(excinfo.value) == f"{name} がありません。{sample} を複製して実値を埋めてください。"


@pytest.mark.parametrize(
    ("loader", "name"),
    [
        (load_packages, "packages.json"),
        (load_files, "files.json"),
        (load_build_targets, "build_targets.local.json"),
    ],
)
def test_loaders_strip_comment_keys(loader, name: str, tmp_path: Path) -> None:
    """`//` で始まるキーは設定ファイルの注記として読み込み時に取り除かれる。"""
    desired_state_dir = _desired_state_dir(tmp_path)
    (desired_state_dir / name).write_text(
        json.dumps({"//": "note", "value": {"//inner": "note", "keep": 1}}),
        encoding="utf-8",
    )

    assert loader(desired_state_dir) == {"value": {"keep": 1}}


def test_loaders_do_not_read_files_outside_the_given_directory(tmp_path: Path) -> None:
    """別プロジェクトの desired_state を、暗黙に読むことはない。"""
    desired_state_dir = _desired_state_dir(tmp_path)
    other = tmp_path / "projects" / "project-b" / "desired_state"
    other.mkdir(parents=True)
    (other / "packages.json").write_text(json.dumps({"packages": []}), encoding="utf-8")

    with pytest.raises(FileNotFoundError):
        load_packages(desired_state_dir)
