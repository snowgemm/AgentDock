"""Provider credential lookup.

Today the key comes from the process environment only. The interface is async and
provider-keyed so an envelope-encrypted / KMS-backed source can replace it later
without touching callers. Keys are never logged, stored in task data or sent to clients.
"""
from __future__ import annotations

import os
from typing import Protocol

from pydantic import SecretStr


class CredentialSource(Protocol):
    async def get_api_key(self, provider: str) -> SecretStr | None: ...


class EnvCredentialSource:
    _VARIABLES = {"openai": "OPENAI_API_KEY"}

    async def get_api_key(self, provider: str) -> SecretStr | None:
        variable = self._VARIABLES.get(provider)
        value = os.environ.get(variable, "").strip() if variable else ""
        return SecretStr(value) if value else None
