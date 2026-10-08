# env_builder

手元PC（Windows / Python）から踏み台越しにSSH接続し、**参照元サーバ(src)を
参考に構築先サーバ(dst)の環境を整える**ための作業基盤。

思想は Ansible 的（宣言的・インベントリ）だが、環境を整える探索フェーズに
合わせて「汎用スクリプト + Agent制御」で実現する。**スクリプトはあくまで
手順の方針**であり、どのスクリプトをどの順で叩くか・出力をどう解釈するかは
すべて Agent が判断する。

## 運用方針（重要）

- **sudo / su は使わない。** root 権限が必要な操作は、必要なユーザーで直接ログインする
  サーバ定義（例: `dst_root`）を使う。
- **src は原則参照専用。** 通常ユーザーで読み取り専用操作を行う。root権限が必要な参照・
  確認だけは `src_root` のようなroot定義で接続できるが、理由を明示し状態は変更しない。
- **OSS はこのリポジトリに保存しない。** 必要な OSS のバージョンは src でコマンドを
  叩いて確認し、その結果を Agent が解釈して dst にコマンドとして投入する。
- **一時ファイルは作業領域に隔離する。** ローカル中継は `build_env/work/<work-id>/`、
  リモート中継は `/tmp/env_builder-<work-id>-XXXXXX/` 配下に限定し、作業終了時に専用
  ディレクトリごと削除する。`/home/<user>` 直下や `/tmp` 直下の固定名は使わない。
- **スクリプトは手順の方針。** 実行判断は Agent が行う。

## ディレクトリ構成

```
env_builder/
├── docs/                       # プロジェクト仕様・タスク資産（Second Brain OS 連携）
│   ├── project.json               # プロジェクト固有設定（base_branch等）
│   ├── tasks.md                   # タスク一覧・進行状況
│   └── issues/                    # Issue 単位の詳細仕様
├── inventory/                  # 接続対象の定義（Ansible のインベントリ相当）
│   ├── servers.sample.json     # 機密なしの接続テンプレート（追跡対象）
│   └── servers.json            # 実体（.gitignoreで除外・機密を含む）
├── desired_state/              # あるべき状態の定義（Git管理外）
│   └── *.local.json             # 環境固有の実体（Git管理外）
├── env_builder/                # 実装本体（Python パッケージ）。import は env_builder.* の1系統だけ
│   ├── __main__.py             # python -m env_builder <command> の入口
│   ├── cli/                    # コマンド（引数解析・表示・終了コードだけ。1コマンド1ファイル）
│   │   ├── __init__.py         # コマンド名とモジュールの対応表、振り分け
│   │   ├── _common.py          # 共通引数（--project）
│   │   ├── init_config.py      # sample から実体ファイルを生成
│   │   ├── check_connectivity.py  # 疎通確認（whoami/hostname）
│   │   ├── probe_src.py        # src の現状収集（OSSバージョン等）
│   │   ├── remote_exec.py      # 任意コマンドによる調査
│   │   ├── container.py        # container解析・image計画・run候補
│   │   ├── run_build.py        # dst でコマンド実行 → ログ回収
│   │   ├── apply_packages.py   # packages 定義に沿って導入（root前提）
│   │   ├── sync_files.py       # 設定ファイルの src→PC→dst 仲介
│   │   └── sync_tree.py        # ディレクトリの src→PC→dst 仲介
│   ├── core/                   # 共通ライブラリ（判断は持たない）
│   │   ├── config.py           # 設定読込（コメント付きJSON対応）
│   │   ├── project.py          # プロジェクトプロファイルの解決
│   │   ├── ssh.py              # 踏み台越しSSH実行・SFTP転送（昇格なし）
│   │   ├── host_keys.py        # SSHホスト鍵の検証
│   │   ├── shell.py            # リモートシェルへ渡す値のクォート・検証
│   │   ├── work_context.py     # 作業ID・一時領域・cleanup・manifest
│   │   ├── logging_utils.py    # ログ出力
│   │   └── container/          # containerモデル・inspect正規化・engine adapter
│   └── ops/                    # SSHを伴う上位処理
│       └── container.py        # container inspect・image移送
├── scripts/                    # 互換ラッパー（従来の scripts/<name>.py を使い続けるため）
│   └── <command>.py            # env_builder.cli.<command>.main を呼ぶだけ。sys.path を操作するのはここだけ
├── tests/                      # pytest（env_builder.* を import してテストする）
├── build_env/                  # 作業エリア（成果物・ログは .gitignore）
│   ├── work/<work-id>/         # 実行中だけ存在する一時中継領域
│   ├── logs/                   # 実行ログ・manifest（明示的に保持）
│   └── artifacts/              # 明示的に保持する手順・資料・取得物
├── .github/                    # GitHub Actions（CI 等）
│   └── workflows/
│       └── ci.yml              # PR で ruff / mypy / pytest を実行
├── pyproject.toml              # uv で管理（依存: paramiko、dev: ruff/mypy/pytest）
└── .gitignore
```

