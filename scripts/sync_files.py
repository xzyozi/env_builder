"""ファイルを src→手元→dst と仲介転送する（download → upload）。

desired_state/files.json の対応表に従い、参照元(src)から設定ファイルを
取得し、構築先(dst)へ配置する。手元PCを中継点にするため、踏み台越しでも
両サーバ間の直接到達性が無くても転送できる。

インターネットから落とした OSS を持ち込む場合は --upload-only で
build_env/artifacts のファイルを dst へ送るだけの使い方も可能。

使い方:
    uv run python scripts/sync_files.py                       # files.json に従い src->dst
    uv run python scripts/sync_files.py --upload-only <local> <remote>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from core.config import BUILD_ENV_DIR, DESIRED_STATE_DIR, load_inventory, load_json  # noqa: E402
from core.logging_utils import get_logger  # noqa: E402
from core.ssh import SSHSession  # noqa: E402


def _load_files() -> dict:
    path = DESIRED_STATE_DIR / "files.json"
    if not path.exists():
        sample = DESIRED_STATE_DIR / "files.sample.json"
        raise FileNotFoundError(
            f"{path.name} がありません。{sample.name} を複製して実値を埋めてください。"
        )
    return load_json(path)


def _sync_via_local(inv, logger, src_key: str, dst_key: str) -> int:
    """files.json に従い src からダウンロードして dst へアップロードする。"""
    cfg = _load_files()
    entries = cfg.get("files", [])
    if not entries:
        logger.info("files.json に対象がありません。")
        return 0

    staging = BUILD_ENV_DIR / "artifacts" / "sync"
    staging.mkdir(parents=True, exist_ok=True)

    logger.info("src(%s) からダウンロードします", src_key)
    with SSHSession(inv, src_key) as src_ssh:
        for i, e in enumerate(entries):
            local = staging / f"file_{i:03d}"
            src_ssh.get_file(e["src_path"], str(local))
            logger.info("  download: %s", e["src_path"])
            e["_local"] = str(local)

    logger.info("dst(%s) へアップロードします", dst_key)
    with SSHSession(inv, dst_key) as dst_ssh:
        for e in entries:
            dst_ssh.put_file(e["_local"], e["dst_path"])
            logger.info("  upload:   %s", e["dst_path"])
            mode = e.get("mode")
            if mode:
                dst_ssh.run(f"chmod {mode} {e['dst_path']}")
    logger.info("転送完了")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--src", default="src", help="取得元（inventory のキー）")
    parser.add_argument("--dst", default="dst", help="配置先（inventory のキー）")
    parser.add_argument(
        "--upload-only", nargs=2, metavar=("LOCAL", "REMOTE"),
        help="ローカルファイルを dst へ送るだけ（download をスキップ）",
    )
    args = parser.parse_args()

    logger = get_logger()
    inv = load_inventory()

    if args.upload_only:
        local, remote = args.upload_only
        logger.info("dst(%s) へアップロード: %s -> %s", args.dst, local, remote)
        with SSHSession(inv, args.dst) as ssh:
            ssh.put_file(local, remote)
        logger.info("完了")
        return 0

    return _sync_via_local(inv, logger, args.src, args.dst)


if __name__ == "__main__":
    raise SystemExit(main())
