"""任意サーバで単発コマンドを実行し、結果を表示・保存する汎用調査ツール。

build 前の調査（ディレクトリ構成の確認、ビルド定義の把握、logout 出力の
原因調査など）に使う。実行判断は Agent が行う前提で、コマンドは引数で渡す。

権限昇格(sudo/su)は行わない。root が必要な操作は --target dst_root を使う。

使い方:
    uv run python scripts/remote_exec.py --target dst -- "ls -la /home/seigyo/neo_app/src/libscl"
    uv run python scripts/remote_exec.py --target dst --save -- "cat Makefile"
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import load_inventory  # noqa: E402
from core.logging_utils import get_logger, new_run_dir  # noqa: E402
from core.ssh import SSHSession  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="dst", help="対象（inventory のキー）")
    parser.add_argument("--save", action="store_true", help="出力を build_env/logs へ保存する")
    parser.add_argument("--timeout", type=int, default=120, help="コマンドのタイムアウト秒")
    parser.add_argument(
        "command", nargs="+",
        help="実行するコマンド（-- の後に記述）",
    )
    args = parser.parse_args()

    command = " ".join(args.command)
    logger = get_logger()
    inv = load_inventory()

    logger.info("[%s] 実行: %s", args.target, command)
    with SSHSession(inv, args.target) as ssh:
        res = ssh.run(command, timeout=args.timeout)

    # 標準出力・標準エラーを表示
    if res.stdout:
        print("----- stdout -----")
        print(res.stdout)
    if res.stderr:
        print("----- stderr -----")
        print(res.stderr)
    logger.info("exit=%d", res.exit_code)

    if args.save:
        run_dir = new_run_dir(label=f"exec_{args.target}")
        (run_dir / "stdout.log").write_text(res.stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(res.stderr, encoding="utf-8")
        logger.info("保存先: %s", run_dir)

    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
