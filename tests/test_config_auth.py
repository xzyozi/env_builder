"""inventory の auth.method 検証。"""

import pytest

from env_builder.core.config import ServerSpec


def test_server_spec_accepts_known_auth_methods() -> None:
    for method in ("key", "password"):
        spec = ServerSpec.from_dict("s", {"host": "h", "user": "u", "auth": {"method": method}})
        assert spec.auth.method == method


def test_server_spec_defaults_to_key_auth() -> None:
    assert ServerSpec.from_dict("s", {"host": "h", "user": "u"}).auth.method == "key"


def test_server_spec_rejects_unknown_auth_method() -> None:
    with pytest.raises(ValueError, match="auth.method"):
        ServerSpec.from_dict("s", {"host": "h", "user": "u", "auth": {"method": "pasword"}})
