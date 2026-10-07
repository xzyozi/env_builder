"""コンテナを解析し、image移送計画とrun候補を出力するCLI。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import load_inventory  # noqa: E402
from core.container import (  # noqa: E402
    build_image_transfer_plan,
    compare_runtime_contexts,
    get_engine_adapter,
    load_container_config,
    render_run_command,
)
from core.logging_utils import get_logger, new_run_dir  # noqa: E402
from core.project import ProjectRegistry  # noqa: E402
from ops.container import execute_image_transfer, inspect_container, inspect_runtime_context  # noqa: E402


def _config_path(profile, filename: str) -> Path:
    path = Path(filename)
    if path.is_absolute() or path.name != filename or path.name in {".", ".."}:
        raise ValueError("--configはdesired_state直下のファイル名だけを指定してください。")
    return profile.desired_state_dir / path


def _build_payload(profile, config, inspection, plan, source_context, destination_context) -> Dict[str, Any]:
    run_command = render_run_command(inspection.run_spec)
    return {
        "schema_version": 1,
        "project_id": profile.project_id,
        "config": config.to_dict(),
        "runtime_contexts": {
            "source": source_context.to_dict(),
            "destination": destination_context.to_dict(),
        },
        "context_warnings": list(compare_runtime_contexts(source_context, destination_context)),
        "inspection": inspection.to_dict(),
        "run_candidate": {
            "command": run_command,
            "automatic_execution": False,
        },
        "image_transfer_plan": plan.to_dict(),
    }


def _print_payload(payload: Dict[str, Any], plan_path: Path) -> None:
    inspection = payload["inspection"]
    run_candidate = payload["run_candidate"]
    plan = payload["image_transfer_plan"]
    print("----- run候補 -----")
    print(run_candidate["command"])
    print("----- image移送計画 -----")
    print(f"mode: {plan['mode']}")
    print(f"target image: {plan['target_image']}")
    for command in plan["source_commands"]:
        print(f"source: {command}")
    for command in plan["destination_commands"]:
        print(f"destination: {command}")
    print("----- warnings / unsupported -----")
    for warning in payload["context_warnings"] + inspection["run_spec"]["warnings"] + plan["warnings"]:
        print(f"- {warning}")
    for item in inspection["run_spec"]["unsupported"]:
        print(f"- unsupported: {item}")
    print("----- plan JSON -----")
    print(plan_path)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", default=None, help="プロジェクトID。未指定ならlegacy設定を使う")
    parser.add_argument(
        "--config",
        default="container.local.json",
        help="desired_state直下のコンテナ設定ファイル名",
    )
    parser.add_argument("--timeout", type=int, default=600, help="各リモート操作のタイムアウト秒")
    parser.add_argument(
        "--execute-image",
        action="store_true",
        help="image移送を実行する（--approve-imageとの併用が必要）",
    )
    parser.add_argument(
        "--approve-image",
        action="store_true",
        help="image移送計画を承認済みとして扱う",
    )
    args = parser.parse_args()

    if args.execute_image and not args.approve_image:
        parser.error("--execute-imageには--approve-imageが必要です。")

    profile = ProjectRegistry().resolve(args.project)
    config = load_container_config(_config_path(profile, args.config))
    adapter = get_engine_adapter(config.engine)
    if args.execute_image and config.transfer_mode == "commit":
        logger = get_logger(project_id=profile.project_id)
        logger.warning("transfer_mode=commitは移送元のimage storeを変更します。")

    inventory = load_inventory(profile.inventory_path)
    source_context = inspect_runtime_context(inventory, config.source_target, adapter, timeout=args.timeout)
    destination_context = inspect_runtime_context(inventory, config.destination_target, adapter, timeout=args.timeout)
    inspection = inspect_container(inventory, config, adapter, timeout=args.timeout)
    plan = build_image_transfer_plan(config, adapter, profile.project_id)
    payload = _build_payload(profile, config, inspection, plan, source_context, destination_context)

    run_dir = new_run_dir(
        label="container_plan",
        build_env_dir=profile.build_env_dir,
        project_id=profile.project_id,
    )
    plan_path = run_dir / "container-plan.json"
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _print_payload(payload, plan_path)

    if not args.execute_image:
        return 0

    result = execute_image_transfer(profile, config, adapter, plan, timeout=args.timeout)
    payload["image_transfer_result"] = result
    plan_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if result.get("status") == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