## コマンドの実行方法

コマンドは `env_builder` パッケージとして実装されています。リポジトリ直下で、次の形で実行します。

```powershell
uv run python -m env_builder <command> [args...]
uv run python -m env_builder --help           # コマンド一覧
uv run python -m env_builder remote_exec --target dst -- "hostname"
```

コマンド名は `remote_exec` でも `remote-exec` でも指定できます。従来の
`uv run python scripts/<command>.py [args...]` も互換ラッパーとして残してあり、同じ動作をします
（引数・既定値・終了コード・ログの出力先は変わりません）。以降の文書の実行例は、どちらの形でも
読み替えられます。

| コマンド                   | 内容                                       |
| -------------------------- | ------------------------------------------ |
| `init_config`              | sample から inventory の実体ファイルを生成 |
| `check_connectivity`       | 踏み台越しの SSH 疎通確認                  |
| `probe_src`                | src の現状収集                             |
| `remote_exec`              | 任意サーバで単発コマンドを実行             |
| `run_build`                | dst で build を実行しログを回収            |
| `apply_packages`           | packages 定義に沿って導入                  |
| `sync_files` / `sync_tree` | ファイル・ディレクトリの仲介転送           |
| `container`                | コンテナ解析・image 移送計画・run 候補     |

## 前提

- 手元PC: Windows + Python（uv 管理。TLS 傍受環境のため `native-tls=true`）
- 接続: 手元PC → 踏み台(bastion) → src / dst（踏み台越し = ProxyJump 相当）
- 構築先/参照元とも Linux（RHEL系, dnf）
- dst は通常ユーザー・rootの別定義でログインできる。srcも通常ユーザー・rootの別定義を
  作成できるが、通常は参照専用の通常ユーザー定義を使う。

## セットアップ

```powershell
# 1. 依存を導入（uv）
uv sync

# 2. 設定の実体ファイルを生成し、inventory/servers.json に実値を記入
uv run python -m env_builder init_config
#    - host / port / user（必要に応じて *_root 定義も作成）
#    - 認証方式（password なら password_env、key なら key_path）
#    - proxy_jump（踏み台のキー名）

# 3. パスワードは環境変数へ（コミット・履歴に残さない）
$env:ENVB_BASTION_PASSWORD = "..."
$env:ENVB_SRC_PASSWORD     = "..."
$env:ENVB_DST_PASSWORD     = "..."
```

接続先のホスト鍵は、初回のみ登録が必要です（未登録の鍵は拒否されます）。フィンガープリントを
別の経路で確認したうえで、初回だけ `ENVB_HOST_KEY_POLICY=accept-new` を設定して接続し、
登録後は解除してください。詳細は `.agent/references/connection.md` を参照してください。

## 複数プロジェクトの管理

複数の配下プロジェクトを扱う場合は、プロジェクトごとにinventory、desired state、ログを分離し、
すべてのCLIへ `--project <id>` を指定します。プロジェクト設定ルートは環境変数で指定できます。

```powershell
$env:ENVB_PROJECT_ROOT = "C:\env_builder-projects"
uv run python scripts/init_config.py --project project-a
uv run python scripts/check_connectivity.py --project project-a
uv run python scripts/probe_src.py --project project-a --target src
uv run python scripts/run_build.py --project project-a --target main
```

各プロジェクトは次の構成を基本とします。`inventory/servers.json`、`desired_state/`、
`build_env/`は機密・環境固有値・作業成果物を含むためGit管理外に置きます。

