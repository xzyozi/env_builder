from pathlib import Path

import pytest

from env_builder.cli import init_config
from env_builder.core import project as project_module

SERVERS_SAMPLE = '{"sample": true}\n'
ENV_SAMPLE = "@echo off\r\nrem template\r\n"


@pytest.fixture
def samples(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """テンプレートを tmp に差し替え、実リポジトリを触らないようにする。"""
    inventory = tmp_path / "samples"
    inventory.mkdir()
    (inventory / "servers.sample.json").write_text(SERVERS_SAMPLE, encoding="utf-8")
    (inventory / "set_env.sample.bat").write_bytes(ENV_SAMPLE.encode("utf-8"))
    monkeypatch.setattr(init_config, "INVENTORY_DIR", inventory)
    monkeypatch.setenv(project_module.PROJECT_ROOT_ENV, str(tmp_path / "projects"))
    return tmp_path / "projects"


def test_creates_servers_and_set_env(samples: Path) -> None:
    assert init_config.main(["--project", "proj-a"]) == 0

    root = samples / "proj-a"
    assert (root / "inventory" / "servers.json").read_text(encoding="utf-8") == SERVERS_SAMPLE
    assert (root / "build_env" / "set_env.bat").exists()


def test_existing_files_are_kept(samples: Path) -> None:
    init_config.main(["--project", "proj-a"])
    env_bat = samples / "proj-a" / "build_env" / "set_env.bat"
    servers = samples / "proj-a" / "inventory" / "servers.json"
    env_bat.write_text("real-secret", encoding="utf-8")
    servers.write_text("edited", encoding="utf-8")

    init_config.main(["--project", "proj-a"])

    assert env_bat.read_text(encoding="utf-8") == "real-secret"
    assert servers.read_text(encoding="utf-8") == "edited"


def test_force_overwrites_servers_but_not_set_env(samples: Path) -> None:
    init_config.main(["--project", "proj-a"])
    env_bat = samples / "proj-a" / "build_env" / "set_env.bat"
    servers = samples / "proj-a" / "inventory" / "servers.json"
    env_bat.write_text("real-secret", encoding="utf-8")
    servers.write_text("edited", encoding="utf-8")

    init_config.main(["--project", "proj-a", "--force"])

    assert servers.read_text(encoding="utf-8") == SERVERS_SAMPLE
    assert env_bat.read_text(encoding="utf-8") == "real-secret"
    assert not env_bat.with_name("set_env.bat.bak").exists()


def test_force_credentials_backs_up_then_overwrites(samples: Path) -> None:
    init_config.main(["--project", "proj-a"])
    env_bat = samples / "proj-a" / "build_env" / "set_env.bat"
    servers = samples / "proj-a" / "inventory" / "servers.json"
    env_bat.write_text("real-secret", encoding="utf-8")
    servers.write_text("edited", encoding="utf-8")

    init_config.main(["--project", "proj-a", "--force-credentials"])

    assert env_bat.read_bytes() == ENV_SAMPLE.encode("utf-8")
    assert env_bat.with_name("set_env.bat.bak").read_text(encoding="utf-8") == "real-secret"
    assert servers.read_text(encoding="utf-8") == "edited"


def test_legacy_path_uses_repo_level_dirs(samples: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    legacy_inventory = tmp_path / "legacy_inventory"
    legacy_build_env = tmp_path / "legacy_build_env"
    monkeypatch.setattr(project_module, "INVENTORY_DIR", legacy_inventory)
    monkeypatch.setattr(project_module, "BUILD_ENV_DIR", legacy_build_env)

    init_config.main([])

    assert (legacy_inventory / "servers.json").exists()
    assert (legacy_build_env / "set_env.bat").exists()
