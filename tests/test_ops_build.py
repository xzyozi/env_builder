"""env_builder.ops.build の検証。

SSH を fake のセッションに差し替え、build の成否判定・途中停止・タイムアウト・Ctrl+C・
実行中ログの追記を確認する。実際の接続は行わない。
"""

import logging
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from env_builder.core.ssh import (
    EXIT_CODE_INTERRUPTED,
    EXIT_CODE_TIMEOUT,
    STATUS_INTERRUPTED,
    STATUS_TIMEOUT,
    OutputCallback,
    SSHInterrupted,
    SSHResult,
)
from env_builder.ops.build import (
    BUILD_ERROR_MARKERS,
    STEP_TIMEOUT_SEC,
    env_prefix,
    has_build_error,
    run_build_steps,
    step_command,
    validate_build_target,
)

# 1 回の run() に対する振る舞い。結果を返すか、例外を送出する。
Behavior = Callable[[Optional[OutputCallback]], SSHResult]


def _ok(stdout: str = "", stderr: str = "", live: bool = True) -> Behavior:
    """正常終了。live なら、出力を実行中に on_output へ流してから結果を返す。"""

    def behave(on_output: Optional[OutputCallback]) -> SSHResult:
        if live and on_output is not None:
            if stdout:
                on_output("stdout", stdout)
            if stderr:
                on_output("stderr", stderr)
        return SSHResult(0, stdout, stderr)

    return behave


def _result(result: SSHResult, live_stdout: str = "", live_stderr: str = "") -> Behavior:
    def behave(on_output: Optional[OutputCallback]) -> SSHResult:
        if on_output is not None:
            if live_stdout:
                on_output("stdout", live_stdout)
            if live_stderr:
                on_output("stderr", live_stderr)
        return result

    return behave


def _interrupted(partial_stdout: str = "", partial_stderr: str = "") -> Behavior:
    def behave(on_output: Optional[OutputCallback]) -> SSHResult:
        if on_output is not None and partial_stdout:
            on_output("stdout", partial_stdout)
        raise SSHInterrupted(
            SSHResult(EXIT_CODE_INTERRUPTED, partial_stdout, partial_stderr, status=STATUS_INTERRUPTED)
        )

    return behave


class FakeRunner:
    """run() ごとに、あらかじめ決めた振る舞いを順に返す。呼ばれたコマンドとタイムアウトを記録する。"""

    def __init__(self, behaviors: List[Behavior]) -> None:
        self._behaviors = list(behaviors)
        self.calls: List[tuple] = []

    def run(
        self,
        command: str,
        timeout: int = 600,
        *,
        on_output: Optional[OutputCallback] = None,
    ) -> SSHResult:
        self.calls.append((command, timeout))
        return self._behaviors.pop(0)(on_output)

    @property
    def commands(self) -> List[str]:
        return [command for command, _ in self.calls]


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_ops_build")


def _run(runner: FakeRunner, run_dir: Path, logger: logging.Logger, commands: List[str], **kwargs):
    return run_build_steps(
        runner,
        workdir=kwargs.pop("workdir", "/home/build/src"),
        commands=commands,
        prefix=kwargs.pop("prefix", ""),
        run_dir=run_dir,
        logger=logger,
        **kwargs,
    )


# --- コマンドの組み立て・検証 -------------------------------------------------


def test_has_build_error_detects_each_marker() -> None:
    for marker in BUILD_ERROR_MARKERS:
        assert has_build_error(f"prefix {marker} suffix"), marker


def test_has_build_error_ignores_ordinary_warnings() -> None:
    assert not has_build_error("warning: unused variable 'x'\nnote: declared here\n")
    assert not has_build_error("")


def test_validate_build_target_returns_export_prefix() -> None:
    assert validate_build_target("/home/build", {"VERSION_MNG": "/opt/x"}) == "export VERSION_MNG=/opt/x; "


def test_validate_build_target_accepts_empty_env() -> None:
    assert validate_build_target("/home/build", {}) == ""


