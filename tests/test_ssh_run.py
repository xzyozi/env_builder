"""SSHSession.run の実行制御の検証（ENVB-0006 / Issue #11）。

paramiko のチャネルを fake に差し替え、無出力の長時間処理・大量の stderr・タイムアウト・
Ctrl+C・マルチバイト文字の分割・接続途中のcleanup を再現する。実機の接続は行わない。
"""

from typing import List, Optional

import pytest

from scripts.core import ssh as ssh_module
from scripts.core.ssh import (
    EXIT_CODE_INTERRUPTED,
    EXIT_CODE_TIMEOUT,
    STATUS_COMPLETED,
    STATUS_INTERRUPTED,
    STATUS_TIMEOUT,
    SSHInterrupted,
    SSHResult,
    SSHSession,
)


class FakeClock:
    """時刻と待機を差し替え、実際には待たずに時間を進める。

    実装がタイムアウトしなくなる退行が入っても、テストが永遠に待ち続けない（CI をハング
    させない）よう、待機回数に上限を設け、超えたら失敗させる。
    """

    MAX_SLEEPS = 10_000

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps = 0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps += 1
        if self.sleeps > self.MAX_SLEEPS:
            raise AssertionError("実装がタイムアウトせず、待機し続けています")
        self.now += seconds


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> FakeClock:
    fake = FakeClock()
    monkeypatch.setattr(ssh_module, "_monotonic", fake.monotonic)
    monkeypatch.setattr(ssh_module, "_sleep", fake.sleep)
    return fake


class FakeChannel:
    """paramiko.Channel の最小限の fake。

    steps は「ポーリング1回ごとに届く出力」。("out"|"err", bytes) のリスト。
    steps を使い切った後に終了する場合は finish_after_steps=True にする。
    """

    def __init__(
        self,
        steps: List[List[tuple]],
        *,
        exit_code: int = 0,
        finish_after_steps: bool = True,
        interrupt_at: Optional[int] = None,
    ) -> None:
        self._steps = list(steps)
        self._exit_code = exit_code
        self._finish_after_steps = finish_after_steps
        self._interrupt_at = interrupt_at
        self._out: List[bytes] = []
        self._err: List[bytes] = []
        self._poll = 0
        self.closed = False
        self.executed: Optional[str] = None
        self.max_buffered = 0

    # --- paramiko.Channel 互換 ---
    def exec_command(self, command: str) -> None:
        self.executed = command

    def _load_step(self) -> None:
        if self._steps:
            for stream, data in self._steps.pop(0):
                (self._out if stream == "out" else self._err).append(data)
        self.max_buffered = max(self.max_buffered, sum(map(len, self._out)) + sum(map(len, self._err)))

    def recv_ready(self) -> bool:
        # 実際のチャネルと同様に、バッファが空のとき次のデータが届く（1ポーリング=1ステップ）
        if not self._out and not self._err:
            self._deliver_next_step()
        return bool(self._out)

    def recv_stderr_ready(self) -> bool:
        return bool(self._err)

    def _deliver_next_step(self) -> None:
        self._poll += 1
        if self._interrupt_at is not None and self._poll >= self._interrupt_at:
            raise KeyboardInterrupt
        self._load_step()

    def recv(self, size: int) -> bytes:
        return self._out.pop(0)

    def recv_stderr(self, size: int) -> bytes:
        return self._err.pop(0)

    def exit_status_ready(self) -> bool:
        return self._finished()

    @property
    def eof_received(self) -> bool:
        return self._finished()

    def _finished(self) -> bool:
        return self._finish_after_steps and not self._steps and not self._out and not self._err

    def recv_exit_status(self) -> int:
        return self._exit_code

    def close(self) -> None:
        self.closed = True


class FakeTransport:
    def __init__(self, channel: FakeChannel) -> None:
        self._channel = channel

    def open_session(self) -> FakeChannel:
        return self._channel


class FakeClient:
    def __init__(self, channel: FakeChannel) -> None:
        self._transport = FakeTransport(channel)
        self.closed = False

    def get_transport(self) -> FakeTransport:
        return self._transport

    def close(self) -> None:
        self.closed = True


def _session(channel: FakeChannel, clock: FakeClock) -> SSHSession:
    """fake のチャネルを持つ、接続済み状態のセッションを返す。"""
    session = SSHSession.__new__(SSHSession)
    session.inventory = None  # type: ignore[assignment]
    session.target = "dst"
    session._chain = []
    session._client = FakeClient(channel)  # type: ignore[assignment]
    return session


def test_run_returns_completed_result_with_both_streams(clock: FakeClock) -> None:
    channel = FakeChannel([[("out", b"hello\n"), ("err", b"warn\n")]], exit_code=0)
    session = _session(channel, clock)

    result = session.run("echo hello", timeout=10)

    assert result.status == STATUS_COMPLETED
    assert result.ok
    assert result.exit_code == 0
    assert result.stdout == "hello"
    assert result.stderr == "warn"
    assert channel.executed == "echo hello"
    assert channel.closed


