"""設定テンプレート(.sample)から実体ファイルを生成する。

例: inventory/servers.sample.json -> inventory/servers.json
    inventory/set_env.sample.bat  -> <project>/build_env/set_env.bat
実体ファイルは .gitignore で除外されるため、生成後に実値を埋めて使う。
既存の実体ファイルは上書きしない。

- --force: servers.json のみ上書きする。
- --force-credentials: 認証情報を持つ set_env.bat を上書きする。
  上書き前に set_env.bat.bak へ退避する。

使い方:
    uv run python scripts/init_config.py
    uv run python scripts/init_config.py --force
    uv run python scripts/init_config.py --force-credentials
"""

from __future__ import annotations

import argparse
import shutil
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import INVENTORY_DIR
from env_builder.core.project import ProjectRegistry


def _mappings(profile):
    """(テンプレート, 実体, 認証情報を含むか) の一覧を返す。"""
    return [
        (INVENTORY_DIR / "servers.sample.json", profile.inventory_path, False),
        (INVENTORY_DIR / "set_env.sample.bat", profile.build_env_dir / "set_env.bat", True),
    ]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    add_project_argument(parser)
    parser.add_argument("--force", action="store_true", help="既存の servers.json を上書きする（set_env.bat は対象外）")
    parser.add_argument(
        "--force-credentials",
        action="store_true",
        help="既存の set_env.bat を上書きする（上書き前に set_env.bat.bak へ退避）",
    )
    args = parser.parse_args(argv)

    profile = ProjectRegistry().resolve(args.project, allow_missing=args.project is not None)
    if args.project is not None:
        profile.root_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    created_env = False
    for sample, target, is_credential in _mappings(profile):
        if not sample.exists():
            print(f"[skip] テンプレートが見つかりません: {sample.name}")
            continue
        overwrite = args.force_credentials if is_credential else args.force
        if target.exists() and not overwrite:
            hint = "--force-credentials" if is_credential else "--force"
            print(f"[keep] 既存のため維持: {target.name}（上書きは {hint}）")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists() and is_credential:
            backup = target.with_name(target.name + ".bak")
            shutil.copyfile(target, backup)
            print(f"[bak]  退避: {backup.name}")
        shutil.copyfile(sample, target)
        print(f"[ok]   生成: {target.name}")
        created += 1
        created_env = created_env or is_credential

    if created:
        print(
            "\n生成したファイルに実値（ホスト名・ユーザー名等）を記入してください。"
            "\nパスワードは password_env で指定した環境変数へ設定します。"
        )
    if created_env:
        print(
            "build_env\\set_env.bat に認証情報を記入し、"
            "実行前に `call build_env\\set_env.bat` で環境変数へ読み込んでください。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
