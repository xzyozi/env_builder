"""ops が受け取るリモートセッションの型。

ops の関数は接続を内部で作らず、`run()` / `get_file()` / `put_file()` を持つセッションを引数で
受け取る。本番では `env_builder.core.ssh.SSHSession` を渡し、テストでは記録済みの結果を返す
fake を渡す（SSH 接続なしで、コマンドの組み立て・成否判定・cleanup の経路を検証できる）。

必要な機能だけを要求するよう、コマンド実行とファイル転送を分けて定義している。コマンド実行の型
`CommandRunner` は、`WorkContext` など core からも使うため `env_builder.core.ssh` にあり、ここで再公開する。
"""

from __future__ import annotations

from typing import Optional, Protocol

from env_builder.core.ssh import CommandRunner

__all__ = ["CommandRunner", "FileTransfer", "RemoteSession"]


class FileTransfer(Protocol):
    """リモートとローカルの間でファイルを転送できるセッション。"""

    def get_file(self, remote_path: str, local_path: str, timeout: Optional[float] = ...) -> None: ...

    def put_file(self, local_path: str, remote_path: str, timeout: Optional[float] = ...) -> None: ...


class RemoteSession(CommandRunner, FileTransfer, Protocol):
    """コマンド実行とファイル転送の両方ができるセッション（`SSHSession` が満たす）。"""