```text
<ENVB_PROJECT_ROOT>/project-a/
├── inventory/servers.json
├── desired_state/
├── build_env/
├── AGENTS.md       # 任意のプロジェクト固有agent入口
└── .agent/         # 任意のプロジェクト固有規約
```

プロジェクトを指定しない既存コマンドは、従来どおりリポジトリ直下の設定を使います。
プロファイルの選択・agent規約の適用順序・安全境界は `.agent/rules/project-management.md` を参照してください。

## コンテナ解析・image移送

コンテナ機能は、プロジェクト設定でengineと使用imageを決めてから実行します。DockerとPodmanの
相互変換は初期対象外で、同じengine間だけを扱います。

- Podman → Podman
- Docker → Docker

プロジェクトの`desired_state/container.local.json`に、実行engine、image、移送元・移送先の
inventory target、参照containerを定義します。このファイルは`desired_state/`配下のためGit管理外です。

```json
{
  "engine": "podman",
  "image": "registry.example/app:stable",
  "source_target": "src",
  "destination_target": "dst",
  "container": "app",
  "transfer_mode": "export",
  "secret_env_prefix": "ENVB_CONTAINER_"
}
```

通常は移送元を変更しない`export/import`を使います。高い再現性が必要な場合だけ、設定の
`transfer_mode`を`commit`に変更し、明示承認後に`commit`と`save/load`を実行します。元imageの
履歴やDockerfileの完全復元は保証しません。

```powershell
# 読み取り解析、image移送計画、run候補の表示
uv run python scripts/container.py --project project-a

# 計画を確認し、承認済みのimage移送を実行（runは実行しない）
uv run python scripts/container.py --project project-a --execute-image --approve-image
```

解析結果は`build_env/logs/<project-id>/container_plan_<timestamp>/container-plan.json`に保存され、
人間向けの`podman run` / `docker run`候補、機械可読JSON、image移送計画、警告を出力します。
run候補は自動実行されません。bind mountの通常ファイル・ディレクトリは、desired stateに明示した
場合だけ既存の`sync_files.py` / `sync_tree.py`で扱います。volume、secret、device/GPU、networkは
自動移送せず、要確認事項として出力します。

image移送は承認後に実行されますが、失敗時も既存imageを自動削除しません。archiveと専用作業領域は
cleanupし、作成済みimageのID・digest・状態はmanifestへ記録します。rootless/rootfulを自動で
切り替えず、実行ユーザーとUID/GIDの差異は計画へ警告します。

## 初期設定Agentで始める

Kiroでは、Agent一覧から `project-initializer` を選択するか、依頼時に
`# project-initializer` を指定して初期設定の壁打ちを開始します。初期設定の手順本体は
`.agent/skills/project-initialization/SKILL.md` にあり、Kiro以外のツールからも参照できます。

Agentは次の順で進めます。

1. legacy経路か明示projectか、project ID、設定ルート、接続対象、認証方式、次工程を確認する。
2. 変更を行わず、生成先・既存ファイルの扱い・実行予定コマンド・未確定事項を計画として示す。
3. ユーザーの明示承認後に、既存ファイルを保持する設定で `scripts/init_config.py` を実行する。
4. ユーザーが `inventory/servers.json` と環境変数、必要な `desired_state` を設定する。
5. 別の承認後に対象を限定した疎通確認を行い、必要なら `env-provisioning` へ引き渡す。

初期設定Agentは、パスワードや秘密鍵の実値を扱いません。また、初期化後に疎通確認、
build、パッケージ導入、ファイル転送、リモート変更を自動開始しません。既存ファイルを
上書きする `--force` は、影響と復元方法を確認した別承認がある場合だけ使用します。

## まず疎通確認

```powershell
# 踏み台越しに src / dst へ接続できるか確認する
uv run python scripts/check_connectivity.py

# 個別に確認する場合
uv run python scripts/check_connectivity.py --target dst
```

## 開発（Lint / 型チェック / テスト）

lint・整形・型チェックの設定は `pyproject.toml` に定義している。開発ツールは
`dev` extra（ruff / mypy / pytest）としてまとめており、次で導入する。

```powershell
# dev 依存を含めて同期
uv sync --extra dev
```

