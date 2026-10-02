# 配下プロジェクト管理

## 目的

`env_builder` は複数の配下プロジェクトについて、参照元(src)と構築先(dst)の接続設定、
あるべき状態、実行ログを分離して扱う。プロジェクトの選択は暗黙に推測せず、
CLIの `--project <id>` または依頼文で明示する。

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
