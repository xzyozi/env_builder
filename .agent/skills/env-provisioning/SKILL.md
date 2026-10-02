---
name: env-provisioning
description: src を参考に dst の環境を整える中核ループ。ビルド疎通・コンテナ構築など作業全般の汎用手順
allowed-tools: [Bash, Read, Grep, Glob]
---

# 環境整備ループ（中核）

「src を参考に dst の環境を整える」作業全般の汎用手順。**ビルドに限らず**、コンテナ環境の
構築など「dst をあるべき状態に近づける」作業はこのループに乗せる。個別のスクリプト操作は
専用スキル（connectivity-check / probe-src / remote-investigation / sync-artifacts）に委ね、
ここでは**全体の順序と判断のループ**を示す。

## 進め方（探索 → 計画 → 実装）

```text
- [ ] 0. 案件メタデータを確認（desired_state / inventory を読む）
- [ ] 1. 疎通確認（connectivity-check）
- [ ] 2. src 現状収集（probe-src）
- [ ] 3. 対象作業を実行（build なら run_build.py）
- [ ] 4. 失敗ログを解釈し、不足を特定（remote-investigation）
- [ ] 5. 環境を整える（apply_packages / sync-artifacts）
- [ ] 6. 再実行して通るまで 3〜5 を繰り返す
```

## Step 0: 案件メタデータの確認

作業対象は案件ごとに異なる。まず Git 管理外のメタデータを読み、今回の対象を把握する。

- プロジェクト: `--project <id>` を指定し、選択したProjectProfileを確認する。未指定時はlegacy経路。
- 接続対象: 選択したprofileの `inventory/servers.json`（キー名 src / dst / dst_root / bastion 等）
- あるべき状態: 選択したprofileの `desired_state/`（build なら `build_targets.local.json`、パッケージなら
  `packages.json`、ファイル対応なら `files.json`）
- 作業成果物・ログ: 選択したprofileの `build_env/`

手順そのものはこのスキルにあり、**何を作るか**はメタデータ側にある。ビルドでもコンテナ
構築でも、この分離で同じループを使い回す。

## Step 1-2: 疎通と現状把握

1. `connectivity-check` で src / dst に接続できることを確認する。
2. `probe-src` で src の現状を収集し、dst との差分の見当をつける。

## Step 3: 対象作業を実行

- **ビルド疎通の場合**:

  ```powershell
  uv run python scripts/run_build.py --target <name>
  ```

  `build_targets.local.json` の定義に従い dst でビルドし、`build_env/logs/build_<name>_<ts>/`
  に stdout/stderr が保存される。
- **コンテナ構築など他作業の場合**: 対象に応じたコマンドを `remote-investigation`
  （remote_exec.py）や専用スクリプトで実行する。状態を変える操作は operation-safety に従う。

## Step 4: 失敗の解釈（重要）

- `run_build.py` は `typechk.sh` 生成のサブシェル経由のため、**終了コードが 0 でも失敗**の
  ことがある。stderr のエラー痕跡マーカー（`致命的エラー` / `fatal error` / `make: ***` /
  `: error:` / `undefined reference` / `ld returned` 等）でも成否を判定する。
- 保存された `stepNN.stderr.log` を読み、不足しているヘッダ・ライブラリ・共通モジュール・
  パッケージを特定する。必要なら `remote-investigation` でリモートを追加調査する。

## Step 5: 環境を整える

特定した不足に応じて、対応する専用スクリプト / スキルを選ぶ。

- **パッケージ不足** → `apply_packages.py --check` で差分確認 → 適用（dst は root ログイン前提）。
- **ファイル / ディレクトリ不足** → `sync-artifacts`（sync_files / sync_tree）で src から配置。
  root 配置先は `--dst` に root 定義を使う（昇格しない）。
- **ビルド定義の問題**（Makefile 等） → 調査の上で修正方針を立てる。

## Step 6: 再実行ループ

環境を整えたら Step 3 を再実行し、通るまで 3〜5 を繰り返す。同じ対処を 2 回繰り返しても
解決しない場合は、対症療法をやめて根本原因を診断し、別アプローチに切り替える。

## 鉄則（常時）

- sudo / su は使わない。root が要る操作は root ログイン定義を使う。
- src は参照専用・読み取り専用。OSS アーカイブは恒久保存しない。
- 破壊的・不可逆な操作は事前に影響を説明して確認を取る。
  （詳細は `.agent/rules/operation-safety.md`）

## 参照

- 各スクリプト仕様: `.agent/references/scripts.md`
- 個別操作: `.agent/skills/{connectivity-check,probe-src,remote-investigation,sync-artifacts}/SKILL.md`
