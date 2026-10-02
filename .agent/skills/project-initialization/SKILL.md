---
name: project-initialization
description: プロジェクト初期設定の要件を壁打ちで整理し、非破壊の計画と明示承認を経て既存CLIへ安全に引き渡す手順。新規projectの作成、legacy構成からの切替、inventory・desired_stateの準備を始めるときに使用する。トリガーキーワード: 初期設定、プロジェクト作成、project initialization、project initializer。
metadata:
  version: "1.0"
  author: "env_builder"
allowed-tools: [Read, Bash]
---

# プロジェクト初期設定

## 概要

このSkillは、env_builderで作業を始める前に、対象projectと必要なメタデータを対話で確定し、初期化計画を作成するための手順である。実際のファイル生成は `scripts/init_config.py` に委譲し、初期化後の疎通確認や環境整備は別のSkillへ引き渡す。

## ワークフロー

### 1. コンテキストを読み込む

次の順に、必要な規約と手順を読む。

1. ルート `AGENTS.md`
2. `.agent/instructions.md`
3. `.agent/rules/operation-safety.md`
4. `.agent/rules/project-management.md`
5. `.agent/references/scripts.md`
6. 初期化後に使う場合だけ、対象の個別Skill

project IDが確定する前に、未選択projectの `AGENTS.md` や `.agent/` を横断して読まない。project選択後は、ルート規約を優先して対象projectの規約を必要な範囲だけ読む。

### 2. 壁打ちで要件を確定する

一度に確認できる範囲で、次の項目を質問する。

- legacy経路を使うか、明示的なprojectを新規作成するか
- 明示projectの場合のproject ID
- `ENVB_PROJECT_ROOT` を使うか、リポジトリ直下の `projects/` を使うか
- 接続対象の役割（`src`、`dst`、`bastion`）
- 通常ユーザー定義とrootユーザー定義の要否
- password認証または鍵認証の選択
- password認証の場合の `password_env` の環境変数名
- 必要なdesired state（build、packages、filesなど）
- 初期化だけで終了するか、初期化後の疎通確認まで行うか

パスワード、秘密鍵の内容、Cookie、トークンなどの実値は質問・表示・保存しない。ホスト名やユーザー名などの環境固有値も、必要以上に会話へ再掲しない。

### 3. 変更なしの計画を提示する

project IDと設定ルートを確定したら、変更を行わずに次を表示する。

- 選択するProjectProfile
- 生成先の `inventory/servers.json`
- 既存ファイルがある場合の扱い（既定は維持）
- `desired_state/` と `build_env/` の準備が別途必要であること
- 実行予定コマンド
- 初期化後にユーザーが記入・設定する項目
- 次に必要な明示承認

project IDの検証、設定ルート外へのパス逸脱防止、profileの解決は `ProjectRegistry` と既存CLIに委譲する。Agent内で同じパス解決ロジックを再実装しない。

### 4. 初期化前のpreflightを行う

次を確認する。

- project IDが英数字で始まり、英数字・ハイフン・アンダースコアの1〜64文字である
- `ENVB_PROJECT_ROOT` または既定の `projects/` を対象としている
- `inventory/servers.sample.json` が存在する
- 既存の `inventory/servers.json` を保持するか、明示的に上書きするか決まっている
- 初期化後に必要な `desired_state` の種類が決まっている
- srcを参照専用として扱い、root操作が必要な対象を区別できている

既存ファイルの内容を会話へ出力しない。存在、非空、必要な構造を確認する場合も、認証情報や秘密値を表示しない。

### 5. 明示承認後に初期化する

ユーザーが「この内容で作成する」と明示した後だけ、Python実行環境を確認して既存CLIを実行する。Python関連の最初の実行前に `uv --version` を一度確認し、プロジェクトがuvを採用している場合は `uv run` を使う。

新規の明示projectでは、原則として次を使う。

```powershell
uv run python scripts/init_config.py --project <project-id>
```

legacy経路では次を使う。

```powershell
uv run python scripts/init_config.py
```

既存ファイルを上書きする `--force` は自動選択しない。上書きが必要な場合は、対象パス、失われる内容、復元方法、可逆性を説明し、別の明示承認を得る。

