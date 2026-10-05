"""
Authentication and Session State Management for Kairo.

Supports:
- Secure token issuance and verification for browser clients (desktop and mobile)
- Private backend instance isolation
- Tracking client type (browser-desktop, browser-mobile, tauri-desktop)
- Role-based permissions (admin, operator, auditor, viewer)
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("orchestrator.auth")

DEFAULT_SECRET_KEY = os.environ.get("KAIRO_AUTH_SECRET", "kairo_master_secret_key_2026")
DEFAULT_STATIC_API_KEY = os.environ.get("KAIRO_API_KEY", "kairo_sec_token_local")
REQUIRE_AUTH = os.environ.get("KAIRO_REQUIRE_AUTH", "false").lower() in ("true", "1", "yes")


@dataclass
class AuthSession:
    token: str
    user_id: str
    role: str  # "admin" | "operator" | "auditor" | "viewer"
    client_type: str  # "browser-desktop" | "browser-mobile" | "tauri-desktop" | "cli"
    created_at: str
    expires_at: float
    last_active: str
    is_active: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class AuthManager:
    """Manages token issuance, verification, and authenticated session state."""

    def __init__(self, secret_key: Optional[str] = None):
        self.secret_key = (secret_key or DEFAULT_SECRET_KEY).encode("utf-8")
        self.static_api_key = DEFAULT_STATIC_API_KEY
        self.require_auth = REQUIRE_AUTH
        self._sessions: Dict[str, AuthSession] = {}
        # Pre-seed default administrative session for local development
        self._seed_default_session()

    def _seed_default_session(self) -> None:
        token = self.static_api_key
        self._sessions[token] = AuthSession(
            token=token,
            user_id="local_admin",
            role="admin",
            client_type="browser-desktop",
            created_at=datetime.now(timezone.utc).isoformat(),
            expires_at=time.time() + (365 * 86400),
            last_active=datetime.now(timezone.utc).isoformat(),
            is_active=True,
            metadata={"default_seed": True, "instance": "private_local"},
        )

    def issue_token(
        self,
        user_id: str = "operator",
        role: str = "operator",
        client_type: str = "browser-desktop",
        ttl_seconds: int = 86400 * 7,  # 7 days
        metadata: Optional[Dict[str, Any]] = None,
    ) -> AuthSession:
        """Issues an authenticated session token for a client."""
        rand_bytes = secrets.token_bytes(24)
        sig = hmac.new(self.secret_key, rand_bytes, hashlib.sha256).hexdigest()[:16]
        token = f"kairo_tok_{rand_bytes.hex()}_{sig}"

        now = time.time()
        now_iso = datetime.now(timezone.utc).isoformat()
        session = AuthSession(
            token=token,
            user_id=user_id,
            role=role,
            client_type=client_type,
            created_at=now_iso,
            expires_at=now + ttl_seconds,
            last_active=now_iso,
            is_active=True,
            metadata=metadata or {},
        )
        self._sessions[token] = session
        logger.info(f"Issued auth session for {user_id} (role={role}, client={client_type})")
        return session

    def verify_token(self, token: Optional[str]) -> Tuple[bool, Optional[AuthSession], Optional[str]]:
        """
        Verifies token validity and returns (is_valid, session, error_msg).
        If auth is disabled (KAIRO_REQUIRE_AUTH=false) and token is missing,
        falls back to default local administrative session.
        """
        if not token:
            if not self.require_auth:
                # Auth disabled: fallback to default local session
                return True, self._sessions.get(self.static_api_key), None
            return False, None, "Missing authorization token"

        # Check in memory sessions
        clean_token = token.replace("Bearer ", "").strip()
        session = self._sessions.get(clean_token)

        if not session:
            # Check static API key match
            if clean_token == self.static_api_key:
                return True, self._sessions.get(self.static_api_key), None
            return False, None, "Invalid or unrecognized authorization token"

        if not session.is_active:
            return False, None, "Session has been revoked or deactivated"

        if time.time() > session.expires_at:
            session.is_active = False
            return False, None, "Session token has expired"

        # Update last active
        session.last_active = datetime.now(timezone.utc).isoformat()
        return True, session, None

    def revoke_token(self, token: str) -> bool:
        """Revokes a session token."""
        clean_token = token.replace("Bearer ", "").strip()
        if clean_token in self._sessions:
            self._sessions[clean_token].is_active = False
            return True
        return False

    def list_active_sessions(self) -> List[Dict[str, Any]]:
        """Lists active sessions without leaking full secret tokens."""
        res = []
        now = time.time()
        for tok, sess in self._sessions.items():
            if sess.is_active and now < sess.expires_at:
                masked_token = f"{tok[:12]}...{tok[-4:]}"
                item = sess.to_dict()
                item["token"] = masked_token
                res.append(item)
        return res


# Global singleton
auth_manager = AuthManager()


def get_auth_manager() -> AuthManager:
    return auth_manager
