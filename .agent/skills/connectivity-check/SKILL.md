---
name: connectivity-check
description: 踏み台越しに src / dst へ SSH 疎通できるかを check_connectivity.py で確認する
allowed-tools: [Bash, Read]
---

# 疎通確認

`scripts/check_connectivity.py` をラップし、build や環境整備に入る前段として
「接続が取れること」だけを検証する。

## 前提

- `inventory/servers.json` が存在すること（無ければ `init_config.py` で生成）。
- パスワードは inventory の `password_env` で指定した環境変数に設定済みであること。

## 手順

1. 全体を確認する。

   ```powershell
   uv run python scripts/check_connectivity.py
   ```

   bastion 以外の全サーバに対し `whoami` / `hostname` を確認する。

2. 個別に確認したいときは対象キーを指定する。

   ```powershell
   uv run python scripts/check_connectivity.py --target dst
   ```

3. 結果の `=== 結果 ===` を読み、OK / NG を確認する。

## NG のときの切り分け（エージェントの判断）

- **未登録のホスト鍵で拒否された**（`未登録のホスト鍵のため接続を拒否しました` と
  フィンガープリントが表示される）: 初回接続の正常な挙動。エージェントは
  `ENVB_HOST_KEY_POLICY=accept-new` を**自分で設定して再実行してはならない**。
  表示されたフィンガープリントをユーザーに示し、別の信頼できる経路での確認と、
  登録の許可を得てから、ユーザー自身が設定する（手順は
  `.agent/references/connection.md` の「ホスト鍵の検証」）。
- **登録済みホストの鍵が変わった**（`BadHostKeyException`）: なりすましの可能性がある。
  接続を続けず、ユーザーに報告する。専用 known_hosts の該当行を勝手に削除しない。
- **接続失敗**（認証・到達性）: `password_env` の環境変数が設定されているか、host/port/user、
  proxy_jump（踏み台）の定義が正しいかを確認する。
- **whoami/hostname が失敗**: 接続はできているがコマンドが通らない状態。ログイン後の
  シェル出力（`logout` 等のノイズ）や権限を疑う。
- root が必要な対象は、通常ユーザーでなく root ログイン定義（例 `dst_root`）を使う。

## 参照

- スクリプト仕様: `.agent/references/scripts.md`（check_connectivity.py）
- 鉄則: `.agent/rules/operation-safety.md`
