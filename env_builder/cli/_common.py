"""各コマンドで共通の引数定義。"""

from __future__ import annotations

import argparse

PROJECT_HELP = "プロジェクトID。未指定ならlegacy設定を使う"


def add_project_argument(parser: argparse.ArgumentParser) -> None:
    """`--project <id>` を追加する。解決は ProjectRegistry が行う。"""
    parser.add_argument("--project", default=None, help=PROJECT_HELP)
