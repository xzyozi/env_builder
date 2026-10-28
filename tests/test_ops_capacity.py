"""env_builder.ops.capacity の検証。

SSH を fake に差し替え、「src のサイズ + 1 GiB」の基準での合否、測定できない場合の失敗、
リモートで実行するコマンドが読み取り専用であることを確認する。実際の接続は行わない。
"""

import logging
import shlex
from typing import Callable, List, Optional

import pytest

from env_builder.core.ssh import OutputCallback, SSHResult
from env_builder.ops.capacity import (
    RESERVE_BYTES,
    available_command,
    format_bytes,
    has_enough_space,
    measure_command,
    measure_source,
    parent_directories,
    parse_df_available,
    parse_du_total,
    verify_destination_space,
)

GIB = 1024**3

Responder = Callable[[str], SSHResult]


class FakeRunner:
    """run() に渡されたコマンドを記録し、responder の結果を返す fake。"""

    def __init__(self, responder: Responder) -> None:
        self._responder = responder
        self.commands: List[str] = []

    def run(self, command: str, timeout: int = 600, *, on_output: Optional[OutputCallback] = None) -> SSHResult:
        self.commands.append(command)
        return self._responder(command)


def df_output(available_bytes: int, mount: str = "/opt") -> str:
    """`df -Pk` 相当の出力を作る（空きは 1024 バイト単位で出力される）。"""
    total_kib = 500 * 1024 * 1024
    avail_kib = available_bytes // 1024
    used_kib = total_kib - avail_kib
    return (
        "Filesystem     1024-blocks      Used Available Capacity Mounted on\n"
        f"/dev/mapper/vg-opt {total_kib} {used_kib} {avail_kib} 50% {mount}\n"
    )


@pytest.fixture
def logger() -> logging.Logger:
    return logging.getLogger("test_ops_capacity")


# --- コマンドの組み立て --------------------------------------------------------------


def test_measure_command_quotes_each_path_and_ends_options() -> None:
    command = measure_command(["/opt/a b", "/opt/c; reboot"])

    assert command == "du -sbc -- '/opt/a b' '/opt/c; reboot'"
    assert shlex.split(command) == ["du", "-sbc", "--", "/opt/a b", "/opt/c; reboot"]


def test_available_command_quotes_path_and_walks_up_to_an_existing_parent() -> None:
    command = available_command("/opt/new dir; reboot")

    assert command.startswith("p='/opt/new dir; reboot'; ")
    assert 'while [ ! -e "$p" ]; do p=$(dirname -- "$p"); done' in command
    assert command.endswith('LC_ALL=C df -Pk -- "$p"')


@pytest.mark.parametrize("command", [measure_command(["/opt/x"]), available_command("/opt/x")])
def test_remote_commands_are_read_only(command: str) -> None:
    for forbidden in ("rm ", "mv ", "cp ", "tar ", "chmod", "mkdir", "touch", ">", "sudo", "su "):
        assert forbidden not in command


# --- 出力の読み取り --------------------------------------------------------------------


def test_parse_du_total_uses_the_last_total_line() -> None:
    output = "100\t/opt/a\n200\t/opt/b\n300\ttotal\n"

    assert parse_du_total(output) == 300


def test_parse_du_total_is_not_fooled_by_a_path_named_total() -> None:
    output = "100\ttotal\n250\ttotal\n"  # 1 行目は "total" という名前のパス、2 行目が合計

    assert parse_du_total(output) == 250


@pytest.mark.parametrize("output", ["", "du: cannot access\n", "abc\ttotal\n"])
def test_parse_du_total_returns_none_when_unreadable(output: str) -> None:
    assert parse_du_total(output) is None


def test_parse_df_available_converts_kib_to_bytes() -> None:
    assert parse_df_available(df_output(7 * GIB)) == 7 * GIB


def test_parse_df_available_handles_spaces_in_filesystem_and_mount_names() -> None:
    output = "Filesystem 1024-blocks Used Available Capacity Mounted on\nmy fs 1000 400 600 40% /mnt/my disk\n"

    assert parse_df_available(output) == 600 * 1024


@pytest.mark.parametrize(
    "output",
    [
        "",
        "Filesystem 1024-blocks Used Available Capacity Mounted on\n",
        "Filesystem 1024-blocks Used Available Capacity Mounted on\nx 0 0 0 - /\n",
    ],
)
def test_parse_df_available_returns_none_when_unreadable(output: str) -> None:
    assert parse_df_available(output) is None


# --- 判定の基準（データのサイズ + 1 GiB） ----------------------------------------------


