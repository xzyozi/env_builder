"""env_builder の共通ライブラリ。

手元PCから踏み台越しにSSH接続し、参照元(src)を参考に構築先(dst)の
環境を整えて build を通すための共通処理を提供する。
"""

from env_builder.core.config import Inventory, ServerSpec, load_inventory
from env_builder.core.logging_utils import get_logger, new_run_dir
from env_builder.core.project import ProjectProfile, ProjectRegistry, validate_project_id
from env_builder.core.ssh import SSHResult, SSHSession
from env_builder.core.work_context import WorkContext

__all__ = [
    "Inventory",
    "ServerSpec",
    "load_inventory",
    "ProjectProfile",
    "ProjectRegistry",
    "validate_project_id",
    "get_logger",
    "new_run_dir",
    "SSHResult",
    "SSHSession",
    "WorkContext",
]
