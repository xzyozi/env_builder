"""リモート作業領域の生成・cleanup 検証（ENVB-0003）。

SSH を fake に差し替え、`mktemp -d` による一意な専用ディレクトリ作成、
パス検証、marker / 所有者確認を伴う cleanup、失敗時の manifest 記録を確認する。
"""

import json
from pathlib import Path
from typing import List

import pytest

from scripts.core.ssh import SSHResult
from scripts.core.work_context import WorkContext, _validate_remote_workspace


class FakeSSH:
    """run() の呼び出しを記録し、あらかじめ決めた結果を返す。"""

    def __init__(self, results: List[SSHResult]) -> None:
        self._results = list(results)
        self.commands: List[str] = []

    def run(self, command: str, timeout: int = 0) -> SSHResult:
        self.commands.append(command)
        return self._results.pop(0)


def _ok(stdout: str = "") -> SSHResult:
    return SSHResult(exit_code=0, stdout=stdout, stderr="")


def _fail(code: int = 1) -> SSHResult:
    return SSHResult(exit_code=code, stdout="", stderr="boom")


def test_validate_accepts_dedicated_directory_under_tmp() -> None:
    _validate_remote_workspace("/tmp/env_builder-work1-AbC123", "work1")


@pytest.mark.parametrize(
    "path",
    [
        "/tmp",  # /tmp 自体
        "/tmp/",  # 末尾スラッシュ
        "/tmp/env_builder-work1-",  # ランダム部が空
        "/tmp/other-work1-AbC123",  # prefix 違い
        "/tmp/env_builder-work2-AbC123",  # 別の作業ID
        "/tmp/../etc/env_builder-work1-AbC123",  # 親ディレクトリ経由
        "/var/tmp/env_builder-work1-AbC123",  # /tmp 直下でない
        "/tmp/sub/env_builder-work1-AbC123",  # /tmp 直下でない
        "/home/user",  # HOME 直下
        "/",  # ルート
        "relative/env_builder-work1-AbC123",  # 相対パス
    ],
)
def test_validate_rejects_paths_outside_dedicated_workspace(path: str) -> None:
    with pytest.raises(ValueError):
        _validate_remote_workspace(path, "work1")


def test_create_remote_workspace_uses_mktemp_with_random_suffix(tmp_path: Path) -> None:
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
        created = f"/tmp/env_builder-{work.work_id}-Xy12Ab"
        ssh = FakeSSH([_ok(created + "\n")])

        path = work.create_remote_workspace(ssh, "dst")  # type: ignore[arg-type]
        work.complete()

    command = ssh.commands[0]
    assert path == created
    # 予測可能な固定名ではなく、mktemp -d のランダム接尾辞で一意なディレクトリを作る
    assert "mktemp -d" in command
    assert f"/tmp/env_builder-{work.work_id}-XXXXXX" in command
    # 失敗時に作りかけのディレクトリを残さない
    assert "trap" in command
    # 他ユーザーに読ませない marker
    assert "chmod 600" in command


def test_create_remote_workspace_rejects_path_outside_tmp(tmp_path: Path) -> None:
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
        ssh = FakeSSH([_ok("/etc\n")])

        with pytest.raises(ValueError):
            work.create_remote_workspace(ssh, "dst")  # type: ignore[arg-type]


def test_create_remote_workspace_raises_when_command_fails(tmp_path: Path) -> None:
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
        ssh = FakeSSH([_fail(1)])

        with pytest.raises(RuntimeError):
            work.create_remote_workspace(ssh, "dst")  # type: ignore[arg-type]


def test_cleanup_verifies_marker_and_owner_before_removal(tmp_path: Path) -> None:
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
        path = f"/tmp/env_builder-{work.work_id}-Xy12Ab"
        ssh = FakeSSH([_ok(path + "\n"), _ok()])
        work.create_remote_workspace(ssh, "dst")  # type: ignore[arg-type]

        assert work.cleanup_remote_workspace(ssh, "dst", path) is True  # type: ignore[arg-type]
        work.complete()

    command = ssh.commands[1]
    # 削除前に、シンボリックリンクでないこと・所有者・marker・作業IDを確認する
    assert "test ! -L" in command
    assert "stat -c %u" in command
    assert ".env_builder_marker" in command
    # rm は検証の後ろにあり、対象はこの専用ディレクトリだけ
    assert command.index("test ! -L") < command.index("rm -rf --")
    assert command.rstrip().endswith(path)

    manifest = json.loads(work.manifest_path.read_text(encoding="utf-8"))
    assert manifest["remote_workspaces"][0]["cleanup"] == "removed"


def test_cleanup_failure_is_recorded_in_manifest(tmp_path: Path) -> None:
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
        path = f"/tmp/env_builder-{work.work_id}-Xy12Ab"
        ssh = FakeSSH([_ok(path + "\n"), _fail(1)])
        work.create_remote_workspace(ssh, "dst")  # type: ignore[arg-type]

        assert work.cleanup_remote_workspace(ssh, "dst", path) is False  # type: ignore[arg-type]

        manifest = json.loads(work.manifest_path.read_text(encoding="utf-8"))
        record = manifest["remote_workspaces"][0]
        assert record["cleanup"] == "failed"
        assert record["cleanup_exit_code"] == 1


def test_cleanup_refuses_path_that_is_not_the_created_workspace(tmp_path: Path) -> None:
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
        path = f"/tmp/env_builder-{work.work_id}-Xy12Ab"
        ssh = FakeSSH([_ok(path + "\n")])
        work.create_remote_workspace(ssh, "dst")  # type: ignore[arg-type]

        # 登録されていないパスは、リモートへコマンドを送る前に拒否される
        with pytest.raises(ValueError):
            work.cleanup_remote_workspace(ssh, "dst", "/tmp")  # type: ignore[arg-type]

    assert len(ssh.commands) == 1


def test_cleanup_failure_of_invalid_path_never_runs_remote_command(tmp_path: Path) -> None:
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
        path = f"/tmp/env_builder-{work.work_id}-Xy12Ab"
        ssh = FakeSSH([_ok(path + "\n")])
        work.create_remote_workspace(ssh, "dst")  # type: ignore[arg-type]
        # 作成後に記録されたパスを不正な値へ書き換えても、rm は送出されない
        work._remote_workspaces[0]["path"] = "/home/user"

        assert work.cleanup_remote_workspace(ssh, "dst", "/home/user") is False  # type: ignore[arg-type]

    assert len(ssh.commands) == 1
