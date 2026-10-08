"""パッケージの冪等な適用（rpm 系）。

desired_state/packages.json の定義に従い、導入済みかを判定して未導入のものだけを導入する
（Ansible の package タスク相当）。接続は内部で作らず、`CommandRunner` を引数で受け取る。

権限昇格(sudo/su)は使わない。root が必要な導入は、呼び出し側が root ログインの
セッション（inventory の `dst_root` など）を渡して行う。
"""

from __future__ import annotations

import shlex
from typing import Any, List, Mapping, Tuple

from env_builder.core.shell import validate_command_name, validate_package_name
from env_builder.core.ssh import SSHResult
from env_builder.ops.session import CommandRunner

DEFAULT_PACKAGE_MANAGER = "dnf"
INSTALL_TIMEOUT_SEC = 1800


def parse_packages_config(config: Mapping[str, Any]) -> Tuple[str, List[str]]:
    """packages.json の内容から、パッケージマネージャ名と導入対象の名前を取り出す。

    `state` が `present`（既定）のものだけを対象にする。値の検証は validate_package_config が行う。
    """
    package_manager = config.get("package_manager", DEFAULT_PACKAGE_MANAGER)
    names = [entry["name"] for entry in config.get("packages", []) if entry.get("state", "present") == "present"]
    return package_manager, names


def validate_package_config(package_manager: str, packages: List[str]) -> None:
    """パッケージマネージャ名とパッケージ名を検証する。不正なら ValueError。

    リモートへ何も送る前に呼び、細工された名前がコマンドに混ざらないようにする。
    """
    validate_command_name(package_manager)
    for name in packages:
        validate_package_name(name)


def rpm_query_command(pkg: str) -> str:
    """導入済みかを rpm で調べるコマンド。名前は検証・クォートし、`--` でオプション誤認を防ぐ。"""
    return f"rpm -q -- {shlex.quote(validate_package_name(pkg))} >/dev/null 2>&1; echo $?"


def install_command(package_manager: str, packages: List[str]) -> str:
    """未導入のパッケージをまとめて導入するコマンド。名前とパッケージマネージャを検証・クォートする。"""
    names = " ".join(shlex.quote(validate_package_name(pkg)) for pkg in packages)
    return f"{shlex.quote(validate_command_name(package_manager))} install -y {names}"


def is_installed(runner: CommandRunner, pkg: str) -> bool:
    """パッケージが導入済みか。rpm の終了コード（`echo $?` の出力）が 0 なら導入済み。"""
    res = runner.run(rpm_query_command(pkg))
    return res.stdout.strip().endswith("0")


def find_missing(runner: CommandRunner, packages: List[str]) -> List[str]:
    """未導入のパッケージを、渡された順序のまま返す（導入済みだけなら空のリスト）。"""
    return [pkg for pkg in packages if not is_installed(runner, pkg)]


def install_missing(
    runner: CommandRunner,
    package_manager: str,
    missing: List[str],
    timeout: int = INSTALL_TIMEOUT_SEC,
) -> SSHResult:
    """未導入のパッケージをまとめて導入する。成否は戻り値の `ok` で判断する。"""
    return runner.run(install_command(package_manager, missing), timeout=timeout)
