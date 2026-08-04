"""Secret resolution at the external-capability adapter boundary."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import Protocol

from bidfusion.ports import ExternalCapabilityError
from bidfusion.schemas.external import ExternalErrorCode, SecretRef

_ENV_SECRET_PREFIX = "secret://env/"
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


class SecretResolver(Protocol):
    """Resolve a logical secret reference without serializing its value."""

    def resolve(self, reference: SecretRef) -> str:
        """Return a secret value or raise a normalized capability failure."""
        ...


class EnvironmentSecretResolver:
    """Resolve ``secret://env/NAME`` references from an environment mapping."""

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ = os.environ if environ is None else environ

    def __repr__(self) -> str:
        """Never include environment contents in diagnostics."""
        return f"{type(self).__name__}()"

    def resolve(self, reference: SecretRef) -> str:
        """Resolve one environment reference and normalize all lookup failures."""
        name = self.environment_name(reference)
        value = self._environ.get(name)
        if value is None or not value.strip():
            raise ExternalCapabilityError(ExternalErrorCode.AUTHENTICATION_FAILED)
        return value.strip()

    @staticmethod
    def environment_name(reference: SecretRef) -> str:
        """Return the validated environment-variable name for a reference."""
        if not reference.reference.startswith(_ENV_SECRET_PREFIX):
            raise ExternalCapabilityError(ExternalErrorCode.AUTHENTICATION_FAILED)
        name = reference.reference.removeprefix(_ENV_SECRET_PREFIX)
        if _ENV_NAME.fullmatch(name) is None:
            raise ExternalCapabilityError(ExternalErrorCode.AUTHENTICATION_FAILED)
        return name
