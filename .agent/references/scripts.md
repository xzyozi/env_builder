# スクリプトリファレンス

`scripts/` 配下の汎用スクリプトの説明。**スクリプトは手順の方針**であり、どれをどの順で
叩き、出力をどう解釈するかはエージェントが判断する。ここは「各スクリプトが何をする道具か」
「どこまでがスクリプトの責務で、どこからがエージェントの判断か」を言語化したもの。

すべて `uv run python scripts/<name>.py ...` で実行する。接続対象は `inventory/servers.json`
の**キー名**（`src` / `dst` / `dst_root` / `bastion` など）で指定する。

## ProjectProfile / --project

複数の配下プロジェクトを扱う場合は、各CLIに `--project <id>` を指定する。`ProjectRegistry` が
project IDを検証し、選択したprofileの `inventory/servers.json`、`desired_state/`、`build_env/` を
解決する。プロジェクト設定ルートは `ENVB_PROJECT_ROOT` で指定し、未指定時はリポジトリ直下の
`projects/` を使う。`--project` を省略した場合は従来のリポジトリ直下設定を使う。

```powershell
$env:ENVB_PROJECT_ROOT = "C:\env_builder-projects"
uv run python scripts/init_config.py --project project-a
uv run python scripts/check_connectivity.py --project project-a
uv run python scripts/run_build.py --project project-a --target main
```

プロジェクト固有のagent規約はPythonスクリプトが自動解釈せず、agentがproject選択後に
`AGENTS.md`／`.agent/`を明示的に読み込む。適用範囲と安全規則は
`.agent/rules/project-management.md`を参照する。

## 初期設定Agent

Kiroでは `.kiro/agents/project-initializer.md` を選択し、初期設定の壁打ちを開始する。
ツール非依存の手順は `.agent/skills/project-initialization/SKILL.md` にある。

初期設定Agentの責務は、legacy/projectの選択、project ID・設定ルート・接続対象の確認、
生成計画の提示、明示承認後の `init_config.py` 呼び出し、初期化後の引き渡しである。
`init_config.py` はサンプルから実体をコピーする機械的処理、`ProjectRegistry` はID検証と
profile解決を担当する。Agentはこれらの処理を再実装しない。

初期設定Agentは、既存ファイルを既定で上書きせず、`--force` を自動選択しない。また、
初期化後のSSH疎通、src調査、build、パッケージ導入、ファイル転送、リモート変更は
自動開始せず、別承認後に対応する。

## スクリプト vs エージェントの境界

- **スクリプトに置く**（機械的処理・再現性）: SSH 多段接続、tar 中継転送、rpm 冪等判定、
  ログ保存、出力の定型パターン検出、専用一時領域の作成とcleanup。引数を変えれば別状況でも
  使い回せるもの。
- **エージェントが判断する**（解釈・順序・意思決定）: どのターゲットを先に処理するか、
  失敗ログのどのマーカーで何を疑うか、次にどのスクリプトをどの引数で叩くか、収集結果を
  どう次の一手に反映するか。
- 迷ったら: 「引数を変えれば使い回せる」ならスクリプト、「状況を読んで決める」ならエージェント。

## 作業コンテキスト（WorkContext）

`scripts/core/work_context.py` が1回の転送作業に作業IDと一時領域を割り当てる。

- ローカル中継: `build_env/work/<work-id>/stage/`
- リモート中継: `/tmp/env_builder-<work-id>-XXXXXX/`（各接続先で生成）
- 作業記録: `build_env/logs/work_<work-id>/manifest.json`
- cleanup: 作業成功・失敗・例外にかかわらず、専用作業領域だけを削除する。
- `keep_workdir=True` は失敗調査など、明示的に保持するときだけ利用する。
- `/home/<user>` 直下、`/tmp` 直下の固定名、`desired_state` の永続配置は作業領域にしない。

manifestには作業ID、対象、状態、cleanup結果を記録する。認証情報や実行コマンド全文は記録しない。
OSによる `/tmp` の定期削除は、強制終了時に残った領域へのfallbackであり、通常のcleanupの代替ではない。

---

## init_config.py — 設定の実体ファイル生成

- **用途**: `*.sample.json` から実体ファイル（`inventory/servers.json`）を生成する。
- **主な引数**: `--force`（既存の実体を上書き）。
- **メモ**: 生成後に実値（ホスト・ユーザー等）を記入し、パスワードは `password_env` で
  指定した環境変数に設定する。既存実体は既定で上書きしない。

