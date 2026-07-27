"""Typed, format-validated identifiers used at architectural boundaries."""

from typing import Annotated

from pydantic import Field

BidId = Annotated[str, Field(pattern=r"^BID-\d{4}-\d{6}$")]
OpportunityId = Annotated[str, Field(pattern=r"^OPP-\d{6,}$")]
DocumentId = Annotated[str, Field(pattern=r"^DOC-\d{3,}$")]
RequirementId = Annotated[str, Field(pattern=r"^REQ-\d{6}$")]
CapabilityId = Annotated[str, Field(pattern=r"^CAP-\d{3,}$")]
RunId = Annotated[str, Field(pattern=r"^RUN-\d{8}-\d{4,}$")]
ArtifactId = Annotated[str, Field(pattern=r"^ART-\d{8}-\d{6,}$")]
ReviewId = Annotated[str, Field(pattern=r"^REV-\d{6,}$")]
ActorId = Annotated[str, Field(pattern=r"^ACT-\d{4,}$")]
KnowledgeItemId = Annotated[str, Field(pattern=r"^KNW-\d{6,}$")]
