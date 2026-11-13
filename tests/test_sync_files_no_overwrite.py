"""sync_files --upload-only --no-overwrite の検証。SSH は fake に差し替える。"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any, List

import pytest

from env_builder.cli import sync_files
from env_builder.core.ssh import SSHResult


class Recorder:
    def __init__(self, remote_exists: bool) -> None:
        self.remote_exists = remote_exists
        self.commands: List[str] = []
        self.puts: List[tuple] = []


def install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, recorder: Recorder) -> None:
    profile = SimpleNamespace(
        project_id="p",
        inventory_path=tmp_path / "servers.json",
        build_env_dir=tmp_path / "build_env",
        desired_state_dir=tmp_path / "desired_state",
    )
    monkeypatch.setattr(sync_files, "ProjectRegistry", lambda: SimpleNamespace(resolve=lambda project: profile))
    monkeypatch.setattr(sync_files, "load_inventory", lambda path: object())

    class FakeSSH:
        def __init__(self, inv: object, key: str) -> None:
            pass

        def __enter__(self) -> "FakeSSH":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def run(self, command: str, timeout: int = 600, **kwargs: Any) -> SSHResult:
            recorder.commands.append(command)
            return SSHResult(0 if recorder.remote_exists else 1, "", "")

        def put_file(self, local: str, remote: str) -> None:
            recorder.puts.append((local, remote))

    monkeypatch.setattr(sync_files, "SSHSession", FakeSSH)


def test_no_overwrite_stops_when_remote_exists(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(remote_exists=True)
    install(monkeypatch, tmp_path, recorder)

    code = sync_files.main(["--dst", "d", "--upload-only", "a.sh", "/tmp/a b.sh", "--no-overwrite"])

    assert code == 1
    assert recorder.puts == []
    assert recorder.commands == ["test -e '/tmp/a b.sh'"]  # 空白を含むパスも引用される


def test_no_overwrite_uploads_when_remote_is_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(remote_exists=False)
    install(monkeypatch, tmp_path, recorder)

    code = sync_files.main(["--dst", "d", "--upload-only", "a.sh", "/tmp/a.sh", "--no-overwrite"])

    assert code == 0
    assert recorder.puts == [("a.sh", "/tmp/a.sh")]


def test_upload_only_without_flag_does_not_check_remote(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    recorder = Recorder(remote_exists=True)
    install(monkeypatch, tmp_path, recorder)

    code = sync_files.main(["--dst", "d", "--upload-only", "a.sh", "/tmp/a.sh"])

    assert code == 0
    assert recorder.commands == []
    assert recorder.puts == [("a.sh", "/tmp/a.sh")]


def test_no_overwrite_requires_upload_only(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install(monkeypatch, tmp_path, Recorder(remote_exists=False))

    with pytest.raises(SystemExit) as exc:
        sync_files.main(["--no-overwrite"])

    assert exc.value.code == 2
