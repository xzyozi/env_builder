# env_builder

手元PC（Windows / Python）から踏み台越しにSSH接続し、**参照元サーバ(src)を
参考に構築先サーバ(dst)の環境を整える**ための作業基盤。

思想は Ansible 的（宣言的・インベントリ）だが、環境を整える探索フェーズに
合わせて「汎用スクリプト + Agent制御」で実現する。**スクリプトはあくまで
手順の方針**であり、どのスクリプトをどの順で叩くか・出力をどう解釈するかは
すべて Agent が判断する。

## 運用方針（重要）

- **sudo / su は使わない。** root 権限が必要な操作は、root ユーザーで
  ログインするサーバ定義(dst)を使う。
- **src には root で入らない。** src は参照専用で通常ユーザーでログインする。
- **OSS はこのリポジトリに保存しない。** 必要な OSS のバージョンは src で
  コマンドを叩いて確認し、その結果を Agent が解釈して dst にコマンドとして
  投入する。アーカイブの持ち込み・保存はしない。
- **スクリプトは手順の方針。** 実行判断は Agent が行う。

## ディレクトリ構成

```
env_builder/
├── inventory/                  # 接続対象の定義（Ansible のインベントリ相当）
│   ├── servers.sample.json        # テンプレート（.gitignore で除外・コミットしない）
│   └── servers.json               # 実体（.gitignore で除外・機密を含む）
├── desired_state/              # あるべき状態の定義（テンプレはコミットしない）
│   └── *.sample.json              # 参考テンプレート（本来は build 用側で作る）
├── scripts/                    # 手元PCから叩く汎用スクリプト（Python）
│   ├── core/                      # 共通ライブラリ（コミット対象）
│   │   ├── config.py                 # 設定読込（コメント付きJSON対応）
│   │   ├── ssh.py                    # 踏み台越しSSH実行・SFTP転送（昇格なし）
│   │   └── logging_utils.py          # ログ出力
│   ├── init_config.py             # sample から実体ファイルを生成
│   ├── check_connectivity.py      # 疎通確認（whoami/hostname）
│   ├── probe_src.py               # src の現状収集（OSSバージョン等）
│   ├── run_build.py               # dst でコマンド実行 → ログ回収
│   ├── apply_packages.py          # packages 定義に沿って導入（root前提）
│   └── sync_files.py              # 設定ファイルの src→PC→dst 仲介
├── build_env/                  # 作業エリア（成果物・ログは .gitignore）
├── pyproject.toml              # uv で管理（依存: paramiko）
└── .gitignore
```

## 前提

- 手元PC: Windows + Python（uv 管理。TLS 傍受環境のため `native-tls=true`）
- 接続: 手元PC → 踏み台(bastion) → src / dst（踏み台越し = ProxyJump 相当）
- 構築先/参照元とも Linux（RHEL系, dnf）
- dst は root/root でログイン可（確認済み）。src は通常ユーザー（確認済み）

## セットアップ

```powershell
# 1. 依存を導入（uv）
uv sync

# 2. 設定の実体ファイルを生成し、inventory/servers.json に実値を記入
uv run python scripts/init_config.py
#    - host / port / user（dst は root）
#    - 認証方式（password なら password_env、key なら key_path）
#    - proxy_jump（踏み台のキー名）

# 3. パスワードは環境変数へ（コミット・履歴に残さない）
$env:ENVB_BASTION_PASSWORD = "..."
$env:ENVB_SRC_PASSWORD     = "..."
$env:ENVB_DST_PASSWORD     = "..."
```

## まず疎通確認

```powershell
# 踏み台越しに src / dst へ接続できるか確認する
uv run python scripts/check_connectivity.py

# 個別に確認する場合
uv run python scripts/check_connectivity.py --target dst
```

## Git 方針

- **共通部分（scripts/core と汎用スクリプト）のみコミット**する。
- `*.sample.json` と機密を含む実体（`servers.json`）、作業成果物
  （`build_env/logs` 等）、`.kiro/` は `.gitignore` で除外。
- パスワードは設定ファイルに書かず、環境変数（`password_env`）で渡す。

## セキュリティ

- 認証情報はコミットしない・コマンドラインに直書きしない。
- `check_connectivity.py` / `probe_src.py` は読み取り専用コマンドのみ実行する。
- パッケージ導入は uv の cooldown（グローバル `exclude-newer`）を前提とする。
