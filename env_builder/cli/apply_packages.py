"""desired_state/packages.json に従い、構築先へ OSS パッケージを冪等に適用する。

Ansible の package タスク相当。既に導入済みならスキップし、未導入のものだけ
インストールする。--check で「何が不足しているか」だけを表示する dry-run も可能。

使い方:
    uv run python scripts/apply_packages.py --check      # 差分確認のみ
    uv run python scripts/apply_packages.py              # 適用（dst は root ログイン前提）
    uv run python scripts/apply_packages.py --target dst
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import load_inventory
from env_builder.core.desired_state import load_packages
from env_builder.core.logging_utils import get_logger
from env_builder.core.project import ProjectRegistry
from env_builder.core.ssh import SSHSession
from env_builder.ops.packages import (
    find_missing,
    install_command,
    install_missing,
    parse_packages_config,
    validate_package_config,
)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="dst", help="適用対象（inventory のキー）")
    add_project_argument(parser)
    parser.add_argument("--check", action="store_true", help="dry-run（差分のみ表示）")
    args = parser.parse_args(argv)

    profile = ProjectRegistry().resolve(args.project)
    logger = get_logger(project_id=profile.project_id)
    cfg = load_packages(profile.desired_state_dir)
    pm, packages = parse_packages_config(cfg)

    # リモートへ何も送る前に、パッケージ名とパッケージマネージャを検証する。
    try:
        validate_package_config(pm, packages)
    except ValueError as exc:
        logger.error("packages.json の内容が不正です: %s", exc)
        return 1

    inv = load_inventory(profile.inventory_path)

    logger.info("%s の状態を確認します（package_manager=%s）", args.target, pm)
    with SSHSession(inv, args.target) as ssh:
        missing = find_missing(ssh, packages)

        if not missing:
            logger.info("すべて導入済み。変更なし（冪等）。")
            return 0

        logger.info("未導入: %s", ", ".join(missing))
        if args.check:
            logger.info("--check 指定のため適用しません。")
            return 0

        # sudo は使わない方針。dst は root でログインしている前提。
        logger.info("インストールを実行します: %s", install_command(pm, missing))
        res = install_missing(ssh, pm, missing)
        if res.ok:
            logger.info("インストール成功")
            return 0
        logger.error("インストール失敗 exit=%d", res.exit_code)
        for line in res.stderr.strip().splitlines()[-15:]:
            logger.error("  | %s", line)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