def test_reserve_is_one_gib() -> None:
    assert RESERVE_BYTES == GIB


def test_has_enough_space_passes_exactly_at_data_plus_one_gib() -> None:
    assert has_enough_space(5 * GIB, 6 * GIB) is True


def test_has_enough_space_fails_one_byte_below_the_boundary() -> None:
    assert has_enough_space(5 * GIB, 6 * GIB - 1) is False


def test_format_bytes_shows_gib_and_raw_value() -> None:
    assert format_bytes(GIB) == "1.00 GiB (1073741824 bytes)"


# --- measure_source --------------------------------------------------------------------


def test_measure_source_returns_the_total(logger: logging.Logger) -> None:
    runner = FakeRunner(lambda command: SSHResult(0, "10\t/opt/a\n4096\ttotal\n", ""))

    assert measure_source(runner, ["/opt/a"], timeout=30, logger=logger) == 4096
    assert runner.commands == ["du -sbc -- /opt/a"]


def test_measure_source_fails_when_du_fails_so_size_is_never_underestimated(
    logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    # 読み取れないファイルがあると du は一部だけ合計して失敗を返す。その値は使わない
    runner = FakeRunner(lambda command: SSHResult(1, "100\ttotal\n", "du: cannot read directory: Permission denied\n"))

    with caplog.at_level(logging.ERROR, logger="test_ops_capacity"):
        assert measure_source(runner, ["/opt/a"], timeout=30, logger=logger) is None

    assert any("測定できません" in record.getMessage() for record in caplog.records)


def test_measure_source_fails_when_output_has_no_total(logger: logging.Logger) -> None:
    runner = FakeRunner(lambda command: SSHResult(0, "unexpected output\n", ""))

    assert measure_source(runner, ["/opt/a"], timeout=30, logger=logger) is None


# --- verify_destination_space ----------------------------------------------------------


def test_verify_passes_when_space_is_data_plus_one_gib(logger: logging.Logger) -> None:
    runner = FakeRunner(lambda command: SSHResult(0, df_output(6 * GIB), ""))

    assert verify_destination_space(runner, ["/opt/mel/lib64"], 5 * GIB, timeout=30, logger=logger) is True


def test_verify_fails_when_space_is_below_data_plus_one_gib(
    logger: logging.Logger, caplog: pytest.LogCaptureFixture
) -> None:
    runner = FakeRunner(lambda command: SSHResult(0, df_output(6 * GIB - 4096), ""))

    with caplog.at_level(logging.ERROR, logger="test_ops_capacity"):
        assert verify_destination_space(runner, ["/opt/mel/lib64"], 5 * GIB, timeout=30, logger=logger) is False

    messages = [record.getMessage() for record in caplog.records]
    assert any("空きが不足しています" in message and "/opt/mel/lib64" in message for message in messages)


def test_verify_fails_when_df_fails(logger: logging.Logger) -> None:
    runner = FakeRunner(lambda command: SSHResult(1, "", "df: boom\n"))

    assert verify_destination_space(runner, ["/opt/x"], 1, timeout=30, logger=logger) is False


def test_verify_fails_when_df_output_is_unreadable(logger: logging.Logger) -> None:
    runner = FakeRunner(lambda command: SSHResult(0, "garbage\n", ""))

    assert verify_destination_space(runner, ["/opt/x"], 1, timeout=30, logger=logger) is False


def test_verify_checks_each_distinct_destination_once_and_fails_if_any_is_short(logger: logging.Logger) -> None:
    def responder(command: str) -> SSHResult:
        # /small だけ空きが足りない
        return SSHResult(0, df_output(2 * GIB if "/small" in command else 100 * GIB), "")

    runner = FakeRunner(responder)

    ok = verify_destination_space(runner, ["/big", "/small", "/big"], 5 * GIB, timeout=30, logger=logger)

    assert ok is False
    assert len(runner.commands) == 2  # 重複する /big は 1 回だけ調べる


def test_verify_still_checks_remaining_destinations_after_a_failure(logger: logging.Logger) -> None:
    runner = FakeRunner(lambda command: SSHResult(0, df_output(0), ""))

    verify_destination_space(runner, ["/a", "/b"], 1, timeout=30, logger=logger)

    assert len(runner.commands) == 2  # 不足を 1 件見つけても、他の配置先の状況も出力する


# --- parent_directories ----------------------------------------------------------------


def test_parent_directories_returns_the_parent_or_dot() -> None:
    assert parent_directories(["/dst/a.conf", "/dst/sub/b.conf", "c.conf"]) == ["/dst", "/dst/sub", "."]
