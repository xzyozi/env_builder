# スクリプトリファレンス

`scripts/` 配下の汎用スクリプトの説明。**スクリプトは手順の方針**であり、どれをどの順で
叩き、出力をどう解釈するかはエージェントが判断する。ここは「各スクリプトが何をする道具か」
「どこまでがスクリプトの責務で、どこからがエージェントの判断か」を言語化したもの。

すべて `uv run python scripts/<name>.py ...` で実行する。接続対象は `inventory/servers.json`
の**キー名**（`src` / `dst` / `dst_root` / `bastion` など）で指定する。

## スクリプト vs エージェントの境界

- **スクリプトに置く**（機械的処理・再現性）: SSH 多段接続、tar 中継転送、rpm 冪等判定、
  ログ保存、出力の定型パターン検出。引数を変えれば別状況でも使い回せるもの。
- **エージェントが判断する**（解釈・順序・意思決定）: どのターゲットを先に処理するか、
  失敗ログのどのマーカーで何を疑うか、次にどのスクリプトをどの引数で叩くか、収集結果を
  どう次の一手に反映するか。
- 迷ったら: 「引数を変えれば使い回せる」ならスクリプト、「状況を読んで決める」ならエージェント。

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

- **エージェントの判断ポイント**:
  - **コマンドの組み立てはエージェントの責務**。何を確認すれば次の一手が決まるかを考えて
    コマンドを作る。読み取り系（`ls` / `cat` / `rpm -q` / `find` など）を基本とする。
  - src に対して使うときは**読み取り専用に限定**する（operation-safety 準拠）。
  - 状態を変える操作（インストール・削除・展開）は、専用スクリプト（apply_packages /
    sync_tree 等）があるならそちらを優先する。remote_exec での状態変更は影響を確認してから。
  - 終了コードだけでなく stdout/stderr の中身を読んで解釈する。`--save` した出力は後の
    調査・比較に使える。

## sync_files.py — ファイル単位の仲介転送

- **用途**: `desired_state/files.json` の対応表に従い、src から設定ファイルを取得して
  dst へ配置する（src→手元PC→dst の中継）。踏み台越しでも両サーバ間の直接到達性が
  なくても運べる。
- **主な引数**:
  - 既定: `files.json` に従い `--src src --dst dst`。
  - `--upload-only <LOCAL> <REMOTE>`（download をスキップし、手元のファイルを dst へ送るだけ）。
- **メモ**: `files.json` に `mode` があれば `chmod` する。root 配置先へは `--dst` に root
  定義を指定する。

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

- **メモ**: 中継の tar は `build_env/artifacts/trees/` に一時保管される（Git 管理外）。
  リモート `/tmp` の tar は処理後に削除される。

## apply_packages.py — パッケージの冪等適用

- **用途**: `desired_state/packages.json` に従い、dst へ OSS パッケージを冪等に適用する
  （Ansible の package タスク相当）。導入済みはスキップ。
- **主な引数**:
  - `--target dst`（root ログイン前提。昇格しない）。
  - `--check`（dry-run。不足分の表示のみ）。
- **エージェントの判断ポイント**: まず `--check` で差分を確認し、probe_src の結果と
  突き合わせて本当に必要なものだけ適用する。`package_manager` は既定 `dnf`。

## run_build.py — dst でのビルド実行とログ回収

- **用途**: `desired_state/build_targets.local.json`（Git 管理外）の定義に従い、dst の
  作業ディレクトリでビルドコマンドを順に実行し、`build_env/logs/build_<name>_<ts>/` に
  stdout/stderr と終了コードを保存する。
- **主な引数**: `--target <name>`（build_targets の name。未指定なら先頭）。
- **重要な挙動**: このビルドは `typechk.sh` 生成のサブシェル経由のため、コンパイルが
  失敗しても最上位の終了コードが 0 になることがある。そのため終了コードだけでなく、
  stderr 中の**エラー痕跡マーカー**（`致命的エラー` / `fatal error` / `make: ***` /
  `: error:` / `undefined reference` / `ld returned` など）も見て成否を判定する。
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
