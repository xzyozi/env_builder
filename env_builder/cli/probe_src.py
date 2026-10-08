"""参照元(src)サーバの現状を収集する。

インストール済みパッケージ一覧、OS情報などを取得し、
build_env/src_snapshot 配下へ保存する。構築先で build を通す際、
「src では何が入っているか」を参照するための材料を集めるのが目的。

使い方:
    uv run python scripts/probe_src.py
    uv run python scripts/probe_src.py --target src
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import load_inventory
from env_builder.core.logging_utils import get_logger
from env_builder.core.project import ProjectRegistry
from env_builder.core.ssh import SSHSession

# 収集コマンド（名前 -> リモートコマンド）。読み取り専用のみ。
PROBES = {
    "os_release": "cat /etc/os-release",
    "kernel": "uname -a",
    "rpm_packages": "rpm -qa | sort",
    "dnf_repolist": "dnf repolist 2>/dev/null || true",
}


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="src", help="収集対象（inventory のキー）")
    add_project_argument(parser)
    args = parser.parse_args(argv)

    profile = ProjectRegistry().resolve(args.project)
    logger = get_logger(project_id=profile.project_id)
    inv = load_inventory(profile.inventory_path)

    out_dir = profile.build_env_dir / "src_snapshot"
    if profile.project_id is not None:
        out_dir = out_dir / profile.project_id
    out_dir = out_dir / args.target
    out_dir.mkdir(parents=True, exist_ok=True)

    logger.info("%s へ接続して現状を収集します", args.target)
    with SSHSession(inv, args.target) as ssh:
        for name, cmd in PROBES.items():
            res = ssh.run(cmd)
            dest = out_dir / f"{name}.txt"
            dest.write_text(res.stdout, encoding="utf-8")
            status = "ok" if res.ok else f"exit={res.exit_code}"
            logger.info("  %-14s -> %s (%s)", name, dest.name, status)

    logger.info("収集完了: %s", out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
