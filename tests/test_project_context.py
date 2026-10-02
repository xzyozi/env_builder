import json
from pathlib import Path

from scripts.core.logging_utils import new_run_dir
from scripts.core.work_context import WorkContext


def test_new_run_dir_namespaces_explicit_project(tmp_path: Path) -> None:
    build_env_dir = tmp_path / "project-a" / "build_env"

    run_dir = new_run_dir(
        label="exec_dst",
        build_env_dir=build_env_dir,
        project_id="project-a",
    )

    assert run_dir.parent == build_env_dir / "logs" / "project-a"
    assert run_dir.name.startswith("exec_dst_")


def test_new_run_dir_preserves_legacy_path_without_project(tmp_path: Path) -> None:
    build_env_dir = tmp_path / "build_env"

    run_dir = new_run_dir(label="exec_dst", build_env_dir=build_env_dir)

    assert run_dir.parent == build_env_dir / "logs"
    assert run_dir.name.startswith("exec_dst_")


def test_work_context_isolated_and_manifest_has_project_id(tmp_path: Path) -> None:
    build_env_dir = tmp_path / "project-a" / "build_env"

    with WorkContext(
        "sync-files",
        build_env_dir=build_env_dir,
        project_id="project-a",
    ) as work:
        assert work.work_dir.parent == build_env_dir / "work"
        assert work.stage_dir.parent == work.work_dir
        payload = json.loads(work.manifest_path.read_text(encoding="utf-8"))
        assert payload["project_id"] == "project-a"
        work.complete()

    assert work.manifest_path.exists()
    final_payload = json.loads(work.manifest_path.read_text(encoding="utf-8"))
    assert final_payload["status"] == "success"
    assert not work.work_dir.exists()
