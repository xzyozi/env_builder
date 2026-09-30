# Claude Code 用エントリポイント

このリポジトリの開発規約・運用鉄則・ワークフローは、ツール非依存の知識ベースとして
**`.agent/` 配下に集約**している。ルート `AGENTS.md` と同じ内容を指すポインタである。

作業を始める前に、以下を読み込んで準拠すること。

- 基本指示: `.agent/instructions.md`
- 運用の鉄則（最重要 / sudo・su 禁止、src に root 禁止、OSS 非保存）: `.agent/rules/operation-safety.md`
- Git 運用: `.agent/rules/git-workflow.md`
- コーディング規約: `.agent/rules/coding-style.md`
- スクリプト仕様と境界: `.agent/references/scripts.md`
- 各種ワークフロー: `.agent/skills/<name>/SKILL.md`

`.agent/skills/` の各 SKILL.md は、frontmatter（`name` / `description` /
`allowed-tools`）付きの手順書。Claude Code のスキルとしても解釈できる。
詳細は `AGENTS.md` を参照。
