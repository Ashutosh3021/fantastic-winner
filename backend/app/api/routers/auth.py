"""Extension authentication (§7, §18.1).

Sign-in is **GitHub OAuth**. A Chrome extension cannot receive an httpOnly
cookie, so the backend owns the browser redirect and then hands the extension
its own opaque token pair:

1. The extension opens ``/auth/extension/login`` in a normal tab.
2. That page sends the browser to GitHub's consent screen.
3. GitHub returns to this backend, which exchanges the code server-to-server,
   reads the verified identity, and mirrors the account.
4. The backend redirects to ``/auth/extension/done`` carrying a one-time code.
5. The extension exchanges that code for its own access/refresh pair.

The code is single-use, short-lived, and carries no identity of its own. The
OAuth ``state`` is HMAC-signed and bound to a validated ``return_to``; an
unchecked ``return_to`` on an auth callback is an open redirect that leaks a
sign-in link.
"""

from __future__ import annotations

import json
import re
import secrets
from typing import Annotated, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Body, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse

from ...api.deps import API_PREFIX
from ...core.config import AuthConfig
from ...core.errors import AppError, BadRequest
from ...core.logging import get_logger
from ...services.github_oauth import (
    authorize_url,
    fetch_identity,
    sign_state,
    verify_state,
)
from ...services.github_oauth import (
    exchange_code as exchange_github_code,
)
from ..dependencies import ContainerDep

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_GITHUB_MARK = (
    '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 0C3.58 0 0 3.58 0 8c0 '
    "3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-"
    "2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 "
    "1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-"
    ".89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 "
    "2.2.82.64-.18 1.32-.27 2-.27.68 0 1.36.09 2 .27 1.53-1.04 2.2-.82 2.2-.82.44 "
    "1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54."
    "73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-"
    '4.42-3.58-8-8-8Z"/></svg>'
)

_LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in to CodeMentor</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;margin:0;display:grid;place-items:center;
      min-height:100vh;background:#0f1115;color:#e8eaed}}
 .card{{background:#181b21;padding:32px;border-radius:12px;width:340px;text-align:center}}
 h1{{font-size:20px;margin:0 0 6px}}
 p{{color:#9aa0a6;font-size:14px;margin:0 0 22px}}
 a.gh{{display:flex;align-items:center;justify-content:center;gap:10px;
      padding:11px 14px;border-radius:8px;background:#24292f;color:#fff;
      font-size:15px;font-weight:600;text-decoration:none;border:1px solid #30363d}}
 a.gh:hover{{background:#32383f}}
 .err{{color:#ff8080;font-size:14px;margin-top:16px;min-height:20px}}
 .fine{{color:#6b7280;font-size:12px;margin-top:18px}}
 svg{{width:18px;height:18px;fill:currentColor}}
</style></head><body>
<div class="card">
  <h1>Sign in</h1>
  <p>CodeMentor reads nothing from your editor until you sign in.</p>
  <a class="gh" href="{github_url}">{mark}Continue with GitHub</a>
  <div class="err">{error}</div>
  <div class="fine">We only read your public profile and verified email.</div>
</div>
</body></html>
"""

_ERROR_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign-in failed</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;margin:0;display:grid;place-items:center;
      min-height:100vh;background:#0f1115;color:#e8eaed;text-align:center}}
 .card{{background:#181b21;padding:32px;border-radius:12px;width:340px}}
 h1{{font-size:20px;margin:0 0 8px}}
 p{{color:#ff8080;font-size:14px;margin:0}}
</style></head><body>
<div class="card">
  <h1>Sign-in failed</h1>
  <p>{message}</p>
  <div class="fine">Close this tab and try again from CodeMentor.</div>
</div>
</body></html>
"""


def _normalise_origin(origin: str) -> str:
    """Strip trailing slashes so ``scheme://host/`` and ``scheme://host`` agree."""
    return origin.strip().rstrip("/").lower()


def _safe_return_to(value: str, allowed: tuple[str, ...]) -> str:
    """Only redirect to an origin we were configured to hand codes to.

    An unchecked ``return_to`` is an open redirect: an attacker sends a learner to
    a page that collects the one-time sign-in code. The check is an exact scheme
    and host match, not a prefix match, so ``https://evil.com/?x=good.com`` and
    ``https://good.com.evil.com`` both fail.
    """
    parsed = urlparse(value)
    if parsed.scheme and parsed.netloc:
        # urlparse moves a trailing slash out of netloc and into path, so both
        # sides are normalised before comparing. Without this, an origin written
        # the natural way (chrome-extension://<id>/) never matches and every
        # sign-in fails.
        origin = _normalise_origin(f"{parsed.scheme}://{parsed.netloc}")
        if origin in {_normalise_origin(item) for item in allowed}:
            return value
        raise BadRequest("That sign-in link is not valid.")
    # Extension origins are relative paths such as /index.html?x=1.
    if not parsed.netloc and not parsed.scheme and value.startswith("/"):
        return value
    raise BadRequest("That sign-in link is not valid.")


def _page(template: str, *, github_url: str = "", error: str = "") -> str:
    from html import escape

    return template.format(
        github_url=escape(github_url, quote=True),
        mark=_GITHUB_MARK,
        error=escape(error),
    )


def _error_page(message: str) -> str:
    from html import escape

    return _ERROR_PAGE.format(message=escape(message))


def _github_start_url(return_to: str) -> str:
    return f"{API_PREFIX}/auth/extension/github?{urlencode({'return_to': return_to})}"


def _github_callback_url(request: Request, auth: AuthConfig) -> str:
    """The exact URL registered as the OAuth app callback.

    A fixed value wins so a proxy can rewrite the public host; otherwise the
    request's own base URL is used, which is right on Render/Fly and in local
    development.
    """
    if auth.github_redirect_url:
        return auth.github_redirect_url
    return f"{str(request.base_url).rstrip('/')}{API_PREFIX}/auth/extension/github/callback"


def _public_base_url(request: Request, auth: AuthConfig) -> str:
    """Origin for the redirect that ends sign-in.

    TLS terminates at the proxy, and uvicorn ignores ``X-Forwarded-Proto``
    unless the proxy's address is trusted. Left alone, ``request.base_url`` is
    therefore ``http://`` on Render while the extension watches ``https://``,
    and the one-time code is never exchanged.
    """
    callback = urlparse(_github_callback_url(request, auth))
    scheme = callback.scheme or "https"
    if not auth.github_redirect_url:
        forwarded = request.headers.get("x-forwarded-proto", "").split(",")[0].strip().lower()
        if forwarded in {"http", "https"}:
            scheme = forwarded
    return f"{scheme}://{callback.netloc}"


_EXTENSION_ID_RE = re.compile(r"^[a-p]{32}$")
_LOGIN_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{8,200}$")


def _extension_id(return_to: str) -> str | None:
    """The Chrome extension id from an already-validated ``return_to``.

    Chrome ids are 32 characters in ``a``-``p``. Returning ``None`` rather than
    a malformed string keeps it out of the page's inline script.
    """
    parsed = urlparse(return_to)
    if parsed.scheme != "chrome-extension":
        return None
    return parsed.netloc if _EXTENSION_ID_RE.match(parsed.netloc) else None


@router.get("/extension/login", response_class=HTMLResponse)
async def extension_login_page(
    container: ContainerDep,
    return_to: Annotated[str, Query(max_length=500)],
) -> HTMLResponse:
    allowed = container.settings.auth.allowed_return_origins
    try:
        target = _safe_return_to(return_to, allowed)
    except BadRequest as exc:
        return HTMLResponse(_page(_LOGIN_PAGE, error=exc.message), status_code=400)

    if not container.settings.auth.github_configured:
        return HTMLResponse(
            _page(_LOGIN_PAGE, error="GitHub sign-in is not configured on this server."),
            status_code=503,
        )
    return HTMLResponse(_page(_LOGIN_PAGE, github_url=_github_start_url(target)))


@router.get("/extension/github")
async def github_start(
    request: Request,
    container: ContainerDep,
    return_to: Annotated[str, Query(max_length=500)],
) -> Response:
    auth = container.settings.auth
    try:
        target = _safe_return_to(return_to, auth.allowed_return_origins)
    except BadRequest as exc:
        return HTMLResponse(_page(_LOGIN_PAGE, error=exc.message), status_code=400)

    if not auth.github_configured:
        return HTMLResponse(
            _page(_LOGIN_PAGE, error="GitHub sign-in is not configured on this server."),
            status_code=503,
        )
    if not auth.state_secret:
        logger.error("GITHUB_CLIENT_SECRET/AUTH_STATE_SECRET missing; cannot sign state")
        return HTMLResponse(
            _page(_LOGIN_PAGE, error="Sign-in is misconfigured. Contact the operator."),
            status_code=503,
        )

    state = sign_state(
        {"return_to": target, "nonce": secrets.token_urlsafe(16)}, auth.state_secret
    )
    location = authorize_url(
        client_id=auth.github_client_id,
        redirect_uri=_github_callback_url(request, auth),
        state=state,
        scopes=auth.github_oauth_scopes,
    )
    return RedirectResponse(location, status_code=302)


@router.get("/extension/github/callback", response_class=HTMLResponse)
async def github_callback(
    request: Request,
    container: ContainerDep,
    code: Annotated[str | None, Query(max_length=500)] = None,
    state: Annotated[str | None, Query(max_length=4096)] = None,
    error: Annotated[str | None, Query(max_length=200)] = None,
) -> Response:
    auth = container.settings.auth
    if error:
        logger.info("github oauth denied: %s", error)
        return HTMLResponse(_error_page("GitHub sign-in was cancelled."), status_code=400)
    if not code or not state:
        return HTMLResponse(_error_page("GitHub sign-in did not complete."), status_code=400)
    if not auth.github_configured:
        return HTMLResponse(
            _error_page("GitHub sign-in is not configured on this server."), status_code=503
        )

    try:
        claims = verify_state(state, auth.state_secret)
        target = _safe_return_to(
            str(claims.get("return_to", "")), auth.allowed_return_origins
        )
        token = await exchange_github_code(
            client_id=auth.github_client_id,
            client_secret=auth.github_client_secret,
            code=code,
            redirect_uri=_github_callback_url(request, auth),
        )
        identity = await fetch_identity(token)
        raw_code = await container.auth.sign_in_with_provider(
            provider="github",
            provider_user_id=identity.provider_user_id,
            email=identity.email,
            email_verified=identity.email_verified,
            return_to=target,
        )
    except AppError as exc:
        logger.info("github sign-in failed: %s", exc.code)
        return HTMLResponse(_error_page(exc.message), status_code=exc.status)

    # End on our own https origin, never on the extension origin.
    #
    # A web page redirecting to chrome-extension:// is refused by Chrome with
    # ERR_BLOCKED_BY_CLIENT, so a flow that returns to the extension by
    # navigating there can never work. The extension watches this tab and the
    # page also messages it directly through `externally_connectable`.
    base = _public_base_url(request, auth)
    params: dict[str, str] = {"code": raw_code}
    ext = _extension_id(target)
    if ext:
        params["ext"] = ext
    location = f"{base}{API_PREFIX}/auth/extension/done?{urlencode(params)}"
    return RedirectResponse(location, status_code=303)


@router.get("/extension/done", response_class=HTMLResponse)
async def extension_done(
    code: Annotated[str, Query(max_length=200)],
    ext: Annotated[str | None, Query(max_length=64)] = None,
) -> HTMLResponse:
    """Where the sign-in flow ends.

    It carries the code in its URL, confirms it, and hands it to the extension
    two ways: the extension watches this tab, and when the page knows the
    extension id it also sends an external message. The message path works even
    if the navigation event is delivered to a worker that was asleep.
    """
    from html import escape

    safe = escape(code[:8], quote=True)
    handoff = ""
    if (
        ext
        and _EXTENSION_ID_RE.match(ext)
        and _LOGIN_CODE_RE.match(code)
    ):
        handoff = (
            "<script>(function(){"
            f"var ext={json.dumps(ext)},code={json.dumps(code)};"
            "try{if(window.chrome&&chrome.runtime&&chrome.runtime.sendMessage){"
            "chrome.runtime.sendMessage(ext,{t:'auth.code',code:code},"
            "function(){void chrome.runtime.lastError;});}}catch(e){}})();</script>"
        )
    return HTMLResponse(
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>Signed in</title>"
        "<style>body{font:16px system-ui,sans-serif;display:grid;place-items:center;"
        "min-height:100vh;margin:0;background:#0f1115;color:#e8eaed;text-align:center}"
        "p{color:#9aa0a6}</style></head><body><div>"
        "<h1>You are signed in</h1>"
        f"<p>Code {safe}&hellip; handed back to CodeMentor.</p>"
        "<p>You can close this tab.</p>"
        "</div>"
        f"{handoff}</body></html>"
    )


@router.post("/extension/code")
async def exchange_code(
    container: ContainerDep, body: Annotated[dict[str, Any], Body()]
) -> dict[str, Any]:
    """Trade the one-time code for the extension's own token pair."""
    raw_code = str(body.get("code", ""))
    if not raw_code or len(raw_code) > 200:
        raise BadRequest("That sign-in link has expired. Please sign in again.")
    return await container.auth.exchange_code(raw_code)


@router.post("/refresh")
async def refresh_tokens(
    container: ContainerDep, body: Annotated[dict[str, Any], Body()]
) -> dict[str, Any]:
    raw = str(body.get("refresh_token", ""))
    if not raw or len(raw) > 200:
        raise BadRequest("Sign in to continue.")
    return await container.auth.refresh(raw)


@router.post("/logout")
async def logout(
    container: ContainerDep, body: Annotated[dict[str, Any], Body()]
) -> dict[str, bool]:
    raw = str(body.get("refresh_token", ""))
    if raw:
        await container.auth.logout(raw)
    return {"ok": True}
