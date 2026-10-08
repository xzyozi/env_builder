"""desired_state/ 配下の定義ファイル（あるべき状態）の読み込み。

環境固有値（サーバ名・パス・パッケージ構成など）はリポジトリにコミットしない方針のため、
定義の実体は Git 管理外の `desired_state/`（プロジェクト指定時は各プロジェクトの
`desired_state/`）に置く。ここは「どのファイルを、どの順で探し、無いときに何を伝えるか」だけを
持ち、中身の解釈（キーの意味づけ・検証）は呼び出し側が行う。

読み込み関数はどれも `desired_state_dir` を引数に取る。既定値は legacy 経路（リポジトリ直下）の
`desired_state/` で、プロジェクトを指定する場合は `ProjectProfile.desired_state_dir` を渡す。
"""

from __future__ import annotations

from pathlib import Path
from typing import Sequence

from .config import DESIRED_STATE_DIR, load_json

PACKAGES_FILE = "packages.json"
FILES_FILE = "files.json"
BUILD_TARGETS_LOCAL_FILE = "build_targets.local.json"
BUILD_TARGETS_LEGACY_FILE = "build_targets.json"


def _load_first_existing(desired_state_dir: Path, names: Sequence[str], missing_message: str) -> dict:
    """候補のうち最初に存在するファイルを読む。どれも無ければ FileNotFoundError。"""
    for name in names:
        path = desired_state_dir / name
        if path.exists():
            return load_json(path)
    raise FileNotFoundError(missing_message)


def _sample_name(filename: str) -> str:
    """`packages.json` -> `packages.sample.json`（複製元として案内するファイル名）。"""
    return Path(filename).stem + ".sample" + Path(filename).suffix


def load_packages(desired_state_dir: Path = DESIRED_STATE_DIR) -> dict:
    """packages.json（導入するパッケージの定義）を読み込む。"""
    return _load_first_existing(
        desired_state_dir,
        [PACKAGES_FILE],
        f"{PACKAGES_FILE} がありません。{_sample_name(PACKAGES_FILE)} を複製して実値を埋めてください。",
    )


def load_files(desired_state_dir: Path = DESIRED_STATE_DIR) -> dict:
    """files.json（src から dst へ転送するファイルの対応表）を読み込む。"""
    return _load_first_existing(
        desired_state_dir,
        [FILES_FILE],
        f"{FILES_FILE} がありません。{_sample_name(FILES_FILE)} を複製して実値を埋めてください。",
    )


def load_build_targets(desired_state_dir: Path = DESIRED_STATE_DIR) -> dict:
    """build ターゲット定義を読み込む。

    環境固有値（サーバ名・作業ディレクトリ・VERSION_MNG 等）はリポジトリに
    コミットしない方針のため、実体は Git 管理外の *.local.json に置く。
    読み込み順は次の通り:
      1. build_targets.local.json（実体・.gitignore 対象）を最優先
      2. 後方互換として build_targets.json があれば読む
    どちらも無ければ、local ファイルの作成を促すエラーにする。
    """
    return _load_first_existing(
        desired_state_dir,
        [BUILD_TARGETS_LOCAL_FILE, BUILD_TARGETS_LEGACY_FILE],
        f"{BUILD_TARGETS_LOCAL_FILE} がありません。環境固有値を含む build 定義は "
        f"{BUILD_TARGETS_LOCAL_FILE}（Git 管理外）に作成してください。",
    )
