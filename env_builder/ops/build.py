"""構築先(dst)での build 手順の実行と、成否の判定。

desired_state の build ターゲットが定義するコマンドを、作業ディレクトリで順に実行し、
各ステップの stdout / stderr を実行中にログへ追記する。接続は内部で作らず、
`CommandRunner` を引数で受け取る。

成否は終了コードだけでなく、stderr のエラー痕跡も見て判定する（このビルドは typechk.sh 生成の
サブシェル経由のため、コンパイルが失敗しても最上位の終了コードが 0 になることがある）。
"""

from __future__ import annotations

import logging
import shlex
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from env_builder.core.shell import quote_remote_path, validate_env_name
from env_builder.core.ssh import SSHInterrupted, SSHResult
from env_builder.ops.session import CommandRunner

STEP_TIMEOUT_SEC = 3600

# コンパイル/リンクの失敗を示す痕跡。終了コードが 0 でも、これらが stderr に
# あれば失敗とみなす（typechk.sh 経由でエラーが最上位に伝播しないため）。
BUILD_ERROR_MARKERS = (
    "致命的エラー",
    "fatal error",
    "make: ***",
    "make[1]: ***",
    "make[2]: ***",
    "] エラー ",
    ": error:",
    "] Error ",
    "undefined reference",
    "ld returned",
)


def has_build_error(stderr: str) -> bool:
    """stderr にコンパイル/リンク失敗の痕跡があるか判定する。"""
    return any(marker in stderr for marker in BUILD_ERROR_MARKERS)


def env_prefix(env: Mapping[str, object]) -> str:
    """環境変数の export 前置きを組み立てる。

    変数名は検証し、値はリテラルとしてクォートする（シェル展開はしない）。
    """
    return "".join(f"export {validate_env_name(key)}={shlex.quote(str(value))}; " for key, value in env.items())


def step_command(workdir: str, prefix: str, cmd: str) -> str:
    """1 ステップ分のリモートコマンドを組み立てる。

    workdir はクォートする（先頭の `~` はホームディレクトリ）。cmd は desired_state が定義する
    ビルド手順そのものなので、シェルコマンドとして渡し、クォートしない。
    """
    return f"cd -- {quote_remote_path(workdir)} && {prefix}{cmd}"


def validate_build_target(workdir: str, env: Mapping[str, object]) -> str:
    """リモートへ何も送る前に、環境変数名と作業ディレクトリを検証し、export 前置きを返す。

    不正なら ValueError。
    """
    prefix = env_prefix(env)
    quote_remote_path(workdir)
    return prefix


@dataclass
class BuildOutcome:
    """build 手順の実行結果。

    ok は全ステップが成功したこと。失敗・タイムアウト・中断のいずれかで止まった場合は ok が偽で、
    `stopped_at` に止まったステップの番号（1 始まり）が入る。
    """

    ok: bool
    interrupted: bool = False
    timed_out: bool = False
    stopped_at: Optional[int] = None
    steps_run: int = 0


def run_build_steps(
    runner: CommandRunner,
    *,
    workdir: str,
    commands: Sequence[str],
    prefix: str,
    run_dir: Path,
    logger: logging.Logger,
    timeout: int = STEP_TIMEOUT_SEC,
) -> BuildOutcome:
    """build のコマンドを順に実行する。最初に失敗・タイムアウト・中断したステップで止まる。

    各ステップの出力は `run_dir/stepNN.stdout.log` / `stepNN.stderr.log` へ実行中に追記し、
    終了後にノイズ除去済みの最終出力で上書きする。タイムアウトや Ctrl+C で止まっても、
    それまでのログは残る。
    """
    outcome = BuildOutcome(ok=True)
    for i, cmd in enumerate(commands, 1):
        full = step_command(workdir, prefix, cmd)
        logger.info("[%d/%d] %s", i, len(commands), cmd)

        # 実行中の出力を逐次ファイルへ追記する。タイムアウトや Ctrl+C で途中終了しても、
        # それまでのログが失われず、無出力のハングと進捗中を後から区別できる。
        stdout_log = run_dir / f"step{i:02d}.stdout.log"
        stderr_log = run_dir / f"step{i:02d}.stderr.log"
        stdout_log.write_text("", encoding="utf-8")
        stderr_log.write_text("", encoding="utf-8")
        sinks = {"stdout": stdout_log, "stderr": stderr_log}

        def append_output(stream: str, text: str, _sinks: Mapping[str, Path] = sinks) -> None:
            with _sinks[stream].open("a", encoding="utf-8", newline="") as handle:
                handle.write(text)

        outcome.steps_run = i
        res: SSHResult
        try:
            res = runner.run(full, timeout=timeout, on_output=append_output)
        except SSHInterrupted as exc:
            res = exc.result
            outcome.interrupted = True

        # ノイズ除去後の最終出力で上書きする（逐次ログは生に近い出力のため）。
        stdout_log.write_text(res.stdout, encoding="utf-8")
        stderr_log.write_text(res.stderr, encoding="utf-8")

        if outcome.interrupted:
            outcome.ok = False
            outcome.stopped_at = i
            logger.error("    -> 中断されました（Ctrl+C）。リモートのプロセスは停止していない可能性があります。")
            break
        if res.timed_out:
            outcome.ok = False
            outcome.timed_out = True
            outcome.stopped_at = i
            logger.error("    -> タイムアウト（%d秒）。リモートのプロセスは停止していない可能性があります。", timeout)
            break

        # このビルドは typechk.sh 生成のサブシェル経由のため、コンパイルが
        # 失敗しても最上位の終了コードが 0 になることがある。終了コードだけ
        # でなく、stderr 中のエラー痕跡も見て成否を判定する。
        failed = (not res.ok) or has_build_error(res.stderr)
        if not failed:
            logger.info("    -> ok")
        else:
            outcome.ok = False
            outcome.stopped_at = i
            logger.error("    -> 失敗 exit=%d（エラー痕跡検出=%s）", res.exit_code, has_build_error(res.stderr))
            # stderr の末尾を要約表示
            tail = res.stderr.strip().splitlines()[-15:]
            for line in tail:
                logger.error("    | %s", line)
            break  # 失敗したら以降は止める
    return outcome
