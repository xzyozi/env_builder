"""env_builder のコマンド一覧と、サブコマンドの振り分け。

各コマンドは `env_builder.cli.<name>` モジュールの `main(argv=None) -> int` として実装する。
ここでは名前とモジュールの対応表だけを持ち、呼ばれたコマンドのモジュールだけを import する
（`--help` や別コマンドの実行で、使わない依存まで読み込まない）。
"""

from __future__ import annotations

import importlib
import sys
from typing import Optional, Sequence, TextIO

# コマンド名 -> (モジュール, 説明)。ファイル名と同じ snake_case を正とする。
COMMANDS = {
    "init_config": ("env_builder.cli.init_config", "sample から inventory の実体ファイルを生成する"),
    "check_connectivity": ("env_builder.cli.check_connectivity", "踏み台越しに SSH 疎通を確認する"),
    "probe_src": ("env_builder.cli.probe_src", "src の現状（OS・パッケージ等）を収集する"),
    "remote_exec": ("env_builder.cli.remote_exec", "任意サーバで単発コマンドを実行する"),
    "run_build": ("env_builder.cli.run_build", "dst で build を実行しログを回収する"),
    "apply_packages": ("env_builder.cli.apply_packages", "packages 定義に沿って導入する"),
    "sync_files": ("env_builder.cli.sync_files", "設定ファイルを src から dst へ仲介転送する"),
    "sync_tree": ("env_builder.cli.sync_tree", "ディレクトリを src から dst へ仲介転送する"),
    "container": ("env_builder.cli.container", "コンテナを解析し、image 移送計画と run 候補を出力する"),
}


def normalize_command(name: str) -> str:
    """`remote-exec` のようなハイフン区切りも、`remote_exec` として受け付ける。"""
    return name.strip().replace("-", "_")


def usage() -> str:
    lines = ["usage: python -m env_builder <command> [args...]", "", "commands:"]
    width = max(len(name) for name in COMMANDS)
    lines.extend(f"  {name:<{width}}  {description}" for name, (_, description) in COMMANDS.items())
    lines.extend(["", "各コマンドの引数は `python -m env_builder <command> --help` で確認できます。"])
    return "\n".join(lines)


def run(argv: Optional[Sequence[str]] = None, stderr: Optional[TextIO] = None) -> int:
    """`<command> [args...]` を受け取り、対応するコマンドの main を実行して終了コードを返す。"""
    args = list(sys.argv[1:] if argv is None else argv)
    err = stderr if stderr is not None else sys.stderr

    if not args:
        print(usage(), file=err)
        return 2
    if args[0] in {"-h", "--help"}:
        print(usage())
        return 0

    name = normalize_command(args[0])
    if name not in COMMANDS:
        print(f"unknown command: {args[0]}\n", file=err)
        print(usage(), file=err)
        return 2

    module = importlib.import_module(COMMANDS[name][0])
    return int(module.main(args[1:]))
