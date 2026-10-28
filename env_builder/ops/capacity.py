"""転送前の容量チェック（読み取り専用）。

src から持ってくるデータのサイズに `RESERVE_BYTES`（1 GiB）を足した空きが、dst の配置先の
ファイルシステムにあるかを、転送を始める前に確認する。足りない場合や、測定できない場合は、
転送せずに失敗として扱う（安全側に倒す）。

このモジュールがリモートで実行するコマンドは `du` と `df` だけで、src・dst のどちらの状態も
変更しない。基準と根拠は `.agent/references/preflight.md` を参照する。

接続は内部で作らず、`CommandRunner`（`run`）を引数で受け取る。本番では `SSHSession` を、
テストでは fake を渡す。
"""

from __future__ import annotations

import logging
import posixpath
import re
import shlex
from typing import List, Optional, Sequence

from env_builder.ops.session import CommandRunner

# 転送データのサイズに加える余裕（1 GiB）。
RESERVE_BYTES = 1024**3

# `du -sbc` の末尾行（"<bytes>\ttotal"）。パス名が "total" でも誤読しないよう、最後の一致を使う。
_DU_TOTAL = re.compile(r"^(\d+)\s+total\s*$", re.MULTILINE)
# `df -Pk` のデータ行（総ブロック・使用・空き・使用率）。ファイルシステム名に空白があっても読める。
_DF_ROW = re.compile(r"\s(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+\S")


def measure_command(paths: Sequence[str]) -> str:
    """対象パスの合計バイト数を測るコマンドを組み立てる（読み取り専用。パスはクォートする）。"""
    quoted = " ".join(shlex.quote(path) for path in paths)
    return f"du -sbc -- {quoted}"


def available_command(path: str) -> str:
    """配置先の空き容量を調べるコマンドを組み立てる（読み取り専用）。

    配置先がまだ存在しない場合（展開時に作られる）は、存在する最も近い親ディレクトリの
    ファイルシステムを調べる。
    """
    return f'p={shlex.quote(path)}; while [ ! -e "$p" ]; do p=$(dirname -- "$p"); done; LC_ALL=C df -Pk -- "$p"'


def parse_du_total(output: str) -> Optional[int]:
    """`du -sbc` の出力から合計バイト数を取り出す。読み取れなければ None。"""
    totals = _DU_TOTAL.findall(output)
    return int(totals[-1]) if totals else None


def parse_df_available(output: str) -> Optional[int]:
    """`df -Pk` の出力から空きバイト数を取り出す。読み取れなければ None。"""
    lines = [line for line in output.splitlines() if line.strip()]
    if len(lines) < 2:
        return None
    match = _DF_ROW.search(lines[-1])
    return int(match.group(3)) * 1024 if match else None


def has_enough_space(data_bytes: int, available: int, reserve: int = RESERVE_BYTES) -> bool:
    """空きが「データのサイズ + 余裕」以上なら True。"""
    return available >= data_bytes + reserve


def format_bytes(value: int) -> str:
    """バイト数を GiB 表記（小数 2 桁）と元の値で表す。"""
    return f"{value / 1024**3:.2f} GiB ({value} bytes)"


def measure_source(
    session: CommandRunner,
    paths: Sequence[str],
    *,
    timeout: int,
    logger: logging.Logger,
) -> Optional[int]:
    """src 側の転送対象の合計バイト数を測る。測定できなければ None（転送を始めない）。

    読み取れないファイルがあると `du` は失敗を返す。サイズを過小に見積もらないよう、その場合も
    None として扱う。
    """
    result = session.run(measure_command(paths), timeout=timeout)
    if not result.ok:
        logger.error("src側のサイズを測定できません exit=%d: %s", result.exit_code, result.stderr.strip()[:300])
        return None
    total = parse_du_total(result.stdout)
    if total is None:
        logger.error("src側のサイズを読み取れません: %s", result.stdout.strip()[:300])
        return None
    logger.info("  転送対象のサイズ: %s", format_bytes(total))
    return total


def verify_destination_space(
    session: CommandRunner,
    dst_paths: Sequence[str],
    data_bytes: int,
    *,
    timeout: int,
    logger: logging.Logger,
    reserve: int = RESERVE_BYTES,
) -> bool:
    """dst の各配置先に「データのサイズ + 余裕」の空きがあれば True。

    配置先が複数ある場合は、どの配置先も全データ分の空きを必要とみなす（同じファイルシステムを
    共有していても、安全側に倒す）。測定できない配置先があれば False。
    """
    unique: List[str] = list(dict.fromkeys(dst_paths))
    ok = True
    for path in unique:
        result = session.run(available_command(path), timeout=timeout)
        if not result.ok:
            logger.error(
                "dst側の空き容量を測定できません %s exit=%d: %s", path, result.exit_code, result.stderr.strip()[:300]
            )
            ok = False
            continue
        available = parse_df_available(result.stdout)
        if available is None:
            logger.error("dst側の空き容量を読み取れません %s: %s", path, result.stdout.strip()[:300])
            ok = False
            continue
        needed = data_bytes + reserve
        if available < needed:
            logger.error(
                "dst側の空きが不足しています %s: 空き %s / 必要 %s（データ %s + 余裕 %s）",
                path,
                format_bytes(available),
                format_bytes(needed),
                format_bytes(data_bytes),
                format_bytes(reserve),
            )
            ok = False
        else:
            logger.info("  dst側の空き: %s (必要 %s) %s", format_bytes(available), format_bytes(needed), path)
    return ok


def parent_directories(dst_paths: Sequence[str]) -> List[str]:
    """配置先ファイルのパスから、親ディレクトリの一覧を作る（親がなければ `.`）。"""
    return [posixpath.dirname(path) or "." for path in dst_paths]
