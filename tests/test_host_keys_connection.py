"""ローカルの簡易 SSH サーバに対する、ホスト鍵検証の接続テスト（ENVB-0002）。

paramiko のサーバ実装を 127.0.0.1 で起動し、実際の接続でポリシーが働くことを確認する。
認証は検証対象外のため、ホスト鍵の検証結果だけを見る。
"""

import socket
import threading
from pathlib import Path
from typing import Iterator

import paramiko
import pytest

from env_builder.core.host_keys import POLICY_ENV, HostKeyError, configure_host_keys


class _AcceptAllServer(paramiko.ServerInterface):
    """テスト専用: 全ユーザーのパスワード認証を許可する（ホスト鍵の検証だけを見るため）。"""

    def check_auth_password(self, username: str, password: str) -> int:
        return paramiko.AUTH_SUCCESSFUL

    def get_allowed_auths(self, username: str) -> str:
        return "password"


@pytest.fixture
def ssh_server() -> Iterator[tuple]:
    """(port, host_key) を返す。テスト終了時にサーバを停止する。"""
    host_key = paramiko.RSAKey.generate(2048)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    listener.settimeout(0.2)
    port = listener.getsockname()[1]
    stop = threading.Event()
    transports = []

    def serve() -> None:
        while not stop.is_set():
            try:
                conn, _ = listener.accept()
            except (socket.timeout, OSError):
                continue
            transport = paramiko.Transport(conn)
            transport.add_server_key(host_key)
            transports.append(transport)
            try:
                transport.start_server(server=_AcceptAllServer())
            except Exception:  # noqa: BLE001 - クライアントが拒否して切断した場合
                pass

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    try:
        yield port, host_key
    finally:
        stop.set()
        thread.join(timeout=2)
        for transport in transports:
            transport.close()
        listener.close()


def _connect(client: "paramiko.SSHClient", port: int) -> None:
    client.connect(
        "127.0.0.1",
        port=port,
        username="tester",
        password="not-a-real-secret",
        allow_agent=False,
        look_for_keys=False,
        timeout=5,
        auth_timeout=5,
    )


def test_strict_rejects_unregistered_server_before_authentication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ssh_server
) -> None:
    monkeypatch.delenv(POLICY_ENV, raising=False)
    port, _ = ssh_server
    client = paramiko.SSHClient()
    configure_host_keys(client, tmp_path / "env_builder_known_hosts")

    with pytest.raises(HostKeyError):
        _connect(client, port)

    assert client.get_transport() is None or not client.get_transport().is_authenticated()
    client.close()


def test_accept_new_registers_then_later_connections_succeed_in_strict_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ssh_server
) -> None:
    port, _ = ssh_server
    known_hosts = tmp_path / "env_builder_known_hosts"

    monkeypatch.setenv(POLICY_ENV, "accept-new")
    first = paramiko.SSHClient()
    configure_host_keys(first, known_hosts)
    _connect(first, port)
    first.close()
    assert known_hosts.is_file()

    # 登録後は strict でも接続できる
    monkeypatch.delenv(POLICY_ENV, raising=False)
    second = paramiko.SSHClient()
    configure_host_keys(second, known_hosts)
    _connect(second, port)
    assert second.get_transport().is_authenticated()
    second.close()


def test_changed_host_key_is_rejected_even_with_accept_new(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ssh_server
) -> None:
    port, _ = ssh_server
    known_hosts = tmp_path / "env_builder_known_hosts"

    # 同じ host:port に、別の鍵を登録済みにする（なりすましを想定）
    impostor_key = paramiko.RSAKey.generate(2048)
    keys = paramiko.HostKeys()
    keys.add(f"[127.0.0.1]:{port}", "ssh-rsa", impostor_key)
    keys.save(str(known_hosts))

    monkeypatch.setenv(POLICY_ENV, "accept-new")
    client = paramiko.SSHClient()
    configure_host_keys(client, known_hosts)

    with pytest.raises(paramiko.BadHostKeyException):
        _connect(client, port)

    client.close()
