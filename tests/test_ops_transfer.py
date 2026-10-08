"""env_builder.ops.transfer の検証。

SSH を fake のセッションに差し替え、中継転送の成否と、成功・失敗・例外のいずれでも
リモートの専用作業領域がcleanupされることを確認する。ローカルの `WorkContext` は
`tmp_path` の実体で動かす。実際の接続は行わない。
"""

import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

import pytest

from env_builder.core.ssh import OutputCallback, SSHResult
from env_builder.core.work_context import WorkContext
from env_builder.ops.transfer import (
    TREE_ARCHIVE_NAME,
    chmod_command,
    deploy_tree,
    download_files,
    fetch_tree,
    pack_command,
    split_remote_dir,
    unpack_command,
    upload_files,
)

Responder = Callable[[str], Optional[SSHResult]]


class FakeSession:
    """run / get_file / put_file を記録する fake。

    作業領域の作成（mktemp）と削除（rm -rf）には、既定で成功を返す。それ以外の run() には
    `responder` が結果を返す。get_file / put_file は `fail_on` に含まれる操作だけ例外を投げる。
    """

    def __init__(
        self,
        work_id: str,
        responder: Optional[Responder] = None,
        fail_on: Optional[List[str]] = None,
        cleanup_result: Optional[SSHResult] = None,
    ) -> None:
        self.workspace = f"/tmp/env_builder-{work_id}-Xy12Ab"
        self._responder = responder
        self._fail_on = fail_on or []
        self._cleanup_result = cleanup_result or SSHResult(0, "", "")
        self.commands: List[str] = []
        self.gets: List[tuple] = []
        self.puts: List[tuple] = []
        self.events: List[str] = []

    def run(
        self,
        command: str,
        timeout: int = 600,
        *,
        on_output: Optional[OutputCallback] = None,
    ) -> SSHResult:
        self.commands.append(command)
        if "mktemp" in command:
            self.events.append("create-workspace")
            return SSHResult(0, self.workspace + "\n", "")
        if "rm -rf --" in command:
            self.events.append("cleanup-workspace")
            return self._cleanup_result
        self.events.append("run")
        if self._responder is not None:
            result = self._responder(command)
            if result is not None:
                return result
        return SSHResult(0, "", "")

    def get_file(self, remote_path: str, local_path: str, timeout: Optional[float] = None) -> None:
        self.events.append("get")
        self.gets.append((remote_path, local_path))
        if "get" in self._fail_on:
            raise OSError("get failed")
        Path(local_path).write_bytes(b"archive")

    def put_file(self, local_path: str, remote_path: str, timeout: Optional[float] = None) -> None:
        self.events.append("put")
        self.puts.append((local_path, remote_path))
        if "put" in self._fail_on:
            raise OSError("put failed")


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_ops_transfer")


@pytest.fixture
def work(tmp_path: Path):
    with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as context:
        yield context


# --- コマンドの組み立て --------------------------------------------------------------


def test_split_remote_dir_ignores_trailing_slash() -> None:
    assert split_remote_dir("/opt/mel/lib64/version_mng") == ("/opt/mel/lib64", "version_mng")
    assert split_remote_dir("/opt/mel/lib64/version_mng/") == ("/opt/mel/lib64", "version_mng")


def test_pack_and_unpack_commands_are_quoted() -> None:
    assert pack_command("/tmp/w/tree.tar.gz", "/opt/a b", "x") == (
        "tar czf /tmp/w/tree.tar.gz -C '/opt/a b' -- x && ls -l -- /tmp/w/tree.tar.gz"
    )
    assert unpack_command("/tmp/w/tree.tar.gz", "/opt/a b", "/opt/a b/x") == (
        "mkdir -p -- '/opt/a b' && tar xzf /tmp/w/tree.tar.gz -C '/opt/a b' && ls -ld -- '/opt/a b/x'"
    )


def test_chmod_command_quotes_mode_and_path() -> None:
    assert chmod_command("755", "/opt/app/run.sh") == "chmod 755 /opt/app/run.sh"
    assert chmod_command(644, "/opt/a; reboot") == "chmod 644 '/opt/a; reboot'"


# --- fetch_tree ------------------------------------------------------------------------


def _fetch(session: FakeSession, work: WorkContext, tmp_path: Path, logger: logging.Logger, **kwargs) -> bool:
    return fetch_tree(
        session,
        work,
        target="src",
        parent="/opt/mel/lib64",
        base="version_mng",
        local_tar=tmp_path / "tree.tar.gz",
        timeout=30,
        logger=logger,
        **kwargs,
    )


