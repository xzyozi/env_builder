"""src→手元PC→dst の中継転送（ファイル単位・ディレクトリ単位）。

接続は内部で作らず、`RemoteSession`（`run` / `get_file` / `put_file`）を引数で受け取る。
本番では `SSHSession` を、テストでは fake を渡す。中継物は `WorkContext` が管理する作業ID付きの
専用領域（ローカルの `stage_dir`、リモートの `/tmp/env_builder-<work-id>-XXXXXX/`）に置き、
成功・失敗・例外のいずれでもリモートの専用領域を削除する。永続の配置先は削除しない。

どの関数も、失敗は例外ではなく戻り値（成否）で返し、理由はログに出す。呼び出し側はその戻り値で
終了コードを決める。
"""

from __future__ import annotations

import logging
import posixpath
import shlex
from pathlib import Path
from typing import Any, List, Mapping, Optional, Sequence

from env_builder.core.work_context import WorkContext
from env_builder.ops.session import RemoteSession

TREE_ARCHIVE_NAME = "tree.tar.gz"


# --- ディレクトリ単位（tar 経由） -----------------------------------------------


def pack_command(src_tar: str, parent: str, base: str) -> str:
    """src 側で対象ディレクトリを tar.gz に固めるコマンドを組み立てる。

    パスはすべて shlex.quote でリテラルとして扱う。base が `-` で始まる場合に
    tar のオプションと解釈されないよう、`--` で位置引数の開始を明示する。
    """
    return (
        f"tar czf {shlex.quote(src_tar)} -C {shlex.quote(parent)} -- {shlex.quote(base)} "
        f"&& ls -l -- {shlex.quote(src_tar)}"
    )


def unpack_command(dst_tar: str, dst_parent: str, destination: str) -> str:
    """dst 側で tar.gz を展開するコマンドを組み立てる（全パスをクォートし、`--` を挟む）。"""
    return (
        f"mkdir -p -- {shlex.quote(dst_parent)} && "
        f"tar xzf {shlex.quote(dst_tar)} -C {shlex.quote(dst_parent)} && "
        f"ls -ld -- {shlex.quote(destination)}"
    )


def split_remote_dir(remote_src: str) -> "tuple[str, str]":
    """取得対象ディレクトリのパスを（親, 名前）に分ける。末尾の `/` は無視する。"""
    normalized = remote_src.rstrip("/")
    return posixpath.dirname(normalized), posixpath.basename(normalized)


def fetch_tree(
    session: RemoteSession,
    work: WorkContext,
    *,
    target: str,
    parent: str,
    base: str,
    local_tar: Path,
    timeout: int,
    logger: logging.Logger,
) -> bool:
    """src 側で tar.gz を作り、手元の `local_tar` へ取得する。成功なら True。

    リモートの専用作業領域は、成功・失敗・例外のいずれでも削除する。削除できなかった場合は
    取得に成功していても False を返す。
    """
    ok = True
    workspace: Optional[str] = None
    try:
        workspace = work.create_remote_workspace(session, target, timeout=timeout)
        src_tar = posixpath.join(workspace, TREE_ARCHIVE_NAME)
        result = session.run(pack_command(src_tar, parent, base), timeout=timeout)
        if not result.ok:
            logger.error("tar 作成失敗 exit=%d: %s", result.exit_code, result.stderr.strip()[:300])
            ok = False
        else:
            logger.info("  %s", result.stdout.strip())
            logger.info("src -> 手元PC: download")
            session.get_file(src_tar, str(local_tar))
    except Exception as exc:
        logger.error("src側の転送に失敗しました: %s", exc)
        ok = False
    finally:
        if workspace and not work.cleanup_remote_workspace(session, target, workspace, timeout):
            logger.error("src側の一時作業領域を削除できませんでした: %s", workspace)
            ok = False
    return ok


def deploy_tree(
    session: RemoteSession,
    work: WorkContext,
    *,
    target: str,
    local_tar: Path,
    dst_parent: str,
    destination: str,
    timeout: int,
    logger: logging.Logger,
) -> bool:
    """手元の `local_tar` を dst 側へ upload し、`dst_parent` 配下へ展開する。成功なら True。

    リモートの専用作業領域は、成功・失敗・例外のいずれでも削除する。展開先（永続配置）は削除しない。
    """
    ok = True
    workspace: Optional[str] = None
    try:
        workspace = work.create_remote_workspace(session, target, timeout=timeout)
        dst_tar = posixpath.join(workspace, TREE_ARCHIVE_NAME)
        session.put_file(str(local_tar), dst_tar)
        logger.info("  upload 完了: %s", dst_tar)

        result = session.run(unpack_command(dst_tar, dst_parent, destination), timeout=timeout)
        if not result.ok:
            logger.error("展開失敗 exit=%d: %s", result.exit_code, result.stderr.strip()[:300])
            ok = False
        else:
            logger.info("  展開完了: %s", result.stdout.strip())
    except Exception as exc:
        logger.error("dst側の転送・展開に失敗しました: %s", exc)
        ok = False
    finally:
        if workspace and not work.cleanup_remote_workspace(session, target, workspace, timeout):
            logger.error("dst側の一時作業領域を削除できませんでした: %s", workspace)
            ok = False
    return ok


# --- ファイル単位 -----------------------------------------------------------------


def chmod_command(mode: Any, path: str) -> str:
    """配置したファイルの権限を変えるコマンド（mode とパスをクォートする）。"""
    return f"chmod {shlex.quote(str(mode))} {shlex.quote(path)}"


def download_files(
    session: RemoteSession,
    entries: Sequence[Mapping[str, Any]],
    stage_dir: Path,
    logger: logging.Logger,
) -> Optional[List[str]]:
    """対応表の `src_path` を、手元の `stage_dir/file_NNN` へ取得する。

    成功すれば、各エントリの取得先パスを対応表と同じ順で返す。1件でも失敗したら、そこで止めて
    None を返す。入力の対応表は変更しない。
    """
    local_paths: List[str] = []
    for i, entry in enumerate(entries):
        local = stage_dir / f"file_{i:03d}"
        try:
            session.get_file(entry["src_path"], str(local))
        except Exception as exc:
            logger.error("download失敗 src=%s: %s", entry["src_path"], exc)
            return None
        logger.info("  download: %s", entry["src_path"])
        local_paths.append(str(local))
    return local_paths


def upload_files(
    session: RemoteSession,
    entries: Sequence[Mapping[str, Any]],
    local_paths: Sequence[str],
    logger: logging.Logger,
) -> bool:
    """取得済みのファイルを `dst_path` へ配置し、`mode` があれば権限を設定する。成功なら True。

    1件でも upload または chmod に失敗したら、そこで止めて False を返す。
    """
    for entry, local in zip(entries, local_paths):
        try:
            session.put_file(local, entry["dst_path"])
        except Exception as exc:
            logger.error("upload失敗 dst=%s: %s", entry["dst_path"], exc)
            return False
        logger.info("  upload:   %s", entry["dst_path"])

        mode = entry.get("mode")
        if mode:
            result = session.run(chmod_command(mode, entry["dst_path"]))
            if not result.ok:
                logger.error("chmod失敗 dst=%s exit=%d", entry["dst_path"], result.exit_code)
                return False
    return True