def test_run_preserves_remote_exit_code(clock: FakeClock) -> None:
    channel = FakeChannel([[("out", b"x\n")]], exit_code=3)

    result = _session(channel, clock).run("false", timeout=10)

    assert result.exit_code == 3
    assert result.status == STATUS_COMPLETED
    assert not result.ok


def test_silent_long_running_command_times_out_with_explicit_status(clock: FakeClock) -> None:
    """出力がまったく無いまま終わらないコマンド。ローカルは時間内に戻り、状態が明示される。"""
    channel = FakeChannel([], finish_after_steps=False)
    session = _session(channel, clock)

    result = session.run("sleep 1000", timeout=3)

    assert result.status == STATUS_TIMEOUT
    assert result.timed_out
    assert result.exit_code == EXIT_CODE_TIMEOUT
    assert not result.ok
    assert channel.closed
    # 壁時計で打ち切られており、timeout を大きく超えて待っていない
    assert 3 <= clock.now < 3.5


def test_remote_exit_code_124_is_distinguishable_from_timeout(clock: FakeClock) -> None:
    channel = FakeChannel([[("out", b"done\n")]], exit_code=124)

    result = _session(channel, clock).run("timeout 1 sleep 5", timeout=10)

    # リモートが 124 を返しただけで、ローカルの timeout ではない
    assert result.exit_code == 124
    assert result.status == STATUS_COMPLETED
    assert not result.timed_out


def test_timeout_keeps_output_received_before_the_deadline(clock: FakeClock) -> None:
    channel = FakeChannel([[("out", b"progress 1\n")], [("err", b"note\n")]], finish_after_steps=False)
    session = _session(channel, clock)

    result = session.run("long", timeout=1)

    assert result.status == STATUS_TIMEOUT
    assert result.stdout == "progress 1"
    assert result.stderr == "note"


def test_large_stderr_is_drained_while_stdout_is_also_read(clock: FakeClock) -> None:
    """stderr が大量でも、stdout と交互に排出されるので詰まらない。"""
    chunk = b"E" * 4096
    steps = [[("err", chunk), ("out", b"line\n")] for _ in range(200)]
    channel = FakeChannel(steps, exit_code=0)

    result = _session(channel, clock).run("noisy", timeout=60)

    assert result.status == STATUS_COMPLETED
    assert len(result.stderr) == 4096 * 200
    assert result.stdout.count("line") == 200
    # 排出が追い付かず溜め込むことなく、1回のポーリング分以上がバッファに残っていない
    assert channel.max_buffered <= 4096 + len(b"line\n")


def test_output_callback_receives_streams_as_they_arrive(clock: FakeClock) -> None:
    channel = FakeChannel([[("out", b"a\n")], [("err", b"b\n")], [("out", b"c\n")]])
    seen: List[tuple] = []

    _session(channel, clock).run("cmd", timeout=10, on_output=lambda stream, text: seen.append((stream, text)))

    assert seen == [("stdout", "a\n"), ("stderr", "b\n"), ("stdout", "c\n")]


def test_multibyte_character_split_across_chunks_is_not_garbled(clock: FakeClock) -> None:
    encoded = "致命的エラー\n".encode("utf-8")
    channel = FakeChannel([[("out", encoded[:2])], [("out", encoded[2:5])], [("out", encoded[5:])]])

    result = _session(channel, clock).run("cmd", timeout=10)

    assert result.stdout == "致命的エラー"
    assert "\ufffd" not in result.stdout


def test_keyboard_interrupt_closes_channel_and_keeps_partial_output(clock: FakeClock) -> None:
    channel = FakeChannel([[("out", b"step 1 done\n")], [("err", b"warn\n")]], finish_after_steps=False, interrupt_at=3)
    session = _session(channel, clock)

    with pytest.raises(SSHInterrupted) as excinfo:
        session.run("make", timeout=60)

    result = excinfo.value.result
    assert isinstance(excinfo.value, KeyboardInterrupt)
    assert result.status == STATUS_INTERRUPTED
    assert result.exit_code == EXIT_CODE_INTERRUPTED
    assert result.stdout == "step 1 done"
    assert result.stderr == "warn"
    assert not result.ok
    assert channel.closed


def test_run_requires_connected_session() -> None:
    session = SSHSession.__new__(SSHSession)
    session._client = None
    session._chain = []

    with pytest.raises(RuntimeError):
        session.run("true")


def test_noise_lines_are_still_removed(clock: FakeClock) -> None:
    channel = FakeChannel([[("out", b"result\nlogout\n"), ("err", b"tset: terminal attributes: x\nreal error\n")]])

    result = _session(channel, clock).run("cmd", timeout=10)

    assert result.stdout == "result"
    assert result.stderr == "real error"


def test_ssh_result_ok_requires_completed_status() -> None:
    assert SSHResult(0, "", "").ok
    assert not SSHResult(0, "", "", status=STATUS_TIMEOUT).ok
    assert not SSHResult(0, "", "", status=STATUS_INTERRUPTED).ok
    assert not SSHResult(1, "", "").ok


class _FakeConnectClient:
    def __init__(self, name: str, fail: bool = False) -> None:
        self.name = name
        self.fail = fail
        self.closed = False

    def get_transport(self):  # pragma: no cover - 使われない
        return None

    def close(self) -> None:
        self.closed = True