## check_connectivity.py — 疎通確認

- **用途**: 踏み台越しに各サーバへ SSH し、`whoami` / `hostname` が通るか確認する。
  build 作業に入る前段の「接続が取れること」の検証。
- **主な引数**: `--target <key>`（未指定なら bastion 以外の全サーバ）。
- **読み取り専用**。昇格しない。エージェントは NG が出たターゲットについて、認証・到達性・
  proxy_jump のどれが原因かを切り分ける。

## probe_src.py — src の現状収集

- **用途**: src の現状（`os-release` / `uname` / `rpm -qa` / `dnf repolist`）を収集し、
  `build_env/src_snapshot/<target>/` に保存する。「src では何が入っているか」を dst で
  再現する際の参照材料。
- **主な引数**: `--target src`。
- **読み取り専用**。エージェントは収集結果を読み、dst に不足しているパッケージ/バージョンを
  判断して次の手（apply_packages や sync）につなげる。

## remote_exec.py — 単発コマンド実行（調査の主力）

- **用途**: 任意サーバで**任意の単発コマンド**を実行し、結果を表示・保存する汎用調査ツール。
  build 前後の調査（ディレクトリ構成の確認、Makefile の中身確認、依存の追跡、`logout`
  出力の原因調査など）に使う中心的な道具。
- **主な引数**:
  - `--target <key>`（既定 `dst`）。root が必要な調査は `--target dst_root`。
  - `--save`（出力を `build_env/logs/exec_<target>_<timestamp>/` に保存）。
  - `--timeout <sec>`（既定 120）。
  - `-- "<command>"`（`--` の後に実行コマンド。複数語はまとめて渡される）。
- **使用例**:

  ```powershell
  # dst のディレクトリを確認
  uv run python scripts/remote_exec.py --target dst -- "ls -la /home/seigyo/neo_app/src/libscl"

  # Makefile を確認しつつログ保存
  uv run python scripts/remote_exec.py --target dst --save -- "cat Makefile"

  # root 権限が要る領域を確認
  uv run python scripts/remote_exec.py --target dst_root -- "ls -ld /opt/mel/modern/lib64"
  ```

- **タイムアウトと中断**:
  - `--timeout` はコマンド全体の上限秒（壁時計）。超過すると、それまでの出力を表示し、
    終了コード 124 で戻る。Ctrl+C の場合は、途中までの出力を表示・保存し、終了コード 130 で戻る。
  - stdout と stderr は同時に排出するため、片方が大量に出力されても詰まらない。
  - **リモートのプロセスが停止することは保証しない。** timeout / Ctrl+C でローカルは
    SSH チャネルを閉じるが、pty を使わない実行では、リモートのコマンドが走り続けることがある。
    確実に止めたい長時間コマンドは、リモート側で `timeout 600 <cmd>` のように包む。
    中断・タイムアウトの後は、`ps` などでリモートに残っていないかを確認する。
  - リモートが本当に 124 を返した場合と区別するには、ログの `status=`（completed /
    timeout / interrupted）を見る。
- **エージェントの判断ポイント**:
  - **コマンドの組み立てはエージェントの責務**。何を確認すれば次の一手が決まるかを考えて
    コマンドを作る。読み取り系（`ls` / `cat` / `rpm -q` / `find` など）を基本とする。
  - src に対して使うときは**読み取り専用に限定**する（operation-safety 準拠）。
  - 状態を変える操作（インストール・削除・展開）は、専用スクリプト（apply_packages /
    sync_tree 等）があるならそちらを優先する。remote_exec での状態変更は影響を確認してから。
  - `remote_exec.py` は任意コマンドを実行するため、任意コマンドが作ったファイルを推測して
    自動削除しない。作業ファイルを作る調査では、コマンド側で `/tmp/env_builder-<work-id>/`
    などの専用領域を使い、処理後にその領域を明示的に削除する。
  - 終了コードだけでなく stdout/stderr の中身を読んで解釈する。`--save` した出力は後の
    調査・比較に使える。

## sync_files.py — ファイル単位の仲介転送

- **用途**: `desired_state/files.json` の対応表に従い、src から設定ファイルを取得して
  dst へ配置する（src→手元PC→dst の中継）。踏み台越しでも両サーバ間の直接到達性が
  なくても運べる。
