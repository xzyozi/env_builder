"""env_builder の共通ライブラリ。

手元PCから踏み台越しにSSH接続し、参照元(src)を参考に構築先(dst)の
環境を整えて build を通すための共通処理を提供する。
"""

from .config import Inventory, ServerSpec, load_inventory
from .logging_utils import get_logger, new_run_dir
from .ssh import SSHResult, SSHSession

__all__ = [
    "Inventory",
    "ServerSpec",
    "load_inventory",
    "get_logger",
    "new_run_dir",
    "SSHResult",
    "SSHSession",
]