def test_enter_closes_already_opened_hops_when_a_later_connection_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    """踏み台までは繋がったが最終ホストの接続に失敗した場合、開いた踏み台を閉じる。"""
    from scripts.core.config import AuthSpec, Inventory, ServerSpec

    inventory = Inventory(
        servers={
            "hop": ServerSpec(name="hop", host="h", user="u", auth=AuthSpec()),
            "dst": ServerSpec(name="dst", host="d", user="u", proxy_jump=["hop"], auth=AuthSpec()),
        }
    )
    opened: List[_FakeConnectClient] = []

    class _HopTransport:
        def open_channel(self, *args, **kwargs):
            return object()

    def fake_connect(spec, sock=None):
        if spec.name == "dst":
            raise RuntimeError("dst unreachable")
        client = _FakeConnectClient(spec.name)
        client.get_transport = lambda: _HopTransport()  # type: ignore[method-assign]
        opened.append(client)
        return client

    monkeypatch.setattr(ssh_module, "_connect_one", fake_connect)

    with pytest.raises(RuntimeError, match="dst unreachable"):
        with SSHSession(inventory, "dst"):
            pass  # pragma: no cover

    assert [client.name for client in opened] == ["hop"]
    assert all(client.closed for client in opened)


def test_enter_closes_hops_when_interrupted_during_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    from scripts.core.config import AuthSpec, Inventory, ServerSpec

    inventory = Inventory(
        servers={
            "hop": ServerSpec(name="hop", host="h", user="u", auth=AuthSpec()),
            "dst": ServerSpec(name="dst", host="d", user="u", proxy_jump=["hop"], auth=AuthSpec()),
        }
    )
    opened: List[_FakeConnectClient] = []

    class _HopTransport:
        def open_channel(self, *args, **kwargs):
            return object()

    def fake_connect(spec, sock=None):
        if spec.name == "dst":
            raise KeyboardInterrupt
        client = _FakeConnectClient(spec.name)
        client.get_transport = lambda: _HopTransport()  # type: ignore[method-assign]
        opened.append(client)
        return client

    monkeypatch.setattr(ssh_module, "_connect_one", fake_connect)

    with pytest.raises(KeyboardInterrupt):
        with SSHSession(inventory, "dst"):
            pass  # pragma: no cover

    assert all(client.closed for client in opened)


def test_test_harness_aborts_instead_of_hanging_when_time_never_advances(
    monkeypatch: pytest.MonkeyPatch, clock: FakeClock
) -> None:
    """退行（タイムアウト判定が働かない）が入っても、テストが無限に待たず失敗として検出できる。

    時刻を固定して実装の deadline 判定を働かなくした状況を作り、fake の安全弁が
    AssertionError で打ち切ることを確認する。ssh.py 自体は書き換えない。
    """
    monkeypatch.setattr(ssh_module, "_monotonic", lambda: 0.0)
    channel = FakeChannel([], finish_after_steps=False)
    session = _session(channel, clock)

    with pytest.raises(AssertionError, match="タイムアウトせず"):
        session.run("sleep 1000", timeout=3)


def test_workspace_cleanup_runs_when_command_is_interrupted(tmp_path, clock: FakeClock) -> None:
    """コマンド実行中の Ctrl+C でも、専用作業領域とローカルの一時領域が片付く。"""
    from scripts.core.work_context import WorkContext

    commands: List[str] = []

    class RecordingSession:
        """作業領域の作成・cleanup を記録し、run の途中で SSHInterrupted を送出する。"""

        def __init__(self, work: WorkContext) -> None:
            self.work = work
            self.path = f"/tmp/env_builder-{work.work_id}-Xy12Ab"

        def run(self, command: str, timeout: int = 0) -> SSHResult:
            commands.append(command)
            if "mktemp" in command:
                return SSHResult(0, self.path + "\n", "")
            if "rm -rf --" in command:
                return SSHResult(0, "", "")
            raise SSHInterrupted(SSHResult(EXIT_CODE_INTERRUPTED, "partial", "", status=STATUS_INTERRUPTED))

    local_dir = None
    with pytest.raises(SSHInterrupted):
        with WorkContext("sync-tree", build_env_dir=tmp_path / "build_env") as work:
            local_dir = work.work_dir
            session = RecordingSession(work)
            workspace = work.create_remote_workspace(session, "dst")  # type: ignore[arg-type]
            try:
                session.run("tar czf ...")
            finally:
                work.cleanup_remote_workspace(session, "dst", workspace)  # type: ignore[arg-type]

    # リモートの専用作業領域はcleanupされ、ローカルの一時領域も削除されている
    assert any("rm -rf --" in command for command in commands)
    assert local_dir is not None and not local_dir.exists()
    manifest = __import__("json").loads(work.manifest_path.read_text(encoding="utf-8"))
    assert manifest["status"] == "failed"
    assert manifest["error_type"] == "SSHInterrupted"
    assert manifest["remote_workspaces"][0]["cleanup"] == "removed"
