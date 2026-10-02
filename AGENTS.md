# Agent Instructions

このリポジトリ（env_builder）の開発ルール・運用鉄則・スクリプト仕様・ワークフローは、
ツール非依存の知識ベースとして **`.agent/` 配下に集約**している。どのエージェント
（Kiro / Claude Code / Antigravity 等）で作業する場合も、ここを参照して準拠すること。

## 何をするリポジトリか

手元PC（Windows / Python）から踏み台越しに SSH 接続し、**参照元サーバ(src)を参考に
構築先サーバ(dst)の環境を整える**作業基盤。スクリプトは手順の方針で、実行判断は
エージェントが行う。作業は build に限らず、コンテナ環境構築なども含む。

## まず読むもの

- 基本指示・役割: `.agent/instructions.md`
- 運用の鉄則（最重要）: `.agent/rules/operation-safety.md`
- Git 運用: `.agent/rules/git-workflow.md`
- コーディング規約: `.agent/rules/coding-style.md`
- スクリプト仕様と境界: `.agent/references/scripts.md`
- 配下プロジェクト管理: `.agent/rules/project-management.md`

## ワークフロー（スキル）

- コンテキスト読込: `.agent/skills/context/SKILL.md`
- 疎通確認: `.agent/skills/connectivity-check/SKILL.md`
- src 現状収集: `.agent/skills/probe-src/SKILL.md`
- リモート調査: `.agent/skills/remote-investigation/SKILL.md`
- ファイル/ツリー配置: `.agent/skills/sync-artifacts/SKILL.md`
- 環境整備ループ（中核）: `.agent/skills/env-provisioning/SKILL.md`

## 絶対に守ること

- sudo / su は使わない。root が要る操作は root ログイン定義を使う。
- src には root で入らない。src は読み取り専用。
- OSS・認証情報・作業成果物はコミットしない（`.gitignore` 準拠）。

詳細は `.agent/rules/operation-safety.md` を参照。
