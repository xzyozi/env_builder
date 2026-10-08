"""env_builder: 参照元(src)を参考に構築先(dst)の環境を整えるための作業基盤。

構成:
- env_builder.core: 設定読込・SSH実行・作業領域・ログなどの共通ライブラリ（判断は持たない）
- env_builder.ops:  SSHを伴う上位処理（現状は container）
- env_builder.cli:  引数解析・表示・終了コードだけを担うコマンド（1コマンド1ファイル）

実行方法:
    uv run python -m env_builder <command> [args...]
    uv run python scripts/<command>.py [args...]   # 互換ラッパー（同じ動作）
"""
