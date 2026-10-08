# コーディング規約

## 言語・実行環境

- スクリプトは Python（`requires-python >= 3.9`）。依存は `paramiko`。
- 実行・依存管理は uv。実行は `uv run python -m env_builder <command> ...` の形
  （従来の `uv run python scripts/<name>.py ...` も互換ラッパーとして同じ動作をする）。
- TLS 傍受環境のため uv は `native-tls=true`（`uv.toml`）を前提とする。

## 文字コード・改行

- すべてのテキストファイルは **UTF-8（BOM なし）/ 改行コード LF** で保存する。
- コミット前に `git diff --check` で CRLF・末尾空白の混入を確認する。

## Lint / 型 / テスト（CI と同じチェック）

設定は `pyproject.toml` に定義。push 前にローカルで通しておく。

```powershell
uv run ruff check .            # Lint（E / F / W / I）
uv run ruff format --check .   # 整形チェック（自動整形は format）
uv run mypy .                  # 型チェック
uv run pytest                  # テスト（tests/ 配下）
```

- `line-length = 120`。`build_env/` は lint/型チェックの除外対象。
- CI（`.github/workflows/ci.yml`）は main / develop 宛の PR で上記を実行する。

## パッケージ構成と core の責務

実装は `env_builder/` パッケージにあり、層は次の 3 つに分ける。

- `env_builder/cli/`: コマンド。**引数解析・表示・終了コード**だけを担い、1 コマンド 1 ファイル。
  `main(argv=None) -> int` を公開し、`env_builder/cli/__init__.py` の `COMMANDS` に登録する。
- `env_builder/core/`: **ライブラリ**。責務は **設定読込・SSH 実行・作業領域・ログ出力** などの
  共通処理に限定する。build ロジックや冪等判定・実行順序といった**判断**は持たせない。
- `env_builder/ops/`: SSH を伴う上位処理（現状は container）。

ルール:

- 実行判断（どのコマンドをどの順で流すか、出力をどう解釈するか）は、`cli` / `ops` と
  エージェント側の責務。
- `core` を使う新しいコードを追加する場合も、この責務分離を守る。
- 公開シンボルは `env_builder/core/__init__.py` の re-export に従う
  （`load_inventory` / `SSHSession` / `get_logger` / `new_run_dir` 等）。
- `scripts/<name>.py` は互換ラッパーで、ロジックを書かない。新しいコマンドを追加したら、
  対応するラッパーも 1 本追加する（`tests/test_entrypoints.py` が対応を検査する）。

## 既存コードへの追従

- 既存コードのスタイル・インデント・import 作法に合わせる。import は
  `from env_builder.core.xxx import ...` の絶対 import に統一する。**`sys.path` は操作しない**
  （操作してよいのは `scripts/` の互換ラッパーだけ。別名のモジュールが二重にロードされる原因になる）。
- 変更時は既存機能への影響を確認し、実装後に lint/型/テストで検証する。
