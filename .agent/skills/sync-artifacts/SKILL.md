---
name: sync-artifacts
description: src から不足するファイル/ディレクトリを専用作業領域経由で dst へ中継配置する
allowed-tools: [Bash, Read]
---

# ファイル / ツリーの中継配置

src→手元PC→dst の中継転送で、dst に不足するファイルやディレクトリを配置する。踏み台越しで
両サーバ間の直接到達性が無くても運べる。用途に応じて 2 つのスクリプトを使い分ける。

転送中継の一時物は、既存の `build_env/artifacts/` や `/home/<user>` 直下には置かない。
ローカルは `build_env/work/<work-id>/stage/`、リモートは `/tmp/env_builder-<work-id>-XXXXXX/`
を使い、作業終了時に専用ディレクトリごとcleanupする。

## 使い分け

- **単一ファイル / 少数の設定ファイル** → `sync_files.py`
- **ディレクトリを丸ごと** → `sync_tree.py`（tar.gz 経由で確実・高速）

## ファイル単位（sync_files.py）

`desired_state/files.json` の対応表に従って src→dst 転送する。

```powershell
uv run python scripts/sync_files.py                       # files.json に従う
uv run python scripts/sync_files.py --upload-only <LOCAL> <REMOTE>   # 手元→dst のみ
```

- srcからの中継ファイルは `build_env/work/<work-id>/stage/file_NNN` に作成される。
- download、upload、`chmod` のどこかで失敗しても、作業コンテキスト終了時に中継領域を削除する。
- `--upload-only` のローカル入力ファイルと、`files.json` の `dst_path` に指定した永続配置先は削除しない。
- root 配置先へ送るときは `--dst` に root 定義（例 `dst_root`）を指定する。
- `files.json` に `mode` があれば配置後に `chmod` され、結果が失敗した場合は処理全体を失敗扱いにする。

## ディレクトリ単位（sync_tree.py）

「ファイルが無いので src から取得して dst に配置する」用途の中核。

```powershell
uv run python scripts/sync_tree.py --src src --dst dst_root `
  --remote-src /opt/mel/modern/lib64/version_mng `
  --remote-dst-parent /opt/mel/modern/lib64
```

- src側とdst側に一意な専用 `/tmp` 作業領域を作成し、その配下に `tree.tar.gz` を置く。
- ローカル中継は `build_env/work/<work-id>/stage/tree.tar.gz` に置く。
- src側のdownload、dst側のupload・展開、通信例外のいずれでも専用作業領域をcleanupする。
- `/tmp` のOS側定期削除はfallbackであり、正常終了時のcleanupを代替しない。
- `--remote-src` の対象名がそのまま `--remote-dst-parent` の下に展開される。
- `--remote-dst-parent` 以下の永続配置物はcleanupしない。

## 判断のポイント（エージェント）

- 何を配置すべきかは、`remote-investigation` や `run_build` の失敗ログから特定する
  （不足ヘッダ・ライブラリ・共通モジュール等）。
- root 配置先（`/opt` 等）は昇格せず root 定義の `--dst` で運ぶ（operation-safety 準拠）。
- OSS アーカイブの恒久的な持ち込みはしない。中継の一時経由に留め、専用作業領域のcleanupを確認する。
- cleanup失敗時は `build_env/logs/work_<work-id>/manifest.json` を確認し、marker・所有者・
  パスprefixを検証してから個別に棚卸しする。`/tmp` 全体やHOME直下を推測で削除しない。

## 参照

- スクリプト仕様: `.agent/references/scripts.md`（sync_files.py / sync_tree.py）
- 運用安全: `.agent/rules/operation-safety.md`
- 中核ループ: `.agent/skills/env-provisioning/SKILL.md`
