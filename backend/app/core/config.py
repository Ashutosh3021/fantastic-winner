"""Typed configuration.

Every limit in ARCHITECTURE.md §24.2 lives here as an environment variable, so
tuning after seeing real usage needs no code change and no redeploy of anything
but this service's configuration.

Nothing in this module reads a secret at import time in a way that makes the app
un-importable: missing optional secrets degrade to "that provider is off", not to
an ImportError.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Literal


def _load_dotenv_once() -> None:
    """Read ``backend/.env`` into the environment, if it exists.

    Without this, ``uvicorn app.main:app`` fails at startup with "PYRONITES_URL
    must be set" even though the developer put the key in .env, because uvicorn
    does not read .env unless python-dotenv is installed. Existing process
    variables always win, so a real environment (containers, Render, Fly)
    overrides the file - which is also why this is safe in production, where the
    file does not exist.
    """
    env_file = Path(__file__).resolve().parent.parent.parent / ".env"
    if not env_file.is_file():
        return
    try:
        raw = env_file.read_text(encoding="utf-8")
    except OSError:
        return
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        key, _, value = stripped.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv_once()


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()

def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    try:
        return int(raw) if raw else default
    except ValueError:
        return default

def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    try:
        return float(raw) if raw else default
    except ValueError:
        return default

def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name).lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")

def _env_list(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    """Comma-separated list. Tolerant of stray quotes and parentheses.

    Values arrive from ``.env`` files written by hand, and a tuple literal such
    as ``("a", "b")`` is an easy thing to write. Parsing it as two items
    ``('("a"', 'b")')`` silently corrupts an allowlist, which is exactly how a
    login redirect list ends up rejecting every real origin.
    """
    raw = _env(name)
    if not raw:
        return default
    items: list[str] = []
    for part in raw.split(","):
        item = part.strip().strip("()").strip().strip('"').strip("'").strip()
        if item:
            items.append(item)
    return tuple(items)

Tier = Literal["fast", "balanced", "strong"]
RouteClass = Literal["light", "heavy", "check", "analysis", "auth"]

@dataclass(frozen=True)
class PyronitesConfig:
    """Where PyroCore lives and which project holds our tables."""

    url: str = "http://localhost:8000"
    api_key: str = ""
    project_slug: str = "codementor"
    request_timeout_s: float = 30.0
    # : Auto-create the project and apply migrations on startup. Convenient for a
    # : single instance; turn it off when migrations are a separate deploy step.
    auto_migrate: bool = True

    @property
    def configured(self) -> bool:
        return bool(self.url and self.api_key)

@dataclass(frozen=True)
class AuthConfig:
    """Extension auth bridge settings (§18.1)."""

    # : Access-token lifetime. Deliberately short: -5.6 keeps tokens in
    # : chrome.storage.local, which is not encrypted at rest.
    access_ttl_s: int = 900
    refresh_ttl_s: int = 60 * 60 * 24 * 30
    # : One-time login codes handed to the extension. Very short by design.
    login_code_ttl_s: int = 120
    # : Hard gate: no AI-generating route runs without a verified email (-16.7).
    require_verified_email: bool = True
    # : When true, a successful PyroCore login marks the email verified. Only
    # : safe for local development - see README.
    auto_verify_dev: bool = False
    #: Origins the login callback may hand a one-time code to. Compared as an
    #: exact ``scheme://netloc`` pair, never as a prefix: an unchecked
    #: ``return_to`` on an auth callback is an open redirect that leaks a sign-in
    #: link to whoever crafted the URL.
    allowed_return_origins: tuple[str, ...] = ("chrome-extension://localhost",)

    # --- GitHub OAuth (-18.1) ---
    #: Credentials of the GitHub OAuth app. Sign-in is disabled when either is
    #: empty; the hosted page says so instead of rendering a dead button.
    github_client_id: str = ""
    github_client_secret: str = ""
    #: Optional fixed callback. Empty derives it from the request base URL,
    #: which is correct on Render/Fly and in local dev. The value must match
    #: the callback registered on the GitHub OAuth app exactly.
    github_redirect_url: str = ""
    github_oauth_scopes: str = "read:user user:email"
    #: HMAC key for the OAuth ``state``. Falls back to the client secret, so a
    #: deployment with only the GitHub app credentials still works.
    oauth_state_secret: str = ""

    @property
    def github_configured(self) -> bool:
        return bool(self.github_client_id and self.github_client_secret)

    @property
    def state_secret(self) -> str:
        return self.oauth_state_secret or self.github_client_secret

@dataclass(frozen=True)
class CreditConfig:
    credits_per_window: int = 12
    window_hours: int = 5
    max_active_sessions: int = 3
    min_plan_questions: int = 3
    max_plan_questions: int = 5
    # : Attempts on one question before the step explanation is released (-10.8).
    attempt_cap: int = 8

@dataclass(frozen=True)
class RateLimitConfig:
    """L1 token buckets (§16.3), keyed by (user, route class)."""

    light_capacity: int = 30
    light_refill_per_min: int = 30
    heavy_capacity: int = 6
    heavy_refill_per_min: int = 6
    check_capacity: int = 20
    check_refill_per_min: int = 20
    analysis_capacity: int = 4
    analysis_refill_per_min: int = 4
    auth_capacity: int = 10
    auth_refill_per_min: int = 10

@dataclass(frozen=True)
class IpBudgetConfig:
    """L1b - the layer that decides whether the free tier is real (§16.4)."""

    ai_calls_per_5min: int = 40
    ai_tokens_per_window: int = 400_000
    ai_calls_per_day: int = 400

@dataclass(frozen=True)
class UserBudgetConfig:
    """L3 - cost leaks through zero-credit actions (§16.7)."""

    ai_tokens_per_window: int = 150_000
    new_account_hours: int = 24
    new_account_token_multiplier: int = 2
    new_account_token_budget: int = 50_000
    analyses_per_session_per_window: int = 4
    analyses_per_problem_per_window: int = 40

@dataclass(frozen=True)
class GatewayConfig:
    """Provider ordering, model tiers, concurrency and deadlines (§15.1, §16.8)."""

    # : Per-tier fallback order. The first entry with a configured key wins.
    provider_order: dict[Tier, tuple[str, ...]] = field(
        default_factory=lambda: {
            "fast": ("openai", "gemini", "anthropic"),
            "balanced": ("openai", "anthropic", "gemini"),
            "strong": ("anthropic", "openai", "gemini"),
        }
    )
    models: dict[tuple[str, Tier], str] = field(
        default_factory=lambda: {
            ("openai", "fast"): "gpt-4o-mini",
            ("openai", "balanced"): "gpt-4o",
            ("openai", "strong"): "gpt-4o",
            ("gemini", "fast"): "gemini-2.0-flash-lite",
            ("gemini", "balanced"): "gemini-2.0-flash",
            ("gemini", "strong"): "gemini-2.5-pro",
            ("anthropic", "fast"): "claude-3-5-haiku-latest",
            ("anthropic", "balanced"): "claude-3-5-sonnet-latest",
            ("anthropic", "strong"): "claude-3-7-sonnet-latest",
        }
    )
    concurrency_interactive: int = 8
    concurrency_generation: int = 4
    concurrency_analysis: int = 3
    queue_timeout_s: float = 8.0
    max_attempts_per_request: int = 2
    backoff_base_s: float = 0.5
    backoff_cap_s: float = 8.0
    breaker_failures: int = 5
    breaker_window_s: float = 30.0
    breaker_open_s: float = 60.0
    # : Cost per 1M tokens, used only for the L5 daily cap and the cost
    # : dashboard. Override to match a contract you actually have.
    cost_per_mtok_in: float = 0.15
    cost_per_mtok_out: float = 0.60

    def model_for(self, provider: str, tier: Tier) -> str:
        return self.models.get((provider, tier), "")

@dataclass(frozen=True)
class CacheConfig:
    """Content cache behaviour (§15.8)."""

    ttl_days: int = 30
    negative_ttl_s: int = 600
    max_rows_per_slug: int = 12
    # : Global "fill" bucket: cache-miss generations are capped separately from
    # : serves, because filling the cache is a cost and serving it is not (-16.8).
    fill_per_min: int = 30

@dataclass(frozen=True)
class ByokConfig:
    """Bring-your-own-key storage settings.

    ``encryption_key`` is a Fernet key: 32 urlsafe-base64 bytes. It is read at
    request time rather than import time, so a deployment without it still
    starts and only the BYOK routes fail closed.
    """

    encryption_key: str = ""
    max_cached_providers: int = 64

    @property
    def configured(self) -> bool:
        return bool(self.encryption_key)

@dataclass(frozen=True)
class ProviderKeys:
    openai: str = ""
    gemini: str = ""
    anthropic: str = ""

    def for_provider(self, name: str) -> str:
        return getattr(self, name, "") or ""

    def any_configured(self) -> bool:
        return bool(self.openai or self.gemini or self.anthropic)

@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    allowed_origins: tuple[str, ...] = ("http://localhost:3000",)
    log_level: str = "INFO"
    #: Reported in /health and sent to providers, so a bad rollout is traceable
    #: to a build rather than to "the API".
    client_version: str = "0.1.0"
    #: How many proxies sit in front of this app. ``X-Forwarded-For`` is only
    #: trusted up to this depth: if it is wrong, a client can spoof its address
    #: and walk around the per-IP AI budget.
    trusted_proxy_count: int = 0

    pyronites: PyronitesConfig = field(default_factory=PyronitesConfig)
    auth: AuthConfig = field(default_factory=AuthConfig)
    credits: CreditConfig = field(default_factory=CreditConfig)
    rate_limits: RateLimitConfig = field(default_factory=RateLimitConfig)
    ip_budget: IpBudgetConfig = field(default_factory=IpBudgetConfig)
    user_budget: UserBudgetConfig = field(default_factory=UserBudgetConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    keys: ProviderKeys = field(default_factory=ProviderKeys)
    byok: ByokConfig = field(default_factory=ByokConfig)

    # : L5 global cost safety (-16.9). 0 disables the cap.
    daily_spend_cap_usd: float = 0.0
    spend_alert_fraction: float = 0.8
    degraded_mode: bool = False

    # : Languages that have a passing leak corpus (-11.4). A language is not
    # : selectable until its corpus exists - this is the gate, enforced here.
    enabled_languages: tuple[str, ...] = ("en",)

    # : Complexity chart budget line (-13.1.3).
    ops_budget_per_second: int = 100_000_000

    # : Enables the deterministic offline provider. Never enable in production.
    allow_offline_provider: bool = False

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def client_version_header(self) -> str:
        return "X-Client-Version"

# : The shipped extension's ID. Public, not a secret: Chrome derives it from the
# : signing key and anyone can read it off the installed extension. It is the
# : one value that must appear in both CORS and the sign-in return allowlist, so
# : it is defined once here rather than copy-pasted into four config files.
EXTENSION_ORIGIN = "chrome-extension://ncbohgigmifjgekpfeebkognlogpflfa"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Read the environment once per process.

    Cached so tests can call ``get_settings.cache_clear()`` after patching env.
    """
    return Settings(
        environment=_env("ENVIRONMENT", "development"),
        allowed_origins=_env_list(
            "ALLOWED_ORIGINS",
            ("http://localhost:3000", EXTENSION_ORIGIN),
        ),
        log_level=_env("LOG_LEVEL", "INFO"),
        client_version=_env("CLIENT_VERSION", "0.1.0"),
        trusted_proxy_count=_env_int("TRUSTED_PROXY_COUNT", 0),
        pyronites=PyronitesConfig(
            url=_env("PYRONITES_URL", "http://localhost:8000").rstrip("/"),
            api_key=_env("PYRONITES_KEY"),
            project_slug=_env("PYRONITES_PROJECT", "codementor"),
            request_timeout_s=_env_float("PYRONITES_TIMEOUT_S", 30.0),
            auto_migrate=_env_bool("PYRONITES_AUTO_MIGRATE", True),
        ),
        auth=AuthConfig(
            access_ttl_s=_env_int("AUTH_ACCESS_TTL_S", 900),
            refresh_ttl_s=_env_int("AUTH_REFRESH_TTL_S", 60 * 60 * 24 * 30),
            login_code_ttl_s=_env_int("AUTH_LOGIN_CODE_TTL_S", 120),
            require_verified_email=_env_bool("REQUIRE_VERIFIED_EMAIL_FOR_AI", True),
            auto_verify_dev=_env_bool("AUTH_AUTO_VERIFY_DEV", False),
            # Default to the shipped extension rather than an empty tuple. An
            # empty allowlist does not fail loudly: it rejects every sign-in
            # with a generic "That sign-in link is not valid", which reads like
            # a broken flow rather than missing configuration.
            allowed_return_origins=_env_list(
                "EXTENSION_RETURN_ORIGINS", (EXTENSION_ORIGIN,)
            ),
            github_client_id=_env("GITHUB_CLIENT_ID"),
            github_client_secret=_env("GITHUB_CLIENT_SECRET"),
            github_redirect_url=_env("GITHUB_OAUTH_REDIRECT_URL"),
            github_oauth_scopes=_env("GITHUB_OAUTH_SCOPES", "read:user user:email"),
            oauth_state_secret=_env("AUTH_STATE_SECRET"),
        ),
        credits=CreditConfig(
            credits_per_window=_env_int("CREDITS_PER_WINDOW", 12),
            window_hours=_env_int("WINDOW_HOURS", 5),
            max_active_sessions=_env_int("MAX_ACTIVE_SESSIONS", 3),
            min_plan_questions=_env_int("MIN_PLAN_QUESTIONS", 3),
            max_plan_questions=_env_int("MAX_PLAN_QUESTIONS", 5),
            attempt_cap=_env_int("QUESTION_ATTEMPT_CAP", 8),
        ),
        rate_limits=RateLimitConfig(
            light_capacity=_env_int("RL_LIGHT_CAPACITY", 30),
            light_refill_per_min=_env_int("RL_LIGHT_PER_MIN", 30),
            heavy_capacity=_env_int("RL_HEAVY_CAPACITY", 6),
            heavy_refill_per_min=_env_int("RL_HEAVY_PER_MIN", 6),
            check_capacity=_env_int("RL_CHECK_CAPACITY", 20),
            check_refill_per_min=_env_int("RL_CHECK_PER_MIN", 20),
            analysis_capacity=_env_int("RL_ANALYSIS_CAPACITY", 4),
            analysis_refill_per_min=_env_int("RL_ANALYSIS_PER_MIN", 4),
            auth_capacity=_env_int("RL_AUTH_CAPACITY", 10),
            auth_refill_per_min=_env_int("RL_AUTH_PER_MIN", 10),
        ),
        ip_budget=IpBudgetConfig(
            ai_calls_per_5min=_env_int("IP_AI_CALLS_PER_5MIN", 40),
            ai_tokens_per_window=_env_int("IP_AI_TOKENS_PER_WINDOW", 400_000),
            ai_calls_per_day=_env_int("IP_AI_CALLS_PER_DAY", 400),
        ),
        user_budget=UserBudgetConfig(
            ai_tokens_per_window=_env_int("USER_AI_TOKEN_BUDGET_PER_WINDOW", 150_000),
            new_account_hours=_env_int("NEW_ACCOUNT_RAMP_HOURS", 24),
            new_account_token_multiplier=_env_int("NEW_ACCOUNT_TOKEN_MULTIPLIER", 2),
            new_account_token_budget=_env_int("NEW_ACCOUNT_TOKEN_BUDGET", 50_000),
            analyses_per_session_per_window=_env_int("ANALYSIS_CAP_PER_SESSION", 4),
            analyses_per_problem_per_window=_env_int("ANALYSIS_CAP_PER_PROBLEM", 40),
        ),
        gateway=GatewayConfig(
            concurrency_interactive=_env_int("AI_CONCURRENCY_INTERACTIVE", 8),
            concurrency_generation=_env_int("AI_CONCURRENCY_GENERATION", 4),
            concurrency_analysis=_env_int("AI_CONCURRENCY_ANALYSIS", 3),
            queue_timeout_s=_env_float("AI_QUEUE_TIMEOUT_S", 8.0),
            max_attempts_per_request=_env_int("AI_MAX_ATTEMPTS", 2),
            backoff_base_s=_env_float("AI_BACKOFF_BASE_S", 0.5),
            backoff_cap_s=_env_float("AI_BACKOFF_CAP_S", 8.0),
            breaker_failures=_env_int("AI_BREAKER_FAILURES", 5),
            breaker_window_s=_env_float("AI_BREAKER_WINDOW_S", 30.0),
            breaker_open_s=_env_float("AI_BREAKER_OPEN_S", 60.0),
            cost_per_mtok_in=_env_float("AI_COST_PER_MTOK_IN", 0.15),
            cost_per_mtok_out=_env_float("AI_COST_PER_MTOK_OUT", 0.60),
        ),
        cache=CacheConfig(
            ttl_days=_env_int("CACHE_TTL_DAYS", 30),
            negative_ttl_s=_env_int("NEGATIVE_CACHE_TTL_S", 600),
            max_rows_per_slug=_env_int("MAX_CACHE_ROWS_PER_SLUG", 12),
            fill_per_min=_env_int("CACHE_FILL_BUCKET_PER_MIN", 30),
        ),
        keys=ProviderKeys(
            openai=_env("AI_OPENAI_KEY") or _env("OPENAI_API_KEY"),
            gemini=_env("AI_GEMINI_KEY") or _env("GEMINI_API_KEY"),
            anthropic=_env("AI_ANTHROPIC_KEY") or _env("ANTHROPIC_API_KEY"),
        ),
        byok=ByokConfig(
            encryption_key=_env("BYOK_ENCRYPTION_KEY"),
            max_cached_providers=_env_int("BYOK_MAX_CACHED_PROVIDERS", 64),
        ),
        daily_spend_cap_usd=_env_float("DAILY_AI_SPEND_CAP_USD", 0.0),
        spend_alert_fraction=_env_float("SPEND_ALERT_FRACTION", 0.8),
        degraded_mode=_env_bool("DEGRADED_MODE", False),
        enabled_languages=_env_list("ENABLED_LANGUAGES", ("en",)),
        ops_budget_per_second=_env_int("OPS_BUDGET_PER_SECOND", 100_000_000),
        allow_offline_provider=_env_bool("ALLOW_OFFLINE_PROVIDER", False),
    )