"""構築先(dst)で build を実行し、ログを回収する。

desired_state/build_targets.json の定義に従い、リモートの作業ディレクトリで
ビルドコマンドを順に実行する。stdout/stderr と終了コードを build_env/logs へ
保存する。エラーになった箇所を調査 → 環境を整える → 再実行、のループを回す
ための中核スクリプト。

使い方:
    uv run python scripts/run_build.py
    uv run python scripts/run_build.py --target main
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import DESIRED_STATE_DIR, load_inventory, load_json  # noqa: E402
from core.logging_utils import get_logger, new_run_dir  # noqa: E402
from core.ssh import SSHSession  # noqa: E402


def _load_targets() -> dict:
    path = DESIRED_STATE_DIR / "build_targets.json"
    if not path.exists():
        sample = DESIRED_STATE_DIR / "build_targets.sample.json"
        raise FileNotFoundError(
            f"{path.name} がありません。{sample.name} を複製して実値を埋めてください。"
        )
    return load_json(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", default=None, help="build_targets の name。未指定なら先頭")
    args = parser.parse_args()

    cfg = _load_targets()
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

    run_dir = new_run_dir(label=f"build_{target.get('name', 'main')}")
    logger = get_logger(logfile=run_dir / "run.log")
    inv = load_inventory()

    server = target.get("server", "dst")
    workdir = target["workdir"]
    commands = target.get("commands", [])
    env = target.get("env", {})

    # 環境変数の export 前置き
    env_prefix = "".join(f"export {k}={v}; " for k, v in env.items())

    logger.info("build 開始: target=%s server=%s workdir=%s",
                target.get("name"), server, workdir)

    overall_ok = True
    with SSHSession(inv, server) as ssh:
        for i, cmd in enumerate(commands, 1):
            full = f"cd {workdir} && {env_prefix}{cmd}"
            logger.info("[%d/%d] %s", i, len(commands), cmd)
            res = ssh.run(full, timeout=3600)

            (run_dir / f"step{i:02d}.stdout.log").write_text(res.stdout, encoding="utf-8")
            (run_dir / f"step{i:02d}.stderr.log").write_text(res.stderr, encoding="utf-8")

            if res.ok:
                logger.info("    -> ok")
            else:
                overall_ok = False
                logger.error("    -> 失敗 exit=%d", res.exit_code)
                # stderr の末尾を要約表示
                tail = res.stderr.strip().splitlines()[-15:]
                for line in tail:
                    logger.error("    | %s", line)
                break  # 失敗したら以降は止める

    logger.info("ログ保存先: %s", run_dir)
    if overall_ok:
        logger.info("build 成功")
        return 0
    logger.error("build 失敗。上記ログを参照して環境を整えてください。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
