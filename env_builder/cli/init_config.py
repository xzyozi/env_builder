"""設定テンプレート(.sample)から実体ファイルを生成する。

例: inventory/servers.sample.json -> inventory/servers.json
実体ファイルは .gitignore で除外されるため、生成後に実値を埋めて使う。
既存の実体ファイルは上書きしない（--force で上書き）。

使い方:
    uv run python scripts/init_config.py
    uv run python scripts/init_config.py --force
"""

from __future__ import annotations

import argparse
import shutil
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import INVENTORY_DIR
from env_builder.core.project import ProjectRegistry


def _mappings(profile):
    return [(INVENTORY_DIR / "servers.sample.json", profile.inventory_path)]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    add_project_argument(parser)
    parser.add_argument("--force", action="store_true", help="既存の実体ファイルを上書きする")
    args = parser.parse_args(argv)

    profile = ProjectRegistry().resolve(args.project, allow_missing=args.project is not None)
    if args.project is not None:
        profile.root_dir.mkdir(parents=True, exist_ok=True)

    created = 0
    for sample, target in _mappings(profile):
        if not sample.exists():
            print(f"[skip] テンプレートが見つかりません: {sample.name}")
            continue
        if target.exists() and not args.force:
            print(f"[keep] 既存のため維持: {target.name}（上書きは --force）")
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(sample, target)
        print(f"[ok]   生成: {target.name}")
        created += 1

    if created:
        print(
            "\n生成したファイルに実値（ホスト名・ユーザー名等）を記入してください。"
            "\nパスワードは password_env で指定した環境変数へ設定します。"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
