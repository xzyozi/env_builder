"""SSH ホスト鍵検証ポリシーの検証（ENVB-0002）。

実際の接続は行わず、ポリシーを直接呼び出して、未登録鍵の拒否・オプトイン時の登録・
鍵不一致の拒否を確認する。
"""

from pathlib import Path

import paramiko
import pytest

from scripts.core.host_keys import (
    KNOWN_HOSTS_ENV,
    POLICY_ENV,
    AcceptNewHostKeyPolicy,
    HostKeyError,
    StrictHostKeyPolicy,
    configure_host_keys,
    fingerprint_sha256,
    host_key_policy_from_env,
    known_hosts_path,
)


@pytest.fixture(scope="module")
def host_key() -> "paramiko.RSAKey":
    return paramiko.RSAKey.generate(2048)


@pytest.fixture(scope="module")
def other_key() -> "paramiko.RSAKey":
    return paramiko.RSAKey.generate(2048)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(POLICY_ENV, raising=False)
    monkeypatch.delenv(KNOWN_HOSTS_ENV, raising=False)


def test_default_policy_is_strict() -> None:
    assert isinstance(host_key_policy_from_env(), StrictHostKeyPolicy)


def test_policy_is_selected_by_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(POLICY_ENV, "accept-new")
    assert isinstance(host_key_policy_from_env(), AcceptNewHostKeyPolicy)

    monkeypatch.setenv(POLICY_ENV, "STRICT")
    assert isinstance(host_key_policy_from_env(), StrictHostKeyPolicy)


def test_unknown_policy_value_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(POLICY_ENV, "auto-add")

    with pytest.raises(ValueError):
        host_key_policy_from_env()


def test_strict_policy_rejects_unknown_key_and_reports_fingerprint(host_key) -> None:
    client = paramiko.SSHClient()

    with pytest.raises(HostKeyError) as excinfo:
        StrictHostKeyPolicy().missing_host_key(client, "dst.example", host_key)

    message = str(excinfo.value)
    assert "dst.example" in message
    assert fingerprint_sha256(host_key) in message
    # 利用者が次に取るべき手順（初回登録のオプトイン）を示す
    assert "accept-new" in message


def test_fingerprint_uses_openssh_sha256_format(host_key) -> None:
    value = fingerprint_sha256(host_key)

    assert value.startswith("SHA256:")
    assert "=" not in value


def test_accept_new_registers_host_in_dedicated_file(tmp_path: Path, host_key) -> None:
    known_hosts = tmp_path / "ssh" / "env_builder_known_hosts"
    client = paramiko.SSHClient()

    AcceptNewHostKeyPolicy(known_hosts).missing_host_key(client, "dst.example", host_key)

    assert known_hosts.is_file()
    stored = paramiko.HostKeys(str(known_hosts)).lookup("dst.example")
    assert stored is not None
    assert stored.get("ssh-rsa") == host_key
    # 同じ接続の間は、登録した鍵がそのまま使われる
    assert client.get_host_keys().lookup("dst.example") is not None


def test_accept_new_appends_without_changing_existing_entries(tmp_path: Path, host_key, other_key) -> None:
    known_hosts = tmp_path / "env_builder_known_hosts"
    policy = AcceptNewHostKeyPolicy(known_hosts)
    client = paramiko.SSHClient()
    policy.missing_host_key(client, "first.example", host_key)
    before = known_hosts.read_text(encoding="utf-8")

    policy.missing_host_key(client, "second.example", other_key)

    after = known_hosts.read_text(encoding="utf-8")
    assert after.startswith(before)
    keys = paramiko.HostKeys(str(known_hosts))
    assert keys.lookup("first.example") is not None
    assert keys.lookup("second.example") is not None


def test_accept_new_registers_non_default_port_in_bracket_form(tmp_path: Path, host_key) -> None:
    known_hosts = tmp_path / "env_builder_known_hosts"

    AcceptNewHostKeyPolicy(known_hosts).missing_host_key(paramiko.SSHClient(), "[dst.example]:2222", host_key)

    assert paramiko.HostKeys(str(known_hosts)).lookup("[dst.example]:2222") is not None
    assert paramiko.HostKeys(str(known_hosts)).lookup("dst.example") is None


@pytest.mark.parametrize("hostname", ["", "bad host", "a,b", "tab\thost"])
def test_accept_new_refuses_hostnames_that_cannot_be_stored_safely(tmp_path: Path, host_key, hostname: str) -> None:
    known_hosts = tmp_path / "env_builder_known_hosts"

    with pytest.raises(HostKeyError):
        AcceptNewHostKeyPolicy(known_hosts).missing_host_key(paramiko.SSHClient(), hostname, host_key)

    assert not known_hosts.exists()


def test_changed_key_is_rejected_even_when_accept_new_is_enabled(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, host_key, other_key
) -> None:
    """登録済みホストの鍵が変わった場合は、オプトインしていても接続を拒否する。"""
    monkeypatch.setenv(POLICY_ENV, "accept-new")
    known_hosts = tmp_path / "env_builder_known_hosts"
    AcceptNewHostKeyPolicy(known_hosts).missing_host_key(paramiko.SSHClient(), "dst.example", host_key)

    client = paramiko.SSHClient()
    configure_host_keys(client, known_hosts)

    # paramiko は登録済みホストの鍵が異なる場合、ポリシーを呼ぶ前に BadHostKeyException を送出する。
    stored = client.get_host_keys().lookup("dst.example")
    assert stored is not None
    assert stored.get("ssh-rsa") == host_key
    assert stored.get("ssh-rsa") != other_key
    assert isinstance(client._policy, AcceptNewHostKeyPolicy)  # noqa: SLF001


def test_configure_host_keys_loads_dedicated_file_and_sets_strict_by_default(tmp_path: Path, host_key) -> None:
    known_hosts = tmp_path / "env_builder_known_hosts"
    AcceptNewHostKeyPolicy(known_hosts).missing_host_key(paramiko.SSHClient(), "dst.example", host_key)
    client = paramiko.SSHClient()

    configure_host_keys(client, known_hosts)

    assert client.get_host_keys().lookup("dst.example") is not None
    assert isinstance(client._policy, StrictHostKeyPolicy)  # noqa: SLF001


def test_configure_host_keys_works_when_dedicated_file_is_missing(tmp_path: Path) -> None:
    client = paramiko.SSHClient()

    configure_host_keys(client, tmp_path / "does-not-exist")

    assert isinstance(client._policy, StrictHostKeyPolicy)  # noqa: SLF001


def test_known_hosts_path_can_be_overridden(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(KNOWN_HOSTS_ENV, str(tmp_path / "custom"))

    assert known_hosts_path() == tmp_path / "custom"


def test_known_hosts_default_is_dedicated_file_not_users_known_hosts() -> None:
    path = known_hosts_path()

    assert path.name == "env_builder_known_hosts"
    assert path.parent.name == ".ssh"
