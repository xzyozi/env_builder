"""ログ出力ユーティリティ。

実行ごとに build_env/logs 配下へタイムスタンプ付きのディレクトリを作り、
build ログや実行ログをそこへ集約する。
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime
from pathlib import Path

from .config import BUILD_ENV_DIR


def new_run_dir(label: str = "run") -> Path:
    """build_env/logs/<label>_<timestamp>/ を作成して返す。"""
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = BUILD_ENV_DIR / "logs" / f"{label}_{ts}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def get_logger(name: str = "env_builder", logfile: Path | None = None) -> logging.Logger:
    """コンソールと（任意で）ファイルへ出力するロガーを返す。"""
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # 二重登録防止
    logger.setLevel(logging.DEBUG)

    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    # stderr に出すと PowerShell 経由で NativeCommandError 扱いになり出力が
    # 見えにくいため、stdout に出す。
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    if logfile is not None:
        logfile.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.FileHandler(logfile, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger
