"""Bring-your-own-key storage.

The only place a raw provider key is allowed to exist in plaintext is between
the request body and :meth:`ByokService.save`, and between decryption and the
provider call. Everything that persists, logs or returns is either ciphertext or
a four-character hint.

Fail-closed behaviour: if ``BYOK_ENCRYPTION_KEY`` is missing or malformed, the
BYOK routes raise ``byok_unavailable``. The rest of the app keeps running, which
is the same trade the provider-key configuration makes elsewhere.
"""

from __future__ import annotations

from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..core.config import ByokConfig
from ..core.errors import BadRequest, ByokUnavailable
from ..core.logging import get_logger
from ..repositories.store import UserAICredentialRepository

logger = get_logger(__name__)

ALLOWED_PROVIDERS = ("openai", "anthropic", "gemini")

#: Below this a value is almost certainly a typo rather than a provider key.
MIN_KEY_LENGTH = 8

#: Only the last four characters are ever stored or shown.
HINT_LENGTH = 4


class ByokService:
    def __init__(self, repo: UserAICredentialRepository, config: ByokConfig) -> None:
        self.repo = repo
        self.config = config

    # -- encryption ---

    def _fernet(self) -> Fernet:
        if not self.config.configured:
            raise ByokUnavailable(
                "Saving your own API key is not available on this server yet."
            )
        try:
            return Fernet(self.config.encryption_key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            # Never include the configured value in the error or the log.
            logger.error("BYOK_ENCRYPTION_KEY is not a valid Fernet key")
            raise ByokUnavailable(
                "Saving your own API key is not available on this server yet."
            ) from exc

    def encrypt(self, api_key: str) -> str:
        return self._fernet().encrypt(api_key.encode("utf-8")).decode("ascii")

    def decrypt(self, ciphertext: str) -> str:
        try:
            return self._fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            # A rotated or corrupted key cannot be recovered. Fail closed rather
            # than silently falling back to the server key, which would bill us.
            logger.error("could not decrypt a stored BYOK credential")
            raise ByokUnavailable(
                "Your saved API key could not be read. Please save it again."
            ) from exc

    # -- public operations ---

    async def save(self, *, user_id: str, provider: str, api_key: str) -> dict[str, Any]:
        provider = provider.strip().lower()
        api_key = api_key.strip()
        if provider not in ALLOWED_PROVIDERS:
            raise BadRequest("Choose OpenAI, Anthropic or Gemini.")
        if len(api_key) < MIN_KEY_LENGTH:
            raise BadRequest("That API key looks too short.")

        ciphertext = self.encrypt(api_key)
        row = await self.repo.upsert(
            user_id=user_id,
            provider=provider,
            ciphertext=ciphertext,
            hint=api_key[-HINT_LENGTH:],
        )
        return self.view(row)

    async def metadata(self, user_id: str) -> dict[str, Any] | None:
        row = await self.repo.for_user(user_id)
        return self.view(row) if row else None

    async def remove(self, user_id: str) -> None:
        await self.repo.delete_for_user(user_id)

    def decrypt_row(self, row: dict[str, Any]) -> tuple[str, str]:
        provider = str(row.get("provider") or "")
        if provider not in ALLOWED_PROVIDERS:
            raise ByokUnavailable("Your saved API key is not usable. Please save it again.")
        return provider, self.decrypt(str(row.get("key_ciphertext") or ""))

    @staticmethod
    def view(row: dict[str, Any]) -> dict[str, Any]:
        """Metadata only. The ciphertext never leaves the service boundary."""
        return {
            "provider": str(row.get("provider") or ""),
            "hint": str(row.get("key_hint") or ""),
            "updatedAt": str(row.get("updated_at") or ""),
        }


__all__ = ["ALLOWED_PROVIDERS", "ByokService"]
