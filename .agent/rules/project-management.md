# 配下プロジェクト管理

## 目的

`env_builder` は複数の配下プロジェクトについて、参照元(src)と構築先(dst)の接続設定、
あるべき状態、実行ログを分離して扱う。プロジェクトの選択は暗黙に推測せず、
CLIの `--project <id>` または依頼文で明示する。

## 初期設定の入口

- Kiroでは `.kiro/agents/project-initializer.md` を選択し、`.agent/skills/project-initialization/SKILL.md` の手順で壁打ちを行う。
- 初期設定Agentはprojectの選択、要件確認、計画提示、明示承認後の `init_config.py` 呼び出しだけを担当する。
- 初期化後の疎通確認、src調査、build、パッケージ導入、ファイル転送、リモート変更は、別承認後に対応する。
- `init_config.py` は既存ファイルを既定で保持する。`--force` の使用には対象と影響を説明した別承認が必要である。

## プロジェクトプロファイル

- `ProjectRegistry.resolve(project_id)` がプロジェクトの設定ルートを解決する。
- `--project` を省略した場合は、従来のリポジトリ直下の `inventory/`、`desired_state/`、
  `build_env/` を使う（legacy経路）。
- 明示的なプロジェクトは、環境変数 `ENVB_PROJECT_ROOT` の直下、または未設定時の
  リポジトリ直下 `projects/` に配置する。
- project IDは英数字で始まり、英数字・ハイフン・アンダースコアだけを使う。
- プロジェクト実体は次の構成を基本とする。

```text
<project-root>/<project-id>/
├── inventory/servers.json       # 機密。Git管理外
├── desired_state/                # 案件固有の実体。Git管理外
├── build_env/                    # ログ・作業領域。Git管理外
├── AGENTS.md                     # 任意。プロジェクト固有のagent入口
└── .agent/                       # 任意。プロジェクト固有の手順・規約
```

認証情報、鍵、実サーバ値はprofile IDやログに埋め込まない。パスワードは既存どおり
`password_env`で指定した環境変数から取得する。

## CLIの選択

次のCLIはすべて `--project <id>` を受け付ける。

- `init_config.py`
- `check_connectivity.py`
- `probe_src.py`
- `remote_exec.py`
- `run_build.py`
- `apply_packages.py`
- `sync_files.py`
- `sync_tree.py`

`--project`を指定した場合、inventory、desired state、ログ、snapshot、WorkContextの
manifestは選択したprofileから解決する。`--project`なしの既存呼出しはlegacy経路として維持する。

## agent規約の適用

Pythonの実行スクリプトは、プロジェクト固有のMarkdownを命令として自動実行しない。
agentはprojectを選択した後、対象projectの `AGENTS.md` と `.agent/` を存在する範囲で
明示的に読み込み、調査・計画・実装の判断に使う。

適用順序は次の原則とする。

1. システム・開発者・ユーザーの指示
2. env_builderルートの `AGENTS.md` と `.agent/rules/`
3. 選択したprojectの `AGENTS.md` と `.agent/`
4. タスク固有の補助文書・生成文書

project固有規約は上位規約を緩和できない。特に次は変更不可とする。

- sudo / suを使わない
- srcを参照専用として扱う
- 認証情報・OSS・作業成果物をコミットしない
- 破壊的・不可逆な操作は影響を説明し、確認を取る

agentは未選択のprojectディレクトリを横断して規約を読み込まない。project IDと対象パスを
確定してから、必要な文書だけを読み込む。project規約間で矛盾がある場合は、上位規約を優先し、
不明な点を推測で埋めずに確認する。

## 実行コンテキスト

同じtarget名やworkdir名を複数projectで使っても、projectごとのbuild_env配下にログ・作業領域を
置く。ログとmanifestにはproject IDを残し、別projectの作業領域をcleanup対象にしない。

## 検証手順（プロジェクト切替とagent規約読込）

実サーバへ接続せずに再現できる手順。いずれも読み取りまたは `tmp_path` 内の操作だけで完結する。

### 1. 自動テスト

```powershell
uv run --frozen --with paramiko --with pytest python -m pytest -q -p no:cacheprovider tests/test_project.py tests/test_project_context.py tests/test_project_isolation.py
```

確認される内容は次のとおり。

- legacy経路（`--project`省略）が従来のリポジトリ直下パスへ解決される（`test_project.py`）
- 不正・未登録のproject IDが拒否される（`test_project.py`）
- ログ・作業領域・manifestがproject IDで名前空間化される（`test_project_context.py`）
- 2プロジェクトで同じlabelを使ってもパスが重ならない（`test_project_isolation.py`）
- `ProjectProfile`とmanifestが認証情報を保持しない（`test_project_isolation.py`）

### 2. 手動確認（接続なし）

```powershell
$env:ENVB_PROJECT_ROOT = "$env:TEMP\envb-verify"
uv run python scripts/init_config.py --project verify-a
uv run python scripts/init_config.py --project verify-b
```

- `verify-a` と `verify-b` の直下に、それぞれ別の `inventory/servers.json` が作られること（`desired_state/` は案件側で用意する）
- `--project ../x` や `--project ""` を指定すると、ディレクトリを作らずエラー終了すること
- 後始末として `$env:TEMP\envb-verify` を削除し、`ENVB_PROJECT_ROOT` を解除すること

### 3. agent規約の読込確認

agent規約の読込は、Pythonでは自動実行せず、agentが明示的に行う。次を確認する。

1. 依頼文または `--project` でproject IDが確定している
2. 対象projectの `AGENTS.md` と `.agent/` が存在する場合だけ読み込む（無ければ読み込まず、その旨を報告する）
3. 未選択のprojectディレクトリを読み込まない
4. ルート規約と矛盾する場合は、上記「agent規約の適用」の優先順位に従いルート規約を優先する
