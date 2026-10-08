"""ディレクトリツリーを src→手元PC→dst と tar 経由で中継転送・配置する。

「ファイルが無いので src から取得して dst に配置する」用途の中核。
SFTP の再帰転送は遅く不安定なため、次の流れで確実に運ぶ。

  1. src の専用 /tmp 作業領域で対象ディレクトリを tar.gz に固める
  2. 手元PCの専用作業領域へ download
  3. dst の専用 /tmp 作業領域へ upload（root 配置なら --dst dst_root）
  4. dst 側の指定パスへ展開
  5. src / dst / 手元PCの専用作業領域を成功・失敗にかかわらず削除

権限昇格(sudo/su)は使わない。/opt 等 root 配置先へは inventory の
root 定義（dst_root）を --dst に指定する。

使い方（例: version_mng を src から dst の /opt/mel/... へ配置）:
    uv run python scripts/sync_tree.py \
        --src src --dst dst_root \
        --remote-src /opt/mel/modern/lib64/version_mng \
        --remote-dst-parent /opt/mel/modern/lib64
"""

from __future__ import annotations

import argparse
import posixpath
from typing import Optional, Sequence

from env_builder.cli._common import add_project_argument
from env_builder.core.config import load_inventory
from env_builder.core.logging_utils import get_logger
from env_builder.core.project import ProjectRegistry
from env_builder.core.ssh import SSHSession
from env_builder.core.work_context import WorkContext
from env_builder.ops.transfer import TREE_ARCHIVE_NAME, deploy_tree, fetch_tree, split_remote_dir


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default="src", help="取得元（inventory のキー）")
    parser.add_argument("--dst", default="dst_root", help="配置先（inventory のキー）")
    add_project_argument(parser)
    parser.add_argument("--remote-src", required=True, help="src 上の取得対象ディレクトリ（絶対パス）")
    parser.add_argument(
        "--remote-dst-parent",
        required=True,
        help="dst 上の展開先の親ディレクトリ（ここに対象名で展開される）",
    )
    parser.add_argument("--timeout", type=int, default=600, help="各リモート操作のタイムアウト秒")
    args = parser.parse_args(argv)

    profile = ProjectRegistry().resolve(args.project)
    logger = get_logger(project_id=profile.project_id)
    inv = load_inventory(profile.inventory_path)

    remote_src = args.remote_src.rstrip("/")
    parent, base = split_remote_dir(remote_src)
    destination = posixpath.join(args.remote_dst_parent, base)

    with WorkContext(
        "sync-tree",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    ) as work:
        local_tar = work.stage_dir / TREE_ARCHIVE_NAME

        # 1. src の専用 /tmp 作業領域で tar.gz を作成して download
        logger.info("src(%s): tar 作成 %s", args.src, remote_src)
        with SSHSession(inv, args.src) as ssh:
            fetched = fetch_tree(
                ssh,
                work,
                target=args.src,
                parent=parent,
                base=base,
                local_tar=local_tar,
                timeout=args.timeout,
                logger=logger,
            )

        if not fetched:
            return 1
        logger.info("  取得: %s (%d bytes)", local_tar.name, local_tar.stat().st_size)

        # 2. dst の専用 /tmp 作業領域へ upload して永続配置先へ展開
        logger.info("dst(%s): upload & 展開先 %s", args.dst, args.remote_dst_parent)
        with SSHSession(inv, args.dst) as ssh:
            deployed = deploy_tree(
                ssh,
                work,
                target=args.dst,
                local_tar=local_tar,
                dst_parent=args.remote_dst_parent,
                destination=destination,
                timeout=args.timeout,
                logger=logger,
            )

        if not deployed:
            return 1

        work.complete()
        logger.info("配置完了: %s -> %s", remote_src, destination)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
