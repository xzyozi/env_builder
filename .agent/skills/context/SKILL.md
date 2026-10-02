---
name: context
description: env_builder の開発ルール・運用鉄則・スクリプト仕様・ワークフローを読み込んでコンテキストに載せる
allowed-tools: [Read, Grep, Glob]
---

# コンテキスト読込

このスキルが呼ばれたら、`.agent/` 配下の知識ベースを読み込み、以降の作業がこのプロジェクトの
ルールと手順に準拠できる状態にする。何かを実行するスキルではなく、**情報を載せるだけ**の入口。

## 読み込むもの

リポジトリルートから相対で、以下を順に読む。

1. `.agent/instructions.md` — エージェントの役割・基本姿勢・案件メタデータの置き場所
2. `.agent/rules/operation-safety.md` — 運用の鉄則（sudo/su 禁止、src に root 禁止、OSS 非保存）
3. `.agent/rules/git-workflow.md` — ブランチ、コミット、機密・成果物の扱い
4. `.agent/rules/coding-style.md` — Python / uv / ruff・mypy・pytest / core の責務
5. `.agent/rules/project-management.md` — project profile、`--project`、agent規約の適用範囲
6. `.agent/references/scripts.md` — 各スクリプトの用途・引数・スクリプトとエージェントの境界

## 読み込んだ後

- 読み込んだ旨をユーザーに簡潔に伝える。
- 実行を伴うワークフローが必要なら、対応する `.agent/skills/<name>/SKILL.md` を参照する。

## 使いどころ

- このリポジトリで作業を始めるとき、最初にルールと手順を把握したい。
- AGENTS.md を自動で読まないツールで、`.agent/` の内容をまとめて載せたい。