ローカルでの実行方法（CI と同じチェック）:

```powershell
# Lint（pycodestyle / Pyflakes / import 整列）
uv run ruff check .

# 整形チェック（差分があれば失敗）。自動整形は uv run ruff format .
uv run ruff format --check .

# 型チェック
uv run mypy .

# テスト（tests/ 配下に test_*.py があれば）
uv run pytest
```

### CI（GitHub Actions）

`.github/workflows/ci.yml` が **main / develop 宛の Pull Request** で起動し、
上記の ruff（lint / 整形チェック）・mypy・pytest を順に実行する。PR を作成すると
自動でチェックが走り、いずれかが失敗すると PR 上でエラーになる。ローカルで
`uv run ruff check .` と `uv run ruff format --check .` を通してから push すると、
CI の失敗を事前に防げる。

## Git 方針

- **共通部分（`env_builder/` パッケージ、`scripts/` の互換ラッパー、テスト）のみコミット**する。
- `inventory/servers.sample.json` は機密なしのため追跡する。機密を含む実体（`servers.json`）、
  `desired_state/`、作業成果物（`build_env/` 等）は `.gitignore` で除外する。
- パスワードは設定ファイルに書かず、環境変数（`password_env`）で渡す。

## セキュリティ

- 認証情報はコミットしない・コマンドラインに直書きしない。
- SSH のホスト鍵は検証し、未登録の鍵は既定で拒否する。初回のみ環境変数
  `ENVB_HOST_KEY_POLICY=accept-new` で登録を許可し、登録後は解除する。手順と注意は
  `.agent/references/connection.md` の「ホスト鍵の検証」を参照する。
- `check_connectivity.py` / `probe_src.py` は読み取り専用コマンドのみ実行する。
- `/home/<user>` 直下を作業領域にしない。リモート一時物は専用 `/tmp/env_builder-<work-id>-XXXXXX/`
  配下に置き、作業終了時にcleanupする。`/tmp` のOS側自動削除は異常終了時のfallbackとする。
- `desired_state` で明示された永続配置先（ビルド成果物、ライブラリ配置等）は一時cleanupの
  対象にしない。
- パッケージ導入は uv の cooldown（グローバル `exclude-newer`）を前提とする。

## env_builder/core の使い方

`env_builder/core` は、コマンド（`env_builder/cli/`）が共通で使うライブラリ。責務は
**設定読込・SSH実行・ファイル転送・作業領域・ログ出力** に限定し、build ロジックや冪等判定と
いった判断は持たない。containerの純粋なモデル・inspect正規化・run候補生成もここに置き、
SSHを伴うcontainer処理は`env_builder/ops`へ分離する。実行判断（どのコマンドをどの順で流すか、
出力をどう解釈するか）は呼び出し側の責務。

公開シンボル（`env_builder/core/__init__.py` で re-export）:

- 設定: `load_inventory`, `Inventory`, `ServerSpec`
- プロジェクト: `ProjectRegistry`, `ProjectProfile`
- SSH: `SSHSession`, `SSHResult`
- 作業領域: `WorkContext`
- ログ: `get_logger`, `new_run_dir`

### 基本形

新しいコマンドやスクリプトは、`env_builder` を通常の Python パッケージとして import する。
`sys.path` を操作する必要はない（`sys.path` を触るのは `scripts/` の互換ラッパーだけ）。
リポジトリ直下から `python -m env_builder ...` で実行するか、`tests/` のように
リポジトリルートが `sys.path` に入っている環境で import する。

```python
from env_builder.core.config import load_inventory
from env_builder.core.logging_utils import get_logger
from env_builder.core.ssh import SSHSession

logger = get_logger()
inv = load_inventory()  # inventory/servers.json を読む

with SSHSession(inv, "dst") as ssh:  # 踏み台があれば自動で多段接続
    res = ssh.run("hostname; whoami", timeout=120)

print(res.stdout)
logger.info("exit=%d", res.exit_code)
```

### 1. config（設定読込）

- `load_inventory()` … `inventory/servers.json` を読み `Inventory` を返す。
  ファイルが無ければ「init_config で生成せよ」という明確なエラーを出す。
- コメント付き JSON 対応 … キー名が `//` で始まる要素は再帰的に無視される
  （設定ファイルの注記用）。
