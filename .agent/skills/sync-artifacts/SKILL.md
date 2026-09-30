---
name: sync-artifacts
description: src から不足するファイル/ディレクトリを sync_files.py / sync_tree.py で dst へ中継配置する
allowed-tools: [Bash, Read]
---

# ファイル / ツリーの中継配置

src→手元PC→dst の中継転送で、dst に不足するファイルやディレクトリを配置する。踏み台越しで
両サーバ間の直接到達性が無くても運べる。用途に応じて 2 つのスクリプトを使い分ける。

## 使い分け

- **単一ファイル / 少数の設定ファイル** → `sync_files.py`
- **ディレクトリを丸ごと** → `sync_tree.py`（tar.gz 経由で確実・高速）

## ファイル単位（sync_files.py）

`desired_state/files.json` の対応表に従って src→dst 転送する。

```powershell
uv run python scripts/sync_files.py                       # files.json に従う
uv run python scripts/sync_files.py --upload-only <LOCAL> <REMOTE>   # 手元→dst のみ
```

- root 配置先へ送るときは `--dst` に root 定義（例 `dst_root`）を指定する。
- `files.json` に `mode` があれば配置後に `chmod` される。

## ディレクトリ単位（sync_tree.py）

「ファイルが無いので src から取得して dst に配置する」用途の中核。

```powershell
uv run python scripts/sync_tree.py --src src --dst dst_root `
  --remote-src /opt/mel/modern/lib64/version_mng `
  --remote-dst-parent /opt/mel/modern/lib64
```

- `--remote-src` の対象名がそのまま `--remote-dst-parent` の下に展開される。
- 中継 tar は `build_env/artifacts/trees/` に一時保管（Git 管理外）。リモート `/tmp` の
  tar は処理後に削除される。

## 判断のポイント（エージェント）

- 何を配置すべきかは、`remote-investigation` や `run_build` の失敗ログから特定する
  （不足ヘッダ・ライブラリ・共通モジュール等）。
- root 配置先（`/opt` 等）は昇格せず root 定義の `--dst` で運ぶ（operation-safety 準拠）。
- OSS アーカイブの恒久持ち込みはしない。中継の一時経由に留める。

## 参照

- スクリプト仕様: `.agent/references/scripts.md`（sync_files.py / sync_tree.py）
- 中核ループ: `.agent/skills/env-provisioning/SKILL.md`
