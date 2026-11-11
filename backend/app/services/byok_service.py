"""Bring-your-own-key storage.

The only place a raw provider key is allowed to exist in plaintext is between
the request body and :meth:`ByokService.save`, and between decryption and the
provider call. Everything that persists, logs or returns is either ciphertext or
a four-character hint.

Fail-closed behaviour: if ``BYOK_ENCRYPTION_KEY`` is missing and there is no
secret to derive one from, the BYOK routes raise ``byok_unavailable``. The rest
of the app keeps running, which is the same trade the provider-key
configuration makes elsewhere.
"""

from __future__ import annotations

import base64
import json
import re
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from ..core.config import ByokConfig
from ..core.errors import BadRequest, ByokUnavailable
from ..core.logging import get_logger
from ..repositories.store import UserAICredentialRepository

logger = get_logger(__name__)

#: Domain separation for the derived key. Changing it makes every stored
#: credential unreadable, which is the same consequence as rotating the key.
_KDF_SALT = b"codementor.byok.v1"
_KDF_INFO = b"fernet-key"

_derivation_warned = False

ALLOWED_PROVIDERS = ("openai", "anthropic", "gemini", "groq")

#: Below this a value is almost certainly a typo rather than a provider key.
MIN_KEY_LENGTH = 8

#: Only the last four characters are ever stored or shown.
HINT_LENGTH = 4

#: Provider model ids: ``llama-3.3-70b-versatile``, ``openai/gpt-oss-120b``,
#: ``accounts/fireworks/models/...`` and similar. Kept deliberately permissive;
#: the provider is the authority on which ids exist.
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}$")


class ByokService:
    def __init__(self, repo: UserAICredentialRepository, config: ByokConfig) -> None:
        self.repo = repo
        self.config = config

    # -- encryption ---

    def _fernet(self) -> Fernet:
        key = self._key_material()
        try:
            return Fernet(key.encode("ascii"))
        except (ValueError, TypeError) as exc:
            # Never include the configured value in the error or the log.
            logger.error("BYOK_ENCRYPTION_KEY is not a valid Fernet key")
            raise ByokUnavailable(
                "Saving your own API key is not available on this server yet."
            ) from exc

    def _key_material(self) -> str:
        if self.config.encryption_key:
            return self.config.encryption_key
        if not self.config.fallback_secret:
            raise ByokUnavailable(
                "Saving your own API key is not available on this server yet."
            )

        global _derivation_warned
        if not _derivation_warned:
            logger.warning(
                "BYOK_ENCRYPTION_KEY is unset; deriving one from PYRONITES_KEY. "
                "Set BYOK_ENCRYPTION_KEY explicitly so rotating the datastore key "
                "does not orphan saved credentials."
            )
            _derivation_warned = True
        derived = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=_KDF_SALT,
            info=_KDF_INFO,
        ).derive(self.config.fallback_secret.encode("utf-8"))
        return base64.urlsafe_b64encode(derived).decode("ascii")

    def encrypt(self, api_key: str) -> str:
        return self._seal(api_key, None)

    def decrypt(self, ciphertext: str) -> str:
        return self._open(ciphertext)[0]

    def _seal(self, api_key: str, model: str | None) -> str:
        """Store the key and any model choice in one opaque value.

        The model is not a secret, but keeping it inside the same ciphertext
        avoids a schema migration for a value that only matters alongside the
        key it was chosen with.
        """
        payload: dict[str, str] = {"key": api_key}
        if model:
            payload["model"] = model
        return self._fernet().encrypt(json.dumps(payload).encode("utf-8")).decode("ascii")

    def _open(self, ciphertext: str) -> tuple[str, str | None]:
        try:
            raw = self._fernet().decrypt(ciphertext.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError) as exc:
            # A rotated or corrupted key cannot be recovered. Fail closed rather
            # than silently falling back to the server key, which would bill us.
            logger.error("could not decrypt a stored BYOK credential")
            raise ByokUnavailable(
                "Your saved API key could not be read. Please save it again."
            ) from exc

        # Rows written before model selection hold the bare key.
        if not raw.startswith("{"):
            return raw, None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw, None
        if not isinstance(payload, dict) or not isinstance(payload.get("key"), str):
            return raw, None
        model = payload.get("model")
        return payload["key"], model if isinstance(model, str) and model else None

    # -- public operations ---

    async def save(
        self,
        *,
        user_id: str,
        provider: str,
        api_key: str,
        model: str | None = None,
    ) -> dict[str, Any]:
        provider = provider.strip().lower()
        api_key = api_key.strip()
        model = (model or "").strip() or None
        if provider not in ALLOWED_PROVIDERS:
            raise BadRequest("Choose OpenAI, Anthropic, Gemini or Groq.")
        if len(api_key) < MIN_KEY_LENGTH:
            raise BadRequest("That API key looks too short.")
        if model is not None and not _MODEL_ID.match(model):
            raise BadRequest("That model id does not look valid.")

        ciphertext = self._seal(api_key, model)
        row = await self.repo.upsert(
            user_id=user_id,
            provider=provider,
            ciphertext=ciphertext,
            hint=api_key[-HINT_LENGTH:],
        )
        return self.view(row, model=model)

    async def metadata(self, user_id: str) -> dict[str, Any] | None:
        row = await self.repo.for_user(user_id)
        if not row:
            return None
        try:
            model = self._open(str(row.get("key_ciphertext") or ""))[1]
        except ByokUnavailable:
            # Still report the provider and hint so a broken credential can be
            # seen and removed instead of disappearing from the popup.
            model = None
        return self.view(row, model=model)

    async def remove(self, user_id: str) -> None:
        await self.repo.delete_for_user(user_id)

    def decrypt_row(self, row: dict[str, Any]) -> tuple[str, str, str | None]:
        provider = str(row.get("provider") or "")
        if provider not in ALLOWED_PROVIDERS:
            raise ByokUnavailable("Your saved API key is not usable. Please save it again.")
        key, model = self._open(str(row.get("key_ciphertext") or ""))
        return provider, key, model

    @staticmethod
    def view(row: dict[str, Any], *, model: str | None = None) -> dict[str, Any]:
        """Metadata only. The ciphertext never leaves the service boundary."""
        return {
            "provider": str(row.get("provider") or ""),
            "hint": str(row.get("key_hint") or ""),
            "model": model,
            "updatedAt": str(row.get("updated_at") or ""),
        }


__all__ = ["ALLOWED_PROVIDERS", "ByokService"]
