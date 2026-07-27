"""Provider-independent configuration and failure contracts."""

from __future__ import annotations

from enum import StrEnum

from pydantic import AnyHttpUrl, Field, model_validator

from bidfusion.schemas.common import BidfusionModel


class SecretRef(BidfusionModel):
    """Logical pointer to a secret; never the secret value itself."""

    reference: str = Field(
        min_length=10,
        pattern=r"^secret://[A-Za-z0-9][A-Za-z0-9._/-]*$",
        description='Logical secret location, e.g. "secret://env/LLM_API_KEY".',
    )


class ProviderConfig(BidfusionModel):
    """Non-secret adapter configuration safe for domain serialization."""

    endpoint: AnyHttpUrl
    secret_ref: SecretRef | None = None
    timeout_seconds: float = Field(default=30.0, gt=0, le=300)

    @model_validator(mode="after")
    def _endpoint_cannot_embed_credentials(self) -> ProviderConfig:
        if (
            self.endpoint.username is not None
            or self.endpoint.password is not None
            or self.endpoint.query is not None
            or self.endpoint.fragment is not None
        ):
            msg = "provider endpoint cannot contain userinfo, query parameters, or fragments"
            raise ValueError(msg)
        return self


class ExternalErrorCode(StrEnum):
    """Small provider-neutral taxonomy exposed across capability boundaries."""

    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    AUTHENTICATION_FAILED = "authentication_failed"
    INVALID_RESPONSE = "invalid_response"
    POLICY_BLOCKED = "policy_blocked"