@pytest.mark.parametrize("env", [{"A-B": "1"}, {"A B": "1"}, {"1A": "1"}, {"A;B": "1"}, {"": "1"}])
def test_validate_build_target_rejects_invalid_env_names(env: dict) -> None:
    with pytest.raises(ValueError):
        validate_build_target("/home/build", env)


@pytest.mark.parametrize("workdir", ["", "/home/\x00build"])
def test_validate_build_target_rejects_invalid_workdir(workdir: str) -> None:
    with pytest.raises(ValueError):
        validate_build_target(workdir, {})


def test_env_prefix_and_step_command_compose_into_one_remote_command() -> None:
    prefix = env_prefix({"CC": "gcc -O2"})

    assert (
        step_command("/home/build/src", prefix, "make -j4") == "cd -- /home/build/src && export CC='gcc -O2'; make -j4"
    )


# --- 実行 -----------------------------------------------------------------------


def test_all_steps_succeed(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok("configured\n"), _ok("built\n", "warning: x\n")])

    outcome = _run(runner, tmp_path, logger, ["./configure", "make"])

    assert outcome.ok
    assert outcome.stopped_at is None
    assert outcome.steps_run == 2
    assert not outcome.interrupted and not outcome.timed_out
    assert runner.commands == [
        "cd -- /home/build/src && ./configure",
        "cd -- /home/build/src && make",
    ]
    assert (tmp_path / "step01.stdout.log").read_text(encoding="utf-8") == "configured\n"
    assert (tmp_path / "step02.stdout.log").read_text(encoding="utf-8") == "built\n"
    assert (tmp_path / "step02.stderr.log").read_text(encoding="utf-8") == "warning: x\n"


def test_each_step_uses_the_step_timeout_by_default(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok(), _ok()])

    _run(runner, tmp_path, logger, ["a", "b"])

    assert [timeout for _, timeout in runner.calls] == [STEP_TIMEOUT_SEC, STEP_TIMEOUT_SEC] == [3600, 3600]


def test_timeout_can_be_overridden(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok()])

    _run(runner, tmp_path, logger, ["a"], timeout=30)

    assert runner.calls[0][1] == 30


def test_environment_prefix_is_applied_to_every_step(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok(), _ok()])

    _run(runner, tmp_path, logger, ["a", "b"], prefix="export A=1; ")

    assert runner.commands == [
        "cd -- /home/build/src && export A=1; a",
        "cd -- /home/build/src && export A=1; b",
    ]


def test_nonzero_exit_stops_the_build_and_skips_later_steps(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok("one\n"), _result(SSHResult(2, "", "boom\n")), _ok("never\n")])

    outcome = _run(runner, tmp_path, logger, ["a", "b", "c"])

    assert not outcome.ok
    assert outcome.stopped_at == 2
    assert outcome.steps_run == 2
    assert len(runner.calls) == 2
    assert not (tmp_path / "step03.stdout.log").exists()


def test_build_error_marker_fails_the_step_even_when_exit_code_is_zero(tmp_path: Path, logger: logging.Logger) -> None:
    """終了コードが 0 でも、stderr にエラー痕跡があれば失敗。typechk.sh 経由で伝播しないため。"""
    runner = FakeRunner([_ok("", "foo.cpp:3: error: expected ';'\n"), _ok("never\n")])

    outcome = _run(runner, tmp_path, logger, ["make", "make install"])

    assert not outcome.ok
    assert outcome.stopped_at == 1
    assert len(runner.calls) == 1


def test_warnings_alone_do_not_fail_a_step(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok("", "warning: deprecated\n")])

    outcome = _run(runner, tmp_path, logger, ["make"])

    assert outcome.ok


