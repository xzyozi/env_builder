"""ファイルを src→手元→dst と仲介転送する（download → upload）。

desired_state/files.json の対応表に従い、参照元(src)から設定ファイルを
取得し、構築先(dst)へ配置する。手元PCを中継点にするため、踏み台越しでも
両サーバ間の直接到達性が無くても転送できる。

インターネットから落とした OSS を持ち込む場合は --upload-only で
ローカルファイルを dst へ送るだけの使い方も可能。src→dst の中継ファイルは
作業ID付きの一時領域へ置き、転送終了時にディレクトリごと削除する。

files.json に従う転送では、転送前に容量を確認する（src のサイズ + 1 GiB が dst の配置先に
空いていること。読み取りのみ）。足りない場合や測定できない場合は、転送せずに失敗する。
--upload-only は src を使わないため、この確認の対象外。

使い方:
    uv run python scripts/sync_files.py                       # files.json に従い src->dst
    uv run python scripts/sync_files.py --upload-only <local> <remote>
"""

from __future__ import annotations

import argparse
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import load_inventory
from env_builder.core.desired_state import load_files
from env_builder.core.logging_utils import get_logger
from env_builder.core.project import ProjectProfile, ProjectRegistry
from env_builder.core.ssh import SSHSession
from env_builder.core.work_context import WorkContext
from env_builder.ops.capacity import measure_source, parent_directories, verify_destination_space
from env_builder.ops.transfer import download_files, upload_files

# 容量チェック（du / df）のタイムアウト秒。
_CAPACITY_TIMEOUT_SEC = 600


def _sync_via_local(inv, logger, src_key: str, dst_key: str, profile: ProjectProfile) -> int:
    """files.json に従い src からダウンロードして dst へアップロードする。"""
    cfg = load_files(profile.desired_state_dir)
    entries = cfg.get("files", [])
    if not entries:
        logger.info("files.json に対象がありません。")
        return 0

    # 転送前の容量チェック（読み取りのみ）。足りない・測れない場合は、作業領域も作らず終了する
    logger.info("容量チェック: src(%s) -> dst(%s)", src_key, dst_key)
    with SSHSession(inv, src_key) as src_ssh:
        data_bytes = measure_source(
            src_ssh, [entry["src_path"] for entry in entries], timeout=_CAPACITY_TIMEOUT_SEC, logger=logger
        )
    if data_bytes is None:
        return 1
    with SSHSession(inv, dst_key) as dst_ssh:
        if not verify_destination_space(
            dst_ssh,
            parent_directories([entry["dst_path"] for entry in entries]),
            data_bytes,
            timeout=_CAPACITY_TIMEOUT_SEC,
            logger=logger,
        ):
            return 1

    with WorkContext(
        "sync-files",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    ) as work:
        logger.info("src(%s) からダウンロードします", src_key)
        with SSHSession(inv, src_key) as src_ssh:
            local_paths = download_files(src_ssh, entries, work.stage_dir, logger)
        if local_paths is None:
            return 1

        logger.info("dst(%s) へアップロードします", dst_key)
        with SSHSession(inv, dst_key) as dst_ssh:
            if not upload_files(dst_ssh, entries, local_paths, logger):
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
