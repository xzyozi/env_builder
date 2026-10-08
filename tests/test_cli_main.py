"""cli の main() を、引数解析から終了コードまで fake のセッションで通す検証。

ops の関数単位のテストでは見えない、cli の薄い層（引数の受け渡し・事前検証・成否と終了コードの
対応）を確認する。`SSHSession` だけを fake に差し替え、実際の接続は行わない。プロジェクトの
実体（inventory / desired_state）は `tmp_path` に作り、`ENVB_PROJECT_ROOT` で指す。
"""

import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest

from env_builder.cli import apply_packages, run_build
from env_builder.core.ssh import (
    EXIT_CODE_INTERRUPTED,
    EXIT_CODE_TIMEOUT,
    STATUS_INTERRUPTED,
    STATUS_TIMEOUT,
    OutputCallback,
    SSHInterrupted,
    SSHResult,
)

PROJECT = "project-a"


class FakeSSHSession:
    """`SSHSession` の代わり。with 文で使え、run() にはクラス変数で用意した結果を順に返す。"""

    script: List[Any] = []
    commands: List[str] = []
    opened: List[str] = []

    def __init__(self, inventory: Any, target: str) -> None:
        FakeSSHSession.opened.append(target)

    def __enter__(self) -> "FakeSSHSession":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def run(
        self,
        command: str,
        timeout: int = 600,
        *,
        on_output: Optional[OutputCallback] = None,
    ) -> SSHResult:
        FakeSSHSession.commands.append(command)
        step = FakeSSHSession.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step


@pytest.fixture
def project_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """プロジェクトの実体を tmp_path に作り、ENVB_PROJECT_ROOT で指す。"""
    root = tmp_path / "projects"
    project = root / PROJECT
    (project / "desired_state").mkdir(parents=True)
    (project / "inventory").mkdir(parents=True)
    (project / "inventory" / "servers.json").write_text(
        json.dumps({"dst": {"host": "h", "user": "u", "auth": {"method": "key"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("ENVB_PROJECT_ROOT", str(root))
    FakeSSHSession.script = []
    FakeSSHSession.commands = []
    FakeSSHSession.opened = []
    return project


def _write(project: Path, name: str, data: Dict[str, Any]) -> None:
    (project / "desired_state" / name).write_text(json.dumps(data), encoding="utf-8")


# --- run_build.main -----------------------------------------------------------------------


def _targets(commands: List[str], **extra: Any) -> Dict[str, Any]:
    target = {"name": "main", "server": "dst", "workdir": "/home/build/src", "commands": commands}
    target.update(extra)
    return {"targets": [target]}


def test_run_build_main_returns_zero_when_every_step_succeeds(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project_dir, "build_targets.local.json", _targets(["./configure", "make"]))
    FakeSSHSession.script = [SSHResult(0, "ok\n", ""), SSHResult(0, "built\n", "")]
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT]) == 0

    assert FakeSSHSession.opened == ["dst"]
    assert FakeSSHSession.commands == [
        "cd -- /home/build/src && ./configure",
        "cd -- /home/build/src && make",
    ]


def test_run_build_main_returns_one_and_stops_when_a_step_fails(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project_dir, "build_targets.local.json", _targets(["a", "b", "c"]))
    FakeSSHSession.script = [SSHResult(0, "", ""), SSHResult(2, "", "boom"), SSHResult(0, "", "")]
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT]) == 1

    assert len(FakeSSHSession.commands) == 2


def test_run_build_main_returns_one_when_stderr_has_error_marker_despite_exit_zero(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project_dir, "build_targets.local.json", _targets(["make"]))
    FakeSSHSession.script = [SSHResult(0, "", "foo.cpp:1: error: oops\n")]
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT]) == 1


def test_run_build_main_returns_one_on_timeout(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(project_dir, "build_targets.local.json", _targets(["make", "make install"]))
    FakeSSHSession.script = [SSHResult(EXIT_CODE_TIMEOUT, "partial", "", status=STATUS_TIMEOUT)]
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT]) == 1

    assert len(FakeSSHSession.commands) == 1


