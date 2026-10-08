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

4. 初回のみ、接続先のホスト鍵を登録する（次節）。
5. 疎通を確認する。

   ```powershell
   uv run python scripts/check_connectivity.py
   ```

## ホスト鍵の検証（中間者攻撃の対策）

接続先が本物であることを確認するため、**未登録のホスト鍵は既定で拒否**する。踏み台を含む
経路上のすべてのホストが検証対象で、パスワードや鍵による認証は、ホスト鍵の検証が済んだ
後でしか行われない。

- 参照する known_hosts: ユーザーの `~/.ssh/known_hosts`（読み取りのみ）と、env_builder
  専用の `~/.ssh/env_builder_known_hosts`。専用ファイルの場所は環境変数
  `ENVB_KNOWN_HOSTS` で変更できる。
- 未登録のホストへ接続すると、ホスト名とフィンガープリント（`SHA256:...`）を表示して
  接続を拒否する。

### 初回登録の手順

1. 接続先のフィンガープリントを、**ネットワーク経由とは別の信頼できる経路**（サーバ管理者、
   サーバのコンソール、構成管理の記録など）で確認する。
2. 初回の接続だけ、環境変数で登録を許可する。未登録のホストだけが専用ファイルへ登録される。

   ```powershell
   $env:ENVB_HOST_KEY_POLICY = "accept-new"
   uv run python scripts/check_connectivity.py   # 表示された SHA256 が 1 の値と一致するか確認する
   Remove-Item Env:ENVB_HOST_KEY_POLICY            # 登録が済んだら必ず解除する
   ```

3. 以降は既定（`strict`）のまま接続できる。

### 注意

- 登録済みのホストで**鍵が変わっている場合は、`accept-new` でも接続を拒否**する
  （`BadHostKeyException`）。サーバの再構築など正当な理由がある場合だけ、専用ファイルの
  該当行を確認のうえ削除して、再登録する。理由が不明な場合はなりすましの可能性があるため、
  接続を続けない。
- `accept-new` は初回登録のための一時的な設定で、常用しない。確認せずに使うと、初回の
  接続が偽のサーバに向いていても受け入れてしまう。
- 非標準ポートのホストは `[host]:port` の形式で登録される。

## 関連

- 実装: `scripts/core/config.py`（inventory 読込）/ `scripts/core/ssh.py`（多段接続）/
  `scripts/core/host_keys.py`（ホスト鍵の検証）
- 疎通の手順: `.agent/skills/connectivity-check/SKILL.md`
- 鉄則: `.agent/rules/operation-safety.md`（昇格せず必要ユーザーで直接ログイン）
