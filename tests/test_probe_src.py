"""probe_src の終了コード検証。SSH は fake に差し替える。"""

from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from env_builder.cli import probe_src
from env_builder.core.ssh import SSHResult


def install(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, failing: str = "") -> None:
    profile = SimpleNamespace(
        project_id=None,
        inventory_path=tmp_path / "servers.json",
        build_env_dir=tmp_path / "build_env",
    )
    monkeypatch.setattr(probe_src, "ProjectRegistry", lambda: SimpleNamespace(resolve=lambda project: profile))
    monkeypatch.setattr(probe_src, "load_inventory", lambda path: object())

    class FakeSSH:
        def __init__(self, inv: object, key: str) -> None:
            pass

        def __enter__(self) -> "FakeSSH":
            return self

        def __exit__(self, *exc: object) -> None:
            return None

        def run(self, command: str, timeout: int = 600, **kwargs: Any) -> SSHResult:
            if failing and failing in command:
                return SSHResult(1, "", "failed")
            return SSHResult(0, "out", "")

    monkeypatch.setattr(probe_src, "SSHSession", FakeSSH)


def test_probe_src_returns_zero_when_all_probes_succeed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install(monkeypatch, tmp_path)

    assert probe_src.main([]) == 0


def test_probe_src_returns_one_when_any_probe_fails(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    install(monkeypatch, tmp_path, failing="uname")

    assert probe_src.main([]) == 1