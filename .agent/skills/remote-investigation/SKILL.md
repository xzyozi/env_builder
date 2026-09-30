---
name: remote-investigation
description: remote_exec.py で任意サーバを読み取り調査し、ビルド失敗や不足の原因を特定する
allowed-tools: [Bash, Read, Grep]
---

# リモート調査

`scripts/remote_exec.py` をラップした、調査の型。ビルド失敗や環境の不足を特定するために、
リモートで読み取りコマンドを流して状況を読む。**コマンドの組み立てと出力の解釈は
エージェントの責務**。

## 基本形

```powershell
uv run python scripts/remote_exec.py --target <key> -- "<command>"
uv run python scripts/remote_exec.py --target <key> --save -- "<command>"
```

- `--target` 既定は `dst`。root が要る領域は `--target dst_root`。src は読み取り専用に限定。
- `--save` で `build_env/logs/exec_<target>_<ts>/` に stdout/stderr を保存（後で比較に使える）。
- `--timeout` 既定 120 秒。

## 調査の型（例）

- **ディレクトリ・ファイル構成**: `ls -la <dir>` / `find <dir> -maxdepth 2 -type f`
- **ビルド定義の把握**: `cat Makefile` / `grep -n 'include\|LDFLAGS\|CFLAGS' Makefile`
- **依存の追跡**: `ldd <binary>` / `rpm -q <pkg>` / `ls -l <期待するライブラリパス>`
- **ヘッダ・ライブラリの有無**: `find / -name '<header>.h' 2>/dev/null`（範囲は絞る）
- **src と dst の差分確認**: 同じコマンドを両者で流し、出力を突き合わせる。

## 判断のポイント

1. 「何が分かれば次の一手が決まるか」を先に決めてからコマンドを組む。
2. まず読み取り系（`ls` / `cat` / `rpm -q` / `find` / `ldd`）で状況を確定する。
3. 状態を変える操作は remote_exec で直に叩かず、専用スクリプト
   （`apply_packages` / `sync_tree` / `sync_files`）があればそちらを使う。
4. 終了コードだけでなく stdout/stderr の中身を読む。想定と違う出力は原因未確定として扱い、
   推測で先に進めない。

## 参照

- スクリプト仕様: `.agent/references/scripts.md`（remote_exec.py を厚めに記載）
- 鉄則: `.agent/rules/operation-safety.md`（src 読み取り専用・昇格しない）
