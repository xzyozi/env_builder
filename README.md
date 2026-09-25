# env_builder

手元PC（Windows / Python）から踏み台越しにSSH接続し、**参照元サーバ(src)を
参考に構築先サーバ(dst)の環境を整えて build を通す**ための作業基盤。

思想は Ansible 的（宣言的・冪等・インベントリ）だが、build を通す探索フェーズに
合わせて「汎用スクリプト + Agent制御」で実現する。環境が固まったら、その結果を
一般化して agent 化・再現可能化していく。

## ディレクトリ構成

```
env_builder/
├── inventory/                  # 接続対象の定義（Ansible のインベントリ相当）
│   ├── servers.sample.json        # テンプレート（コミット対象）
│   └── servers.json               # 実体（.gitignore で除外・機密を含む）
├── desired_state/              # あるべき状態（Ansible の Playbook/role 相当）
│   ├── packages.sample.json       # 導入すべき OSS パッケージ
│   ├── files.sample.json          # 配置すべき設定ファイルの対応表
│   └── build_targets.sample.json  # build コマンドと作業ディレクトリの定義
├── scripts/                    # 手元PCから叩く汎用スクリプト（Python）
│   ├── core/                      # 共通ライブラリ（コミット対象）
│   │   ├── config.py                 # 設定読込（コメント付きJSON対応）
│   │   ├── ssh.py                    # 踏み台越しSSH実行・SFTP転送
│   │   └── logging_utils.py          # ログ出力
│   ├── init_config.py             # .sample から実体ファイルを生成
│   ├── probe_src.py               # src の現状収集（パッケージ一覧等）
│   ├── run_build.py               # dst で build 実行 → ログ回収
│   ├── apply_packages.py          # packages.json を冪等に適用
│   └── sync_files.py              # download→upload 仲介（src→PC→dst）
├── build_env/                  # 作業エリア（成果物・ログは .gitignore）
│   ├── logs/                      # build/実行ログ
│   ├── src_snapshot/              # src から取得した参考情報
│   └── artifacts/                 # ネットから落とした OSS 等の持ち込み物
├── pyproject.toml              # uv で管理（依存: paramiko）
└── .gitignore
```

## 前提

- 手元PC: Windows + Python（uv 管理）
- 接続: 手元PC → 踏み台(bastion) → src / dst（踏み台越し = ProxyJump 相当）
- 構築先/参照元とも Linux（RHEL系, dnf）
- インターネット利用可

## セットアップ

```powershell
# 1. 依存を導入（uv）
uv sync

# 2. 設定の実体ファイルを生成
uv run python scripts/init_config.py

# 3. inventory/servers.json に実値を記入
#    - host / user / port
#    - 認証方式（key なら key_path、password なら password_env）
#    - proxy_jump（踏み台のキー名）
#    - build 用ユーザーへ切替が必要なら become_user

# 4. パスワード認証を使う場合は環境変数へ（例）
$env:ENVB_BASTION_PASSWORD = "..."   # 実運用ではコミット・履歴に残さない
```

## 使い方（build を通すループ）

```powershell
# src の現状を収集（何が入っているか把握）
uv run python scripts/probe_src.py

# dst で build を実行（desired_state/build_targets.json に従う）
uv run python scripts/run_build.py

# 不足パッケージを確認（dry-run）
uv run python scripts/apply_packages.py --check

# 不足パッケージを適用
uv run python scripts/apply_packages.py

# src の設定ファイルを dst へ配置（files.json に従う）
uv run python scripts/sync_files.py

# 再 build。エラーが消えるまで繰り返す
uv run python scripts/run_build.py
```

## Git 方針

- **共通部分のみコミット**する。`*.sample.json` はコミット対象。
- 機密を含む実体（`servers.json` 等）と作業成果物（`build_env/logs` 等）は
  `.gitignore` で除外。
- パスワードは設定ファイルに書かず、環境変数（`password_env`）で渡す。

## セキュリティ

- 認証情報はコミットしない・コマンドラインに直書きしない。
- `probe_src.py` は読み取り専用コマンドのみ実行する。
- パッケージ導入は uv の cooldown（グローバル `exclude-newer`）を前提とする。
