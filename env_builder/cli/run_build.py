"""構築先(dst)で build を実行し、ログを回収する。

desired_state/build_targets.local.json の定義に従い、リモートの作業ディレクトリ
でビルドコマンドを順に実行する。環境固有値（サーバ・パス等）を含む定義は Git
管理外の *.local.json に置く。stdout/stderr と終了コードを build_env/logs へ
保存する。エラーになった箇所を調査 → 環境を整える → 再実行、のループを回す
ための中核スクリプト。

使い方:
    uv run python scripts/run_build.py
    uv run python scripts/run_build.py --target main
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import load_inventory
from env_builder.core.desired_state import load_build_targets
from env_builder.core.logging_utils import get_logger, new_run_dir
from env_builder.core.project import ProjectRegistry
from env_builder.core.ssh import EXIT_CODE_INTERRUPTED, SSHSession
from env_builder.ops.build import run_build_steps, validate_build_target


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=None, help="build_targets の name。未指定なら先頭")
    add_project_argument(parser)
    args = parser.parse_args(argv)

    profile = ProjectRegistry().resolve(args.project)
    cfg = load_build_targets(profile.desired_state_dir)
    targets = cfg.get("targets", [])
    if not targets:
        print("build_targets.json に targets がありません。")
        return 1

    target = targets[0]
    if args.target:
        matched = [t for t in targets if t.get("name") == args.target]
        if not matched:
            print(f"target '{args.target}' が見つかりません。")
            return 1
        target = matched[0]

    run_dir = new_run_dir(
        label=f"build_{target.get('name', 'main')}",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    )
    logger = get_logger(logfile=run_dir / "run.log", project_id=profile.project_id)
    inv = load_inventory(profile.inventory_path)

    server = target.get("server", "dst")
    workdir = target["workdir"]
    commands = target.get("commands", [])
    env = target.get("env", {})

    # リモートへ何も送る前に、環境変数名と作業ディレクトリを検証する。
    try:
        prefix = validate_build_target(workdir, env)
    except ValueError as exc:
        logger.error("build_targets の内容が不正です: %s", exc)
        return 1

    logger.info("build 開始: target=%s server=%s workdir=%s", target.get("name"), server, workdir)

    with SSHSession(inv, server) as ssh:
        outcome = run_build_steps(
            ssh,
            workdir=workdir,
            commands=commands,
            prefix=prefix,
            run_dir=run_dir,
            logger=logger,
        )

    logger.info("ログ保存先: %s", run_dir)
    if outcome.ok:
        logger.info("build 成功")
        return 0
    if outcome.interrupted:
        logger.error("build を中断しました。それまでのログは上記に保存されています。")
        return EXIT_CODE_INTERRUPTED
    logger.error("build 失敗。上記ログを参照して環境を整えてください。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
