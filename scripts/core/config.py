"""inventory / desired_state の設定ファイルを読み込む。

機密（パスワード等）は設定ファイルに実値を書かず、環境変数から取得する
方針。servers.json は .gitignore で除外され、servers.sample.json のみを
コミットする。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# リポジトリルート（scripts/core/config.py から2つ上）
REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY_DIR = REPO_ROOT / "inventory"
DESIRED_STATE_DIR = REPO_ROOT / "desired_state"
BUILD_ENV_DIR = REPO_ROOT / "build_env"


def _strip_comments(obj):
    """JSON 内の "//" で始まるコメントキーを再帰的に除去する。"""
    if isinstance(obj, dict):
        return {
            k: _strip_comments(v)
            for k, v in obj.items()
            if not (isinstance(k, str) and k.startswith("//"))
        }
    if isinstance(obj, list):
        return [_strip_comments(v) for v in obj]
    return obj


def load_json(path: Path) -> dict:
    """コメント付き JSON を読み込み、コメントを除去して返す。"""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    return _strip_comments(data)


@dataclass
class AuthSpec:
    method: str = "key"  # "key" | "password"
    key_path: Optional[str] = None
    password_env: Optional[str] = None

    def resolve_password(self) -> Optional[str]:
        """password_env で指定された環境変数から実値を取得する。"""
        if self.password_env:
            return os.environ.get(self.password_env)
        return None

    def resolve_key_path(self) -> Optional[Path]:
        if self.key_path:
            return Path(self.key_path).expanduser()
        return None


@dataclass
class ServerSpec:
    name: str
    host: str
    user: str
    port: int = 22
    # 多段の踏み台に対応するため、経由順のキー列で持つ（近い踏み台から順）。
    # 例: ["gateway", "host"] なら local -> gateway -> host -> このサーバ。
    proxy_jump: list = field(default_factory=list)
    auth: AuthSpec = field(default_factory=AuthSpec)

    @classmethod
    def from_dict(cls, name: str, d: dict) -> "ServerSpec":
        auth_d = d.get("auth", {}) or {}
        auth = AuthSpec(
            method=auth_d.get("method", "key"),
            key_path=auth_d.get("key_path"),
            password_env=auth_d.get("password_env"),
        )
        # proxy_jump は文字列（単一）とリスト（多段）の両方を受け付ける。
        raw_pj = d.get("proxy_jump")
        if raw_pj is None:
            proxy_jump: list = []
        elif isinstance(raw_pj, str):
            proxy_jump = [raw_pj]
        else:
            proxy_jump = list(raw_pj)
        return cls(
            name=name,
            host=d["host"],
            user=d["user"],
            port=int(d.get("port", 22)),
            proxy_jump=proxy_jump,
            auth=auth,
        )


@dataclass
class Inventory:
    servers: dict[str, ServerSpec]

    def get(self, name: str) -> ServerSpec:
        if name not in self.servers:
            raise KeyError(
                f"サーバ '{name}' が inventory に定義されていません。"
                f" 定義済み: {list(self.servers)}"
            )
        return self.servers[name]


def load_inventory(path: Optional[Path] = None) -> Inventory:
    """inventory/servers.json を読み込む。無ければ明確なエラーを出す。"""
    path = path or (INVENTORY_DIR / "servers.json")
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。init_config スクリプトで "
            "servers.sample.json から生成してください。"
        )
    raw = load_json(path)
    servers = {name: ServerSpec.from_dict(name, spec) for name, spec in raw.items()}
    return Inventory(servers=servers)
