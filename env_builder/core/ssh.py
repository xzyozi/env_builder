"""踏み台越しの SSH 実行・ファイル転送。

paramiko を用い、踏み台(bastion)を経由して src / dst へ接続する
（OpenSSH の ProxyJump 相当）。パスワード認証・公開鍵認証の双方に対応。

このモジュールは「接続してコマンドを実行し、結果を返す」ことに責務を
限定する。build のロジックや冪等判定は呼び出し側スクリプトが持つ。

コマンド実行（SSHSession.run）の取り決め:
- stdout / stderr は同時に排出する（片方が大量でも詰まらない）。
- timeout は壁時計（コマンド全体の上限秒）。超過すると SSHResult.status が "timeout"
  になり、それまでの出力を保持したまま戻る（終了コードは 124）。
- Ctrl+C（KeyboardInterrupt）は SSHInterrupted（KeyboardInterrupt のサブクラス）として
  送出する。途中までの出力は SSHInterrupted.result に入る（終了コードは 130）。
- timeout / 中断のとき、ローカルは SSH チャネルを閉じるが、**リモートのプロセスが停止する
  ことは保証しない**。pty を使わない実行では、チャネルを閉じてもリモートのコマンドが
  走り続けることがある。確実に止めたいコマンドは、リモート側で `timeout 600 <cmd>` の
  ように包む。
"""

from __future__ import annotations

import codecs
import logging
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Protocol

try:
    import paramiko
except ImportError as e:  # pragma: no cover - 依存未導入時の明確なエラー
    raise ImportError("paramiko が必要です。`uv sync` もしくは `uv add paramiko` で導入してください。") from e

from .config import Inventory, ServerSpec
from .host_keys import configure_host_keys

logger = logging.getLogger("env_builder")

# dst の seigyo はログインシェルで tset を実行するため、非対話SSHでは
# stdout 末尾に "logout"、stderr に "tset: terminal attributes: ..." が
# 必ず混じる。build の成否判定を誤らせるノイズなので除去する。
# ここは「行そのものがノイズと一致する場合のみ」除去し、正規の出力は残す。
_NOISE_STDOUT_PREFIXES = ("logout",)
_NOISE_STDERR_SUBSTRINGS = ("tset: terminal attributes",)


# keepalive の送出間隔（秒）。OpenSSH の ServerAliveInterval に相当する。
# 無通信が続く長時間処理（make 等）でも、この間隔でダミーパケットを送って
# 接続を維持し、途中切断を防ぐ。踏み台を含む全 transport に設定する。
_KEEPALIVE_INTERVAL_SEC = 30

# コマンド実行の状態。呼び出し側が「正常終了 / タイムアウト / 中断」を区別するために使う。
STATUS_COMPLETED = "completed"
STATUS_TIMEOUT = "timeout"
STATUS_INTERRUPTED = "interrupted"

# timeout / 中断時の終了コード（GNU timeout / シェルの慣例に合わせる）。
EXIT_CODE_TIMEOUT = 124
EXIT_CODE_INTERRUPTED = 130

# 出力を取り込む間隔と、1回に読む最大バイト数。
_POLL_INTERVAL_SEC = 0.05
_READ_CHUNK_BYTES = 65536

# SFTP 転送の無通信タイムアウト（秒）。転送が進んでいる間は延長される。
_SFTP_TIMEOUT_SEC = 600

# テストで差し替えられるよう、時刻と待機はモジュール変数経由で呼ぶ。
_monotonic = time.monotonic
_sleep = time.sleep

OutputCallback = Callable[[str, str], None]


class CommandRunner(Protocol):
    """リモートで 1 コマンドを実行できるもの（`SSHSession` や、テスト用の fake が満たす）。

    コマンド実行だけを必要とする処理（`WorkContext` の作業領域の作成・削除など）が、
    具体的な `SSHSession` に依存せずに済むよう、必要な機能だけを型として切り出している。
    """

    def run(
        self,
        command: str,
        timeout: int = 600,
        *,
        on_output: Optional[OutputCallback] = None,
    ) -> "SSHResult": ...


