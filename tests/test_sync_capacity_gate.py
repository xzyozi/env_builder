"""sync_tree / sync_files の容量チェック（転送前のゲート）の検証。

容量が足りない場合や測定できない場合は、作業領域（WorkContext）も作らず、転送もせずに
終了コード 1 で終わることを確認する。足りる場合だけ転送に進む。SSH は fake に差し替える。
"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

import pytest

from env_builder.cli import sync_files, sync_tree
from env_builder.core.ssh import OutputCallback, SSHResult

GIB = 1024**3


def df_output(available_bytes: int) -> str:
    avail_kib = available_bytes // 1024
    return (
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n"
        f"/dev/sda1 {avail_kib * 2} {avail_kib} {avail_kib} 50% /opt\n"
    )


class Recorder:
    """接続先ごとの実行コマンドと、転送系の呼び出しを記録する。"""

    def __init__(self, src_bytes: Optional[int], dst_available: int) -> None:
        self.src_bytes = src_bytes
        self.dst_available = dst_available
        self.opened: List[str] = []
        self.commands: List[tuple] = []
        self.work_contexts = 0
        self.transfers: List[str] = []


def install_fakes(monkeypatch: pytest.MonkeyPatch, module: Any, tmp_path: Path, recorder: Recorder) -> None:
    profile = SimpleNamespace(
        project_id="p",
        inventory_path=tmp_path / "servers.json",
        build_env_dir=tmp_path / "build_env",
        desired_state_dir=tmp_path / "desired_state",
    )
    monkeypatch.setattr(module, "ProjectRegistry", lambda: SimpleNamespace(resolve=lambda project: profile))
    monkeypatch.setattr(module, "load_inventory", lambda path: object())

    class FakeSSH:
        def __init__(self, inv: object, key: str) -> None:
            self.key = key
            recorder.opened.append(key)

        def __enter__(self) -> "FakeSSH":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def run(self, command: str, timeout: int = 600, *, on_output: Optional[OutputCallback] = None) -> SSHResult:
            recorder.commands.append((self.key, command))
            if command.startswith("du "):
                if recorder.src_bytes is None:
                    return SSHResult(1, "", "du: boom\n")
                return SSHResult(0, f"{recorder.src_bytes}\ttotal\n", "")
            if "df -Pk" in command:
                return SSHResult(0, df_output(recorder.dst_available), "")
            raise AssertionError(f"容量チェックの段階で想定外のコマンド: {command}")

    class FakeWork:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            recorder.work_contexts += 1
            self.stage_dir = tmp_path / "stage"
            self.stage_dir.mkdir(parents=True, exist_ok=True)

        def __enter__(self) -> "FakeWork":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def complete(self) -> None:
            return None

    monkeypatch.setattr(module, "SSHSession", FakeSSH)
    monkeypatch.setattr(module, "WorkContext", FakeWork)


# --- sync_tree -------------------------------------------------------------------------


def run_sync_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, recorder: Recorder) -> int:
    install_fakes(monkeypatch, sync_tree, tmp_path, recorder)

    def fake_fetch(*args: Any, local_tar: Path, **kwargs: Any) -> bool:
        recorder.transfers.append("fetch")
        local_tar.write_bytes(b"archive")
        return True

    def fake_deploy(*args: Any, **kwargs: Any) -> bool:
        recorder.transfers.append("deploy")
        return True

    monkeypatch.setattr(sync_tree, "fetch_tree", fake_fetch)
    monkeypatch.setattr(sync_tree, "deploy_tree", fake_deploy)
    return sync_tree.main(
        ["--src", "src", "--dst", "dst", "--remote-src", "/opt/mel/version_mng", "--remote-dst-parent", "/opt/mel"]
    )


def test_sync_tree_proceeds_when_space_is_data_plus_one_gib(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(src_bytes=5 * GIB, dst_available=6 * GIB)

    assert run_sync_tree(monkeypatch, tmp_path, recorder) == 0

    assert recorder.transfers == ["fetch", "deploy"]
    # 容量チェックは転送より前に、src → dst の順で行う
    assert recorder.opened[:2] == ["src", "dst"]


def test_sync_tree_stops_before_any_work_when_space_is_short(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(src_bytes=5 * GIB, dst_available=6 * GIB - 4096)

    assert run_sync_tree(monkeypatch, tmp_path, recorder) == 1

    assert recorder.work_contexts == 0
    assert recorder.transfers == []


def test_sync_tree_stops_when_source_size_cannot_be_measured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(src_bytes=None, dst_available=1000 * GIB)

    assert run_sync_tree(monkeypatch, tmp_path, recorder) == 1

    assert recorder.work_contexts == 0
    assert recorder.transfers == []
    assert recorder.opened == ["src"]  # サイズが分からないので dst には進まない


def test_sync_tree_capacity_check_only_reads(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(src_bytes=5 * GIB, dst_available=1000 * GIB)

    run_sync_tree(monkeypatch, tmp_path, recorder)

    for _, command in recorder.commands:
        assert command.startswith("du ") or "df -Pk" in command
        assert "rm " not in command and "mv " not in command and "mkdir" not in command


# --- sync_files ------------------------------------------------------------------------


def run_sync_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, recorder: Recorder) -> int:
    install_fakes(monkeypatch, sync_files, tmp_path, recorder)
    entries: List[Dict[str, Any]] = [
        {"src_path": "/src/a.conf", "dst_path": "/opt/etc/a.conf"},
        {"src_path": "/src/b.conf", "dst_path": "/opt/etc/b.conf"},
    ]
    monkeypatch.setattr(sync_files, "load_files", lambda directory: {"files": entries})

    def fake_download(session: Any, entries: Any, stage_dir: Path, logger: Any) -> List[str]:
        recorder.transfers.append("download")
        return ["/stage/file_000", "/stage/file_001"]

    def fake_upload(*args: Any, **kwargs: Any) -> bool:
        recorder.transfers.append("upload")
        return True

    monkeypatch.setattr(sync_files, "download_files", fake_download)
    monkeypatch.setattr(sync_files, "upload_files", fake_upload)
    return sync_files.main(["--src", "src", "--dst", "dst"])


def test_sync_files_proceeds_when_space_is_enough(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(src_bytes=2048, dst_available=2 * GIB)

    assert run_sync_files(monkeypatch, tmp_path, recorder) == 0

    assert recorder.transfers == ["download", "upload"]
    # 配置先の親ディレクトリは重複を除いて 1 回だけ調べる
    assert len([c for _, c in recorder.commands if "df -Pk" in c]) == 1


def test_sync_files_stops_before_any_work_when_space_is_short(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(src_bytes=2048, dst_available=GIB)  # 2048 バイト + 1 GiB に満たない

    assert run_sync_files(monkeypatch, tmp_path, recorder) == 1

    assert recorder.work_contexts == 0
    assert recorder.transfers == []


def test_sync_files_stops_when_source_size_cannot_be_measured(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(src_bytes=None, dst_available=1000 * GIB)

    assert run_sync_files(monkeypatch, tmp_path, recorder) == 1

    assert recorder.work_contexts == 0
    assert recorder.transfers == []
