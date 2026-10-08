"""env_builder.ops.packages の検証。

SSH を fake のセッションに差し替え、導入済み判定・冪等性・設定の解釈・失敗の扱いを確認する。
実際の接続は行わない。
"""

from typing import Dict, List, Optional

import pytest

from env_builder.core.ssh import OutputCallback, SSHResult
from env_builder.ops.packages import (
    DEFAULT_PACKAGE_MANAGER,
    INSTALL_TIMEOUT_SEC,
    find_missing,
    install_command,
    install_missing,
    is_installed,
    parse_packages_config,
    rpm_query_command,
    validate_package_config,
)


class FakeRunner:
    """run() の呼び出しを記録し、コマンドごとに用意した結果を返す。"""

    def __init__(self, results: Optional[Dict[str, SSHResult]] = None, default: Optional[SSHResult] = None) -> None:
        self._results = results or {}
        self._default = default or SSHResult(0, "0\n", "")
        self.calls: List[tuple] = []

    def run(
        self,
        command: str,
        timeout: int = 600,
        *,
        on_output: Optional[OutputCallback] = None,
    ) -> SSHResult:
        self.calls.append((command, timeout))
        return self._results.get(command, self._default)

    @property
    def commands(self) -> List[str]:
        return [command for command, _ in self.calls]


def _query_result(installed: bool) -> SSHResult:
    """`rpm -q ...; echo $?` の出力。導入済みなら 0、未導入なら rpm の終了コード(1)。"""
    return SSHResult(0, "0\n" if installed else "1\n", "")


def test_parse_packages_config_uses_default_manager_and_present_state() -> None:
    manager, names = parse_packages_config(
        {
            "packages": [
                {"name": "gcc"},
                {"name": "make", "state": "present"},
                {"name": "unwanted", "state": "absent"},
            ]
        }
    )

    assert manager == DEFAULT_PACKAGE_MANAGER == "dnf"
    assert names == ["gcc", "make"]


def test_parse_packages_config_respects_explicit_package_manager() -> None:
    manager, names = parse_packages_config({"package_manager": "yum", "packages": [{"name": "gcc"}]})

    assert manager == "yum"
    assert names == ["gcc"]


def test_parse_packages_config_handles_empty_definition() -> None:
    assert parse_packages_config({}) == ("dnf", [])


def test_validate_package_config_accepts_normal_definition() -> None:
    validate_package_config("dnf", ["gcc", "libcurl-devel", "pkg-1.2-3.el8.x86_64"])


@pytest.mark.parametrize("manager", ["dnf; reboot", "/usr/bin/dnf", "dnf -y", "", "$(reboot)"])
def test_validate_package_config_rejects_unsafe_manager(manager: str) -> None:
    with pytest.raises(ValueError):
        validate_package_config(manager, ["gcc"])


@pytest.mark.parametrize("name", ["-y", "a b", "a;b", "$(x)", "a\nb", ""])
def test_validate_package_config_rejects_unsafe_package_name(name: str) -> None:
    with pytest.raises(ValueError):
        validate_package_config("dnf", ["gcc", name])


def test_is_installed_true_when_rpm_exit_code_is_zero() -> None:
    runner = FakeRunner(default=_query_result(True))

    assert is_installed(runner, "gcc") is True
    assert runner.commands == [rpm_query_command("gcc")]


def test_is_installed_false_when_rpm_exit_code_is_nonzero() -> None:
    runner = FakeRunner(default=_query_result(False))

    assert is_installed(runner, "gcc") is False


def test_find_missing_returns_only_uninstalled_in_given_order() -> None:
    runner = FakeRunner(
        {
            rpm_query_command("gcc"): _query_result(True),
            rpm_query_command("make"): _query_result(False),
            rpm_query_command("cmake"): _query_result(True),
            rpm_query_command("libcurl-devel"): _query_result(False),
        }
    )

    assert find_missing(runner, ["gcc", "make", "cmake", "libcurl-devel"]) == ["make", "libcurl-devel"]
    # 渡した順に、1 パッケージにつき 1 回だけ問い合わせる
    assert runner.commands == [
        rpm_query_command("gcc"),
        rpm_query_command("make"),
        rpm_query_command("cmake"),
        rpm_query_command("libcurl-devel"),
    ]


def test_find_missing_is_empty_when_everything_is_installed_so_nothing_is_changed() -> None:
    """すべて導入済みなら空のリスト（冪等）。リモートへ送るのは読み取りの問い合わせだけ。"""
    runner = FakeRunner(default=_query_result(True))

    assert find_missing(runner, ["gcc", "make"]) == []
    assert all(command.startswith("rpm -q --") for command in runner.commands)
    assert not any("install" in command for command in runner.commands)


def test_find_missing_with_no_packages_makes_no_remote_calls() -> None:
    runner = FakeRunner()

    assert find_missing(runner, []) == []
    assert runner.calls == []


def test_find_missing_never_sends_a_hostile_name_to_the_remote() -> None:
    runner = FakeRunner()

    with pytest.raises(ValueError):
        find_missing(runner, ["gcc", "a; reboot"])

    # 正当な名前の問い合わせは先に行われうるが、細工された名前は送られない
    assert not any("reboot" in command for command in runner.commands)


def test_install_missing_runs_one_install_with_long_timeout() -> None:
    runner = FakeRunner(default=SSHResult(0, "", ""))

    result = install_missing(runner, "dnf", ["make", "libcurl-devel"])

    assert result.ok
    assert runner.calls == [(install_command("dnf", ["make", "libcurl-devel"]), INSTALL_TIMEOUT_SEC)]
    assert runner.commands == ["dnf install -y make libcurl-devel"]


def test_install_missing_reports_failure_without_raising() -> None:
    failure = SSHResult(1, "", "No match for argument: nosuch")
    runner = FakeRunner(default=failure)

    result = install_missing(runner, "dnf", ["nosuch"])

    assert not result.ok
    assert result.exit_code == 1
    assert result.stderr == "No match for argument: nosuch"


def test_install_missing_treats_a_timeout_as_failure() -> None:
    runner = FakeRunner(default=SSHResult(124, "partial", "", status="timeout"))

    result = install_missing(runner, "dnf", ["gcc"])

    assert not result.ok
    assert result.timed_out


def test_install_missing_rejects_hostile_package_manager_before_running() -> None:
    runner = FakeRunner()

    with pytest.raises(ValueError):
        install_missing(runner, "dnf; reboot", ["gcc"])

    assert runner.calls == []