- `Inventory.get(name)` … 対象サーバの `ServerSpec` を取得。未定義なら
  定義済み一覧つきで `KeyError`。
- 認証は環境変数経由 … `AuthSpec.resolve_password()` が `password_env` で
  指定した環境変数から実値を取得する。パスワードは設定ファイルに書かない。
  鍵認証は `resolve_key_path()`。
- `proxy_jump` … 文字列（単一）でもリスト（多段）でも受け付け、内部でリスト化。
  近い踏み台から順に並べる（例 `['gateway', 'host']`）。

### 2. ssh（踏み台越し実行・ファイル転送）

- `SSHSession(inventory, target)` を `with` で使う。`__enter__` で `proxy_jump`
  を近い踏み台から順に張り、各段のチャネルを次段へ引き渡して多段接続する
  （OpenSSH の ProxyJump 相当）。`__exit__` で接続と逆順にクローズ。
- `ssh.run(command, timeout=600)` → `SSHResult(exit_code, stdout, stderr, status)`。
  `status` は `completed` / `timeout` / `interrupted`。`res.ok` は
  `status == "completed"` かつ `exit_code == 0` のときだけ真になる。
  stdout / stderr は同時に排出し、`timeout` はコマンド全体の上限秒（壁時計）。Ctrl+C は
  `SSHInterrupted` として送出し、途中までの出力を `.result` に持つ。timeout / 中断でも
  リモートのプロセスが停止するとは限らない（`.agent/references/scripts.md` を参照）。
- ホスト鍵 … 未登録のホスト鍵は既定で拒否する（`env_builder/core/host_keys.py`）。
- 昇格しない … sudo/su は使わない。root が必要なら root ログインのサーバ定義
  を使う。
- ノイズ除去 … ログインシェル由来の `logout`（stdout）と
  `tset: terminal attributes`（stderr）だけを行単位で除去し、正規の出力は残す。
- keepalive … 全 transport に 30 秒間隔の keepalive を設定。無音が続く長時間
  処理（`make` 等）でも切断を防ぐ。
- ファイル転送 … `ssh.get_file(remote, local)`（download）/
  `ssh.put_file(local, remote)`（upload）。内部で SFTP を開閉する。

### 3. work_context（作業領域・cleanup）

- `WorkContext("sync-tree")` のように使い、作業IDを発行する。
- ローカルの一時中継は `build_env/work/<work-id>/stage/` に作る。
- `create_remote_workspace()` はリモートの `/tmp` 直下に `mktemp -d` で専用領域を作り、
  markerを記録する。
- `cleanup_remote_workspace()` は作業IDに対応するmarker、prefix、`/tmp` 直下であることを
  検証してから専用ディレクトリを削除する。
- `complete()` を呼ばずに終了した場合も、作業は失敗扱いとしてローカル一時領域をcleanupする。
- manifestは `build_env/logs/work_<work-id>/manifest.json` に残る。cleanup結果や失敗状態を
  確認できるが、認証情報や実行コマンド全文は保存しない。

### 4. logging_utils（ログ）

- `get_logger(name="env_builder", logfile=None)` … コンソール（stdout）へ
  INFO 以上を出す。`logfile` を渡すと DEBUG 以上をファイルにも出す。同名ロガーは
  使い回して二重登録を防ぐ。stderr でなく stdout に出すのは、PowerShell 経由で
  stderr が `NativeCommandError` 扱いになり見えにくいのを避けるため。
- `new_run_dir(label="run")` … 実行ごとのログ用ディレクトリを作って返す。

### 注意点

- `core` はライブラリであり単体では動かない。CLI として叩くのは
  `env_builder/cli/` のコマンド（`python -m env_builder <command>`）。
- 新しいコマンドは `env_builder/cli/<name>.py` に `main(argv=None) -> int` として追加し、
  `env_builder/cli/__init__.py` の `COMMANDS` に登録する。`scripts/<name>.py` の互換ラッパーも
  1本追加する（`tests/test_entrypoints.py` が、表とラッパーの対応を検査する）。
  実行判断は呼び出し側が持つ。
- パスは `config.py` の `REPO_ROOT`（`env_builder/core/config.py` から2つ上）起点で
  解決される。
