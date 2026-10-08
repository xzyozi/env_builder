"""リモートシェルへ渡す値のクォートと検証。

SSH でリモートへ送るコマンドは 1 本の文字列で、リモートのシェルが解釈する。設定ファイル由来の
値（パッケージ名・環境変数・作業ディレクトリ）をそのまま埋め込むと、メタ文字が別のコマンドとして
実行されるため、値はここでリテラルとして扱う。

- 名前系（パッケージ名・環境変数名・コマンド名）は許可文字で検証し、違反時は ValueError にする。
- パスと値は shlex.quote でリテラルにする。先頭の `~` だけは、ホームディレクトリとして扱えるよう
  `"$HOME"` に置き換える（shlex.quote は `~` を展開させないため）。
"""

from __future__ import annotations

import re
import shlex

# rpm / dnf のパッケージ名。バージョン・アーキテクチャ付き（pkg-1.2-3.el8.x86_64）やグループ（@name）を許す。
# 先頭が `-` のものはオプションと解釈されるため拒否する。
_PACKAGE_NAME_RE = re.compile(r"^[A-Za-z0-9_@][A-Za-z0-9._+:@-]*$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_COMMAND_NAME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


def _require_match(value: object, pattern: "re.Pattern[str]", label: str) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise ValueError(f"{label} に使えない文字が含まれています: {value!r}")
    return value


def validate_package_name(name: object) -> str:
    """パッケージ名を検証して返す。"""
    return _require_match(name, _PACKAGE_NAME_RE, "パッケージ名")


def validate_env_name(name: object) -> str:
    """環境変数名を検証して返す（英数字とアンダースコア、先頭は数字不可）。"""
    return _require_match(name, _ENV_NAME_RE, "環境変数名")


def validate_command_name(name: object) -> str:
    """パッケージマネージャ等のコマンド名を検証して返す（パスや引数は許さない）。"""
    return _require_match(name, _COMMAND_NAME_RE, "コマンド名")


def quote_remote_path(path: str) -> str:
    """リモートのパスをリテラルとしてクォートする。先頭の `~` はホームディレクトリとして扱う。"""
    if not isinstance(path, str) or not path:
        raise ValueError(f"パスが空、または文字列ではありません: {path!r}")
    if "\x00" in path:
        raise ValueError("パスに NUL 文字は使えません。")
    if path == "~":
        return '"$HOME"'
    if path.startswith("~/"):
        rest = path[2:]
        return '"$HOME"/' + shlex.quote(rest) if rest else '"$HOME"'
    return shlex.quote(path)
