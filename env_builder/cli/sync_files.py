"""ファイルを src→手元→dst と仲介転送する（download → upload）。

desired_state/files.json の対応表に従い、参照元(src)から設定ファイルを
取得し、構築先(dst)へ配置する。手元PCを中継点にするため、踏み台越しでも
両サーバ間の直接到達性が無くても転送できる。

インターネットから落とした OSS を持ち込む場合は --upload-only で
ローカルファイルを dst へ送るだけの使い方も可能。src→dst の中継ファイルは
作業ID付きの一時領域へ置き、転送終了時にディレクトリごと削除する。

使い方:
    uv run python scripts/sync_files.py                       # files.json に従い src->dst
    uv run python scripts/sync_files.py --upload-only <local> <remote>
"""

from __future__ import annotations

import argparse
import shlex
from pathlib import Path
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import DESIRED_STATE_DIR, load_inventory, load_json
from env_builder.core.logging_utils import get_logger
from env_builder.core.project import ProjectProfile, ProjectRegistry
from env_builder.core.ssh import SSHSession
from env_builder.core.work_context import WorkContext


def _load_files(desired_state_dir: Path = DESIRED_STATE_DIR) -> dict:
    path = desired_state_dir / "files.json"
    if not path.exists():
        sample = desired_state_dir / "files.sample.json"
        raise FileNotFoundError(f"{path.name} がありません。{sample.name} を複製して実値を埋めてください。")
    return load_json(path)


def _sync_via_local(inv, logger, src_key: str, dst_key: str, profile: ProjectProfile) -> int:
    """files.json に従い src からダウンロードして dst へアップロードする。"""
    cfg = _load_files(profile.desired_state_dir)
    entries = cfg.get("files", [])
    if not entries:
        logger.info("files.json に対象がありません。")
        return 0

    with WorkContext(
        "sync-files",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    ) as work:
        logger.info("src(%s) からダウンロードします", src_key)
        with SSHSession(inv, src_key) as src_ssh:
            for i, entry in enumerate(entries):
                local = work.stage_dir / f"file_{i:03d}"
                try:
                    src_ssh.get_file(entry["src_path"], str(local))
                except Exception as exc:
                    logger.error("download失敗 src=%s: %s", entry["src_path"], exc)
                    return 1
                logger.info("  download: %s", entry["src_path"])
                entry["_local"] = str(local)

        logger.info("dst(%s) へアップロードします", dst_key)
        with SSHSession(inv, dst_key) as dst_ssh:
            for entry in entries:
                try:
                    dst_ssh.put_file(entry["_local"], entry["dst_path"])
                except Exception as exc:
                    logger.error("upload失敗 dst=%s: %s", entry["dst_path"], exc)
                    return 1
                logger.info("  upload:   %s", entry["dst_path"])

                mode = entry.get("mode")
                if mode:
                    result = dst_ssh.run(
                        f"chmod {shlex.quote(str(mode))} {shlex.quote(entry['dst_path'])}",
                    )
                    if not result.ok:
                        logger.error("chmod失敗 dst=%s exit=%d", entry["dst_path"], result.exit_code)
                        return 1

        work.complete()
        logger.info("転送完了")
        return 0


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default="src", help="取得元（inventory のキー）")
    parser.add_argument("--dst", default="dst", help="配置先（inventory のキー）")
    add_project_argument(parser)
    parser.add_argument(
        "--upload-only",
        nargs=2,
        metavar=("LOCAL", "REMOTE"),
        help="ローカルファイルを dst へ送るだけ（download をスキップ）",
    )
    args = parser.parse_args(argv)

    profile = ProjectRegistry().resolve(args.project)
    logger = get_logger(project_id=profile.project_id)
    inv = load_inventory(profile.inventory_path)

    if args.upload_only:
        local, remote = args.upload_only
        logger.info("dst(%s) へアップロード: %s -> %s", args.dst, local, remote)
        with SSHSession(inv, args.dst) as ssh:
            ssh.put_file(local, remote)
        logger.info("完了")
        return 0

    return _sync_via_local(inv, logger, args.src, args.dst, profile)


if __name__ == "__main__":
    raise SystemExit(main())
