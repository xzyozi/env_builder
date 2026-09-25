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

    with 文で使う。proxy_jump（経由順のキー列）が指定されていれば、
    近い踏み台から順に接続し、各段のチャネル(sock)を次段へ引き渡して
    多段に潜る（OpenSSH の ProxyJump チェーン相当）。

    各段は独立した SSH チャネルとして張られ、run() は常に最終ホスト上で
    コマンドを実行する。TTL のように「シェルに ssh を打ち込んで潜る」方式
    ではないため、「今どこにいるか」を見失わない。
    """

    def __init__(self, inventory: Inventory, target: str):
        self.inventory = inventory
        self.target = target
        # 踏み台を含む接続済みクライアントを接続順に保持し、逆順で閉じる。
        self._chain: list[paramiko.SSHClient] = []
        self._client: Optional[paramiko.SSHClient] = None

    def __enter__(self) -> "SSHSession":
        spec = self.inventory.get(self.target)

        sock = None
        prev_transport = None
        # proxy_jump を近い踏み台から順に張っていく。
        hop_specs = [self.inventory.get(h) for h in spec.proxy_jump]
        # 次に繋ぐ相手（踏み台の次段 or 最終ホスト）のアドレスを決めるため、
        # 経由チェーン + 最終ホストを1本の列にする。
        route = hop_specs + [spec]
        for i, hop in enumerate(hop_specs):
            client = _connect_one(hop, sock=sock)
            self._chain.append(client)
            prev_transport = client.get_transport()
            # この踏み台上から「次のホスト」への direct-tcpip チャネルを開く
            next_host = route[i + 1]
            sock = prev_transport.open_channel(
                "direct-tcpip",
                (next_host.host, next_host.port),
                ("127.0.0.1", 0),
            )

        self._client = _connect_one(spec, sock=sock)
        return self

    def __exit__(self, *exc) -> None:
        if self._client:
            self._client.close()
        # 踏み台は接続と逆順で閉じる
        for client in reversed(self._chain):
            client.close()

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
