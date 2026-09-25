"""踏み台越しの SSH 実行・ファイル転送。

paramiko を用い、踏み台(bastion)を経由して src / dst へ接続する
（OpenSSH の ProxyJump 相当）。パスワード認証・公開鍵認証の双方に対応。

このモジュールは「接続してコマンドを実行し、結果を返す」ことに責務を
限定する。build のロジックや冪等判定は呼び出し側スクリプトが持つ。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

try:
    import paramiko
except ImportError as e:  # pragma: no cover - 依存未導入時の明確なエラー
    raise ImportError(
        "paramiko が必要です。`uv sync` もしくは `uv add paramiko` で導入してください。"
    ) from e

from .config import Inventory, ServerSpec


@dataclass
class SSHResult:
    """コマンド実行結果。"""

    exit_code: int
    stdout: str
    stderr: str

    @property
    def ok(self) -> bool:
        return self.exit_code == 0


def _connect_one(
    spec: ServerSpec, sock: Optional[object] = None
) -> "paramiko.SSHClient":
    """単一ホストへ接続した SSHClient を返す。sock は踏み台チャネル。"""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    connect_kwargs: dict = {
        "hostname": spec.host,
        "port": spec.port,
        "username": spec.user,
        "timeout": 30,
        "sock": sock,
    }

    if spec.auth.method == "password":
        pw = spec.auth.resolve_password()
        if not pw:
            raise RuntimeError(
                f"[{spec.name}] パスワード認証だが環境変数 "
                f"{spec.auth.password_env} が未設定です。"
            )
        connect_kwargs["password"] = pw
        connect_kwargs["look_for_keys"] = False
        connect_kwargs["allow_agent"] = False
    else:  # key
        key_path = spec.auth.resolve_key_path()
        if key_path:
            connect_kwargs["key_filename"] = str(key_path)

    client.connect(**connect_kwargs)
    return client


class SSHSession:
    """踏み台越しに1ホストへ接続するセッション。

    with 文で使う。proxy_jump が指定されていれば踏み台へ先に接続し、
    そのチャネル(sock)経由で目的ホストへ繋ぐ。
    """

    def __init__(self, inventory: Inventory, target: str):
        self.inventory = inventory
        self.target = target
        self._bastion: Optional[paramiko.SSHClient] = None
        self._client: Optional[paramiko.SSHClient] = None

    def __enter__(self) -> "SSHSession":
        spec = self.inventory.get(self.target)
        sock = None
        if spec.proxy_jump:
            bastion_spec = self.inventory.get(spec.proxy_jump)
            self._bastion = _connect_one(bastion_spec)
            transport = self._bastion.get_transport()
            # 踏み台上で目的ホストへの direct-tcpip チャネルを開く
            sock = transport.open_channel(
                "direct-tcpip",
                (spec.host, spec.port),
                ("127.0.0.1", 0),
            )
        self._client = _connect_one(spec, sock=sock)
        return self

    def __exit__(self, *exc) -> None:
        if self._client:
            self._client.close()
        if self._bastion:
            self._bastion.close()

    def run(self, command: str, timeout: int = 600) -> SSHResult:
        """リモートで1コマンドを実行し結果を返す。

        権限昇格(sudo/su)は行わない方針。root 権限が必要な操作は、
        inventory で root ユーザーとしてログインするサーバ定義を使う。
        """
        if self._client is None:
            raise RuntimeError("セッションが未接続です。with 文で使ってください。")
        stdin, stdout, stderr = self._client.exec_command(command, timeout=timeout)
        out = stdout.read().decode("utf-8", errors="replace")
        err = stderr.read().decode("utf-8", errors="replace")
        code = stdout.channel.recv_exit_status()
        return SSHResult(exit_code=code, stdout=out, stderr=err)

    def get_file(self, remote_path: str, local_path: str) -> None:
        """リモート→ローカルへファイルを取得（download）。"""
        if self._client is None:
            raise RuntimeError("セッションが未接続です。")
        sftp = self._client.open_sftp()
        try:
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()

    def put_file(self, local_path: str, remote_path: str) -> None:
        """ローカル→リモートへファイルを転送（upload）。"""
        if self._client is None:
            raise RuntimeError("セッションが未接続です。")
        sftp = self._client.open_sftp()
        try:
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()