def test_fetch_tree_creates_packs_downloads_then_cleans_up(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    session = FakeSession(work.work_id)

    assert _fetch(session, work, tmp_path, logger) is True

    assert session.events == ["create-workspace", "run", "get", "cleanup-workspace"]
    assert session.gets == [(f"{session.workspace}/{TREE_ARCHIVE_NAME}", str(tmp_path / "tree.tar.gz"))]
    assert session.commands[1] == pack_command(
        f"{session.workspace}/{TREE_ARCHIVE_NAME}", "/opt/mel/lib64", "version_mng"
    )
    assert (tmp_path / "tree.tar.gz").read_bytes() == b"archive"


def test_fetch_tree_cleans_up_when_tar_fails_and_skips_download(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    session = FakeSession(work.work_id, responder=lambda command: SSHResult(2, "", "tar: boom\n"))

    assert _fetch(session, work, tmp_path, logger) is False

    assert session.events == ["create-workspace", "run", "cleanup-workspace"]
    assert session.gets == []


def test_fetch_tree_cleans_up_when_download_raises(work: WorkContext, tmp_path: Path, logger: logging.Logger) -> None:
    session = FakeSession(work.work_id, fail_on=["get"])

    assert _fetch(session, work, tmp_path, logger) is False

    assert session.events == ["create-workspace", "run", "get", "cleanup-workspace"]


def test_fetch_tree_reports_failure_when_cleanup_fails_even_if_download_succeeded(
    work: WorkContext, tmp_path: Path, logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    session = FakeSession(work.work_id, cleanup_result=SSHResult(1, "", "rm failed"))

    with caplog.at_level(logging.ERROR, logger="test_ops_transfer"):
        assert _fetch(session, work, tmp_path, logger) is False

    assert any("一時作業領域を削除できませんでした" in record.getMessage() for record in caplog.records)
    assert session.gets  # 取得自体は行われた


def test_fetch_tree_does_nothing_remote_after_workspace_creation_fails(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    class BrokenSession(FakeSession):
        def run(self, command: str, timeout: int = 600, *, on_output: Optional[OutputCallback] = None) -> SSHResult:
            self.commands.append(command)
            return SSHResult(1, "", "mktemp failed")

    session = BrokenSession(work.work_id)

    assert _fetch(session, work, tmp_path, logger) is False

    # 作業領域が作れなかったので、tar も削除も送られない
    assert len(session.commands) == 1
    assert "mktemp" in session.commands[0]
    assert session.gets == []


def test_fetch_tree_records_the_workspace_cleanup_in_the_manifest(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    import json

    session = FakeSession(work.work_id)

    _fetch(session, work, tmp_path, logger)

    manifest = json.loads(work.manifest_path.read_text(encoding="utf-8"))
    assert manifest["remote_workspaces"][0]["target"] == "src"
    assert manifest["remote_workspaces"][0]["cleanup"] == "removed"


# --- deploy_tree -----------------------------------------------------------------------


def _deploy(session: FakeSession, work: WorkContext, tmp_path: Path, logger: logging.Logger) -> bool:
    local_tar = tmp_path / "tree.tar.gz"
    local_tar.write_bytes(b"archive")
    return deploy_tree(
        session,
        work,
        target="dst_root",
        local_tar=local_tar,
        dst_parent="/opt/mel/lib64",
        destination="/opt/mel/lib64/version_mng",
        timeout=30,
        logger=logger,
    )


def test_deploy_tree_creates_uploads_unpacks_then_cleans_up(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    session = FakeSession(work.work_id)

    assert _deploy(session, work, tmp_path, logger) is True

    assert session.events == ["create-workspace", "put", "run", "cleanup-workspace"]
    dst_tar = f"{session.workspace}/{TREE_ARCHIVE_NAME}"
    assert session.puts == [(str(tmp_path / "tree.tar.gz"), dst_tar)]
    assert session.commands[1] == unpack_command(dst_tar, "/opt/mel/lib64", "/opt/mel/lib64/version_mng")


def test_deploy_tree_cleans_up_when_unpack_fails(work: WorkContext, tmp_path: Path, logger: logging.Logger) -> None:
    session = FakeSession(work.work_id, responder=lambda command: SSHResult(1, "", "tar: boom\n"))

    assert _deploy(session, work, tmp_path, logger) is False

    assert session.events == ["create-workspace", "put", "run", "cleanup-workspace"]


def test_deploy_tree_cleans_up_when_upload_raises_and_never_unpacks(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    session = FakeSession(work.work_id, fail_on=["put"])

    assert _deploy(session, work, tmp_path, logger) is False

    assert session.events == ["create-workspace", "put", "cleanup-workspace"]
    assert not any(command.startswith("mkdir") for command in session.commands)


def test_deploy_tree_never_removes_the_permanent_destination(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    session = FakeSession(work.work_id)

    _deploy(session, work, tmp_path, logger)

    # 作業領域の作成コマンド（mktemp）は、失敗時の後始末として trap の中に rm を含む。削除そのものを行う
    # コマンドだけを対象にする。
    removals = [command for command in session.commands if "rm -rf --" in command and "mktemp" not in command]
    assert len(removals) == 1
    assert session.workspace in removals[0]
    assert "/opt/mel/lib64" not in removals[0]


def test_deploy_tree_reports_failure_when_cleanup_fails(
    work: WorkContext, tmp_path: Path, logger: logging.Logger
) -> None:
    session = FakeSession(work.work_id, cleanup_result=SSHResult(1, "", "rm failed"))

    assert _deploy(session, work, tmp_path, logger) is False


# --- download_files / upload_files ----------------------------------------------------


ENTRIES: List[Dict[str, Any]] = [
    {"src_path": "/src/a.conf", "dst_path": "/dst/a.conf"},
    {"src_path": "/src/b.conf", "dst_path": "/dst/b.conf", "mode": "644"},
    {"src_path": "/src/c.sh", "dst_path": "/dst/c.sh", "mode": 755},
]


def test_download_files_returns_stage_paths_in_order_without_changing_entries(
    tmp_path: Path, logger: logging.Logger
) -> None:
    session = FakeSession("w")
    entries = [dict(entry) for entry in ENTRIES]

    paths = download_files(session, entries, tmp_path, logger)

    assert paths == [str(tmp_path / "file_000"), str(tmp_path / "file_001"), str(tmp_path / "file_002")]
    assert [remote for remote, _ in session.gets] == ["/src/a.conf", "/src/b.conf", "/src/c.sh"]
    # 入力の対応表は書き換えない
    assert entries == ENTRIES
    assert all("_local" not in entry for entry in entries)


def test_download_files_stops_at_the_first_failure(tmp_path: Path, logger: logging.Logger) -> None:
    class FailSecond(FakeSession):
        def get_file(self, remote_path: str, local_path: str, timeout: Optional[float] = None) -> None:
            if remote_path == "/src/b.conf":
                raise OSError("no such file")
            super().get_file(remote_path, local_path, timeout)

    session = FailSecond("w")

    assert download_files(session, ENTRIES, tmp_path, logger) is None

    assert [remote for remote, _ in session.gets] == ["/src/a.conf"]  # 3件目は取得しない


def test_download_files_with_no_entries_returns_empty_list(tmp_path: Path, logger: logging.Logger) -> None:
    assert download_files(FakeSession("w"), [], tmp_path, logger) == []


def test_upload_files_puts_each_file_and_applies_mode_only_when_given(logger: logging.Logger) -> None:
    session = FakeSession("w")
    local_paths = ["/stage/file_000", "/stage/file_001", "/stage/file_002"]

    assert upload_files(session, ENTRIES, local_paths, logger) is True

    assert session.puts == [
        ("/stage/file_000", "/dst/a.conf"),
        ("/stage/file_001", "/dst/b.conf"),
        ("/stage/file_002", "/dst/c.sh"),
    ]
    # mode がある 2 件だけ chmod する（a.conf は mode なし）
    assert session.commands == ["chmod 644 /dst/b.conf", "chmod 755 /dst/c.sh"]


def test_upload_files_stops_when_chmod_fails(logger: logging.Logger) -> None:
    session = FakeSession("w", responder=lambda command: SSHResult(1, "", "chmod: boom"))

    assert upload_files(session, ENTRIES, ["/s/0", "/s/1", "/s/2"], logger) is False

    # b.conf の chmod で失敗したので、c.sh は配置されない
    assert [remote for _, remote in session.puts] == ["/dst/a.conf", "/dst/b.conf"]


def test_upload_files_stops_when_upload_raises(logger: logging.Logger) -> None:
    session = FakeSession("w", fail_on=["put"])

    assert upload_files(session, ENTRIES, ["/s/0", "/s/1", "/s/2"], logger) is False

    assert len(session.puts) == 1  # 最初の upload で失敗して止まる
    assert session.commands == []


def test_upload_files_quotes_hostile_destination_in_chmod(logger: logging.Logger) -> None:
    session = FakeSession("w")
    entries = [{"src_path": "/s", "dst_path": "/dst/a; reboot", "mode": "600"}]

    assert upload_files(session, entries, ["/stage/file_000"], logger) is True

    assert session.commands == ["chmod 600 '/dst/a; reboot'"]
