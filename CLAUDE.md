# Claude Code 用エントリポイント

このリポジトリの開発規約・運用鉄則・ワークフローは、ツール非依存の知識ベースとして
**`.agent/` 配下に集約**している。ルート `AGENTS.md` と同じ内容を指すポインタである。

## 絶対に守ること（最初に確認）

ポインタ先を読む前でも、次は常に守る。詳細・根拠は `.agent/rules/operation-safety.md`。

- sudo / su は使わない。root が要る操作は root ログイン定義（例: `dst_root`）を使う。
- src は参照専用。状態を変える操作はしない。root 定義での接続は、理由を明示して確認を取った場合に限る。
- OSS・認証情報・作業成果物はコミットしない（`.gitignore` 準拠）。パスワードは環境変数で渡し、コマンドラインに直書きしない。
- 破壊的・不可逆な操作と、承認が必要な操作は、実行前にユーザーへ内容と影響を提示して**応答を待つ**。承認を自動で通す設定でも、確認なしに進めない。

## 読み込むもの

作業を始める前に、以下を読み込んで準拠すること。

- 基本指示: `.agent/instructions.md`
- 運用の鉄則（最重要 / sudo・su 禁止、src は参照専用、OSS 非保存）: `.agent/rules/operation-safety.md`
- Git 運用: `.agent/rules/git-workflow.md`
- コーディング規約: `.agent/rules/coding-style.md`
- スクリプト仕様と境界: `.agent/references/scripts.md`
- 各種ワークフロー: `.agent/skills/<name>/SKILL.md`

`.agent/skills/` の各 SKILL.md は、frontmatter（`name` / `description` /
`allowed-tools`）付きの手順書。ただし配置が `.agent/skills/` のため、Claude Code の
スキルとしては**自動検出されない**。必要な手順は、対応する `SKILL.md` を自分で開いて
読むこと（`context` スキルで一括読込もできる）。`allowed-tools` は Claude Code 形式の
ツール名で、他のツールでは無視される。

Claude Code のスキルとして使いたい場合は、`.claude/skills/<name>/` へ `SKILL.md` を
リンクまたはコピーする（ローカルでの任意の対応。リポジトリには含めない）。

詳細は `AGENTS.md` を参照。