- **主な引数**:
  - 既定: `files.json` に従い `--src src --dst dst`。
  - `--upload-only <LOCAL> <REMOTE>`（download をスキップし、手元のファイルを dst へ送るだけ）。
- **中継物**: `build_env/work/<work-id>/stage/file_NNN` に作成し、作業終了時に作業ディレクトリごと削除。
  失敗時もcleanupする。`--upload-only` の入力ファイルと `dst_path` の永続配置先は削除しない。
- **メモ**: `files.json` に `mode` があれば `chmod` し、失敗時は転送全体を失敗扱いにする。root
  配置先へは `--dst` に root 定義を指定する。

## sync_tree.py — ディレクトリ丸ごとの中継転送

- **用途**: ディレクトリツリーを src→手元PC→dst と **tar.gz 経由**で確実に運ぶ。
  「ファイルが無いので src から取得して dst に配置する」用途の中核。SFTP 再帰転送より
  速く安定する。
- **主な引数**:
  - `--src src` / `--dst dst_root`（root 配置先なら root 定義）。
  - `--remote-src <src上の絶対パス>`（取得対象ディレクトリ）。
  - `--remote-dst-parent <dst上の親ディレクトリ>`（ここに対象名で展開される）。
  - `--timeout <sec>`（既定 600）。
- **使用例**:

  ```powershell
  uv run python scripts/sync_tree.py --src src --dst dst_root `
    --remote-src /opt/mel/modern/lib64/version_mng `
    --remote-dst-parent /opt/mel/modern/lib64
  ```

- **中継物**: src/dstの一時tarは各接続先の `/tmp/env_builder-<work-id>-XXXXXX/`、
  ローカルtarは `build_env/work/<work-id>/stage/tree.tar.gz` に置く。成功・失敗・例外時に
  専用作業ディレクトリをcleanupし、固定名の `/tmp` ファイルやHOME直下を使わない。
- **永続配置**: `--remote-dst-parent` 以下への展開物はcleanupしない。
- **安全性**: リモートパスをshellへ渡す際はquoteし、作業領域はmarker・パス形式を検証して削除する。

## apply_packages.py — パッケージの冪等適用

- **用途**: `desired_state/packages.json` に従い、dst へ OSS パッケージを冪等に適用する
  （Ansible の package タスク相当）。導入済みはスキップ。
- **主な引数**:
  - `--target dst`（root ログイン前提。昇格しない）。
  - `--check`（dry-run。不足分の表示のみ）。
- **エージェントの判断ポイント**: まず `--check` で差分を確認し、probe_src の結果と
  突き合わせて本当に必要なものだけ適用する。`package_manager` は既定 `dnf`。
- **入力の検証**: リモートへ何も送る前に、パッケージ名とパッケージマネージャ名を検証する。
  パッケージ名は英数字と `. _ + : @ -` だけ（先頭は `-` 不可）、パッケージマネージャは
  英数字と `_ -` だけで、パスや引数は指定できない。違反があると、エラーを表示して終了コード 1
  で止まる。`rpm -q` と `install` に渡す名前は、すべてクォートされる。

## run_build.py — dst でのビルド実行とログ回収

- **用途**: `desired_state/build_targets.local.json`（Git 管理外）の定義に従い、dst の
  作業ディレクトリでビルドコマンドを順に実行し、`build_env/logs/build_<name>_<ts>/` に
  stdout/stderr と終了コードを保存する。
- **主な引数**: `--target <name>`（build_targets の name。未指定なら先頭）。
- **重要な挙動**: このビルドは `typechk.sh` 生成のサブシェル経由のため、コンパイルが
  失敗しても最上位の終了コードが 0 になることがある。そのため終了コードだけでなく、
  stderr 中の**エラー痕跡マーカー**（`致命的エラー` / `fatal error` / `make: ***` /
  `: error:` / `undefined reference` / `ld returned` など）も見て成否を判定する。
- **env と workdir の扱い**: `env` の変数名は英数字と `_` だけ（先頭は数字不可）で、値は
  **リテラル**として `export` される（`$HOME` などのシェル展開はされない）。`workdir` は
  クォートされ、先頭の `~` だけはホームディレクトリとして扱われる。`commands` は
  ビルド手順そのものなので、クォートせずシェルコマンドとして実行される。不正な名前や
  空の `workdir` があると、リモートへ接続する前にエラーで終了コード 1 になる。
