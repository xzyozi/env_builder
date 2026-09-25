"""desired_state/packages.json に従い、構築先へ OSS パッケージを冪等に適用する。

Ansible の package タスク相当。既に導入済みならスキップし、未導入のものだけ
インストールする。--check で「何が不足しているか」だけを表示する dry-run も可能。

使い方:
    uv run python scripts/apply_packages.py --check      # 差分確認のみ
    uv run python scripts/apply_packages.py              # 適用（要 sudo 権限）
    uv run python scripts/apply_packages.py --target dst
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import DESIRED_STATE_DIR, load_inventory, load_json  # noqa: E402
from core.logging_utils import get_logger  # noqa: E402
from core.ssh import SSHSession  # noqa: E402


def _load_packages() -> dict:
    path = DESIRED_STATE_DIR / "packages.json"
    if not path.exists():
        sample = DESIRED_STATE_DIR / "packages.sample.json"
        raise FileNotFoundError(
            f"{path.name} がありません。{sample.name} を複製して実値を埋めてください。"
        )
    return load_json(path)


def _is_installed(ssh: SSHSession, pkg: str) -> bool:
    res = ssh.run(f"rpm -q {pkg} >/dev/null 2>&1; echo $?")
    return res.stdout.strip().endswith("0")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="dst", help="適用対象（inventory のキー）")
    parser.add_argument("--check", action="store_true", help="dry-run（差分のみ表示）")
    args = parser.parse_args()

    logger = get_logger()
    cfg = _load_packages()
    pm = cfg.get("package_manager", "dnf")
    packages = [p["name"] for p in cfg.get("packages", []) if p.get("state", "present") == "present"]
    inv = load_inventory()

    logger.info("%s の状態を確認します（package_manager=%s）", args.target, pm)
    with SSHSession(inv, args.target) as ssh:
        missing = [p for p in packages if not _is_installed(ssh, p)]

        if not missing:
            logger.info("すべて導入済み。変更なし（冪等）。")
            return 0

        logger.info("未導入: %s", ", ".join(missing))
        if args.check:
            logger.info("--check 指定のため適用しません。")
            return 0

        install_cmd = f"sudo {pm} install -y " + " ".join(missing)
        logger.info("インストールを実行します: %s", install_cmd)
        res = ssh.run(install_cmd, timeout=1800)
        if res.ok:
            logger.info("インストール成功")
            return 0
        logger.error("インストール失敗 exit=%d", res.exit_code)
        for line in res.stderr.strip().splitlines()[-15:]:
            logger.error("  | %s", line)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
