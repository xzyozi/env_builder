"""互換ラッパー: `python -m env_builder apply_packages` と同じ動作をする。

従来の `uv run python scripts/apply_packages.py` を使い続けられるように残している。
実装は `env_builder.cli.apply_packages` にある。
"""

import sys
from pathlib import Path

# 直接実行では sys.path[0] が scripts/ になるため、リポジトリルートを追加して env_builder を import できるようにする。
# プロジェクト内で sys.path を操作するのは、これらのラッパーだけにする。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from env_builder.cli.apply_packages import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