- **実行中ログ**: 各ステップの出力は、実行中に `stepNN.stdout.log` / `stepNN.stderr.log` へ
  逐次追記される。タイムアウトや Ctrl+C で止まっても、それまでのログが残る。ログが増えて
  いればビルドは進行中、増えなければ無応答（ハング）と判断できる。タイムアウトは 3600 秒。
  中断時の終了コードは 130。リモートのプロセスが残っていないかは別途確認する。
- **エージェントの判断ポイント**: 失敗時は保存された `stepNN.stderr.log` を読み、
  どの依存・ヘッダ・ライブラリが不足しているかを特定する。次の一手（sync_tree で
  version_mng を配置、apply_packages で依存導入、Makefile 修正など）はエージェントが決め、
  整備後に run_build を再実行するループを回す。

---

## 典型的な作業ループ（詳細は skills/env-provisioning）

1. `check_connectivity.py` で疎通を確認する。
2. `probe_src.py` で src の現状を収集する。
3. `run_build.py`（または対象作業）を実行し、失敗ログを読む。
4. 不足を判断し、`sync_tree.py` / `sync_files.py` / `apply_packages.py` で環境を整える。
5. 再実行して通るまで 3〜4 を繰り返す。


## container.py — コンテナ解析・image移送計画

- **用途**: プロジェクトで定義したengine・image・移送元・移送先・参照containerを使い、Docker/Podmanのcontainer inspectを共通モデルへ正規化し、run候補とimage移送計画を出力する。
- **設定**: `desired_state/container.local.json`（Git管理外）。最低限、`engine`（`podman`または`docker`）、`image`、`source_target`、`destination_target`、`container`を指定する。`transfer_mode`は既定`export`で、必要な場合だけ`commit`を指定する。
- **対応engine**: 初期対応はPodman→Podman、Docker→Docker。同じengine内の移送だけを扱い、Podman/Docker間の変換は対象外。
- **基本実行**:

  ```powershell
  # 読み取り解析、run候補、image移送計画を出力
  uv run python scripts/container.py --project project-a

  # 計画を確認後、明示承認してimage移送を実行（runは実行しない）
  uv run python scripts/container.py --project project-a --execute-image --approve-image
  ```

- **通常の移送**: 移送元で`podman export` / `docker export`、移送先で`podman import` / `docker import`を使う。元imageの履歴やDockerfileは復元しない。
- **高再現性の移送**: `transfer_mode=commit`のときだけ、承認後に`commit` → `save/load`を使う。移送元のimage storeを変更するため、通常方式より影響が大きい。
- **出力**: `build_env/logs/<project-id>/container_plan_<timestamp>/container-plan.json`へ、inspect要約、環境変数参照へ置換したrun候補、image移送計画、警告、未対応項目を保存する。
- **run候補の初期対応**: image、name、command/entrypoint、environment、workdir、user、port、bind mount、network、restart policy。resource制限、capability、device/GPU、namespace、healthcheck等は解析・警告まで。
- **外部依存**: bind mountの通常ファイル・ディレクトリはdesired stateへ明示した場合だけ既存の`sync_files.py` / `sync_tree.py`で扱う。named volume、secret、device/GPU、networkは自動移送しない。
- **秘密情報**: password/token等は実値を保存せず、`${ENVB_CONTAINER_<KEY>}`形式の環境変数参照へ置き換える。secret/configの内容は収集しない。
- **権限**: rootless/rootfulを自動切替しない。基本は移送元・移送先の実行コンテキストを揃え、差異は計画の警告とする。sudo/suは使わない。
- **承認**: image移送は`--execute-image --approve-image`を併用した場合だけ実行する。run候補は表示するだけで、自動runしない。
- **失敗時**: archiveと専用作業領域はcleanupする。作成済みimageは自動削除せず、ID・digest・状態をmanifestへ記録する。同名tagは上書きしない。
- **安全性**: archiveは`build_env/work/<work-id>/`とリモートの専用`/tmp/env_builder-<work-id>-XXXXXX/`だけに置き、Gitへ保存しない。参照元の`src`ではexportは読み取り操作として扱い、commitは明示承認なしに実行しない。
