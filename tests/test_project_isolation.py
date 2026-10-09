"""配下プロジェクト間の分離と、認証情報を保持しないことを確認する（Issue #12 受け入れ条件）。"""

import dataclasses
import json
from pathlib import Path

import pytest

from env_builder.core.logging_utils import new_run_dir
from env_builder.core.project import ProjectRegistry
from env_builder.core.work_context import WorkContext


@pytest.fixture
def two_projects(tmp_path: Path) -> ProjectRegistry:
    """同じ target 名・設定ファイル名を持つ 2 プロジェクトを作る。"""
    root = tmp_path / "projects"
    for project_id, host in (("project-a", "host-a"), ("project-b", "host-b")):
        (root / project_id / "inventory").mkdir(parents=True)
        (root / project_id / "desired_state").mkdir(parents=True)
        (root / project_id / "inventory" / "servers.json").write_text(
            json.dumps({"dst": {"host": host}}), encoding="utf-8"
        )
    return ProjectRegistry(projects_root=root)


def test_projects_resolve_to_disjoint_directories(two_projects: ProjectRegistry) -> None:
    a = two_projects.resolve("project-a")
    b = two_projects.resolve("project-b")

    for attr in ("root_dir", "inventory_path", "desired_state_dir", "build_env_dir"):
        assert getattr(a, attr) != getattr(b, attr)
    assert json.loads(a.inventory_path.read_text(encoding="utf-8"))["dst"]["host"] == "host-a"
    assert json.loads(b.inventory_path.read_text(encoding="utf-8"))["dst"]["host"] == "host-b"


def test_same_label_does_not_collide_across_projects(two_projects: ProjectRegistry) -> None:
    a = two_projects.resolve("project-a")
    b = two_projects.resolve("project-b")

    run_a = new_run_dir(label="build_main", build_env_dir=a.build_env_dir, project_id="project-a")
    run_b = new_run_dir(label="build_main", build_env_dir=b.build_env_dir, project_id="project-b")

    assert run_a != run_b
    assert a.build_env_dir in run_a.parents
    assert b.build_env_dir not in run_a.parents
    assert b.build_env_dir in run_b.parents


def test_work_dirs_and_manifests_are_separated_per_project(two_projects: ProjectRegistry) -> None:
    a = two_projects.resolve("project-a")
    b = two_projects.resolve("project-b")

    with WorkContext("sync-files", build_env_dir=a.build_env_dir, project_id="project-a") as work_a:
        with WorkContext("sync-files", build_env_dir=b.build_env_dir, project_id="project-b") as work_b:
            assert work_a.work_dir != work_b.work_dir
            assert a.build_env_dir in work_a.work_dir.parents
            assert b.build_env_dir in work_b.work_dir.parents
            assert json.loads(work_a.manifest_path.read_text(encoding="utf-8"))["project_id"] == "project-a"
            assert json.loads(work_b.manifest_path.read_text(encoding="utf-8"))["project_id"] == "project-b"
            work_b.complete()
        work_a.complete()


def test_project_profile_holds_no_credential_fields() -> None:
    """ProjectProfile はパス情報だけを持ち、認証情報の入れ物を持たない。"""
    names = {field.name for field in dataclasses.fields(ProjectRegistry().resolve())}

    assert names == {"project_id", "root_dir", "inventory_path", "desired_state_dir", "build_env_dir"}


def test_manifest_does_not_contain_password_value(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ENVB_TEST_SECRET", "s3cret-value")

    with WorkContext("sync-files", build_env_dir=tmp_path / "build_env", project_id="project-a") as work:
        work.complete()

    assert "s3cret-value" not in work.manifest_path.read_text(encoding="utf-8")


def test_unspecified_project_is_legacy_and_never_picks_a_project(two_projects: ProjectRegistry) -> None:
    """--project 未指定は legacy 経路であり、登録済みプロジェクトを暗黙に選ばない。"""
    profile = two_projects.resolve(None)

    assert profile.is_legacy
    assert profile.project_id is None
    assert "project-a" not in profile.root_dir.parts
    assert "project-b" not in profile.root_dir.parts
