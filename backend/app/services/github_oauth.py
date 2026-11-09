"""GitHub OAuth (authorization-code flow) used by the hosted sign-in page.

The extension cannot finish a browser redirect on its own: a web page may not
navigate to ``chrome-extension://`` (Chrome answers ``ERR_BLOCKED_BY_CLIENT``).
The backend therefore owns the GitHub callback and hands the extension the same
single-use code the previous password flow used. Everything after the callback
is unchanged: one-time code -> opaque access/refresh pair.

Only the authorization-code grant is implemented. There is no client-side
secret, and the token exchange runs server to server so the client secret never
leaves this service.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode

import httpx

from ..core.errors import BadRequest, UpstreamError
from ..core.logging import get_logger

logger = get_logger(__name__)

GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
GITHUB_EXCHANGE_URL = "https://github.com/login/oauth/access_token"
GITHUB_API_URL = "https://api.github.com"

#: The signed ``state`` is short-lived: a learner may take a minute on GitHub's
#: consent screen, but a captured callback URL should not stay useful for long.
STATE_MAX_AGE_S = 600

_USER_AGENT = "CodeMentor/0.1"


@dataclass(frozen=True)
class GitHubIdentity:
    provider_user_id: str
    login: str
    email: str
    email_verified: bool


def authorize_url(
    *, client_id: str, redirect_uri: str, state: str, scopes: str
) -> str:
    query = urlencode(
        {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scopes,
            "state": state,
            "allow_signup": "true",
        }
    )
    return f"{GITHUB_AUTHORIZE_URL}?{query}"


def sign_state(payload: dict[str, Any], secret: str) -> str:
    """Sign an OAuth ``state`` so the callback needs no server-side storage.

    The payload carries the validated ``return_to`` and an issue time; replay is
    bounded by ``STATE_MAX_AGE_S``. The value is opaque to GitHub and to the
    browser's address bar, but it is not an authority on its own: the callback
    re-validates ``return_to`` against the allowlist after verifying the
    signature.
    """
    claimed = {**payload, "iat": int(time.time())}
    raw = json.dumps(claimed, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")
    signature = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256)
    return f"{encoded}.{signature.hexdigest()}"


def verify_state(state: str, secret: str, *, max_age_s: int = STATE_MAX_AGE_S) -> dict[str, Any]:
    if not secret:
        raise BadRequest("GitHub sign-in is not configured on this server.")
    try:
        encoded, signature = state.rsplit(".", 1)
    except ValueError as exc:
        raise BadRequest("That sign-in link is not valid. Please start again.") from exc

    expected = hmac.new(secret.encode("utf-8"), encoded.encode("ascii"), hashlib.sha256)
    if not hmac.compare_digest(expected.hexdigest(), signature):
        raise BadRequest("That sign-in link is not valid. Please start again.")

    try:
        padded = encoded + "=" * (-len(encoded) % 4)
        claims = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
    except (ValueError, json.JSONDecodeError) as exc:
        raise BadRequest("That sign-in link is not valid. Please start again.") from exc

    issued = int(claims.get("iat", 0))
    if issued <= 0 or time.time() - issued > max_age_s:
        raise BadRequest("That sign-in link has expired. Please start again.")
    return claims


async def exchange_code(
    *, client_id: str, client_secret: str, code: str, redirect_uri: str
) -> str:
    """Trade the GitHub callback ``code`` for an access token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            GITHUB_EXCHANGE_URL,
            headers={"Accept": "application/json", "User-Agent": _USER_AGENT},
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        )

    if not response.is_success:
        logger.warning("github token exchange -> %s", response.status_code)
        raise UpstreamError("GitHub sign-in is unavailable right now. Try again shortly.")

    try:
        payload = response.json()
    except ValueError as exc:
        raise UpstreamError("GitHub returned an unexpected response.") from exc

    token = payload.get("access_token")
    if not token:
        # GitHub returns HTTP 200 with ``error`` for an invalid/expired code.
        logger.info("github token exchange rejected: %s", payload.get("error", "no_token"))
        raise BadRequest("GitHub sign-in did not complete. Please try again.")
    return str(token)


async def fetch_identity(access_token: str) -> GitHubIdentity:
    """Read the GitHub account and pick a verified email.

    ``user:email`` is requested because a GitHub profile email can be private.
    A verified email from ``/user/emails`` is preferred; the public profile
    email is a fallback GitHub only exposes after it has been verified.
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": _USER_AGENT,
        "X-GitHub-Api-Version": "2022-11-28",
    }
    async with httpx.AsyncClient(timeout=15.0, headers=headers) as client:
        user_response = await client.get(f"{GITHUB_API_URL}/user")
        if user_response.status_code in (401, 403):
            raise BadRequest("GitHub did not authorise this sign-in. Please try again.")
        if not user_response.is_success:
            logger.warning("github /user -> %s", user_response.status_code)
            raise UpstreamError("GitHub sign-in is unavailable right now. Try again shortly.")
        user = user_response.json()

        emails_response = await client.get(f"{GITHUB_API_URL}/user/emails")
        emails = emails_response.json() if emails_response.is_success else []

    email = ""
    if isinstance(emails, list):
        primary = next(
            (
                item
                for item in emails
                if item.get("primary") and item.get("verified") and item.get("email")
            ),
            None,
        )
        verified = primary or next(
            (item for item in emails if item.get("verified") and item.get("email")), None
        )
        if verified:
            email = str(verified["email"])

    if not email and user.get("email"):
        # A public profile email is one GitHub has already verified.
        email = str(user["email"])

    provider_user_id = user.get("id")
    login = user.get("login")
    if not provider_user_id or not login:
        raise UpstreamError("GitHub returned an unexpected identity.")
    if not email:
        raise BadRequest(
            "Your GitHub account has no verified email address. "
            "Add and verify one on GitHub, then try again."
        )

    return GitHubIdentity(
        provider_user_id=str(provider_user_id),
        login=str(login),
        email=email.lower(),
        email_verified=True,
    )
