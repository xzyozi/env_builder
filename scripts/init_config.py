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
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import DESIRED_STATE_DIR, INVENTORY_DIR  # noqa: E402

# (sample パス, 生成先パス) の対応
MAPPINGS = [
    (INVENTORY_DIR / "servers.sample.json", INVENTORY_DIR / "servers.json"),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="既存の実体ファイルを上書きする"
    )
    args = parser.parse_args()

    created = 0
    for sample, target in MAPPINGS:
        if not sample.exists():
            print(f"[skip] テンプレートが見つかりません: {sample.name}")
            continue
        if target.exists() and not args.force:
            print(f"[keep] 既存のため維持: {target.name}（上書きは --force）")
            continue
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
