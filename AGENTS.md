# Agent Instructions

このリポジトリ（env_builder）の開発ルール・運用鉄則・スクリプト仕様・ワークフローは、
ツール非依存の知識ベースとして **`.agent/` 配下に集約**している。どのエージェント
（Kiro / Claude Code / Antigravity 等）で作業する場合も、ここを参照して準拠すること。

## 絶対に守ること（最初に確認）

ポインタ先を読む前でも、次は常に守る。詳細・根拠は `.agent/rules/operation-safety.md`。

- sudo / su は使わない。root が要る操作は root ログイン定義（例: `dst_root`）を使う。
- src は書き込み禁止。許可するのは、読み取りと、コピーによる取得だけ。root 定義での読み取りは確認なしで可（使う定義は引数で明示する）。
- 構築は確認待ちで止まらずに進める。既存の環境を壊したら、まず元に戻し、調査結果を添えて引き継ぐ（詳細は `operation-safety.md`）。
- OSS・認証情報・作業成果物はコミットしない（`.gitignore` 準拠）。パスワードは環境変数で渡し、コマンドラインに直書きしない。
- 破壊的・不可逆な操作と、承認が必要な操作は、実行前にユーザーへ内容と影響を提示して**応答を待つ**。ただし dst は基本的に制約なし（広範囲で取り返しのつかない操作を除く。詳細は `operation-safety.md`）。承認 UI のないツールでも、確認なしに進めない。

## 何をするリポジトリか

手元PC（Windows / Python）から踏み台越しに SSH 接続し、**参照元サーバ(src)を参考に
構築先サーバ(dst)の環境を整える**作業基盤。スクリプトは手順の方針で、実行判断は
エージェントが行う。作業は build に限らず、コンテナ環境構築なども含む。

## まず読むもの

- 基本指示・役割: `.agent/instructions.md`
- 運用の鉄則（最重要）: `.agent/rules/operation-safety.md`
- Git 運用: `.agent/rules/git-workflow.md`
- コーディング規約: `.agent/rules/coding-style.md`
- 転送前の事前チェック（容量の基準と、自動実行の範囲）: `.agent/references/preflight.md`
- スクリプト仕様と境界: `.agent/references/scripts.md`
- 全体フロー（開始から環境整備まで）: `.agent/references/workflow.md`
- 配下プロジェクト管理: `.agent/rules/project-management.md`
- 初期設定手順（全ツール共通）: `.agent/skills/project-initialization/SKILL.md`
- 補足（Kiro のみ）: Agent 一覧から `.kiro/agents/project-initializer.md` を選べる。他のツールは上の共通手順を直接読む

## ワークフロー（スキル）

- コンテキスト読込: `.agent/skills/context/SKILL.md`
- プロジェクト初期設定: `.agent/skills/project-initialization/SKILL.md`
- 疎通確認: `.agent/skills/connectivity-check/SKILL.md`
- src 現状収集: `.agent/skills/probe-src/SKILL.md`
- リモート調査: `.agent/skills/remote-investigation/SKILL.md`
- ファイル/ツリー配置: `.agent/skills/sync-artifacts/SKILL.md`
- コンテナ解析・image 移送: `.agent/skills/container/SKILL.md`
- 環境整備ループ（中核）: `.agent/skills/env-provisioning/SKILL.md`

## 絶対に守ること

冒頭の「絶対に守ること（最初に確認）」を参照。詳細は `.agent/rules/operation-safety.md`。
