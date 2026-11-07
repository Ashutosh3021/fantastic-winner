"""Auth bridge (§18.1, ARCHITECTURE §27.3.4 resolved).

PyroCore authenticates browsers with an **opaque session token in an httpOnly
cookie**. A Chrome extension can receive neither: the cookie is not visible to
`fetch` from a service worker on a different origin, and sending one back would
mean a third origin holding it. So there is no token format to reuse and no
flow to point at - the plan's `Authorization: Bearer <jwt>` is simply not what
PyroCore offers.

What exists instead:

    extension tab -> hosted login page -> POST credentials
      -> backend calls PyroCore /auth/login server-to-server, captures the cookie
      -> backend calls PyroCore /auth/me to learn the identity
      -> backend mints a one-time code, redirects the tab to chrome-extension://
      -> extension exchanges the code for a short-lived access token + refresh token

Tokens are opaque and stored **hashed**, so a datastore dump yields nothing
usable. Access tokens are short-lived because the extension keeps them in
``chrome.storage.local``, which is not encrypted at rest.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Any

from ..core.config import AuthConfig
from ..core.errors import BadRequest, Unauthorized
from ..core.logging import get_logger
from ..repositories.gateway import PyronitesGateway
from ..repositories.store import (
    AuthTokenRepository,
    LoginCodeRepository,
    UserRepository,
    now_iso,
)

logger = get_logger(__name__)

@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str
    email_verified: bool
    account_age_days: float
    # : 0 = free/credits, 1 = unlimited with an own key.
    plan_tier: int = 0
    # : Filled by the request layer from stored credential metadata, never from
    # : a client-supplied field.
    has_own_key: bool = False

    def require_verified(self, *, enforced: bool) -> None:
        """The gate on every AI-generating route (§16.7).

        Read-only routes stay open for unverified accounts on purpose: a learner
        who has not verified can still browse saved content and read their
        mistake journal, which is both kinder and cheaper.
        """
        if enforced and not self.email_verified:
            from ..core.errors import EmailUnverified

            raise EmailUnverified(
                "Verify your email address to use AI features. "
                "Saved concepts and your mistake journal are still available."
            )

    @property
    def is_new_account(self) -> bool:
        return self.account_age_days < 1.0

class AuthService:
    def __init__(
        self,
        gateway: PyronitesGateway,
        config: AuthConfig,
        *,
        users: UserRepository,
        tokens: AuthTokenRepository,
        codes: LoginCodeRepository,
    ) -> None:
        self.gw = gateway
        self.config = config
        self.users = users
        self.tokens = tokens
        self.codes = codes

    # -- login ---

    async def sign_in(self, *, email: str, password: str, return_to: str) -> str:
        """Exchange credentials for a one-time code. Returns the raw code."""
        session = await self.gw.pyrocore_login(email.strip().lower(), password)
        identity = await self.gw.pyrocore_me(session["session_token"])

        user, _created = await self.users.ensure(
            pyrocore_user_id=identity["id"],
            email=identity["email"],
            auto_verify=self.config.auto_verify_dev,
        )

        raw_code = secrets.token_urlsafe(32)
        await self.codes.issue(
            user_id=str(user["id"]),
            raw=raw_code,
            return_to=return_to,
            ttl_s=self.config.login_code_ttl_s,
        )
        logger.info("issued login code for user_hash=%s", user["id"][:8])
        return raw_code

    async def sign_up(self, *, email: str, password: str, return_to: str) -> str:
        session = await self.gw.pyrocore_signup(email.strip().lower(), password)
        identity = await self.gw.pyrocore_me(session["session_token"])

        user, _created = await self.users.ensure(
            pyrocore_user_id=identity["id"],
            email=identity["email"],
            auto_verify=self.config.auto_verify_dev,
        )
        raw_code = secrets.token_urlsafe(32)
        await self.codes.issue(
            user_id=str(user["id"]),
            raw=raw_code,
            return_to=return_to,
            ttl_s=self.config.login_code_ttl_s,
        )
        return raw_code

    async def exchange_code(self, raw_code: str) -> dict[str, Any]:
        """Single-use: consuming the code is what marks it used."""
        row = await self.codes.consume(raw_code)
        if row is None:
            raise BadRequest("That sign-in link has expired. Please sign in again.")
        return await self._issue_pair(str(row["user_id"]))

    # -- tokens ---

    async def refresh(self, raw_refresh: str) -> dict[str, Any]:
        row = await self.tokens.lookup(raw_refresh)
        if row is None or row.get("kind") != "refresh":
            raise Unauthorized("Your session has expired. Please sign in again.")

        # Rotate: the presented refresh token is revoked, then a full new pair is
        # issued, so a captured refresh token is single-use.
        await self.tokens.update(str(row["id"]), {"revoked_at": now_iso()})
        return await self._issue_pair(str(row["user_id"]))

    async def logout(self, raw_refresh: str) -> None:
        await self.tokens.revoke(raw_refresh)

    async def identity_for(self, raw_token: str) -> Identity:
        row = await self.tokens.lookup(raw_token)
        if row is None:
            raise Unauthorized("Sign in to continue.")
        user = await self.users.get(str(row["user_id"]))
        if user is None:
            raise Unauthorized("Sign in to continue.")
        return self._identity(user)

    def _identity(self, user: dict[str, Any]) -> Identity:
        created = str(user.get("created_at") or now_iso())
        age_days = _age_days(created)
        return Identity(
            user_id=str(user["id"]),
            email=str(user.get("email") or ""),
            email_verified=bool(user.get("email_verified_at")),
            account_age_days=age_days,
            plan_tier=max(0, min(1, int(user.get("plan_tier") or 0))),
        )

    async def _issue_pair(self, user_id: str) -> dict[str, Any]:
        """Mint an access token and a refresh token.

        Refresh rotation is *not* handled here: this always issues a fresh pair.
        Callers that are rotating revoke the presented token first, so a captured
        refresh token is single-use (§7.3). Keeping the revoke outside this
        function is what stops a failure between the two steps from returning a
        client a pair while leaving the old token live.
        """
        access_raw = secrets.token_urlsafe(32)
        refresh_raw = secrets.token_urlsafe(32)

        access_row = await self.tokens.issue(
            user_id=user_id, raw=access_raw, kind="access", ttl_s=self.config.access_ttl_s
        )
        await self.tokens.store(access_row)

        refresh_row = await self.tokens.issue(
            user_id=user_id, raw=refresh_raw, kind="refresh", ttl_s=self.config.refresh_ttl_s
        )
        await self.tokens.store(refresh_row)

        return {
            "access_token": access_raw,
            "refresh_token": refresh_raw,
            "expires_in": self.config.access_ttl_s,
        }

def _age_days(created_iso: str) -> float:
    from datetime import UTC, datetime

    try:
        created = datetime.fromisoformat(created_iso.replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    return max(0.0, (datetime.now(UTC) - created).total_seconds() / 86_400)

def build_auth_state(identity: Identity | None) -> dict[str, Any]:
    """The shape the extension's popup and content script expect."""
    if identity is None:
        return {"signedIn": False, "email": None, "emailVerified": False}
    return {
        "signedIn": True,
        "email": identity.email,
        "emailVerified": identity.email_verified,
    }