"""SSH ホスト鍵の検証ポリシー。

接続先が本物であることを確認するため、未登録のホスト鍵は既定で拒否する
（中間者攻撃の対策）。パスワードや秘密鍵による認証は、ホスト鍵の検証が済んだ
後でしか行われない。

- 既定（strict）: 未登録のホスト鍵は接続前に拒否し、フィンガープリントを表示する。
- accept-new: 環境変数 ENVB_HOST_KEY_POLICY=accept-new を明示した場合だけ、未登録の
  ホストを専用の known_hosts ファイルへ登録して接続する（初回登録用）。
  既に登録済みのホストで鍵が変わっている場合は、どちらのモードでも拒否される。

known_hosts は、ユーザーの ~/.ssh/known_hosts（読み取りのみ）と、env_builder 専用の
ファイル（既定 ~/.ssh/env_builder_known_hosts、環境変数 ENVB_KNOWN_HOSTS で変更可）を
合わせて参照する。登録先は専用ファイルだけで、ユーザーの known_hosts は変更しない。
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
from pathlib import Path
from typing import Optional

import paramiko
from paramiko.hostkeys import HostKeyEntry

POLICY_ENV = "ENVB_HOST_KEY_POLICY"
KNOWN_HOSTS_ENV = "ENVB_KNOWN_HOSTS"
POLICY_STRICT = "strict"
POLICY_ACCEPT_NEW = "accept-new"

logger = logging.getLogger("env_builder")


class HostKeyError(paramiko.SSHException):
    """ホスト鍵を検証できず、接続を拒否した場合のエラー。"""


def known_hosts_path() -> Path:
    """env_builder 専用の known_hosts ファイルのパスを返す。"""
    override = os.environ.get(KNOWN_HOSTS_ENV)
    if override:
        return Path(override).expanduser()
    return Path.home() / ".ssh" / "env_builder_known_hosts"


def fingerprint_sha256(key: "paramiko.PKey") -> str:
    """OpenSSH の表記（SHA256:...）と同じ形式のフィンガープリントを返す。"""
    digest = hashlib.sha256(key.asbytes()).digest()
    return "SHA256:" + base64.b64encode(digest).decode("ascii").rstrip("=")


class StrictHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """未登録のホスト鍵を拒否する（既定）。"""

    def missing_host_key(self, client, hostname, key) -> None:
        raise HostKeyError(
            f"未登録のホスト鍵のため接続を拒否しました: {hostname} "
            f"({key.get_name()} {fingerprint_sha256(key)})。"
            f"フィンガープリントを別の経路で確認したうえで known_hosts へ登録するか、"
            f"初回のみ {POLICY_ENV}={POLICY_ACCEPT_NEW} を指定して登録してください。"
        )


class AcceptNewHostKeyPolicy(paramiko.MissingHostKeyPolicy):
    """未登録のホストだけを専用 known_hosts へ登録して受け入れる（明示的なオプトイン）。"""

    def __init__(self, known_hosts_file: Optional[Path] = None) -> None:
        self._known_hosts_file = known_hosts_file

    def missing_host_key(self, client, hostname, key) -> None:
        path = self._known_hosts_file or known_hosts_path()
        _append_host_key(path, hostname, key)
        client.get_host_keys().add(hostname, key.get_name(), key)
        logger.warning(
            "未登録のホスト鍵を登録しました: %s (%s %s) -> %s",
            hostname,
            key.get_name(),
            fingerprint_sha256(key),
            path,
        )


def _append_host_key(path: Path, hostname: str, key: "paramiko.PKey") -> None:
    """専用 known_hosts へ1行追記する。既存の内容は変更しない。"""
    if not hostname or any(ch.isspace() or ch == "," for ch in hostname):
        raise HostKeyError(f"known_hosts に登録できないホスト名です: {hostname!r}")
    line = HostKeyEntry([hostname], key).to_line()
    if line is None:
        raise HostKeyError(f"ホスト鍵を known_hosts の形式にできません: {hostname}")

    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8", newline="\n") as handle:
        handle.write(line)


def host_key_policy_from_env(known_hosts_file: Optional[Path] = None) -> "paramiko.MissingHostKeyPolicy":
    """環境変数 ENVB_HOST_KEY_POLICY に応じたポリシーを返す。未指定は strict。"""
    mode = (os.environ.get(POLICY_ENV) or POLICY_STRICT).strip().lower()
    if mode == POLICY_STRICT:
        return StrictHostKeyPolicy()
    if mode == POLICY_ACCEPT_NEW:
        return AcceptNewHostKeyPolicy(known_hosts_file)
    raise ValueError(f"{POLICY_ENV} は {POLICY_STRICT} または {POLICY_ACCEPT_NEW} を指定してください: {mode!r}")


def configure_host_keys(client: "paramiko.SSHClient", known_hosts_file: Optional[Path] = None) -> None:
    """既知のホスト鍵を読み込み、未登録時のポリシーを設定する。"""
    client.load_system_host_keys()
    path = known_hosts_file or known_hosts_path()
    if path.is_file():
        client.load_host_keys(str(path))
    client.set_missing_host_key_policy(host_key_policy_from_env(path))
