
from orangecode.auth.allowlist import is_allowed, reset_warning_state
from orangecode.auth.capability_token import issue_token, verify_token


def test_allowlist_logic():
    reset_warning_state()
    # 默认拒绝
    assert not is_allowed("feishu", "user_1", None)
    assert not is_allowed("feishu", "user_1", [])

    # 通配放行
    assert is_allowed("feishu", "user_1", ["*"])

    # 精确匹配
    assert is_allowed("feishu", "user_1", ["user_1", "user_2"])
    assert not is_allowed("feishu", "user_3", ["user_1", "user_2"])
    # 自动 stringify
    assert is_allowed("feishu", 12345, ["12345"])


def test_capability_token_roundtrip():
    secret = "test-secret-key-42"
    token_str = issue_token(
        secret=secret,
        agent_id="subagent_reader",
        capabilities=["fs:read", "web:fetch"],
        ttl_seconds=3600,
        metadata={"role": "researcher"},
    )

    token = verify_token(secret, token_str)
    assert token is not None
    assert token.agent_id == "subagent_reader"
    assert token.capabilities == ["fs:read", "web:fetch"]
    assert token.metadata == {"role": "researcher"}


def test_capability_token_tampered_or_expired():
    secret = "test-secret-key-42"
    token_str = issue_token(
        secret=secret,
        agent_id="subagent_reader",
        capabilities=["fs:read"],
        ttl_seconds=1,
    )

    # 篡改数据
    parts = token_str.split(".")
    tampered_str = parts[0] + "tampered." + parts[1]
    assert verify_token(secret, tampered_str) is None

    # 错误密钥
    assert verify_token("wrong-secret", token_str) is None

    # 过期令牌 (ttl_seconds=-10)
    expired_str = issue_token(
        secret=secret,
        agent_id="subagent_reader",
        capabilities=["fs:read"],
        ttl_seconds=-10,
    )
    assert verify_token(secret, expired_str) is None
