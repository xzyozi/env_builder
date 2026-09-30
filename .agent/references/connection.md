# 接続構成リファレンス（前提条件）

このプロジェクトは「手元PC → 踏み台 → src / dst」で SSH 接続することが作業の入口である。
ここでは**接続がどう構成されているか（前提条件）**を説明する。具体的なホスト名・IP・
ユーザー名・パスワードといった機密は書かない。実値は Git 管理外の
`inventory/servers.json` に閉じ込め、パスワードは環境変数で渡す。

> このファイルは構造の説明用サンプルである。実体の接続定義は
> `inventory/servers.json`（`.gitignore` で除外）を参照すること。

## サーバの役割と経由経路

`inventory/servers.json` はサーバを**キー名**で定義する。想定する役割は次の通り
（キー名は例。実際の命名は inventory 側で決める）。

| キー名（例） | 役割                      | 接続経路                        | 権限         |
| ------------ | ------------------------- | ------------------------------- | ------------ |
| `bastion1`   | src 用踏み台 1 段目       | 手元PC から直接                 | 通常ユーザー |
| `bastion2`   | src 用踏み台 2 段目       | bastion1 経由                   | 通常ユーザー |
| `src`        | 参照元（参照専用）        | bastion1 → bastion2 の 2 段経由 | 通常ユーザー |
| `src_root`   | 参照元と同一ホストに root | bastion1 → bastion2 の 2 段経由 | root         |
| `dst`        | 構築先（build・調査用）   | 手元PC から直接（踏み台なし）   | 通常ユーザー |
| `dst_root`   | 構築先と同一ホストに root | 手元PC から直接（踏み台なし）   | root         |

経由図:

```text
                       ┌───────────┐   ┌───────────┐   ┌───────────────┐
手元PC ─(直接)─────────▶│ bastion1  │──▶│ bastion2  │──▶│ src / src_root │
  │                    └───────────┘   └───────────┘   └───────────────┘
  │                                                     参照元。用途に応じ user を替えて接続
  ├─(直接)──────────────▶ dst        構築先。build / 調査（通常ユーザー）
  └─(直接)──────────────▶ dst_root   dst と同一ホストに root で接続（root 権限が要る操作用）
```

## ユーザー替えでの接続（重要）

同一ホストに対しても、**用途に応じてログインユーザーを替えた別定義**を用意できる。
sudo / su で昇格するのではなく、**必要なユーザーで直接ログインする定義を選ぶ**のが
このプロジェクトの方針。

- **src / dst とも、通常ユーザー定義と root 定義の両方を作れる。** 例:
  `src`（通常ユーザー・参照用）と `src_root`（root）、`dst`（通常ユーザー）と
  `dst_root`（root）。ホスト・踏み台経路は同じで `user` と `password_env`（または
  鍵）だけを替える。
- 参照元でも root 接続は可能である。root 権限が必要な参照・確認が要る場合は、
  root 定義（例 `src_root`）を対象に指定する。
- その他の要件でも、別ユーザーが必要になれば同じ要領でユーザー替えの定義を追加できる
  （ホストは共通、`user` と認証だけ差し替える）。

### 運用上の使い分け（方針）

技術的にはどのユーザーでも定義できるが、既定の運用方針は次の通り。逸脱が必要な場合は
その理由を明示する。

- **src への通常アクセスは参照専用**とし、状態を変えない読み取りコマンドに限る。
- root が要る操作は、対象ホストの root 定義（`*_root`）を明示的に選んで実行する。
  昇格（sudo / su）はしない。
- 破壊的・不可逆な操作は事前に影響を説明して確認を取る。
  （詳細は `.agent/rules/operation-safety.md`）

## 前提として押さえること

- **src は 2 段踏み台（bastion1 → bastion2）経由**。**dst は踏み台なしで直結**。
- root 権限は同一ホストの root 定義（`*_root`）で得る。sudo / su は使わない。
- 多段経路は `proxy_jump` に**近い踏み台から順**のキー列で書く（例: src なら
  `["bastion1", "bastion2"]`）。SSH 実行側が経由順にチャネルを張って多段接続する
  （OpenSSH の ProxyJump 相当）。

