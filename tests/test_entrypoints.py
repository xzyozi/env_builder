"""エントリポイントの検証（ENVB-0008 / Issue #15）。

`python -m env_builder <command>` と、`scripts/<name>.py` の互換ラッパーが同じコマンドを
呼ぶこと、全 CLI を import しても別名のモジュール（`core` / `scripts.core`）が二重に
読み込まれないことを確認する。sys.path を操作するラッパーを検証するため、サブプロセスで実行する。
"""

import os
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest

from env_builder.cli import COMMANDS, normalize_command, run

REPO_ROOT = Path(__file__).resolve().parents[1]
COMMAND_NAMES = sorted(COMMANDS)


def _run(args: List[str]) -> Tuple[int, str, str]:
    """リポジトリルートを cwd にして Python を実行し、(終了コード, stdout, stderr) を返す。

    Windows の既定エンコーディング（cp932）に依存しないよう、子プロセスの入出力は UTF-8 に固定する。
    """
    env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    proc = subprocess.run(
        [sys.executable, *args],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def test_commands_table_matches_the_scripts_wrappers() -> None:
    wrappers = sorted(path.stem for path in (REPO_ROOT / "scripts").glob("*.py"))

    assert wrappers == COMMAND_NAMES


def test_commands_table_points_to_existing_modules() -> None:
    for name, (module, _description) in COMMANDS.items():
        assert module == f"env_builder.cli.{name}"
        assert (REPO_ROOT / "env_builder" / "cli" / f"{name}.py").is_file()


@pytest.mark.parametrize("name", COMMAND_NAMES)
def test_module_entrypoint_runs_each_command(name: str) -> None:
    code, stdout, stderr = _run(["-m", "env_builder", name, "--help"])

    assert code == 0, stderr
    assert "--project" in stdout or name == "remote_exec"
    assert "usage:" in stdout


@pytest.mark.parametrize("name", COMMAND_NAMES)
def test_scripts_wrapper_runs_each_command(name: str) -> None:
    code, stdout, stderr = _run([f"scripts/{name}.py", "--help"])

    assert code == 0, stderr
    assert "usage:" in stdout


@pytest.mark.parametrize("name", COMMAND_NAMES)
def test_wrapper_and_module_entrypoint_print_the_same_options(name: str) -> None:
    """ラッパーと -m で、引数の定義（--help の選択肢）が一致する。"""

    def options(output: str) -> List[str]:
        return sorted({token.rstrip(",") for token in output.split() if token.startswith("--")})

    _, via_module, _ = _run(["-m", "env_builder", name, "--help"])
    _, via_wrapper, _ = _run([f"scripts/{name}.py", "--help"])

    assert options(via_module) == options(via_wrapper)
    assert options(via_module)  # 少なくとも --help は含まれる


def test_project_option_is_defined_the_same_way_in_every_command() -> None:
    for name in COMMAND_NAMES:
        if name == "remote_exec":
            continue  # remote_exec は後続の位置引数を持つが、--project は同様に定義される
        _, stdout, _ = _run(["-m", "env_builder", name, "--help"])
        assert "--project" in stdout, name
        assert "プロジェクトID" in stdout, name


def test_hyphenated_command_names_are_accepted() -> None:
    assert normalize_command("remote-exec") == "remote_exec"
    assert normalize_command("check-connectivity") == "check_connectivity"

    code, stdout, stderr = _run(["-m", "env_builder", "remote-exec", "--help"])

    assert code == 0, stderr
    assert "usage:" in stdout


def test_no_arguments_prints_usage_and_fails() -> None:
    code, stdout, stderr = _run(["-m", "env_builder"])

    assert code == 2
    assert "usage: python -m env_builder" in stderr
    assert stdout == ""


def test_help_lists_every_command() -> None:
    code, stdout, _ = _run(["-m", "env_builder", "--help"])

    assert code == 0
    for name in COMMAND_NAMES:
        assert name in stdout


def test_unknown_command_is_rejected_with_usage() -> None:
    code, _, stderr = _run(["-m", "env_builder", "no_such_command"])

    assert code == 2
    assert "unknown command: no_such_command" in stderr
    assert "commands:" in stderr


def test_run_returns_two_for_unknown_command_without_importing_anything(capsys: pytest.CaptureFixture) -> None:
    assert run(["nope"]) == 2

    assert "unknown command" in capsys.readouterr().err


def test_importing_every_command_does_not_load_modules_under_another_name() -> None:
    """全 CLI を import しても、`core` / `scripts.core` のような別名の二重ロードが起きない。"""
    code = "\n".join(
        [
            "import importlib, sys",
            "from env_builder.cli import COMMANDS",
            "for module, _ in COMMANDS.values():",
            "    importlib.import_module(module)",
            "bad = sorted(",
            "    name for name in sys.modules",
            "    if name == 'core' or name.startswith('core.')",
            "    or name == 'scripts' or name.startswith('scripts.')",
            "    or name == 'ops' or name.startswith('ops.')",
            ")",
            "print('BAD=' + ','.join(bad))",
        ]
    )

    rc, stdout, stderr = _run(["-c", code])

    assert rc == 0, stderr
    assert stdout.strip() == "BAD="


def test_same_class_is_used_by_commands_and_library() -> None:
    """CLI が使う ProjectRegistry と、ライブラリの ProjectRegistry が同一のクラスである。"""
    code = "\n".join(
        [
            "import env_builder.cli.run_build as run_build",
            "import env_builder.core.project as project",
            "print(run_build.ProjectRegistry is project.ProjectRegistry)",
        ]
    )

    rc, stdout, stderr = _run(["-c", code])

    assert rc == 0, stderr
    assert stdout.strip() == "True"


def test_only_wrappers_modify_sys_path() -> None:
    """sys.path を操作するのは scripts/ の互換ラッパーだけで、パッケージ本体は触らない。"""
    package_users = [
        str(path.relative_to(REPO_ROOT))
        for path in (REPO_ROOT / "env_builder").rglob("*.py")
        if "sys.path" in path.read_text(encoding="utf-8")
    ]

    assert package_users == []
