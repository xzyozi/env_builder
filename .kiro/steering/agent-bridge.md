---
inclusion: always
---

# Project Agent Steering（.agent/ へのブリッジ）

このプロジェクト（env_builder）の開発ルール・運用鉄則・スクリプト仕様・ワークフローは、
ツール非依存の知識ベースとして **`.agent/` 配下に集約**している。二重管理を避けるため、
Kiro 固有の場所には規約本体を置かず、このブリッジから `.agent/` を参照する。

作業を行う際は、状況に応じて以下を読み込んで準拠すること。

- 基本指示・役割: `.agent/instructions.md`
- 運用の鉄則（最重要）: `.agent/rules/operation-safety.md`
  - sudo / su は使わない。root が要る操作は root ログイン定義を使う。
  - src には root で入らない。src は読み取り専用。
  - OSS・認証情報・作業成果物はコミットしない。
- Git 運用: `.agent/rules/git-workflow.md`
- 配下プロジェクト管理: `.agent/rules/project-management.md`
- コーディング規約: `.agent/rules/coding-style.md`
- スクリプト仕様と境界: `.agent/references/scripts.md`
- 各種ワークフロー: `.agent/skills/` 配下の各 `SKILL.md`
  （context / connectivity-check / probe-src / remote-investigation /
  sync-artifacts / env-provisioning）

#[[file:.agent/rules/project-management.md]]

ルートの `AGENTS.md` も同じ `.agent/` を指すエントリポイントである。