## 定義フォーマット（サンプル・実値なし）

`inventory/servers.json` は次の形。値はすべてプレースホルダで、実値は書かない。
`//` で始まるキーはコメントとして無視される。

```jsonc
{
  "//": "接続対象の実体定義。機密は password_env の環境変数で渡す。.gitignore で除外。",

  "bastion1": {
    "//": "src 用踏み台 1 段目",
    "host": "<BASTION1_HOST>",
    "port": 22,
    "user": "<USER>",
    "auth": { "method": "password", "password_env": "ENVB_BASTION1_PASSWORD" }
  },

  "bastion2": {
    "//": "src 用踏み台 2 段目（bastion1 経由）",
    "host": "<BASTION2_HOST>",
    "port": 22,
    "user": "<USER>",
    "proxy_jump": ["bastion1"],
    "auth": { "method": "password", "password_env": "ENVB_BASTION2_PASSWORD" }
  },

  "src": {
    "//": "参照元。2 段経由。通常ユーザー（参照用）",
    "host": "<SRC_HOST>",
    "port": 22,
    "user": "<USER>",
    "proxy_jump": ["bastion1", "bastion2"],
    "auth": { "method": "password", "password_env": "ENVB_SRC_PASSWORD" }
  },

  "src_root": {
    "//": "参照元と同一ホストに root で接続。ホスト・経路は src と同じで user だけ替える",
    "host": "<SRC_HOST>",
    "port": 22,
    "user": "root",
    "proxy_jump": ["bastion1", "bastion2"],
    "auth": { "method": "password", "password_env": "ENVB_SRC_ROOT_PASSWORD" }
  },

  "dst": {
    "//": "構築先。踏み台なしで直結。build / 調査用（通常ユーザー）",
    "host": "<DST_HOST>",
    "port": 22,
    "user": "<USER>",
    "auth": { "method": "password", "password_env": "ENVB_DST_PASSWORD" }
  },

  "dst_root": {
    "//": "dst と同一ホストに root で接続。root 権限が要る操作用",
    "host": "<DST_HOST>",
    "port": 22,
    "user": "root",
    "auth": { "method": "password", "password_env": "ENVB_DST_ROOT_PASSWORD" }
  }
}
```

### 認証の指定

- `auth.method` は `"password"` または `"key"`。
- パスワード認証: `password_env` に**環境変数名**を書く。実パスワードは書かない。
- 鍵認証: `key_path` に鍵ファイルのパスを書く（`~` 展開に対応）。
- 同一ホストにユーザー替えの定義を足すときは、`host` と `proxy_jump` を同じにし、
  `user` と認証（`password_env` / `key_path`）だけ替える。

## 初期セットアップの流れ

1. テンプレートから実体を生成する。

   ```powershell
   uv run python scripts/init_config.py
   ```

2. `inventory/servers.json` に実値（host / user / port / proxy_jump / 認証方式）を記入する。
   必要なユーザー替えの定義（`*_root` など）もここで足す。
3. パスワードを環境変数へ設定する。`password_env` で指定した名前と一致させる。
   （このプロジェクトでは機密の環境変数をまとめたスクリプトに集約している。そのスクリプトは
   機密を含むため Git 管理外。）

   ```powershell
   $env:ENVB_BASTION1_PASSWORD = "..."
   $env:ENVB_BASTION2_PASSWORD = "..."
   $env:ENVB_SRC_PASSWORD      = "..."
   $env:ENVB_SRC_ROOT_PASSWORD = "..."
   $env:ENVB_DST_PASSWORD      = "..."
   $env:ENVB_DST_ROOT_PASSWORD = "..."
   ```

4. 疎通を確認する。

   ```powershell
   uv run python scripts/check_connectivity.py
   ```

## 関連

- 実装: `scripts/core/config.py`（inventory 読込）/ `scripts/core/ssh.py`（多段接続）
- 疎通の手順: `.agent/skills/connectivity-check/SKILL.md`
- 鉄則: `.agent/rules/operation-safety.md`（昇格せず必要ユーザーで直接ログイン）