def _strip_shell_noise(text: str, patterns_prefix=(), patterns_substr=()) -> str:
    """ログインシェル由来のノイズ行だけを取り除く。"""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if any(stripped == p or stripped.startswith(p) for p in patterns_prefix):
            continue
        if any(s in line for s in patterns_substr):
            continue
        kept.append(line)
    return "\n".join(kept)


@dataclass
class SSHResult:
    """コマンド実行結果。

    status は "completed"（正常終了）/ "timeout"（時間切れ）/ "interrupted"（Ctrl+C）。
    exit_code だけでは、リモートが 124 を返した場合と区別できないため status も見る。
    """

    exit_code: int
    stdout: str
    stderr: str
    status: str = STATUS_COMPLETED

    @property
    def ok(self) -> bool:
        return self.status == STATUS_COMPLETED and self.exit_code == 0

    @property
    def timed_out(self) -> bool:
        return self.status == STATUS_TIMEOUT


class SSHInterrupted(KeyboardInterrupt):
    """コマンド実行中の Ctrl+C。途中までの出力を result に持つ。

    KeyboardInterrupt のサブクラスなので、捕捉しない呼び出し側ではこれまで通り
    プログラムが中断される。
    """

    def __init__(self, result: SSHResult) -> None:
        super().__init__("SSH コマンドの実行が中断されました")
        self.result = result


class _OutputCollector:
    """stdout / stderr を UTF-8 として逐次デコードして溜める。

    マルチバイト文字がチャンクの境目で分割されても、文字化けさせない。
    """

    def __init__(self, on_output: Optional[OutputCallback] = None) -> None:
        self._decoders = {
            "stdout": codecs.getincrementaldecoder("utf-8")(errors="replace"),
            "stderr": codecs.getincrementaldecoder("utf-8")(errors="replace"),
        }
        self._parts: Dict[str, List[str]] = {"stdout": [], "stderr": []}
        self._on_output = on_output

    def feed(self, stream: str, data: bytes, final: bool = False) -> None:
        text = self._decoders[stream].decode(data, final=final)
        if not text:
            return
        self._parts[stream].append(text)
        if self._on_output is not None:
            self._on_output(stream, text)

    def finish(self) -> None:
        """未確定のバイトを吐き出す。"""
        for stream in ("stdout", "stderr"):
            self.feed(stream, b"", final=True)

    def text(self, stream: str) -> str:
        return "".join(self._parts[stream])


def _read_available(channel, collector: _OutputCollector) -> bool:
    """今読める stdout / stderr をすべて取り込む。1バイトでも読めたら True。"""
    moved = False
    while channel.recv_ready():
        data = channel.recv(_READ_CHUNK_BYTES)
        if not data:
            break
        collector.feed("stdout", data)
        moved = True
    while channel.recv_stderr_ready():
        data = channel.recv_stderr(_READ_CHUNK_BYTES)
        if not data:
            break
        collector.feed("stderr", data)
        moved = True
    return moved


def _channel_finished(channel) -> bool:
    """コマンドが終了し、出力もすべて届き終えたか。"""
    return bool(channel.closed or (channel.exit_status_ready() and channel.eof_received))


def _pump(channel, collector: _OutputCollector, timeout: float) -> str:
    """コマンドが終わるか timeout になるまで、stdout / stderr を同時に取り込む。

    stdout と stderr を同じループで交互に排出するため、片方が大量に出力されても
    バッファが詰まってコマンドが止まることはない。
    """
    deadline = _monotonic() + timeout
    while True:
        moved = _read_available(channel, collector)
        if _channel_finished(channel) and not moved:
            return STATUS_COMPLETED
        if _monotonic() >= deadline:
            return STATUS_TIMEOUT
        if not moved:
            _sleep(_POLL_INTERVAL_SEC)


