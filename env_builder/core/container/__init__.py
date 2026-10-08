"""コンテナ解析とimage移送計画の共通モデル。"""

from .context import RuntimeContext, compare_runtime_contexts, normalize_runtime_context
from .engines import EngineAdapter, get_engine_adapter
from .image_plan import build_image_transfer_plan, snapshot_image_ref
from .inspect import InspectionError, normalize_container_inspection, parse_inspect_json
from .models import (
    ContainerInspection,
    ContainerProjectConfig,
    ContainerRunSpec,
    EnvironmentEntry,
    ImageTransferPlan,
    MountSpec,
    PortSpec,
)
from .project_config import load_container_config
from .run_spec import render_run_command

__all__ = [
    "ContainerInspection",
    "ContainerProjectConfig",
    "ContainerRunSpec",
    "EnvironmentEntry",
    "EngineAdapter",
    "ImageTransferPlan",
    "InspectionError",
    "MountSpec",
    "PortSpec",
    "RuntimeContext",
    "build_image_transfer_plan",
    "compare_runtime_contexts",
    "get_engine_adapter",
    "load_container_config",
    "normalize_container_inspection",
    "normalize_runtime_context",
    "parse_inspect_json",
    "render_run_command",
    "snapshot_image_ref",
]
