---
name: probe-src
description: 参照元 src の現状（OS 情報・導入パッケージ等）を probe_src.py で収集し、dst 整備の材料にする
allowed-tools: [Bash, Read, Grep]
---

# src 現状収集

`scripts/probe_src.py` をラップし、src の現状を収集して `build_env/src_snapshot/<target>/`
に保存する。「src では何が入っているか」を dst で再現するための参照材料を作る。

## 前提

- src は**参照専用・読み取り専用**。root で入らない（operation-safety 準拠）。

## 手順

1. src の現状を収集する。

   ```powershell
   uv run python scripts/probe_src.py --target src
   ```

   収集項目は `os_release` / `kernel` / `rpm_packages` / `dnf_repolist`。
   結果は `build_env/src_snapshot/src/<name>.txt` に保存される。

2. 収集結果を読み込み、dst との差分を検討する。

   - `rpm_packages.txt` … src に入っているパッケージ一覧。
   - `os_release.txt` / `kernel.txt` … OS・カーネルの世代確認。
   - `dnf_repolist.txt` … 利用可能なリポジトリ。

## 収集後の判断（エージェント）

- dst に不足しているパッケージ/バージョンを特定し、`apply_packages`（冪等適用）や
  `sync-artifacts`（ファイル/ツリー配置）につなげる。
- OSS のアーカイブは持ち込まない。必要なら src で version を確認し、その結果を dst への
  コマンドに反映する（operation-safety 準拠）。

## 参照

- スクリプト仕様: `.agent/references/scripts.md`（probe_src.py）
- 次の手: `.agent/skills/env-provisioning/SKILL.md`
