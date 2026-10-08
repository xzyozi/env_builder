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
import shlex
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import load_inventory  # noqa: E402
from core.logging_utils import get_logger  # noqa: E402
from core.project import ProjectRegistry  # noqa: E402
from core.ssh import SSHSession  # noqa: E402
from core.work_context import WorkContext  # noqa: E402


def _pack_command(src_tar: str, parent: str, base: str) -> str:
    """src 側で対象ディレクトリを tar.gz に固めるコマンドを組み立てる。

    パスはすべて shlex.quote でリテラルとして扱う。base が `-` で始まる場合に
    tar のオプションと解釈されないよう、`--` で位置引数の開始を明示する。
    """
    return (
        f"tar czf {shlex.quote(src_tar)} -C {shlex.quote(parent)} -- {shlex.quote(base)} "
        f"&& ls -l -- {shlex.quote(src_tar)}"
    )


def _unpack_command(dst_tar: str, dst_parent: str, destination: str) -> str:
    """dst 側で tar.gz を展開するコマンドを組み立てる（全パスをクォートし、`--` を挟む）。"""
    return (
        f"mkdir -p -- {shlex.quote(dst_parent)} && "
        f"tar xzf {shlex.quote(dst_tar)} -C {shlex.quote(dst_parent)} && "
        f"ls -ld -- {shlex.quote(destination)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default="src", help="取得元（inventory のキー）")
    parser.add_argument("--dst", default="dst_root", help="配置先（inventory のキー）")
    parser.add_argument("--project", default=None, help="プロジェクトID。未指定ならlegacy設定を使う")
    parser.add_argument("--remote-src", required=True, help="src 上の取得対象ディレクトリ（絶対パス）")
    parser.add_argument(
        "--remote-dst-parent",
        required=True,
        help="dst 上の展開先の親ディレクトリ（ここに対象名で展開される）",
    )
    parser.add_argument("--timeout", type=int, default=600, help="各リモート操作のタイムアウト秒")
    args = parser.parse_args()

    profile = ProjectRegistry().resolve(args.project)
    logger = get_logger(project_id=profile.project_id)
    inv = load_inventory(profile.inventory_path)

    remote_src = args.remote_src.rstrip("/")
    parent = posixpath.dirname(remote_src)
    base = posixpath.basename(remote_src)
    destination = posixpath.join(args.remote_dst_parent, base)
    overall_ok = True

    with WorkContext(
        "sync-tree",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    ) as work:
        local_tar = work.stage_dir / "tree.tar.gz"

        # 1. src の専用 /tmp 作業領域で tar.gz を作成して download
        logger.info("src(%s): tar 作成 %s", args.src, remote_src)
        with SSHSession(inv, args.src) as ssh:
            src_workspace = None
            try:
                src_workspace = work.create_remote_workspace(ssh, args.src, timeout=args.timeout)
                src_tar = posixpath.join(src_workspace, "tree.tar.gz")
                command = _pack_command(src_tar, parent, base)
                result = ssh.run(command, timeout=args.timeout)
                if not result.ok:
                    logger.error("tar 作成失敗 exit=%d: %s", result.exit_code, result.stderr.strip()[:300])
                    overall_ok = False
                else:
                    logger.info("  %s", result.stdout.strip())
                    logger.info("src -> 手元PC: download")
                    ssh.get_file(src_tar, str(local_tar))
            except Exception as exc:
                logger.error("src側の転送に失敗しました: %s", exc)
                overall_ok = False
            finally:
                if src_workspace and not work.cleanup_remote_workspace(ssh, args.src, src_workspace, args.timeout):
                    logger.error("src側の一時作業領域を削除できませんでした: %s", src_workspace)
                    overall_ok = False

        if not overall_ok:
            return 1
        logger.info("  取得: %s (%d bytes)", local_tar.name, local_tar.stat().st_size)

        # 2. dst の専用 /tmp 作業領域へ upload して永続配置先へ展開
        logger.info("dst(%s): upload & 展開先 %s", args.dst, args.remote_dst_parent)
        with SSHSession(inv, args.dst) as ssh:
            dst_workspace = None
            try:
                dst_workspace = work.create_remote_workspace(ssh, args.dst, timeout=args.timeout)
                dst_tar = posixpath.join(dst_workspace, "tree.tar.gz")
                ssh.put_file(str(local_tar), dst_tar)
                logger.info("  upload 完了: %s", dst_tar)

                command = _unpack_command(dst_tar, args.remote_dst_parent, destination)
                result = ssh.run(command, timeout=args.timeout)
                if not result.ok:
                    logger.error("展開失敗 exit=%d: %s", result.exit_code, result.stderr.strip()[:300])
                    overall_ok = False
                else:
                    logger.info("  展開完了: %s", result.stdout.strip())
            except Exception as exc:
                logger.error("dst側の転送・展開に失敗しました: %s", exc)
                overall_ok = False
            finally:
                if dst_workspace and not work.cleanup_remote_workspace(ssh, args.dst, dst_workspace, args.timeout):
                    logger.error("dst側の一時作業領域を削除できませんでした: %s", dst_workspace)
                    overall_ok = False

        if not overall_ok:
            return 1

        work.complete()
        logger.info("配置完了: %s -> %s", remote_src, destination)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
