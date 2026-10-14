"""Extension authentication (§7, §18.1).

A Chrome extension cannot receive an httpOnly cookie, so PyroCore's browser
auth is unusable from the extension directly. The flow here bridges it:

1. The extension opens ``/auth/extension/login`` in a normal tab.
2. This backend performs the PyroCore login *server to server*, captures the
   session, and redirects back to the extension origin with a one-time code.
3. The extension exchanges that code for its own opaque access/refresh pair.

The code is single-use, short-lived, and carries no identity of its own. That is
the whole security argument: the redirect target is validated against a
configured allowlist first, because an unchecked ``return_to`` on an auth
callback is an open redirect that leaks a sign-in link.
"""

from __future__ import annotations

from typing import Annotated, Any
from urllib.parse import urlencode, urlparse

from fastapi import APIRouter, Body, Form, Query
from fastapi.responses import HTMLResponse, RedirectResponse

from ...api.deps import Container
from ...core.errors import BadRequest
from ...core.logging import get_logger
from ..dependencies import ContainerDep

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_LOGIN_PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sign in to CodeMentor</title>
<style>
 body{{font:16px/1.5 system-ui,sans-serif;margin:0;display:grid;place-items:center;
      min-height:100vh;background:#0f1115;color:#e8eaed}}
 form{{background:#181b21;padding:32px;border-radius:12px;width:320px}}
 h1{{font-size:20px;margin:0 0 4px}}
 p{{color:#9aa0a6;font-size:14px;margin:0 0 20px}}
 label{{display:block;font-size:13px;margin:14px 0 4px;color:#9aa0a6}}
 input{{width:100%;padding:10px;border-radius:8px;border:1px solid #30363d;
        background:#0f1115;color:#e8eaed;font-size:15px;box-sizing:border-box}}
 button{{width:100%;margin-top:20px;padding:11px;border:0;border-radius:8px;
         background:#4f8cff;color:#fff;font-size:15px;font-weight:600;cursor:pointer}}
 .err{{color:#ff8080;font-size:14px;margin-top:14px;min-height:20px}}
 .alt{{margin-top:16px;font-size:13px}}
 .alt a{{color:#4f8cff}}
</style></head><body>
<form method="post" autocomplete="on">
  <h1>Sign in</h1>
  <p>CodeMentor reads nothing from your editor until you sign in.</p>
  <label for="email">Email</label>
  <input id="email" name="email" type="email" required autocomplete="username">
  <label for="password">Password</label>
  <input id="password" name="password" type="password" required
         autocomplete="current-password" minlength="8">
  <input type="hidden" name="return_to" value="{return_to}">
  <button type="submit">Continue</button>
  <div class="err">{error}</div>
  <div class="alt">
    <a href="/v1/auth/extension/signup?return_to={return_to}">Create an account</a>
  </div>
</form>
</body></html>
"""

_SIGNUP_PAGE = _LOGIN_PAGE.replace("Sign in", "Create an account").replace(
    "CodeMentor reads nothing", "It takes a moment. CodeMentor reads nothing"
).replace(
    '<button type="submit">Continue</button>',
    '<button type="submit">Create account</button>',
).replace(
    '<a href="/v1/auth/extension/signup?return_to={return_to}">Create an account</a>',
    '<a href="/v1/auth/extension/login?return_to={return_to}">I already have an account</a>',
)


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


def _page(template: str, *, return_to: str, error: str = "") -> str:
    from html import escape

    return template.format(return_to=escape(return_to, quote=True), error=escape(error))


@router.get("/extension/login", response_class=HTMLResponse)
async def extension_login_page(
    container: ContainerDep,
    return_to: Annotated[str, Query(max_length=500)],
) -> HTMLResponse:
    allowed = container.settings.auth.allowed_return_origins
    try:
        target = _safe_return_to(return_to, allowed)
    except BadRequest as exc:
        return HTMLResponse(_page(_LOGIN_PAGE, return_to="", error=exc.message), status_code=400)
    return HTMLResponse(_page(_LOGIN_PAGE, return_to=target))


@router.get("/extension/signup", response_class=HTMLResponse)
async def extension_signup_page(
    container: ContainerDep,
    return_to: Annotated[str, Query(max_length=500)],
) -> HTMLResponse:
    allowed = container.settings.auth.allowed_return_origins
    try:
        target = _safe_return_to(return_to, allowed)
    except BadRequest as exc:
        return HTMLResponse(_page(_SIGNUP_PAGE, return_to="", error=exc.message), status_code=400)
    return HTMLResponse(_page(_SIGNUP_PAGE, return_to=target))


@router.post("/extension/login")
async def extension_login_submit(
    container: ContainerDep,
    email: Annotated[str, Form(max_length=200)],
    password: Annotated[str, Form(max_length=200)],
    return_to: Annotated[str, Form(max_length=500)],
) -> RedirectResponse:
    return await _complete(
        container,
        email=email,
        password=password,
        return_to=return_to,
        template=_LOGIN_PAGE,
        action="sign_in",
    )


@router.post("/extension/signup")
async def extension_signup_submit(
    container: ContainerDep,
    email: Annotated[str, Form(max_length=200)],
    password: Annotated[str, Form(max_length=200)],
    return_to: Annotated[str, Form(max_length=500)],
) -> RedirectResponse:
    return await _complete(
        container,
        email=email,
        password=password,
        return_to=return_to,
        template=_SIGNUP_PAGE,
        action="sign_up",
    )


async def _complete(
    container: Container,
    *,
    email: str,
    password: str,
    return_to: str,
    template: str,
    action: str,
) -> RedirectResponse:
    allowed = container.settings.auth.allowed_return_origins
    try:
        target = _safe_return_to(return_to, allowed)
    except BadRequest as exc:
        return HTMLResponse(_page(template, return_to="", error=exc.message), status_code=400)  # type: ignore[return-value]

    try:
        if action == "sign_up":
            code = await container.auth.sign_up(
                email=email, password=password, return_to=target
            )
        else:
            code = await container.auth.sign_in(
                email=email, password=password, return_to=target
            )
    except BadRequest as exc:
        # Re-render the form with the message rather than redirecting: losing the
        # typed email would make a typo twice as annoying.
        return HTMLResponse(  # type: ignore[return-value]
            _page(template, return_to=target, error=exc.message), status_code=400
        )

    separator = "&" if "?" in target else "?"
    location = f"{target}{separator}{urlencode({'code': code})}"
    return RedirectResponse(location, status_code=303)


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
