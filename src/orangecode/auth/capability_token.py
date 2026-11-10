"""基于 HMAC-SHA256 的 Agent 权能令牌 (CapabilityToken) 签发与强校验。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any

_SIG_ALGO = hashlib.sha256


@dataclass
class CapabilityToken:
    """Agent 或子代理能力的权限凭据载体。"""

    agent_id: str
    capabilities: list[str] = field(default_factory=list)
    issued_at: int = field(default_factory=lambda: int(time.time()))
    expires_at: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_payload(self) -> dict[str, Any]:
        return {
            "agent_id": self.agent_id,
            "capabilities": list(self.capabilities),
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> CapabilityToken:
        return cls(
            agent_id=str(payload.get("agent_id", "")),
            capabilities=list(payload.get("capabilities", [])),
            issued_at=int(payload.get("issued_at", 0)),
            expires_at=payload.get("expires_at"),
            metadata=dict(payload.get("metadata", {})),
        )


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(s: str) -> bytes:
    padding = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode((s + padding).encode("ascii"))


def issue_token(
    secret: str,
    agent_id: str,
    capabilities: list[str],
    ttl_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    """签发一个带防篡改签名的权能令牌字符串。格式为 <b64_payload>.<b64_sig>。"""
    now = int(time.time())
    expires_at = (now + ttl_seconds) if ttl_seconds else None
    token = CapabilityToken(
        agent_id=agent_id,
        capabilities=capabilities,
        issued_at=now,
        expires_at=expires_at,
        metadata=metadata or {},
    )
    payload_bytes = json.dumps(token.to_payload(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = _b64url_encode(payload_bytes)

    sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), _SIG_ALGO).digest()
    sig_b64 = _b64url_encode(sig)

    return f"{payload_b64}.{sig_b64}"


def verify_token(secret: str, token_str: str) -> CapabilityToken | None:
    """验证权能令牌的签名与过期时间。若签名不匹配或已过期，则安全失效返回 None。"""
    if "." not in token_str:
        return None

    parts = token_str.strip().split(".")
    if len(parts) != 2:
        return None

    payload_b64, sig_b64 = parts

    expected_sig = hmac.new(secret.encode("utf-8"), payload_b64.encode("ascii"), _SIG_ALGO).digest()
    try:
        actual_sig = _b64url_decode(sig_b64)
    except Exception:
        return None

    if not hmac.compare_digest(expected_sig, actual_sig):
        return None

    try:
        raw_json = _b64url_decode(payload_b64).decode("utf-8")
        payload = json.loads(raw_json)
        token = CapabilityToken.from_payload(payload)
    except Exception:
        return None

    # 验证是否超时过期
    if token.expires_at is not None and token.expires_at <= time.time():
        return None

    return token