def test_failure_logs_the_tail_of_stderr(
    tmp_path: Path, logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    stderr = "".join(f"line {i}\n" for i in range(40)) + "make: *** [all] Error 1\n"
    runner = FakeRunner([_result(SSHResult(2, "", stderr))])

    with caplog.at_level(logging.ERROR, logger="test_ops_build"):
        _run(runner, tmp_path, logger, ["make"])

    messages = [record.getMessage() for record in caplog.records]
    assert any("失敗 exit=2" in message and "エラー痕跡検出=True" in message for message in messages)
    tail = [message for message in messages if message.startswith("    | ")]
    assert len(tail) == 15  # 末尾 15 行だけを要約表示する
    assert tail[-1] == "    | make: *** [all] Error 1"
    assert "    | line 0" not in tail


def test_timeout_stops_the_build_and_is_distinguished(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner(
        [
            _result(SSHResult(EXIT_CODE_TIMEOUT, "partial\n", "", status=STATUS_TIMEOUT), live_stdout="partial\n"),
            _ok("never\n"),
        ]
    )

    outcome = _run(runner, tmp_path, logger, ["make", "make install"], timeout=5)

    assert not outcome.ok
    assert outcome.timed_out
    assert not outcome.interrupted
    assert outcome.stopped_at == 1
    assert len(runner.calls) == 1
    # タイムアウトまでの出力はログに残る
    assert (tmp_path / "step01.stdout.log").read_text(encoding="utf-8") == "partial\n"


def test_timeout_message_reports_the_configured_seconds(
    tmp_path: Path, logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    runner = FakeRunner([_result(SSHResult(EXIT_CODE_TIMEOUT, "", "", status=STATUS_TIMEOUT))])

    with caplog.at_level(logging.ERROR, logger="test_ops_build"):
        _run(runner, tmp_path, logger, ["make"], timeout=42)

    assert any("タイムアウト（42秒）" in record.getMessage() for record in caplog.records)


def test_interrupt_stops_the_build_and_keeps_partial_logs(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_interrupted("compiling a.o\n", "")])

    outcome = _run(runner, tmp_path, logger, ["make", "make install"])

    assert not outcome.ok
    assert outcome.interrupted
    assert not outcome.timed_out
    assert outcome.stopped_at == 1
    assert len(runner.calls) == 1
    assert (tmp_path / "step01.stdout.log").read_text(encoding="utf-8") == "compiling a.o\n"


def test_output_is_appended_while_running_and_replaced_by_the_final_output(
    tmp_path: Path, logger: logging.Logger
) -> None:
    """実行中は生の出力を追記し、終了後にノイズ除去済みの最終出力で上書きする。"""
    seen_during_run: List[str] = []

    def behave(on_output: Optional[OutputCallback]) -> SSHResult:
        assert on_output is not None
        on_output("stdout", "building...\n")
        # 実行の途中でも、すでにログファイルへ書かれている
        seen_during_run.append((tmp_path / "step01.stdout.log").read_text(encoding="utf-8"))
        on_output("stdout", "logout\n")
        return SSHResult(0, "building...", "")  # 最終出力はノイズ（logout）が除かれている

    outcome = _run(FakeRunner([behave]), tmp_path, logger, ["make"])

    assert outcome.ok
    assert seen_during_run == ["building...\n"]
    assert (tmp_path / "step01.stdout.log").read_text(encoding="utf-8") == "building..."


def test_stream_outputs_go_to_separate_files(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok("to-stdout\n", "to-stderr\n")])

    _run(runner, tmp_path, logger, ["make"])

    assert (tmp_path / "step01.stdout.log").read_text(encoding="utf-8") == "to-stdout\n"
    assert (tmp_path / "step01.stderr.log").read_text(encoding="utf-8") == "to-stderr\n"


def test_no_commands_is_a_successful_empty_build(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([])

    outcome = _run(runner, tmp_path, logger, [])

    assert outcome.ok
    assert outcome.steps_run == 0
    assert runner.calls == []


def test_hostile_workdir_cannot_inject_a_command(tmp_path: Path, logger: logging.Logger) -> None:
    runner = FakeRunner([_ok()])

    _run(runner, tmp_path, logger, ["make"], workdir="/opt/a; touch /tmp/pwned")

    assert runner.commands == ["cd -- '/opt/a; touch /tmp/pwned' && make"]
