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
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import load_inventory
from env_builder.core.logging_utils import get_logger, new_run_dir
from env_builder.core.project import ProjectRegistry
from env_builder.core.ssh import SSHInterrupted, SSHSession


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default="dst", help="対象（inventory のキー）")
    add_project_argument(parser)
    parser.add_argument("--save", action="store_true", help="出力を build_env/logs へ保存する")
    parser.add_argument("--timeout", type=int, default=120, help="コマンドのタイムアウト秒")
    parser.add_argument(
        "command",
        nargs="+",
        help="実行するコマンド（-- の後に記述）",
    )
    args = parser.parse_args(argv)

    command = " ".join(args.command)
    profile = ProjectRegistry().resolve(args.project)
    logger = get_logger(project_id=profile.project_id)
    inv = load_inventory(profile.inventory_path)

    logger.info("[%s] 実行: %s", args.target, command)
    interrupted = False
    with SSHSession(inv, args.target) as ssh:
        try:
            res = ssh.run(command, timeout=args.timeout)
        except SSHInterrupted as exc:
            # Ctrl+C。途中までの出力は捨てずに表示・保存する。
            res = exc.result
            interrupted = True

    # 標準出力・標準エラーを表示
    if res.stdout:
        print("----- stdout -----")
        print(res.stdout)
    if res.stderr:
        print("----- stderr -----")
        print(res.stderr)
    if interrupted:
        logger.error("中断されました（Ctrl+C）。リモートのプロセスは停止していない可能性があります。")
    elif res.timed_out:
        logger.error(
            "タイムアウト（%d秒）。それまでの出力を表示しました。リモートのプロセスは停止していない可能性があります。",
            args.timeout,
        )
    logger.info("exit=%d status=%s", res.exit_code, res.status)

    if args.save:
        run_dir = new_run_dir(
            label=f"exec_{args.target}",
            build_env_dir=profile.build_env_dir,
            project_id=profile.project_id,
        )
        (run_dir / "stdout.log").write_text(res.stdout, encoding="utf-8")
        (run_dir / "stderr.log").write_text(res.stderr, encoding="utf-8")
        logger.info("保存先: %s", run_dir)

    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
