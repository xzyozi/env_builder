# Git 運用ルール

## ブランチ

- `main` / `master` へ直接 push しない。作業は新規ブランチで行う。
- ブランチ作成・切り替えは `git switch` を使う（`git switch -c <branch>`）。
- ブランチ名は英数字とハイフンのみ（例: `feature/agent-config`）。

## コミットメッセージ

`[種別] 概要` の形式を必須とする。概要は日本語でよい。

| 種別      | 用途         | 例                                |
| --------- | ------------ | --------------------------------- |
| `[feat]`  | 新機能       | `[feat] .agent 知識ベースを追加`  |
| `[fix]`   | バグ修正     | `[fix] NULL チェック漏れの修正`   |
| `[docs]`  | ドキュメント | `[docs] scripts リファレンス追加` |
| `[other]` | 上記以外     | `[other] .gitignore 更新`         |

## コミットしないもの（機密・作業成果物）

`.gitignore` で除外済み。誤ってステージしない。

- 接続定義の実体: `inventory/servers.json`、`inventory/*.local.json`
- あるべき状態の実体: `desired_state/` 配下
- テンプレート: `*.sample.json`
- 作業エリア: `build_env/*`（`.gitkeep` を除く。`set_env.bat` は機密を含むため特に注意）
- 秘密鍵・認証情報: `*.pem` / `*.key` / `*.ppk` / `secrets/`
- Kiro のローカル作業ログ: `.kiro/`

## コミット時の作法

- `git add .` ではなく、対象ファイルを名指しでステージする。
- コミット前に `git diff --check`（空白・改行の混入確認）を通す。
- コミットはユーザーが明示的に依頼したときに行う。
- `--amend` や force push などの履歴書き換えは、明示依頼がない限り行わない。

## コミット対象（このリポジトリで管理するもの）

- 汎用スクリプト（`scripts/` と `scripts/core/`）
- `.agent/` 配下の知識ベース、ルート `AGENTS.md` / `CLAUDE.md`
- `.kiro/steering/agent-bridge.md`（ブリッジのみ。他の `.kiro/` は除外）
