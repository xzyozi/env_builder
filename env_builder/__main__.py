"""`python -m env_builder <command>` の入口。"""

from __future__ import annotations

from env_builder.cli import run

if __name__ == "__main__":
    raise SystemExit(run())
