"""ディレクトリツリーを src→手元PC→dst と tar 経由で中継転送・配置する。

「ファイルが無いので src から取得して dst に配置する」用途の中核。
SFTP の再帰転送は遅く不安定なため、次の流れで確実に運ぶ。

  1. src で対象ディレクトリを tar.gz に固める（/tmp に作成）
  2. 手元PC(build_env/artifacts) に download
  3. dst に upload（root 配置なら --dst dst_root）
  4. dst 側の指定パスへ展開

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
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import BUILD_ENV_DIR, load_inventory  # noqa: E402
from core.logging_utils import get_logger  # noqa: E402
from core.ssh import SSHSession  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default="src", help="取得元（inventory のキー）")
    parser.add_argument("--dst", default="dst_root", help="配置先（inventory のキー）")
    parser.add_argument("--remote-src", required=True, help="src 上の取得対象ディレクトリ（絶対パス）")
    parser.add_argument(
        "--remote-dst-parent", required=True,
        help="dst 上の展開先の親ディレクトリ（ここに対象名で展開される）",
    )
    parser.add_argument("--timeout", type=int, default=600, help="各リモート操作のタイムアウト秒")
    args = parser.parse_args()

    logger = get_logger()
    inv = load_inventory()

    remote_src = args.remote_src.rstrip("/")
    parent = posixpath.dirname(remote_src)
    base = posixpath.basename(remote_src)
    ts = time.strftime("%Y%m%d_%H%M%S")
    tar_name = f"envb_{base}_{ts}.tar.gz"
    src_tar = f"/tmp/{tar_name}"
    dst_tar = f"/tmp/{tar_name}"

    staging = BUILD_ENV_DIR / "artifacts" / "trees"
    staging.mkdir(parents=True, exist_ok=True)
    local_tar = staging / tar_name

    # 1. src で tar.gz 作成
    logger.info("src(%s): tar 作成 %s", args.src, remote_src)
    with SSHSession(inv, args.src) as ssh:
        # -C で親に移動し、対象名だけを固める（展開時にフルパスにならないように）
        res = ssh.run(f"tar czf {src_tar} -C {parent} {base} && ls -l {src_tar}", timeout=args.timeout)
        if not res.ok:
            logger.error("tar 作成失敗 exit=%d: %s", res.exit_code, res.stderr.strip()[:300])
            return 1
        logger.info("  %s", res.stdout.strip())
        # download
        logger.info("src -> 手元PC: download")
        ssh.get_file(src_tar, str(local_tar))
        ssh.run(f"rm -f {src_tar}")
    logger.info("  取得: %s (%d bytes)", local_tar.name, local_tar.stat().st_size)

    # 2. dst へ upload して展開
    logger.info("dst(%s): upload & 展開先 %s", args.dst, args.remote_dst_parent)
    with SSHSession(inv, args.dst) as ssh:
        ssh.put_file(str(local_tar), dst_tar)
        logger.info("  upload 完了: %s", dst_tar)
        # 展開先の親を作成し、そこへ展開
        cmd = (
            f"mkdir -p {args.remote_dst_parent} && "
            f"tar xzf {dst_tar} -C {args.remote_dst_parent} && "
            f"rm -f {dst_tar} && "
            f"ls -ld {posixpath.join(args.remote_dst_parent, base)}"
        )
        res = ssh.run(cmd, timeout=args.timeout)
        if not res.ok:
            logger.error("展開失敗 exit=%d: %s", res.exit_code, res.stderr.strip()[:300])
            return 1
        logger.info("  展開完了: %s", res.stdout.strip())

    logger.info("配置完了: %s -> %s", remote_src, posixpath.join(args.remote_dst_parent, base))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