def test_run_build_main_returns_interrupted_exit_code_on_ctrl_c(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project_dir, "build_targets.local.json", _targets(["make", "make install"]))
    FakeSSHSession.script = [SSHInterrupted(SSHResult(EXIT_CODE_INTERRUPTED, "p", "", status=STATUS_INTERRUPTED))]
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT]) == EXIT_CODE_INTERRUPTED == 130

    assert len(FakeSSHSession.commands) == 1


def test_run_build_main_rejects_invalid_env_before_connecting(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project_dir, "build_targets.local.json", _targets(["make"], env={"A;B": "1"}))
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT]) == 1

    assert FakeSSHSession.opened == []  # 接続すらしない


def test_run_build_main_selects_target_by_name(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config = {
        "targets": [
            {"name": "first", "server": "dst", "workdir": "/a", "commands": ["one"]},
            {"name": "second", "server": "dst", "workdir": "/b", "commands": ["two"]},
        ]
    }
    _write(project_dir, "build_targets.local.json", config)
    FakeSSHSession.script = [SSHResult(0, "", "")]
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT, "--target", "second"]) == 0

    assert FakeSSHSession.commands == ["cd -- /b && two"]


def test_run_build_main_returns_one_for_unknown_target(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _write(project_dir, "build_targets.local.json", _targets(["make"]))
    monkeypatch.setattr(run_build, "SSHSession", FakeSSHSession)

    assert run_build.main(["--project", PROJECT, "--target", "nope"]) == 1

    assert "target 'nope' が見つかりません" in capsys.readouterr().out
    assert FakeSSHSession.opened == []


# --- apply_packages.main ------------------------------------------------------------------


def _query(installed: bool) -> SSHResult:
    return SSHResult(0, "0\n" if installed else "1\n", "")


def test_apply_packages_main_installs_only_missing_packages(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(project_dir, "packages.json", {"packages": [{"name": "gcc"}, {"name": "make"}]})
    FakeSSHSession.script = [_query(True), _query(False), SSHResult(0, "", "")]
    monkeypatch.setattr(apply_packages, "SSHSession", FakeSSHSession)

    assert apply_packages.main(["--project", PROJECT]) == 0

    assert FakeSSHSession.commands[-1] == "dnf install -y make"
    assert len(FakeSSHSession.commands) == 3


def test_apply_packages_main_changes_nothing_when_everything_is_installed(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project_dir, "packages.json", {"packages": [{"name": "gcc"}]})
    FakeSSHSession.script = [_query(True)]
    monkeypatch.setattr(apply_packages, "SSHSession", FakeSSHSession)

    assert apply_packages.main(["--project", PROJECT]) == 0

    assert not any("install" in command for command in FakeSSHSession.commands)


def test_apply_packages_main_check_mode_never_installs(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(project_dir, "packages.json", {"packages": [{"name": "gcc"}]})
    FakeSSHSession.script = [_query(False)]
    monkeypatch.setattr(apply_packages, "SSHSession", FakeSSHSession)

    assert apply_packages.main(["--project", PROJECT, "--check"]) == 0

    assert not any("install" in command for command in FakeSSHSession.commands)


def test_apply_packages_main_returns_one_when_install_fails(project_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(project_dir, "packages.json", {"packages": [{"name": "nosuch"}]})
    FakeSSHSession.script = [_query(False), SSHResult(1, "", "No match for argument: nosuch\n")]
    monkeypatch.setattr(apply_packages, "SSHSession", FakeSSHSession)

    assert apply_packages.main(["--project", PROJECT]) == 1


def test_apply_packages_main_rejects_hostile_name_before_connecting(
    project_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _write(project_dir, "packages.json", {"packages": [{"name": "gcc; reboot"}]})
    monkeypatch.setattr(apply_packages, "SSHSession", FakeSSHSession)

    assert apply_packages.main(["--project", PROJECT]) == 1

    assert FakeSSHSession.opened == []
    assert FakeSSHSession.commands == []