def _build_result(collector: _OutputCollector, exit_code: int, status: str) -> SSHResult:
    # ログインシェル由来のノイズ（logout / tset）を除去してから返す。
    out = _strip_shell_noise(collector.text("stdout"), patterns_prefix=_NOISE_STDOUT_PREFIXES)
    err = _strip_shell_noise(collector.text("stderr"), patterns_substr=_NOISE_STDERR_SUBSTRINGS)
    return SSHResult(exit_code=exit_code, stdout=out, stderr=err, status=status)


def _connect_one(spec: ServerSpec, sock: Optional[object] = None) -> "paramiko.SSHClient":
    """単一ホストへ接続した SSHClient を返す。sock は踏み台チャネル。

    ホスト鍵は known_hosts で検証し、未登録の鍵は既定で拒否する（host_keys.py）。
    検証に失敗した場合や接続が途中で中断された場合は、開きかけた接続を閉じる。
    """
    client = paramiko.SSHClient()
    configure_host_keys(client)

    connect_kwargs: dict = {
        "hostname": spec.host,
        "port": spec.port,
        "username": spec.user,
        "timeout": 30,
        "sock": sock,
    }

    if spec.auth.method == "password":
        pw = spec.auth.resolve_password()
        if not pw:
            raise RuntimeError(f"[{spec.name}] パスワード認証だが環境変数 {spec.auth.password_env} が未設定です。")
        connect_kwargs["password"] = pw
        connect_kwargs["look_for_keys"] = False
        connect_kwargs["allow_agent"] = False
    else:  # key
        key_path = spec.auth.resolve_key_path()
        if key_path:
            connect_kwargs["key_filename"] = str(key_path)

    try:
        client.connect(**connect_kwargs)

        # 接続維持のため keepalive を有効化する（OpenSSH の ServerAliveInterval 相当）。
        # 踏み台・最終ホストとも同じ設定にし、無音の長時間処理での切断を防ぐ。
        transport = client.get_transport()
        if transport is not None:
            transport.set_keepalive(_KEEPALIVE_INTERVAL_SEC)
    except BaseException:
        client.close()
        raise

    return client


