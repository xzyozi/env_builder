"""疎通確認スクリプト。

inventory/servers.json の定義に従い、踏み台越しに各サーバへSSH接続し、
whoami / hostname が通るかを確認する。build 作業に入る前段の「接続が
取れること」だけを検証する目的。

権限昇格(sudo/su)は行わない。root 権限が必要なサーバ(dst)は inventory で
root ユーザーとしてログインする定義にしておく。

使い方:
    uv run python scripts/check_connectivity.py            # 全サーバ
    uv run python scripts/check_connectivity.py --target dst
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import load_inventory  # noqa: E402
from core.logging_utils import get_logger  # noqa: E402
from core.ssh import SSHSession  # noqa: E402

# 疎通確認に使う読み取り専用コマンド
CHECK_COMMANDS = {
    "whoami": "whoami",
    "hostname": "hostname",
}


def _check_one(inv, logger, target: str) -> bool:
    spec = inv.get(target)
    via = f"（踏み台 {spec.proxy_jump} 経由）" if spec.proxy_jump else "（直接）"
    logger.info("[%s] %s@%s:%s へ接続します%s",
                target, spec.user, spec.host, spec.port, via)
    try:
        with SSHSession(inv, target) as ssh:
            for label, cmd in CHECK_COMMANDS.items():
                res = ssh.run(cmd, timeout=30)
                if res.ok:
                    logger.info("  %-9s = %s", label, res.stdout.strip())
                else:
                    logger.error("  %-9s 失敗 exit=%d %s",
                                 label, res.exit_code, res.stderr.strip())
                    return False
        logger.info("[%s] 疎通OK", target)
        return True
    except Exception as e:  # 接続自体の失敗（認証・到達性など）
        logger.error("[%s] 接続失敗: %s", target, e)
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--target", default=None,
        help="確認対象（inventory のキー）。未指定なら bastion 以外の全サーバ。",
    )
    args = parser.parse_args()

    logger = get_logger()
    inv = load_inventory()

    if args.target:
        targets = [args.target]
    else:
        # 踏み台は経由先の接続で間接的に検証されるため、単体対象からは除く
        targets = [name for name in inv.servers if name != "bastion"]

    logger.info("疎通確認を開始します: %s", ", ".join(targets))
    results = {t: _check_one(inv, logger, t) for t in targets}

    logger.info("=== 結果 ===")
    all_ok = True
    for t, ok in results.items():
        logger.info("  %-6s : %s", t, "OK" if ok else "NG")
        all_ok = all_ok and ok

    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
