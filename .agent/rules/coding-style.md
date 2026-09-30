# コーディング規約

## 言語・実行環境

- スクリプトは Python（`requires-python >= 3.9`）。依存は `paramiko`。
- 実行・依存管理は uv。実行は `uv run python scripts/<name>.py ...` の形。
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

## scripts/core の責務

- `core` は**ライブラリ**であり、責務は **設定読込・SSH 実行・ログ出力** の 3 つに限定する。
  build ロジックや冪等判定・実行順序といった**判断**は持たせない。
- 実行判断（どのコマンドをどの順で流すか、出力をどう解釈するか）は、上位スクリプトと
  エージェント側の責務。
- `core` を使う新スクリプトを追加する場合も、この責務分離を守る。
- 公開シンボルは `scripts/core/__init__.py` の re-export に従う
  （`load_inventory` / `SSHSession` / `get_logger` / `new_run_dir` 等）。

## 既存コードへの追従

- 既存スクリプトのスタイル・インデント・import 作法に合わせる。
  （`sys.path` に `scripts/` を足してから `core` を読む既存の作法を踏襲する）
- 変更時は既存機能への影響を確認し、実装後に lint/型/テストで検証する。