### 6. 利用者による設定を案内する

初期化後は、ユーザーが次を行う。

1. `inventory/servers.json` にhost、port、user、接続方式、`proxy_jump`を設定する
2. password認証の場合は `password_env` で指定した環境変数へパスワードを設定する
3. 鍵認証の場合は秘密鍵をリポジトリ外で管理し、`key_path`だけを設定する
4. 必要な `desired_state` を作成する
5. 設定実体、秘密情報、作業成果物をGitへ追加しない

Agentは秘密値を受け取らず、ファイルへ記入しない。設定確認では非秘密の存在・構造だけを扱う。

### 7. 初期化後に段階的に引き渡す

初期化と利用者による設定が完了しても、疎通確認や環境変更を自動開始しない。

1. 別の明示承認を得て、対象を限定した `check_connectivity.py --project <project-id> --target <target>` を実行する
2. 疎通が確認できたら、ユーザーの次工程承認を得る
3. `env-provisioning` Skillへproject ID、対象target、確認済み事項、残課題だけを引き渡す
4. `probe_src.py`、build、パッケージ導入、ファイル転送は次工程で個別に判断する

srcでは読み取り専用操作だけを行う。rootが必要な操作は、sudo / suではなくrootログイン定義を使う。

## ルール

1. project IDと対象を暗黙に推測しない。
2. 壁打ちと計画提示の段階では、ファイル変更・ネットワーク接続・リモート操作を行わない。
3. ファイル生成は `scripts/init_config.py` に委譲し、Agent内でJSONを直接生成・編集しない。
4. 既存ファイルは既定で保持する。`--force` は別の明示承認なしに実行しない。
5. パスワード、秘密鍵、トークン、Cookieなどの実値を聞かない、表示しない、ログに残さない。
6. `ProjectRegistry` のID検証とprofile解決を再実装しない。
7. sudo / suを使わない。srcを変更しない。root操作はrootログイン定義を使う。
8. 初期化Agentからbuild、package導入、ファイル転送、リモート変更を自動開始しない。
9. 失敗時は観測したエラー全文と期待状態を説明する。ただし秘密情報と不要な絶対パスはマスクする。
10. 作成・更新するテキストファイルはUTF-8（BOMなし）/ LFで扱う。

## 出力フォーマット

各段階で次の形式を使う。

```text
状態: interview | plan | waiting-for-approval | initialized | handoff-ready | blocked

確定事項:
- project:
- 設定ルート:
- 対象:
- 認証方式:

未確定事項:
- ...

予定操作:
- ...

次の質問または承認:
- ...
```

`initialized` では生成・維持したファイル名だけを示し、ファイル内容や秘密値は出力しない。`handoff-ready` ではproject ID、対象、確認済み事項、残課題だけを引き渡す。

## 例

### 新規projectの例

入力:

```text
project-aを新しく作り、接続設定だけ初期化したい。
```

計画:

```text
状態: waiting-for-approval

確定事項:
- project: project-a
- 設定ルート: ENVB_PROJECT_ROOT配下
- 対象: inventoryの初期化のみ
- 認証方式: 未確定

予定操作:
- uv run python scripts/init_config.py --project project-a
- 既存のservers.jsonは上書きしない
- desired_stateと疎通確認はこの段階では実行しない

次の質問または承認:
- この内容で初期化してよいですか？
```

### 既存ファイルがある場合

```text
状態: blocked

予定操作:
- inventory/servers.jsonは既存のため維持

次の質問または承認:
- 既存ファイルを使うか、上書きが必要な理由と復元方法を確認してください。
```

## ガイドライン

- 初期設定Agentは「判断のための壁打ち」と「安全なCLI委譲」を担当し、環境構築そのものを担当しない。
- `desired_state` の具体的な内容は案件ごとのメタデータであり、このSkillに固定値として埋め込まない。
- project選択後に対象projectの規約を読むが、上位のシステム・開発者・ユーザー指示とルート規約を緩和しない。
- 初期化が完了しても、設定値の妥当性や接続成功を推測で宣言しない。確認できた事実と未確認事項を分ける。
- 同じ修正を二度繰り返しても解決しない場合は、初期化を繰り返さず、原因を診断して別の調査手順へ切り替える。
