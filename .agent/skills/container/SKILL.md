---
name: container
description: container.py で container を inspect 解析し、run 候補と image 移送計画を作る。移送は明示承認後だけ実行する
allowed-tools: [Bash, Read, Grep]
---

# コンテナ解析・image 移送計画

`scripts/container.py` をラップし、移送元の container を inspect して共通モデルへ
正規化し、run 候補と image 移送計画を出力する。**計画の確認と承認はエージェントと
ユーザーの責務**で、image 移送は明示承認があるときだけ実行する。run は自動実行しない。

標準の実行形式は `uv run python -m env_builder container ...`。
`uv run python scripts/container.py ...` は同じコマンドを呼ぶ互換ラッパー。

## 前提

- 設定は選択した project の `desired_state/container.local.json`（Git 管理外）。
  最低限 `engine`（`podman` または `docker`）、`image`、`source_target`、
  `destination_target`、`container` を指定する。
- `transfer_mode` は既定 `export`。高再現性が要るときだけ `commit` を指定する。
- 対応は同一 engine 内の移送のみ（Podman→Podman / Docker→Docker）。engine 間変換は対象外。
- src を移送元にする場合、`export` は読み取り操作として扱う。`commit` は src の
  image store を変更するため、明示承認なしに実行しない（operation-safety 準拠）。

## 手順

1. まず読み取り解析だけを行い、計画を出力する。

   ```powershell
   uv run python scripts/container.py --project <project-id>
   ```

   `inspect` 要約、run 候補、image 移送計画が
   `build_env/logs/<project-id>/container_plan_<timestamp>/container-plan.json` に保存される。

2. 出力された計画を読み、移送方式・run 候補・警告・未対応項目を確認する。

   - run 候補の初期対応: image / name / command・entrypoint / environment / workdir /
     user / port / bind mount / network / restart policy。
   - resource 制限・capability・device/GPU・namespace・healthcheck は解析・警告まで。
   - 秘密情報は実値を保存せず `${ENVB_CONTAINER_<KEY>}` 形式の参照に置換される。

3. 計画に問題がなく、ユーザーの明示承認が得られたときだけ image 移送を実行する。

   ```powershell
   uv run python scripts/container.py --project <project-id> --execute-image --approve-image
   ```

   `--execute-image --approve-image` を併用したときだけ移送が走る。run は実行しない。

## 判断のポイント（エージェント）

- まず承認なしで計画を出し、移送方式（`export` か `commit` か）と影響を説明してから
  承認を求める。`commit` は移送元の image store を変える分、影響が大きい。
- bind mount の通常ファイル・ディレクトリは、desired state に明示したものだけ既存の
  `sync-artifacts`（sync_files / sync_tree）で扱う。named volume・secret・device/GPU・
  network は自動移送しない。警告として扱い、必要可否をユーザーと確認する。
- rootless/rootful は自動切替しない。移送元・移送先の実行コンテキストを揃え、差異は
  計画の警告として残す。sudo / su は使わない。
- 失敗時、archive と専用作業領域は cleanup される。作成済み image は自動削除せず、
  ID・digest・状態が manifest に記録される。同名 tag は上書きしない。

## 参照

- スクリプト仕様: `.agent/references/scripts.md`（container.py）
- 運用安全: `.agent/rules/operation-safety.md`
- 中核ループ: `.agent/skills/env-provisioning/SKILL.md`
- 配置の実務: `.agent/skills/sync-artifacts/SKILL.md`