class SSHSession:
    """踏み台越しに1ホストへ接続するセッション。

    with 文で使う。proxy_jump（経由順のキー列）が指定されていれば、
    近い踏み台から順に接続し、各段のチャネル(sock)を次段へ引き渡して
    多段に潜る（OpenSSH の ProxyJump チェーン相当）。

    各段は独立した SSH チャネルとして張られ、run() は常に最終ホスト上で
    コマンドを実行する。TTL のように「シェルに ssh を打ち込んで潜る」方式
    ではないため、「今どこにいるか」を見失わない。

    接続の途中で失敗・中断（Ctrl+C）した場合は、そこまでに開いた踏み台の接続も
    すべて閉じる。
    """

    def __init__(self, inventory: Inventory, target: str):
        self.inventory = inventory
        self.target = target
        # 踏み台を含む接続済みクライアントを接続順に保持し、逆順で閉じる。
        self._chain: List[paramiko.SSHClient] = []
        self._client: Optional[paramiko.SSHClient] = None

    def __enter__(self) -> "SSHSession":
        try:
            self._open()
        except BaseException:
            self._close()
            raise
        return self

    def _open(self) -> None:
        spec = self.inventory.get(self.target)

        sock = None
        prev_transport = None
        # proxy_jump を近い踏み台から順に張っていく。
        hop_specs = [self.inventory.get(h) for h in spec.proxy_jump]
        # 次に繋ぐ相手（踏み台の次段 or 最終ホスト）のアドレスを決めるため、
        # 経由チェーン + 最終ホストを1本の列にする。
        route = hop_specs + [spec]
        for i, hop in enumerate(hop_specs):
            client = _connect_one(hop, sock=sock)
            self._chain.append(client)
            prev_transport = client.get_transport()
            # この踏み台上から「次のホスト」への direct-tcpip チャネルを開く
            next_host = route[i + 1]
            sock = prev_transport.open_channel(
                "direct-tcpip",
                (next_host.host, next_host.port),
                ("127.0.0.1", 0),
            )

        self._client = _connect_one(spec, sock=sock)

    def _close(self) -> None:
        """開いている接続をすべて閉じる。最終ホスト → 踏み台の逆順で、1つ失敗しても続ける。"""
        clients = ([self._client] if self._client else []) + list(reversed(self._chain))
        self._client = None
        self._chain = []
        for client in clients:
            try:
                client.close()
            except Exception as exc:  # noqa: BLE001 - 後始末では残りの接続を閉じることを優先する
                logger.debug("SSH接続のクローズに失敗しました: %s", exc)

    def __exit__(self, *exc) -> None:
        self._close()

    def run(
        self,
        command: str,
        timeout: int = 600,
        *,
        on_output: Optional[OutputCallback] = None,
    ) -> SSHResult:
        """リモートで1コマンドを実行し結果を返す。

        権限昇格(sudo/su)は行わない方針。root 権限が必要な操作は、
        inventory で root ユーザーとしてログインするサーバ定義を使う。

        timeout はコマンド全体の上限秒（壁時計）。超過すると、それまでの出力を持った
        SSHResult(status="timeout", exit_code=124) を返す。Ctrl+C は SSHInterrupted を送出する。
        on_output(stream, text) を渡すと、出力が届くたびに呼ばれる（stream は
        "stdout" / "stderr"）。長時間のコマンドの進捗確認や、途中経過の保存に使う。

        timeout / 中断の際、ローカルは SSH チャネルを閉じるが、リモートのプロセスが
        停止するとは限らない（モジュール冒頭を参照）。
        """
        if self._client is None:
            raise RuntimeError("セッションが未接続です。with 文で使ってください。")
        transport = self._client.get_transport()
        if transport is None:
            raise RuntimeError("SSH transport が利用できません。再接続してください。")

        channel = transport.open_session()
        collector = _OutputCollector(on_output)
        try:
            channel.exec_command(command)
            status = _pump(channel, collector, timeout)
            exit_code = channel.recv_exit_status() if status == STATUS_COMPLETED else EXIT_CODE_TIMEOUT
        except KeyboardInterrupt as exc:
            collector.finish()
            result = _build_result(collector, EXIT_CODE_INTERRUPTED, STATUS_INTERRUPTED)
            logger.warning(
                "[%s] コマンドの実行を中断しました。リモートのプロセスは停止していない可能性があります。",
                self.target,
            )
            raise SSHInterrupted(result) from exc
        finally:
            channel.close()

        collector.finish()
        if status == STATUS_TIMEOUT:
            logger.warning(
                "[%s] コマンドが %s 秒以内に完了しませんでした。リモートのプロセスは停止していない可能性があります。",
                self.target,
                timeout,
            )
        return _build_result(collector, exit_code, status)

    def get_file(self, remote_path: str, local_path: str, timeout: Optional[float] = _SFTP_TIMEOUT_SEC) -> None:
        """リモート→ローカルへファイルを取得（download）。

        timeout は無通信の上限秒（転送が進んでいる間は延長される）。失敗・中断時は
        SFTP を閉じる。途中まで書かれたローカルファイルは削除しない。
        """
        if self._client is None:
            raise RuntimeError("セッションが未接続です。")
        sftp = self._client.open_sftp()
        try:
            sftp.get_channel().settimeout(timeout)
            sftp.get(remote_path, local_path)
        finally:
            sftp.close()

    def put_file(self, local_path: str, remote_path: str, timeout: Optional[float] = _SFTP_TIMEOUT_SEC) -> None:
        """ローカル→リモートへファイルを転送（upload）。

        timeout は無通信の上限秒（転送が進んでいる間は延長される）。失敗・中断時は
        SFTP を閉じる。途中まで書かれたリモートファイルは削除しない。
        """
        if self._client is None:
            raise RuntimeError("セッションが未接続です。")
        sftp = self._client.open_sftp()
        try:
            sftp.get_channel().settimeout(timeout)
            sftp.put(local_path, remote_path)
        finally:
            sftp.close()
